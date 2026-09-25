package sqlitestate

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

var (
	ErrInvalidIdentityMutationRequest    = errors.New("invalid identity mutation request")
	ErrIdentityMutationParameterMismatch = errors.New("identity mutation request parameter mismatch")
	ErrIdentityMutationRequestNotFound   = errors.New("identity mutation request not found")
	ErrIdentityAuthoritySetNotFound      = errors.New("identity authority set not found")
	ErrInvalidIdentityAuthoritySet       = errors.New("invalid identity authority set")
)

type identityMutationRequestRecord struct {
	RequestID       corpus.IdentityMutationRequestID
	Kind            corpus.IdentityMutationKind
	Fingerprint     corpus.IdentityMutationFingerprint
	AuthoritySetID  corpus.IdentityAuthoritySetID
	ObservationID   corpus.ObservationID
	ArtifactID      corpus.ArtifactID
	RevisionID      corpus.RevisionID
	RevisionCreated bool
	DecisionKind    string
	DecisionID      string
	AcceptedAt      time.Time
}

func validateIdentityMutationRequest(request corpus.IdentityMutationRequest, requireContentForRegular bool) error {
	if strings.TrimSpace(string(request.ID)) == "" ||
		request.ScanID == "" ||
		request.AuthoritySetID == "" ||
		request.DecidedAt.IsZero() {
		return ErrInvalidIdentityMutationRequest
	}
	if err := validateObservationInput(request.Observation); err != nil {
		return err
	}
	if request.Observation.AssignmentState != corpus.AssignmentUnresolved ||
		request.Observation.ArtifactID != "" ||
		request.Observation.RevisionID != "" {
		return fmt.Errorf("%w: observation must be unresolved", ErrInvalidIdentityMutationRequest)
	}
	if request.Observation.ProviderObject.IdentityState != corpus.ObjectIdentityObserved ||
		request.Observation.ProviderObject.ID == "" {
		return fmt.Errorf("%w: hardened mutation requires observed provider identity", ErrInvalidIdentityMutationRequest)
	}
	switch request.Observation.Kind {
	case corpus.EntryRegularFile:
		if request.ContentEvidence == nil {
			if requireContentForRegular {
				return fmt.Errorf("%w: regular SAME requires content evidence", ErrInvalidIdentityMutationRequest)
			}
			return nil
		}
		if err := corpus.ValidateContentEvidence(*request.ContentEvidence); err != nil {
			return err
		}
		if request.ContentEvidence.Size != request.Observation.Size {
			return fmt.Errorf("%w: evidence size mismatch", ErrInvalidIdentityMutationRequest)
		}
	default:
		if request.ContentEvidence != nil {
			return fmt.Errorf("%w: non-regular entry has content evidence", ErrInvalidIdentityMutationRequest)
		}
	}
	return nil
}

func validateAuthorityScope(set corpus.IdentityAuthoritySet, scan corpus.ScanSession, input corpus.ObservationRecordInput) error {
	if set.ProviderID != scan.ProviderID ||
		set.ScopeID != scan.Root ||
		input.ProviderObject.ProviderID != scan.ProviderID ||
		input.ProviderObject.ID != set.CurrentObjectID {
		return fmt.Errorf("%w: authority/input/scan mismatch", ErrScanScopeMismatch)
	}
	for _, locator := range input.Locators {
		if locator.ProviderID != scan.ProviderID || locator.Root != scan.Root {
			return fmt.Errorf("%w: locator=%#v", ErrScanScopeMismatch, locator)
		}
	}
	return nil
}

func identityMutationRequestConn(conn *sqlite.Conn, id corpus.IdentityMutationRequestID) (identityMutationRequestRecord, bool, error) {
	var record identityMutationRequestRecord
	var acceptedText string
	var revisionCreated int64
	var found bool
	err := sqlitex.Execute(conn,
		"SELECT operation_kind, fingerprint_version, fingerprint_sha256, authority_set_id, observation_id, artifact_id, COALESCE(revision_id, ''), revision_created, decision_kind, decision_id, accepted_at FROM identity_mutation_requests WHERE request_id = ?1",
		&sqlitex.ExecOptions{
			Args: []any{string(id)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				found = true
				record.RequestID = id
				record.Kind = corpus.IdentityMutationKind(stmt.ColumnText(0))
				record.Fingerprint.Version = stmt.ColumnText(1)
				record.Fingerprint.SHA256 = stmt.ColumnText(2)
				record.AuthoritySetID = corpus.IdentityAuthoritySetID(stmt.ColumnText(3))
				record.ObservationID = corpus.ObservationID(stmt.ColumnText(4))
				record.ArtifactID = corpus.ArtifactID(stmt.ColumnText(5))
				record.RevisionID = corpus.RevisionID(stmt.ColumnText(6))
				revisionCreated = stmt.ColumnInt64(7)
				record.DecisionKind = stmt.ColumnText(8)
				record.DecisionID = stmt.ColumnText(9)
				acceptedText = stmt.ColumnText(10)
				return nil
			},
		})
	if err != nil {
		return identityMutationRequestRecord{}, false, fmt.Errorf("query identity mutation request: %w", err)
	}
	if !found {
		return identityMutationRequestRecord{}, false, nil
	}
	record.RevisionCreated = revisionCreated != 0
	record.AcceptedAt, err = time.Parse(time.RFC3339Nano, acceptedText)
	if err != nil {
		return identityMutationRequestRecord{}, false, fmt.Errorf("parse identity mutation time: %w", err)
	}
	return record, true, nil
}

func reconcileExistingIdentityMutation(record identityMutationRequestRecord, kind corpus.IdentityMutationKind, fingerprint corpus.IdentityMutationFingerprint) error {
	if record.Kind != kind ||
		record.Fingerprint.Version != fingerprint.Version ||
		record.Fingerprint.SHA256 != fingerprint.SHA256 {
		return fmt.Errorf("%w: request=%s", ErrIdentityMutationParameterMismatch, record.RequestID)
	}
	return nil
}

func insertIdentityMutationRequestConn(conn *sqlite.Conn, record identityMutationRequestRecord) error {
	var revisionID any
	if record.RevisionID != "" {
		revisionID = string(record.RevisionID)
	}
	created := int64(0)
	if record.RevisionCreated {
		created = 1
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO identity_mutation_requests (request_id, operation_kind, fingerprint_version, fingerprint_sha256, authority_set_id, observation_id, artifact_id, revision_id, revision_created, decision_kind, decision_id, accepted_at) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12)",
		&sqlitex.ExecOptions{Args: []any{
			string(record.RequestID), string(record.Kind), record.Fingerprint.Version,
			record.Fingerprint.SHA256, string(record.AuthoritySetID), string(record.ObservationID),
			string(record.ArtifactID), revisionID, created, record.DecisionKind, record.DecisionID,
			record.AcceptedAt.UTC().Format(time.RFC3339Nano),
		}}); err != nil {
		return fmt.Errorf("insert identity mutation request: %w", err)
	}
	return nil
}

func (s *Store) revisionRecordByID(ctx context.Context, artifactID corpus.ArtifactID, revisionID corpus.RevisionID) (corpus.RevisionRecord, error) {
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return corpus.RevisionRecord{}, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)
	var record corpus.RevisionRecord
	var found bool
	err = sqlitex.Execute(conn,
		"SELECT sequence, content_algorithm, content_digest, content_size FROM revisions WHERE revision_id = ?1 AND artifact_id = ?2",
		&sqlitex.ExecOptions{
			Args: []any{string(revisionID), string(artifactID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				found = true
				record = corpus.RevisionRecord{
					Revision: corpus.Revision{ID: revisionID, ArtifactID: artifactID},
					Sequence: uint64(stmt.ColumnInt64(0)),
					Evidence: corpus.ContentEvidence{
						Algorithm: stmt.ColumnText(1),
						Digest: stmt.ColumnText(2),
						Size: stmt.ColumnInt64(3),
					},
				}
				return nil
			},
		})
	if err != nil {
		return corpus.RevisionRecord{}, fmt.Errorf("query Revision by ID: %w", err)
	}
	if !found {
		return corpus.RevisionRecord{}, fmt.Errorf("%w: revision=%s", corpus.ErrArtifactNotFound, revisionID)
	}
	return record, nil
}
