package sqlitestate

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/google/uuid"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

var (
	ErrInvalidContinuityAcceptance = errors.New("invalid continuity acceptance")
	ErrAcceptedContinuityNotFound   = errors.New("accepted continuity decision not found")
	ErrProviderObjectBindingConflict = errors.New("provider object binding conflicts with resolved Artifact")
)

// AcceptSameObservationInScan loads durable authority and derives SAME inside
// the mutation transaction. Caller cannot submit a pre-resolved decision.
func (s *Store) AcceptSameObservationInScan(ctx context.Context, request corpus.IdentityMutationRequest) (out corpus.ContinuityAcceptance, err error) {
	if err := validateIdentityMutationRequest(request, true); err != nil {
		return corpus.ContinuityAcceptance{}, err
	}
	fingerprint, err := corpus.FingerprintIdentityMutation(corpus.IdentityMutationSame, request)
	if err != nil {
		return corpus.ContinuityAcceptance{}, err
	}
	var replay *identityMutationRequestRecord

	conn, err := s.pool.Get(ctx)
	if err != nil {
		return corpus.ContinuityAcceptance{}, fmt.Errorf("get state connection: %w", err)
	}
	err = func() (txErr error) {
		end, txErr := sqlitex.ImmediateTransaction(conn)
		if txErr != nil {
			return fmt.Errorf("begin SAME acceptance transaction: %w", txErr)
		}
		defer end(&txErr)

		existing, found, txErr := identityMutationRequestConn(conn, request.ID)
		if txErr != nil {
			return txErr
		}
		if found {
			if txErr := reconcileExistingIdentityMutation(existing, corpus.IdentityMutationSame, fingerprint); txErr != nil {
				return txErr
			}
			value := existing
			replay = &value
			return nil
		}
		scan, txErr := scanSessionConn(conn, request.ScanID)
		if txErr != nil {
			return txErr
		}
		if scan.Status != corpus.ScanOpen {
			return fmt.Errorf("%w: %s", ErrScanNotOpen, request.ScanID)
		}
		authority, txErr := identityAuthoritySetConn(conn, request.AuthoritySetID)
		if txErr != nil {
			return txErr
		}
		if txErr := validateAuthorityScope(authority, scan, request.Observation); txErr != nil {
			return txErr
		}
		resolution, txErr := candidateResolutionFromAuthority(authority)
		if txErr != nil {
			return txErr
		}
		if resolution.State != corpus.CandidateSetResolvedSame || resolution.SelectedArtifactID == "" {
			return fmt.Errorf("%w: derived state=%s", ErrInvalidContinuityAcceptance, resolution.State)
		}
		exists, txErr := artifactExists(conn, resolution.SelectedArtifactID)
		if txErr != nil {
			return txErr
		}
		if !exists {
			return fmt.Errorf("%w: %s", corpus.ErrArtifactNotFound, resolution.SelectedArtifactID)
		}
		if bound, binding, txErr := providerArtifactBindingConn(
			conn, authority.IdentityDomain, authority.ProviderID, authority.CurrentObjectID,
		); txErr != nil {
			return txErr
		} else if bound && binding.ArtifactID != resolution.SelectedArtifactID {
			return fmt.Errorf(
				"%w: provider=%s domain=%s object=%s bound=%s resolved=%s",
				ErrProviderObjectBindingConflict,
				authority.ProviderID,
				authority.IdentityDomain,
				authority.CurrentObjectID,
				binding.ArtifactID,
				resolution.SelectedArtifactID,
			)
		}

		input := request.Observation
		revision, txErr := observeRevisionConn(conn, resolution.SelectedArtifactID, *request.ContentEvidence)
		if txErr != nil {
			return txErr
		}
		input.ArtifactID = resolution.SelectedArtifactID
		input.RevisionID = revision.Current.Revision.ID
		input.AssignmentState = corpus.AssignmentAssigned
		observation, txErr := recordObservationConn(conn, request.ScanID, input)
		if txErr != nil {
			return txErr
		}
		resolutionJSON, txErr := json.Marshal(resolution)
		if txErr != nil {
			return fmt.Errorf("marshal continuity resolution: %w", txErr)
		}
		decision := corpus.AcceptedContinuityRecord{
			ID:             corpus.AcceptedContinuityID("cont_" + uuid.NewString()),
			RequestID:      request.ID,
			AuthoritySetID: request.AuthoritySetID,
			ObservationID:  observation.ID,
			ArtifactID:     resolution.SelectedArtifactID,
			State:          resolution.State,
			PolicyID:       authority.PolicyID,
			Resolution:     resolution,
			DecidedAt:      request.DecidedAt.UTC(),
		}
		if txErr := sqlitex.Execute(conn,
			"INSERT INTO accepted_continuity_decisions (decision_id, observation_id, artifact_id, decision_state, policy_id, resolution_json, decided_at) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
			&sqlitex.ExecOptions{Args: []any{
				string(decision.ID), string(decision.ObservationID), string(decision.ArtifactID),
				string(decision.State), decision.PolicyID, string(resolutionJSON),
				decision.DecidedAt.Format(time.RFC3339Nano),
			}}); txErr != nil {
			return fmt.Errorf("insert accepted continuity decision: %w", txErr)
		}
		if txErr := insertIdentityMutationRequestConn(conn, identityMutationRequestRecord{
			RequestID: request.ID, Kind: corpus.IdentityMutationSame, Fingerprint: fingerprint,
			AuthoritySetID: request.AuthoritySetID, ObservationID: observation.ID,
			ArtifactID: decision.ArtifactID, RevisionID: revision.Current.Revision.ID,
			RevisionCreated: revision.Created, DecisionKind: "CONTINUITY",
			DecisionID: string(decision.ID), AcceptedAt: decision.DecidedAt,
		}); txErr != nil {
			return txErr
		}
		out = corpus.ContinuityAcceptance{Observation: observation, Revision: &revision, Decision: decision}
		return nil
	}()
	s.pool.Put(conn)
	if err != nil {
		return corpus.ContinuityAcceptance{}, err
	}
	if replay == nil {
		return out, nil
	}

	observation, err := s.Observation(ctx, replay.ObservationID)
	if err != nil {
		return corpus.ContinuityAcceptance{}, err
	}
	decision, err := s.AcceptedContinuity(ctx, replay.ObservationID)
	if err != nil {
		return corpus.ContinuityAcceptance{}, err
	}
	var revisionObservation *corpus.RevisionObservation
	if replay.RevisionID != "" {
		record, err := s.revisionRecordByID(ctx, replay.ArtifactID, replay.RevisionID)
		if err != nil {
			return corpus.ContinuityAcceptance{}, err
		}
		revisionObservation = &corpus.RevisionObservation{Current: record, Created: replay.RevisionCreated}
	}
	return corpus.ContinuityAcceptance{
		Observation: observation, Revision: revisionObservation, Decision: decision, Replayed: true,
	}, nil
}

func (s *Store) AcceptedContinuity(ctx context.Context, observationID corpus.ObservationID) (corpus.AcceptedContinuityRecord, error) {
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return corpus.AcceptedContinuityRecord{}, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)
	var record corpus.AcceptedContinuityRecord
	var resolutionJSON, decidedText string
	var found bool
	err = sqlitex.Execute(conn,
		"SELECT decision_id, artifact_id, decision_state, policy_id, resolution_json, decided_at FROM accepted_continuity_decisions WHERE observation_id = ?1",
		&sqlitex.ExecOptions{
			Args: []any{string(observationID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				found = true
				record.ID = corpus.AcceptedContinuityID(stmt.ColumnText(0))
				record.ObservationID = observationID
				record.ArtifactID = corpus.ArtifactID(stmt.ColumnText(1))
				record.State = corpus.CandidateSetState(stmt.ColumnText(2))
				record.PolicyID = stmt.ColumnText(3)
				resolutionJSON = stmt.ColumnText(4)
				decidedText = stmt.ColumnText(5)
				return nil
			},
		})
	if err != nil {
		return corpus.AcceptedContinuityRecord{}, fmt.Errorf("query accepted continuity decision: %w", err)
	}
	if !found {
		return corpus.AcceptedContinuityRecord{}, fmt.Errorf("%w: observation=%s", ErrAcceptedContinuityNotFound, observationID)
	}
	if err := json.Unmarshal([]byte(resolutionJSON), &record.Resolution); err != nil {
		return corpus.AcceptedContinuityRecord{}, fmt.Errorf("decode accepted continuity resolution: %w", err)
	}
	if err := corpus.ValidateCandidateSetResolution(record.Resolution); err != nil {
		return corpus.AcceptedContinuityRecord{}, fmt.Errorf("validate accepted continuity resolution: %w", err)
	}
	record.DecidedAt, err = time.Parse(time.RFC3339Nano, decidedText)
	if err != nil {
		return corpus.AcceptedContinuityRecord{}, fmt.Errorf("parse accepted continuity timestamp: %w", err)
	}
	err = sqlitex.Execute(conn,
		"SELECT request_id, authority_set_id FROM identity_mutation_requests WHERE observation_id = ?1 AND operation_kind = 'SAME' LIMIT 1",
		&sqlitex.ExecOptions{
			Args: []any{string(observationID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				record.RequestID = corpus.IdentityMutationRequestID(stmt.ColumnText(0))
				record.AuthoritySetID = corpus.IdentityAuthoritySetID(stmt.ColumnText(1))
				return nil
			},
		})
	if err != nil {
		return corpus.AcceptedContinuityRecord{}, fmt.Errorf("query continuity mutation provenance: %w", err)
	}
	return record, nil
}
