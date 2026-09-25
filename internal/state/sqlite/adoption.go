package sqlitestate

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/google/uuid"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

var ErrObservationHistoryExists = errors.New("observation history already exists for provider/root")

// StartBootstrapScan atomically proves that the scope has no prior observed
// object history before opening a scan eligible for first-observation adoption.
func (s *Store) StartBootstrapScan(ctx context.Context, providerID corpus.ProviderID, root string, startedAt time.Time) (scan corpus.ScanSession, err error) {
	if providerID == "" || root == "" || startedAt.IsZero() {
		return corpus.ScanSession{}, ErrInvalidScan
	}

	conn, err := s.pool.Get(ctx)
	if err != nil {
		return corpus.ScanSession{}, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)

	end, err := sqlitex.ImmediateTransaction(conn)
	if err != nil {
		return corpus.ScanSession{}, fmt.Errorf("begin bootstrap scan transaction: %w", err)
	}
	defer end(&err)

	history, err := observationHistoryExistsConn(conn, providerID, root)
	if err != nil {
		return corpus.ScanSession{}, err
	}
	if history {
		return corpus.ScanSession{}, fmt.Errorf("%w: %s/%s", ErrObservationHistoryExists, providerID, root)
	}

	scan = corpus.ScanSession{
		ID:         corpus.ScanSessionID("scan_" + uuid.NewString()),
		ProviderID: providerID,
		Root:       root,
		Status:     corpus.ScanOpen,
		StartedAt:  startedAt.UTC(),
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO scan_sessions (scan_id, provider_id, root, status, started_at, finished_at) VALUES (?1, ?2, ?3, 'OPEN', ?4, NULL)",
		&sqlitex.ExecOptions{Args: []any{
			string(scan.ID),
			string(scan.ProviderID),
			scan.Root,
			scan.StartedAt.Format(time.RFC3339Nano),
		}}); err != nil {
		return corpus.ScanSession{}, fmt.Errorf("insert bootstrap scan: %w", err)
	}
	return scan, nil
}

func observationHistoryExistsConn(conn *sqlite.Conn, providerID corpus.ProviderID, root string) (bool, error) {
	var exists bool
	err := sqlitex.Execute(conn,
		"SELECT 1 FROM observations o JOIN locators l ON l.observation_id = o.observation_id WHERE l.provider_id = ?1 AND l.root = ?2 LIMIT 1",
		&sqlitex.ExecOptions{
			Args: []any{string(providerID), root},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				exists = true
				return nil
			},
		})
	if err != nil {
		return false, fmt.Errorf("query observation history: %w", err)
	}
	return exists, nil
}

// AdoptObservationInScan creates one new Artifact, optional Revision 1, and the
// assigned Observation in a single transaction.
//
// The caller may use this only after a bootstrap boundary has established that
// the occurrence has no prior continuity candidate.
func (s *Store) AdoptObservationInScan(ctx context.Context, scanID corpus.ScanSessionID, input corpus.ObservationRecordInput, evidence *corpus.ContentEvidence) (out corpus.ObservationRecord, err error) {
	if err := validateObservationInput(input); err != nil {
		return corpus.ObservationRecord{}, err
	}
	if input.AssignmentState != corpus.AssignmentUnresolved || input.ArtifactID != "" || input.RevisionID != "" {
		return corpus.ObservationRecord{}, fmt.Errorf("%w: adoption input must be unresolved", ErrInvalidObservation)
	}
	if evidence != nil {
		if input.Kind != corpus.EntryRegularFile {
			return corpus.ObservationRecord{}, fmt.Errorf("%w: content evidence on non-regular entry", ErrInvalidObservation)
		}
		if err := corpus.ValidateContentEvidence(*evidence); err != nil {
			return corpus.ObservationRecord{}, err
		}
		if evidence.Size != input.Size {
			return corpus.ObservationRecord{}, fmt.Errorf("%w: content evidence size=%d observation size=%d", ErrInvalidObservation, evidence.Size, input.Size)
		}
	}

	conn, err := s.pool.Get(ctx)
	if err != nil {
		return corpus.ObservationRecord{}, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)

	end, err := sqlitex.ImmediateTransaction(conn)
	if err != nil {
		return corpus.ObservationRecord{}, fmt.Errorf("begin adoption transaction: %w", err)
	}
	defer end(&err)

	scan, err := scanSessionConn(conn, scanID)
	if err != nil {
		return corpus.ObservationRecord{}, err
	}
	if scan.Status != corpus.ScanOpen {
		return corpus.ObservationRecord{}, fmt.Errorf("%w: %s", ErrScanNotOpen, scanID)
	}
	if input.ProviderObject.ProviderID != scan.ProviderID {
		return corpus.ObservationRecord{}, fmt.Errorf("%w: provider=%s scan_provider=%s", ErrScanScopeMismatch, input.ProviderObject.ProviderID, scan.ProviderID)
	}
	for _, locator := range input.Locators {
		if locator.ProviderID != scan.ProviderID || locator.Root != scan.Root {
			return corpus.ObservationRecord{}, fmt.Errorf("%w: locator=%#v scan=%s/%s", ErrScanScopeMismatch, locator, scan.ProviderID, scan.Root)
		}
	}

	artifactID := corpus.ArtifactID("art_" + uuid.NewString())
	if err := sqlitex.Execute(conn,
		"INSERT INTO artifacts (artifact_id) VALUES (?1)",
		&sqlitex.ExecOptions{Args: []any{string(artifactID)}}); err != nil {
		return corpus.ObservationRecord{}, fmt.Errorf("insert adopted Artifact: %w", err)
	}

	var revisionID corpus.RevisionID
	if evidence != nil {
		revisionID = corpus.RevisionID("rev_" + uuid.NewString())
		if err := sqlitex.Execute(conn,
			"INSERT INTO revisions (revision_id, artifact_id, sequence, content_algorithm, content_digest, content_size) VALUES (?1, ?2, 1, ?3, ?4, ?5)",
			&sqlitex.ExecOptions{Args: []any{
				string(revisionID),
				string(artifactID),
				evidence.Algorithm,
				evidence.Digest,
				evidence.Size,
			}}); err != nil {
			return corpus.ObservationRecord{}, fmt.Errorf("insert adopted Revision: %w", err)
		}
	}

	input.ArtifactID = artifactID
	input.RevisionID = revisionID
	input.AssignmentState = corpus.AssignmentAssigned
	return recordObservationConn(conn, scanID, input)
}
