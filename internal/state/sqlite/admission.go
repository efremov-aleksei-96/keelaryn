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
	ErrInvalidArtifactAdmission         = errors.New("invalid Artifact admission")
	ErrAdmissionAlreadyAccepted         = errors.New("Artifact admission request already accepted")
	ErrAcceptedAdmissionNotFound        = errors.New("accepted Artifact admission not found")
	ErrProviderObjectAlreadyBound       = errors.New("provider object already bound to an Artifact")
	ErrProviderArtifactBindingNotFound  = errors.New("provider Artifact binding not found")
)

// AcceptResolvedNewObservationInScan atomically admits exactly one occurrence
// whose provider-neutral identity result is already RESOLVED_NEW.
//
// It never infers candidate-universe completeness. A stable requestID is the
// replay/reconciliation key: retrying an already accepted request cannot mint
// another Artifact.
func (s *Store) AcceptResolvedNewObservationInScan(
	ctx context.Context,
	requestID corpus.AdmissionRequestID,
	scanID corpus.ScanSessionID,
	input corpus.ObservationRecordInput,
	resolution corpus.OccurrenceIdentityResolution,
	evidence *corpus.ContentEvidence,
	decidedAt time.Time,
	policyID string,
) (out corpus.ArtifactAdmissionAcceptance, err error) {
	if err := validateObservationInput(input); err != nil {
		return corpus.ArtifactAdmissionAcceptance{}, err
	}
	if strings.TrimSpace(string(requestID)) == "" ||
		scanID == "" ||
		decidedAt.IsZero() ||
		strings.TrimSpace(policyID) == "" {
		return corpus.ArtifactAdmissionAcceptance{}, ErrInvalidArtifactAdmission
	}
	if input.AssignmentState != corpus.AssignmentUnresolved ||
		input.ArtifactID != "" ||
		input.RevisionID != "" {
		return corpus.ArtifactAdmissionAcceptance{}, fmt.Errorf("%w: input must be unresolved", ErrInvalidArtifactAdmission)
	}
	if input.ProviderObject.IdentityState != corpus.ObjectIdentityObserved ||
		input.ProviderObject.ID == "" {
		return corpus.ArtifactAdmissionAcceptance{}, fmt.Errorf("%w: admission requires observed provider identity", ErrInvalidArtifactAdmission)
	}
	if err := corpus.ValidateOccurrenceIdentityResolution(resolution); err != nil {
		return corpus.ArtifactAdmissionAcceptance{}, err
	}
	if resolution.State != corpus.OccurrenceIdentityResolvedNew ||
		resolution.SelectedArtifactID != "" ||
		resolution.Universe == nil ||
		resolution.Universe.Coverage != corpus.CandidateUniverseComplete {
		return corpus.ArtifactAdmissionAcceptance{}, fmt.Errorf("%w: state=%s", ErrInvalidArtifactAdmission, resolution.State)
	}
	proof := *resolution.Universe
	if proof.PolicyID != policyID ||
		proof.ProviderID != input.ProviderObject.ProviderID ||
		proof.CurrentObjectID != input.ProviderObject.ID {
		return corpus.ArtifactAdmissionAcceptance{}, fmt.Errorf("%w: proof/input policy or identity mismatch", ErrInvalidArtifactAdmission)
	}
	if evidence != nil {
		if input.Kind != corpus.EntryRegularFile {
			return corpus.ArtifactAdmissionAcceptance{}, fmt.Errorf("%w: content evidence on non-regular entry", ErrInvalidArtifactAdmission)
		}
		if err := corpus.ValidateContentEvidence(*evidence); err != nil {
			return corpus.ArtifactAdmissionAcceptance{}, err
		}
		if evidence.Size != input.Size {
			return corpus.ArtifactAdmissionAcceptance{}, fmt.Errorf(
				"%w: evidence size=%d observation size=%d",
				ErrInvalidArtifactAdmission,
				evidence.Size,
				input.Size,
			)
		}
	}

	resolutionJSON, err := json.Marshal(resolution)
	if err != nil {
		return corpus.ArtifactAdmissionAcceptance{}, fmt.Errorf("marshal admission resolution: %w", err)
	}

	conn, err := s.pool.Get(ctx)
	if err != nil {
		return corpus.ArtifactAdmissionAcceptance{}, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)

	end, err := sqlitex.ImmediateTransaction(conn)
	if err != nil {
		return corpus.ArtifactAdmissionAcceptance{}, fmt.Errorf("begin Artifact admission transaction: %w", err)
	}
	defer end(&err)

	accepted, err := admissionRequestExistsConn(conn, requestID)
	if err != nil {
		return corpus.ArtifactAdmissionAcceptance{}, err
	}
	if accepted {
		return corpus.ArtifactAdmissionAcceptance{}, fmt.Errorf("%w: %s", ErrAdmissionAlreadyAccepted, requestID)
	}

	scan, err := scanSessionConn(conn, scanID)
	if err != nil {
		return corpus.ArtifactAdmissionAcceptance{}, err
	}
	if scan.Status != corpus.ScanOpen {
		return corpus.ArtifactAdmissionAcceptance{}, fmt.Errorf("%w: %s", ErrScanNotOpen, scanID)
	}
	if input.ProviderObject.ProviderID != scan.ProviderID ||
		proof.ProviderID != scan.ProviderID ||
		proof.ScopeID != scan.Root {
		return corpus.ArtifactAdmissionAcceptance{}, fmt.Errorf(
			"%w: admission proof/input scan scope mismatch",
			ErrScanScopeMismatch,
		)
	}
	for _, locator := range input.Locators {
		if locator.ProviderID != scan.ProviderID || locator.Root != scan.Root {
			return corpus.ArtifactAdmissionAcceptance{}, fmt.Errorf(
				"%w: locator=%#v scan=%s/%s",
				ErrScanScopeMismatch,
				locator,
				scan.ProviderID,
				scan.Root,
			)
		}
	}

	bound, _, err := providerArtifactBindingConn(
		conn,
		proof.IdentityDomain,
		proof.ProviderID,
		proof.CurrentObjectID,
	)
	if err != nil {
		return corpus.ArtifactAdmissionAcceptance{}, err
	}
	if bound {
		return corpus.ArtifactAdmissionAcceptance{}, fmt.Errorf(
			"%w: %s/%s/%s",
			ErrProviderObjectAlreadyBound,
			proof.IdentityDomain,
			proof.ProviderID,
			proof.CurrentObjectID,
		)
	}

	artifactID := corpus.ArtifactID("art_" + uuid.NewString())
	if err := sqlitex.Execute(conn,
		"INSERT INTO artifacts (artifact_id) VALUES (?1)",
		&sqlitex.ExecOptions{Args: []any{string(artifactID)}}); err != nil {
		return corpus.ArtifactAdmissionAcceptance{}, fmt.Errorf("insert admitted Artifact: %w", err)
	}

	var revisionObservation *corpus.RevisionObservation
	if evidence != nil {
		revision, err := observeRevisionConn(conn, artifactID, *evidence)
		if err != nil {
			return corpus.ArtifactAdmissionAcceptance{}, err
		}
		revisionObservation = &revision
		input.RevisionID = revision.Current.Revision.ID
	}

	input.ArtifactID = artifactID
	input.AssignmentState = corpus.AssignmentAssigned
	observation, err := recordObservationConn(conn, scanID, input)
	if err != nil {
		return corpus.ArtifactAdmissionAcceptance{}, err
	}

	binding := corpus.ProviderArtifactBinding{
		IdentityDomain:   proof.IdentityDomain,
		ProviderID:       proof.ProviderID,
		ProviderObjectID: proof.CurrentObjectID,
		ArtifactID:       artifactID,
		PolicyID:         policyID,
		AcceptedAt:       decidedAt.UTC(),
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO provider_artifact_bindings (identity_domain, provider_id, native_object_id, artifact_id, policy_id, accepted_at) VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
		&sqlitex.ExecOptions{Args: []any{
			binding.IdentityDomain,
			string(binding.ProviderID),
			string(binding.ProviderObjectID),
			string(binding.ArtifactID),
			binding.PolicyID,
			binding.AcceptedAt.Format(time.RFC3339Nano),
		}}); err != nil {
		return corpus.ArtifactAdmissionAcceptance{}, fmt.Errorf("insert provider Artifact binding: %w", err)
	}

	decision := corpus.AcceptedAdmissionRecord{
		RequestID:        requestID,
		ObservationID:    observation.ID,
		ArtifactID:       artifactID,
		State:            resolution.State,
		PolicyID:         policyID,
		IdentityDomain:   proof.IdentityDomain,
		ProviderID:       proof.ProviderID,
		ProviderObjectID: proof.CurrentObjectID,
		Resolution:       resolution,
		DecidedAt:        decidedAt.UTC(),
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO accepted_artifact_admissions (request_id, observation_id, artifact_id, identity_domain, provider_id, native_object_id, decision_state, policy_id, resolution_json, decided_at) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)",
		&sqlitex.ExecOptions{Args: []any{
			string(decision.RequestID),
			string(decision.ObservationID),
			string(decision.ArtifactID),
			decision.IdentityDomain,
			string(decision.ProviderID),
			string(decision.ProviderObjectID),
			string(decision.State),
			decision.PolicyID,
			string(resolutionJSON),
			decision.DecidedAt.Format(time.RFC3339Nano),
		}}); err != nil {
		return corpus.ArtifactAdmissionAcceptance{}, fmt.Errorf("insert accepted Artifact admission: %w", err)
	}

	return corpus.ArtifactAdmissionAcceptance{
		Observation: observation,
		Revision:    revisionObservation,
		Decision:    decision,
		Binding:     binding,
	}, nil
}

func (s *Store) AcceptedAdmission(ctx context.Context, requestID corpus.AdmissionRequestID) (corpus.AcceptedAdmissionRecord, error) {
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return corpus.AcceptedAdmissionRecord{}, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)

	var record corpus.AcceptedAdmissionRecord
	var resolutionJSON, decidedText string
	var found bool
	err = sqlitex.Execute(conn,
		"SELECT observation_id, artifact_id, identity_domain, provider_id, native_object_id, decision_state, policy_id, resolution_json, decided_at FROM accepted_artifact_admissions WHERE request_id = ?1",
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
	return record, nil
}

func (s *Store) ProviderArtifactBinding(
	ctx context.Context,
	identityDomain string,
	providerID corpus.ProviderID,
	objectID corpus.ProviderObjectID,
) (corpus.ProviderArtifactBinding, error) {
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
		return corpus.ProviderArtifactBinding{}, fmt.Errorf(
			"%w: %s/%s/%s",
			ErrProviderArtifactBindingNotFound,
			identityDomain,
			providerID,
			objectID,
		)
	}
	return binding, nil
}

func admissionRequestExistsConn(conn *sqlite.Conn, requestID corpus.AdmissionRequestID) (bool, error) {
	var exists bool
	if err := sqlitex.Execute(conn,
		"SELECT 1 FROM accepted_artifact_admissions WHERE request_id = ?1 LIMIT 1",
		&sqlitex.ExecOptions{
			Args: []any{string(requestID)},
			ResultFunc: func(*sqlite.Stmt) error {
				exists = true
				return nil
			},
		}); err != nil {
		return false, fmt.Errorf("query Artifact admission request: %w", err)
	}
	return exists, nil
}

func providerArtifactBindingConn(
	conn *sqlite.Conn,
	identityDomain string,
	providerID corpus.ProviderID,
	objectID corpus.ProviderObjectID,
) (bool, corpus.ProviderArtifactBinding, error) {
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
