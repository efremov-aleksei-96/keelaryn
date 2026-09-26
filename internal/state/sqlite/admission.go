package sqlitestate

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"github.com/google/uuid"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

var (
	ErrInvalidArtifactAdmission        = errors.New("invalid Artifact admission")
	ErrAcceptedAdmissionNotFound       = errors.New("accepted Artifact admission not found")
	ErrProviderObjectAlreadyBound      = errors.New("provider object already bound to an Artifact")
	ErrProviderArtifactBindingNotFound = errors.New("provider Artifact binding not found")
)

// AcceptNewObservationInScan loads durable authority and derives NEW inside the
// transaction. Caller cannot submit COMPLETE/CONCLUSIVE/resolved state.
func (s *Store) AcceptNewObservationInScan(ctx context.Context, request corpus.IdentityMutationRequest) (out corpus.ArtifactAdmissionAcceptance, err error) {
	if err := validateIdentityMutationRequest(request, false); err != nil {
		return corpus.ArtifactAdmissionAcceptance{}, err
	}
	fingerprint, err := corpus.FingerprintIdentityMutation(corpus.IdentityMutationNew, request)
	if err != nil {
		return corpus.ArtifactAdmissionAcceptance{}, err
	}
	var replay *identityMutationRequestRecord

	conn, err := s.pool.Get(ctx)
	if err != nil {
		return corpus.ArtifactAdmissionAcceptance{}, fmt.Errorf("get state connection: %w", err)
	}
	err = func() (txErr error) {
		end, txErr := sqlitex.ImmediateTransaction(conn)
		if txErr != nil {
			return fmt.Errorf("begin NEW acceptance transaction: %w", txErr)
		}
		defer end(&txErr)

		existing, found, txErr := identityMutationRequestConn(conn, request.ID)
		if txErr != nil {
			return txErr
		}
		if found {
			if txErr := reconcileExistingIdentityMutation(existing, corpus.IdentityMutationNew, fingerprint); txErr != nil {
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
		remoteSegment, remoteBinding, remoteAuthority, txErr := revalidateRemoteHistoryIdentityAuthorityConn(conn, authority)
		if txErr != nil {
			return txErr
		}
		var lifetimeSegmentID any
		if remoteAuthority {
			lifetimeSegmentID = string(remoteSegment.ID)
			if remoteBinding != nil {
				return fmt.Errorf("%w: current segment %s is already bound to %s", ErrProviderLifetimeArtifactBindingConflict, remoteSegment.ID, remoteBinding.ArtifactID)
			}
		}
		resolution, txErr := occurrenceResolutionFromAuthority(authority)
		if txErr != nil {
			return txErr
		}
		if resolution.State != corpus.OccurrenceIdentityResolvedNew ||
			resolution.SelectedArtifactID != "" ||
			resolution.Universe == nil ||
			resolution.Universe.Coverage != corpus.CandidateUniverseComplete {
			return fmt.Errorf("%w: derived state=%s", ErrInvalidArtifactAdmission, resolution.State)
		}
		if !remoteAuthority {
			bound, _, txErr := providerArtifactBindingConn(conn, authority.IdentityDomain, authority.ProviderID, authority.CurrentObjectID)
			if txErr != nil {
				return txErr
			}
			if bound {
				return fmt.Errorf("%w: %s/%s/%s", ErrProviderObjectAlreadyBound, authority.IdentityDomain, authority.ProviderID, authority.CurrentObjectID)
			}
		}

		artifactID := corpus.ArtifactID("art_" + uuid.NewString())
		if txErr := sqlitex.Execute(conn,
			"INSERT INTO artifacts (artifact_id) VALUES (?1)",
			&sqlitex.ExecOptions{Args: []any{string(artifactID)}}); txErr != nil {
			return fmt.Errorf("insert admitted Artifact: %w", txErr)
		}
		input := request.Observation
		var revisionObservation *corpus.RevisionObservation
		if request.ContentEvidence != nil {
			revision, txErr := observeRevisionConn(conn, artifactID, *request.ContentEvidence)
			if txErr != nil {
				return txErr
			}
			revisionObservation = &revision
			input.RevisionID = revision.Current.Revision.ID
		}
		input.ArtifactID = artifactID
		input.AssignmentState = corpus.AssignmentAssigned
		observation, txErr := recordObservationConn(conn, request.ScanID, input)
		if txErr != nil {
			return txErr
		}
		binding := corpus.ProviderArtifactBinding{
			IdentityDomain: authority.IdentityDomain, ProviderID: authority.ProviderID,
			ProviderObjectID: authority.CurrentObjectID, ArtifactID: artifactID,
			PolicyID: authority.PolicyID, AcceptedAt: request.DecidedAt.UTC(),
		}
		if !remoteAuthority {
			if txErr := sqlitex.Execute(conn,
				"INSERT INTO provider_artifact_bindings (identity_domain, provider_id, native_object_id, artifact_id, policy_id, accepted_at) VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
				&sqlitex.ExecOptions{Args: []any{
					binding.IdentityDomain, string(binding.ProviderID), string(binding.ProviderObjectID),
					string(binding.ArtifactID), binding.PolicyID, binding.AcceptedAt.Format(time.RFC3339Nano),
				}}); txErr != nil {
				return fmt.Errorf("insert provider Artifact binding: %w", txErr)
			}
		}
		if remoteAuthority {
			if _, _, txErr := insertProviderLifetimeArtifactBindingConn(conn, ProviderLifetimeArtifactBinding{
				LifetimeSegmentID: remoteSegment.ID,
				ArtifactID:        artifactID,
				PolicyID:          remoteHistoryLifetimeAuthorityPolicyV1,
				AuthoritySetID:    authority.ID,
				AcceptedAt:        request.DecidedAt.UTC(),
			}); txErr != nil {
				return txErr
			}
		}
		resolutionJSON, txErr := json.Marshal(resolution)
		if txErr != nil {
			return fmt.Errorf("marshal admission resolution: %w", txErr)
		}
		decision := corpus.AcceptedAdmissionRecord{
			RequestID: request.ID, AuthoritySetID: request.AuthoritySetID,
			ObservationID: observation.ID, ArtifactID: artifactID, State: resolution.State,
			PolicyID: authority.PolicyID, IdentityDomain: authority.IdentityDomain,
			ProviderID: authority.ProviderID, ProviderObjectID: authority.CurrentObjectID,
			LifetimeSegmentID: stringOrEmpty(lifetimeSegmentID),
			Resolution: resolution, DecidedAt: request.DecidedAt.UTC(),
		}
		if txErr := sqlitex.Execute(conn,
			"INSERT INTO accepted_artifact_admissions (request_id, observation_id, artifact_id, identity_domain, provider_id, native_object_id, decision_state, policy_id, resolution_json, decided_at, lifetime_segment_id) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)",
			&sqlitex.ExecOptions{Args: []any{
				string(decision.RequestID), string(decision.ObservationID), string(decision.ArtifactID),
				decision.IdentityDomain, string(decision.ProviderID), string(decision.ProviderObjectID),
				string(decision.State), decision.PolicyID, string(resolutionJSON),
				decision.DecidedAt.Format(time.RFC3339Nano), lifetimeSegmentID,
			}}); txErr != nil {
			return fmt.Errorf("insert accepted Artifact admission: %w", txErr)
		}
		revisionID := corpus.RevisionID("")
		revisionCreated := false
		if revisionObservation != nil {
			revisionID = revisionObservation.Current.Revision.ID
			revisionCreated = revisionObservation.Created
		}
		if txErr := insertIdentityMutationRequestConn(conn, identityMutationRequestRecord{
			RequestID: request.ID, Kind: corpus.IdentityMutationNew, Fingerprint: fingerprint,
			AuthoritySetID: request.AuthoritySetID, ObservationID: observation.ID,
			ArtifactID: artifactID, RevisionID: revisionID, RevisionCreated: revisionCreated,
			DecisionKind: "ADMISSION", DecisionID: string(decision.RequestID), AcceptedAt: decision.DecidedAt,
		}); txErr != nil {
			return txErr
		}
		out = corpus.ArtifactAdmissionAcceptance{
			Observation: observation, Revision: revisionObservation, Decision: decision, Binding: binding,
		}
		return nil
	}()
	s.pool.Put(conn)
	if err != nil {
		return corpus.ArtifactAdmissionAcceptance{}, err
	}
	if replay == nil {
		return out, nil
	}

	observation, err := s.Observation(ctx, replay.ObservationID)
	if err != nil {
		return corpus.ArtifactAdmissionAcceptance{}, err
	}
	decision, err := s.AcceptedAdmission(ctx, replay.RequestID)
	if err != nil {
		return corpus.ArtifactAdmissionAcceptance{}, err
	}
	var binding corpus.ProviderArtifactBinding
	if decision.LifetimeSegmentID != "" {
		lifetimeBinding, err := s.ProviderLifetimeArtifactBinding(ctx, remotehistory.ProviderObjectLifetimeSegmentID(decision.LifetimeSegmentID))
		if err != nil {
			return corpus.ArtifactAdmissionAcceptance{}, err
		}
		if lifetimeBinding.ArtifactID != decision.ArtifactID || lifetimeBinding.PolicyID != decision.PolicyID {
			return corpus.ArtifactAdmissionAcceptance{}, fmt.Errorf("%w: replay lifetime binding mismatch", ErrInvalidArtifactAdmission)
		}
		binding = corpus.ProviderArtifactBinding{
			IdentityDomain: decision.IdentityDomain,
			ProviderID: decision.ProviderID,
			ProviderObjectID: decision.ProviderObjectID,
			ArtifactID: lifetimeBinding.ArtifactID,
			PolicyID: lifetimeBinding.PolicyID,
			AcceptedAt: lifetimeBinding.AcceptedAt,
		}
	} else {
		binding, err = s.ProviderArtifactBinding(ctx, decision.IdentityDomain, decision.ProviderID, decision.ProviderObjectID)
		if err != nil {
			return corpus.ArtifactAdmissionAcceptance{}, err
		}
	}
	var revisionObservation *corpus.RevisionObservation
	if replay.RevisionID != "" {
		record, err := s.revisionRecordByID(ctx, replay.ArtifactID, replay.RevisionID)
		if err != nil {
			return corpus.ArtifactAdmissionAcceptance{}, err
		}
		revisionObservation = &corpus.RevisionObservation{Current: record, Created: replay.RevisionCreated}
	}
	return corpus.ArtifactAdmissionAcceptance{
		Observation: observation, Revision: revisionObservation, Decision: decision,
		Binding: binding, Replayed: true,
	}, nil
}

func (s *Store) AcceptedAdmission(ctx context.Context, requestID corpus.IdentityMutationRequestID) (corpus.AcceptedAdmissionRecord, error) {
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return corpus.AcceptedAdmissionRecord{}, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)
	var record corpus.AcceptedAdmissionRecord
	var resolutionJSON, decidedText string
	var found bool
	err = sqlitex.Execute(conn,
		"SELECT observation_id, artifact_id, identity_domain, provider_id, native_object_id, decision_state, policy_id, resolution_json, decided_at, COALESCE(lifetime_segment_id,'') FROM accepted_artifact_admissions WHERE request_id = ?1",
		&sqlitex.ExecOptions{
			Args: []any{string(requestID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				found = true
				record.RequestID = requestID
				record.ObservationID = corpus.ObservationID(stmt.ColumnText(0))
				record.ArtifactID = corpus.ArtifactID(stmt.ColumnText(1))
				record.IdentityDomain = stmt.ColumnText(2)
				record.ProviderID = corpus.ProviderID(stmt.ColumnText(3))
				record.ProviderObjectID = corpus.ProviderObjectID(stmt.ColumnText(4))
				record.State = corpus.OccurrenceIdentityState(stmt.ColumnText(5))
				record.PolicyID = stmt.ColumnText(6)
				resolutionJSON = stmt.ColumnText(7)
				decidedText = stmt.ColumnText(8)
				record.LifetimeSegmentID = stmt.ColumnText(9)
				return nil
			},
		})
	if err != nil {
		return corpus.AcceptedAdmissionRecord{}, fmt.Errorf("query accepted Artifact admission: %w", err)
	}
	if !found {
		return corpus.AcceptedAdmissionRecord{}, fmt.Errorf("%w: %s", ErrAcceptedAdmissionNotFound, requestID)
	}
	if err := json.Unmarshal([]byte(resolutionJSON), &record.Resolution); err != nil {
		return corpus.AcceptedAdmissionRecord{}, fmt.Errorf("decode admission resolution: %w", err)
	}
	if err := corpus.ValidateOccurrenceIdentityResolution(record.Resolution); err != nil {
		return corpus.AcceptedAdmissionRecord{}, fmt.Errorf("validate accepted admission resolution: %w", err)
	}
	if record.State != corpus.OccurrenceIdentityResolvedNew ||
		record.State != record.Resolution.State ||
		record.Resolution.Universe == nil ||
		record.PolicyID != record.Resolution.Universe.PolicyID ||
		record.IdentityDomain != record.Resolution.Universe.IdentityDomain ||
		record.ProviderID != record.Resolution.Universe.ProviderID ||
		record.ProviderObjectID != record.Resolution.Universe.CurrentObjectID {
		return corpus.AcceptedAdmissionRecord{}, fmt.Errorf("%w: stored admission provenance mismatch", ErrInvalidArtifactAdmission)
	}
	record.DecidedAt, err = time.Parse(time.RFC3339Nano, decidedText)
	if err != nil {
		return corpus.AcceptedAdmissionRecord{}, fmt.Errorf("parse admission timestamp: %w", err)
	}
	var provenanceFound bool
	err = sqlitex.Execute(conn,
		"SELECT authority_set_id FROM identity_mutation_requests WHERE request_id = ?1 AND operation_kind = 'NEW' AND decision_kind = 'ADMISSION' AND decision_id = ?1 AND observation_id = ?2 AND artifact_id = ?3 LIMIT 1",
		&sqlitex.ExecOptions{
			Args: []any{string(requestID), string(record.ObservationID), string(record.ArtifactID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				provenanceFound = true
				record.AuthoritySetID = corpus.IdentityAuthoritySetID(stmt.ColumnText(0))
				return nil
			},
		})
	if err != nil {
		return corpus.AcceptedAdmissionRecord{}, fmt.Errorf("query admission mutation provenance: %w", err)
	}
	if !provenanceFound {
		return corpus.AcceptedAdmissionRecord{}, fmt.Errorf("%w: missing identity mutation provenance", ErrInvalidArtifactAdmission)
	}
	if record.PolicyID == remoteHistoryLifetimeAuthorityPolicyV1 {
		if record.LifetimeSegmentID == "" {
			return corpus.AcceptedAdmissionRecord{}, fmt.Errorf("%w: missing lifetime segment provenance", ErrInvalidArtifactAdmission)
		}
		found, lifetimeBinding, err := providerLifetimeArtifactBindingConn(conn, remotehistory.ProviderObjectLifetimeSegmentID(record.LifetimeSegmentID))
		if err != nil {
			return corpus.AcceptedAdmissionRecord{}, err
		}
		if !found ||
			lifetimeBinding.ArtifactID != record.ArtifactID ||
			lifetimeBinding.PolicyID != record.PolicyID ||
			lifetimeBinding.AuthoritySetID != record.AuthoritySetID {
			return corpus.AcceptedAdmissionRecord{}, fmt.Errorf("%w: lifetime binding provenance mismatch", ErrInvalidArtifactAdmission)
		}
	} else if record.LifetimeSegmentID != "" {
		return corpus.AcceptedAdmissionRecord{}, fmt.Errorf("%w: non-RemoteHistory admission has lifetime segment provenance", ErrInvalidArtifactAdmission)
	}
	return record, nil
}

func stringOrEmpty(value any) string {
	if value == nil {
		return ""
	}
	if text, ok := value.(string); ok {
		return text
	}
	return fmt.Sprint(value)
}

func (s *Store) ProviderArtifactBinding(ctx context.Context, identityDomain string, providerID corpus.ProviderID, objectID corpus.ProviderObjectID) (corpus.ProviderArtifactBinding, error) {
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return corpus.ProviderArtifactBinding{}, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)
	found, binding, err := providerArtifactBindingConn(conn, identityDomain, providerID, objectID)
	if err != nil {
		return corpus.ProviderArtifactBinding{}, err
	}
	if !found {
		return corpus.ProviderArtifactBinding{}, fmt.Errorf("%w: %s/%s/%s", ErrProviderArtifactBindingNotFound, identityDomain, providerID, objectID)
	}
	return binding, nil
}

func providerArtifactBindingConn(conn *sqlite.Conn, identityDomain string, providerID corpus.ProviderID, objectID corpus.ProviderObjectID) (bool, corpus.ProviderArtifactBinding, error) {
	var binding corpus.ProviderArtifactBinding
	var acceptedText string
	var found bool
	if err := sqlitex.Execute(conn,
		"SELECT artifact_id, policy_id, accepted_at FROM provider_artifact_bindings WHERE identity_domain = ?1 AND provider_id = ?2 AND native_object_id = ?3",
		&sqlitex.ExecOptions{
			Args: []any{identityDomain, string(providerID), string(objectID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				found = true
				binding.IdentityDomain = identityDomain
				binding.ProviderID = providerID
				binding.ProviderObjectID = objectID
				binding.ArtifactID = corpus.ArtifactID(stmt.ColumnText(0))
				binding.PolicyID = stmt.ColumnText(1)
				acceptedText = stmt.ColumnText(2)
				return nil
			},
		}); err != nil {
		return false, corpus.ProviderArtifactBinding{}, fmt.Errorf("query provider Artifact binding: %w", err)
	}
	if !found {
		return false, corpus.ProviderArtifactBinding{}, nil
	}
	var err error
	binding.AcceptedAt, err = time.Parse(time.RFC3339Nano, acceptedText)
	if err != nil {
		return false, corpus.ProviderArtifactBinding{}, fmt.Errorf("parse provider Artifact binding time: %w", err)
	}
	return true, binding, nil
}
