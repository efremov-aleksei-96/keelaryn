package sqlitestate

import (
	"encoding/json"
	"errors"
	"fmt"
	"strconv"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

const (
	historicalContentEvidenceValidationFunction = "keelaryn_historical_content_evidence_valid"
	historicalContinuityResolutionValidationFunction = "keelaryn_historical_continuity_resolution_valid"
	historicalAdmissionResolutionValidationFunction = "keelaryn_historical_admission_resolution_valid"
)

var ErrHistoricalCoreIdentityAuthorityInvalid = errors.New("historical core identity authority is invalid")

func registerHistoricalCoreIdentityValidationConn(conn *sqlite.Conn) error {
	if err := conn.CreateFunction(historicalContentEvidenceValidationFunction, &sqlite.FunctionImpl{
		NArgs: 3, Deterministic: true, AllowIndirect: true,
		Scalar: func(_ sqlite.Context, args []sqlite.Value) (sqlite.Value, error) {
			size, err := strconv.ParseInt(args[2].Text(), 10, 64)
			if err != nil {
				return sqlite.IntegerValue(0), nil
			}
			if err := corpus.ValidateContentEvidence(corpus.ContentEvidence{
				Algorithm: args[0].Text(), Digest: args[1].Text(), Size: size,
			}); err != nil {
				return sqlite.IntegerValue(0), nil
			}
			return sqlite.IntegerValue(1), nil
		},
	}); err != nil {
		return fmt.Errorf("register historical ContentEvidence validation: %w", err)
	}
	if err := conn.CreateFunction(historicalContinuityResolutionValidationFunction, &sqlite.FunctionImpl{
		NArgs: 3, Deterministic: true, AllowIndirect: true,
		Scalar: func(_ sqlite.Context, args []sqlite.Value) (sqlite.Value, error) {
			if historicalContinuityResolutionValid(args[0].Text(), args[1].Text(), args[2].Text()) {
				return sqlite.IntegerValue(1), nil
			}
			return sqlite.IntegerValue(0), nil
		},
	}); err != nil {
		return fmt.Errorf("register historical continuity resolution validation: %w", err)
	}
	if err := conn.CreateFunction(historicalAdmissionResolutionValidationFunction, &sqlite.FunctionImpl{
		NArgs: 6, Deterministic: true, AllowIndirect: true,
		Scalar: func(_ sqlite.Context, args []sqlite.Value) (sqlite.Value, error) {
			if historicalAdmissionResolutionValid(
				args[0].Text(), args[1].Text(), args[2].Text(),
				args[3].Text(), args[4].Text(), args[5].Text(),
			) {
				return sqlite.IntegerValue(1), nil
			}
			return sqlite.IntegerValue(0), nil
		},
	}); err != nil {
		return fmt.Errorf("register historical admission resolution validation: %w", err)
	}
	return nil
}

func historicalContinuityResolutionValid(raw, state, artifactID string) bool {
	var resolution corpus.CandidateSetResolution
	if err := json.Unmarshal([]byte(raw), &resolution); err != nil {
		return false
	}
	if err := corpus.ValidateCandidateSetResolution(resolution); err != nil {
		return false
	}
	return state == string(corpus.CandidateSetResolvedSame) &&
		resolution.State == corpus.CandidateSetResolvedSame &&
		resolution.SelectedArtifactID == corpus.ArtifactID(artifactID)
}

func historicalAdmissionResolutionValid(raw, state, policyID, identityDomain, providerID, objectID string) bool {
	var resolution corpus.OccurrenceIdentityResolution
	if err := json.Unmarshal([]byte(raw), &resolution); err != nil {
		return false
	}
	if err := corpus.ValidateOccurrenceIdentityResolution(resolution); err != nil {
		return false
	}
	if state != string(corpus.OccurrenceIdentityResolvedNew) ||
		resolution.State != corpus.OccurrenceIdentityResolvedNew ||
		resolution.SelectedArtifactID != "" ||
		resolution.Universe == nil ||
		resolution.Universe.Coverage != corpus.CandidateUniverseComplete {
		return false
	}
	return resolution.Universe.PolicyID == policyID &&
		resolution.Universe.IdentityDomain == identityDomain &&
		string(resolution.Universe.ProviderID) == providerID &&
		string(resolution.Universe.CurrentObjectID) == objectID
}

func verifyHistoricalCoreIdentityAuthorityConn(conn *sqlite.Conn) error {
	var artifactIDs []string
	if err := sqlitex.Execute(conn, "SELECT artifact_id FROM artifacts ORDER BY artifact_id",
		&sqlitex.ExecOptions{ResultFunc: func(stmt *sqlite.Stmt) error {
			artifactIDs = append(artifactIDs, stmt.ColumnText(0))
			return nil
		}}); err != nil {
		return fmt.Errorf("%w: list Artifacts: %v", ErrHistoricalCoreIdentityAuthorityInvalid, err)
	}
	for _, id := range artifactIDs {
		if id == "" {
			return fmt.Errorf("%w: empty Artifact ID", ErrHistoricalCoreIdentityAuthorityInvalid)
		}
	}

	lastSequence := make(map[corpus.ArtifactID]uint64)
	if err := sqlitex.Execute(conn,
		"SELECT revision_id,artifact_id,sequence,content_algorithm,content_digest,content_size FROM revisions ORDER BY artifact_id,sequence",
		&sqlitex.ExecOptions{ResultFunc: func(stmt *sqlite.Stmt) error {
			revisionID := stmt.ColumnText(0)
			artifactID := corpus.ArtifactID(stmt.ColumnText(1))
			sequence := uint64(stmt.ColumnInt64(2))
			if revisionID == "" || artifactID == "" || sequence != lastSequence[artifactID]+1 {
				return ErrHistoricalCoreIdentityAuthorityInvalid
			}
			evidence := corpus.ContentEvidence{
				Algorithm: stmt.ColumnText(3), Digest: stmt.ColumnText(4), Size: stmt.ColumnInt64(5),
			}
			if err := corpus.ValidateContentEvidence(evidence); err != nil {
				return err
			}
			lastSequence[artifactID] = sequence
			return nil
		}}); err != nil {
		return fmt.Errorf("%w: Revision validation: %v", ErrHistoricalCoreIdentityAuthorityInvalid, err)
	}

	if err := sqlitex.Execute(conn,
		"SELECT identity_domain,provider_id,native_object_id,artifact_id,policy_id,accepted_at FROM provider_artifact_bindings ORDER BY identity_domain,provider_id,native_object_id",
		&sqlitex.ExecOptions{ResultFunc: func(stmt *sqlite.Stmt) error {
			valid, err := historicalProviderArtifactBindingValidConn(
				conn,
				stmt.ColumnText(0), corpus.ProviderID(stmt.ColumnText(1)),
				corpus.ProviderObjectID(stmt.ColumnText(2)), corpus.ArtifactID(stmt.ColumnText(3)),
				stmt.ColumnText(4), stmt.ColumnText(5),
			)
			if err != nil {
				return err
			}
			if !valid {
				return ErrHistoricalCoreIdentityAuthorityInvalid
			}
			return nil
		}}); err != nil {
		return fmt.Errorf("%w: provider binding validation: %v", ErrHistoricalCoreIdentityAuthorityInvalid, err)
	}

	if err := sqlitex.Execute(conn,
		"SELECT resolution_json,decision_state,artifact_id FROM accepted_continuity_decisions ORDER BY decision_id",
		&sqlitex.ExecOptions{ResultFunc: func(stmt *sqlite.Stmt) error {
			if !historicalContinuityResolutionValid(stmt.ColumnText(0), stmt.ColumnText(1), stmt.ColumnText(2)) {
				return ErrHistoricalCoreIdentityAuthorityInvalid
			}
			return nil
		}}); err != nil {
		return fmt.Errorf("%w: continuity resolution validation: %v", ErrHistoricalCoreIdentityAuthorityInvalid, err)
	}

	if err := sqlitex.Execute(conn,
		"SELECT resolution_json,decision_state,policy_id,identity_domain,provider_id,native_object_id FROM accepted_artifact_admissions ORDER BY request_id",
		&sqlitex.ExecOptions{ResultFunc: func(stmt *sqlite.Stmt) error {
			if !historicalAdmissionResolutionValid(
				stmt.ColumnText(0), stmt.ColumnText(1), stmt.ColumnText(2),
				stmt.ColumnText(3), stmt.ColumnText(4), stmt.ColumnText(5),
			) {
				return ErrHistoricalCoreIdentityAuthorityInvalid
			}
			return nil
		}}); err != nil {
		return fmt.Errorf("%w: admission resolution validation: %v", ErrHistoricalCoreIdentityAuthorityInvalid, err)
	}
	return nil
}

func historicalProviderArtifactBindingValidConn(
	conn *sqlite.Conn,
	identityDomain string,
	providerID corpus.ProviderID,
	objectID corpus.ProviderObjectID,
	artifactID corpus.ArtifactID,
	policyID string,
	acceptedAt string,
) (bool, error) {
	if identityDomain == "" || providerID == "" || objectID == "" || artifactID == "" || policyID == "" ||
		policyID == remoteHistoryLifetimeAuthorityPolicyV1 {
		return false, nil
	}
	parsed, err := time.Parse(time.RFC3339Nano, acceptedAt)
	if err != nil || acceptedAt != parsed.UTC().Format(time.RFC3339Nano) {
		return false, nil
	}
	var found bool
	if err := sqlitex.Execute(conn,
		"SELECT 1 FROM accepted_artifact_admissions WHERE identity_domain=?1 AND provider_id=?2 AND native_object_id=?3 AND artifact_id=?4 AND policy_id=?5 AND decided_at=?6 AND lifetime_segment_id IS NULL LIMIT 1",
		&sqlitex.ExecOptions{
			Args: []any{identityDomain, string(providerID), string(objectID), string(artifactID), policyID, acceptedAt},
			ResultFunc: func(*sqlite.Stmt) error { found = true; return nil },
		}); err != nil {
		return false, err
	}
	return found, nil
}
