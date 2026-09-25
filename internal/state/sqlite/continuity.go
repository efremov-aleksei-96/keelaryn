package sqlitestate

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/google/uuid"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

var (
	ErrInvalidContinuityAcceptance = errors.New("invalid continuity acceptance")
	ErrAcceptedContinuityNotFound  = errors.New("accepted continuity decision not found")
)

// AcceptResolvedObservationInScan atomically commits one already-resolved
// continuity decision. This function does not infer or strengthen evidence.
func (s *Store) AcceptResolvedObservationInScan(
	ctx context.Context,
	scanID corpus.ScanSessionID,
	input corpus.ObservationRecordInput,
	resolution corpus.CandidateSetResolution,
	evidence *corpus.ContentEvidence,
	decidedAt time.Time,
	policyID string,
) (out corpus.ContinuityAcceptance, err error) {
	if err := validateObservationInput(input); err != nil {
		return corpus.ContinuityAcceptance{}, err
	}
	if input.AssignmentState != corpus.AssignmentUnresolved ||
		input.ArtifactID != "" ||
		input.RevisionID != "" {
		return corpus.ContinuityAcceptance{}, fmt.Errorf("%w: input must be unresolved", ErrInvalidContinuityAcceptance)
	}
	if scanID == "" || decidedAt.IsZero() || strings.TrimSpace(policyID) == "" {
		return corpus.ContinuityAcceptance{}, ErrInvalidContinuityAcceptance
	}
	if err := corpus.ValidateCandidateSetResolution(resolution); err != nil {
		return corpus.ContinuityAcceptance{}, err
	}
	if resolution.State != corpus.CandidateSetResolvedSame || resolution.SelectedArtifactID == "" {
		return corpus.ContinuityAcceptance{}, fmt.Errorf("%w: state=%s", ErrInvalidContinuityAcceptance, resolution.State)
	}

	switch input.Kind {
	case corpus.EntryRegularFile:
		if evidence == nil {
			return corpus.ContinuityAcceptance{}, fmt.Errorf("%w: regular file requires content evidence", ErrInvalidContinuityAcceptance)
		}
		if err := corpus.ValidateContentEvidence(*evidence); err != nil {
			return corpus.ContinuityAcceptance{}, err
		}
		if evidence.Size != input.Size {
			return corpus.ContinuityAcceptance{}, fmt.Errorf(
				"%w: evidence size=%d observation size=%d",
				ErrInvalidContinuityAcceptance,
				evidence.Size,
				input.Size,
			)
		}
	default:
		if evidence != nil {
			return corpus.ContinuityAcceptance{}, fmt.Errorf("%w: non-regular entry has content evidence", ErrInvalidContinuityAcceptance)
		}
	}

	resolutionJSON, err := json.Marshal(resolution)
	if err != nil {
		return corpus.ContinuityAcceptance{}, fmt.Errorf("marshal continuity resolution: %w", err)
	}

	conn, err := s.pool.Get(ctx)
	if err != nil {
		return corpus.ContinuityAcceptance{}, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)

	end, err := sqlitex.ImmediateTransaction(conn)
	if err != nil {
		return corpus.ContinuityAcceptance{}, fmt.Errorf("begin continuity acceptance transaction: %w", err)
	}
	defer end(&err)

	scan, err := scanSessionConn(conn, scanID)
	if err != nil {
		return corpus.ContinuityAcceptance{}, err
	}
	if scan.Status != corpus.ScanOpen {
		return corpus.ContinuityAcceptance{}, fmt.Errorf("%w: %s", ErrScanNotOpen, scanID)
	}
	if input.ProviderObject.ProviderID != scan.ProviderID {
		return corpus.ContinuityAcceptance{}, fmt.Errorf(
			"%w: provider=%s scan_provider=%s",
			ErrScanScopeMismatch,
			input.ProviderObject.ProviderID,
			scan.ProviderID,
		)
	}
	for _, locator := range input.Locators {
		if locator.ProviderID != scan.ProviderID || locator.Root != scan.Root {
			return corpus.ContinuityAcceptance{}, fmt.Errorf(
				"%w: locator=%#v scan=%s/%s",
				ErrScanScopeMismatch,
				locator,
				scan.ProviderID,
				scan.Root,
			)
		}
	}

	exists, err := artifactExists(conn, resolution.SelectedArtifactID)
	if err != nil {
		return corpus.ContinuityAcceptance{}, err
	}
	if !exists {
		return corpus.ContinuityAcceptance{}, fmt.Errorf(
			"%w: %s",
			corpus.ErrArtifactNotFound,
			resolution.SelectedArtifactID,
		)
	}

	var revisionObservation *corpus.RevisionObservation
	if evidence != nil {
		revision, err := observeRevisionConn(conn, resolution.SelectedArtifactID, *evidence)
		if err != nil {
			return corpus.ContinuityAcceptance{}, err
		}
		revisionObservation = &revision
		input.RevisionID = revision.Current.Revision.ID
	}

	input.ArtifactID = resolution.SelectedArtifactID
	input.AssignmentState = corpus.AssignmentAssigned
	observation, err := recordObservationConn(conn, scanID, input)
	if err != nil {
		return corpus.ContinuityAcceptance{}, err
	}

	decision := corpus.AcceptedContinuityRecord{
		ID:            corpus.AcceptedContinuityID("cont_" + uuid.NewString()),
		ObservationID: observation.ID,
		ArtifactID:    resolution.SelectedArtifactID,
		State:         resolution.State,
		PolicyID:      policyID,
		Resolution:    resolution,
		DecidedAt:     decidedAt.UTC(),
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO accepted_continuity_decisions (decision_id, observation_id, artifact_id, decision_state, policy_id, resolution_json, decided_at) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
		&sqlitex.ExecOptions{Args: []any{
			string(decision.ID),
			string(decision.ObservationID),
			string(decision.ArtifactID),
			string(decision.State),
			decision.PolicyID,
			string(resolutionJSON),
			decision.DecidedAt.Format(time.RFC3339Nano),
		}}); err != nil {
		return corpus.ContinuityAcceptance{}, fmt.Errorf("insert accepted continuity decision: %w", err)
	}

	return corpus.ContinuityAcceptance{
		Observation: observation,
		Revision:    revisionObservation,
		Decision:    decision,
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
	return record, nil
}
