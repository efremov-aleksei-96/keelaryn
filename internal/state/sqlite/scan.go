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

var (
	ErrInvalidScan          = errors.New("invalid scan session")
	ErrScanNotFound         = errors.New("scan session not found")
	ErrScanNotOpen          = errors.New("scan session is not open")
	ErrScanScopeMismatch    = errors.New("observation does not match scan scope")
)

func (s *Store) StartScan(ctx context.Context, providerID corpus.ProviderID, root string, startedAt time.Time) (corpus.ScanSession, error) {
	if providerID == "" || root == "" || startedAt.IsZero() {
		return corpus.ScanSession{}, ErrInvalidScan
	}
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return corpus.ScanSession{}, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)

	scan := corpus.ScanSession{
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
		return corpus.ScanSession{}, fmt.Errorf("insert scan session: %w", err)
	}
	return scan, nil
}

func (s *Store) RecordObservationInScan(ctx context.Context, scanID corpus.ScanSessionID, input corpus.ObservationRecordInput) (out corpus.ObservationRecord, err error) {
	if err := validateObservationInput(input); err != nil {
		return corpus.ObservationRecord{}, err
	}
	if scanID == "" {
		return corpus.ObservationRecord{}, ErrInvalidScan
	}

	conn, err := s.pool.Get(ctx)
	if err != nil {
		return corpus.ObservationRecord{}, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)

	end, err := sqlitex.ImmediateTransaction(conn)
	if err != nil {
		return corpus.ObservationRecord{}, fmt.Errorf("begin scan Observation transaction: %w", err)
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
	return recordObservationConn(conn, scanID, input)
}

func (s *Store) CompleteScan(ctx context.Context, scanID corpus.ScanSessionID, finishedAt time.Time) error {
	return s.finishScan(ctx, scanID, corpus.ScanComplete, finishedAt)
}

func (s *Store) AbortScan(ctx context.Context, scanID corpus.ScanSessionID, finishedAt time.Time) error {
	return s.finishScan(ctx, scanID, corpus.ScanAborted, finishedAt)
}

func (s *Store) finishScan(ctx context.Context, scanID corpus.ScanSessionID, status corpus.ScanStatus, finishedAt time.Time) error {
	if scanID == "" || finishedAt.IsZero() || (status != corpus.ScanComplete && status != corpus.ScanAborted) {
		return ErrInvalidScan
	}
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)

	end, err := sqlitex.ImmediateTransaction(conn)
	if err != nil {
		return fmt.Errorf("begin scan finish transaction: %w", err)
	}
	defer end(&err)

	scan, err := scanSessionConn(conn, scanID)
	if err != nil {
		return err
	}
	if scan.Status != corpus.ScanOpen {
		return fmt.Errorf("%w: %s", ErrScanNotOpen, scanID)
	}
	if finishedAt.UTC().Before(scan.StartedAt) {
		return fmt.Errorf("%w: finish before start", ErrInvalidScan)
	}
	if err := sqlitex.Execute(conn,
		"UPDATE scan_sessions SET status = ?1, finished_at = ?2 WHERE scan_id = ?3 AND status = 'OPEN'",
		&sqlitex.ExecOptions{Args: []any{
			string(status),
			finishedAt.UTC().Format(time.RFC3339Nano),
			string(scanID),
		}}); err != nil {
		return fmt.Errorf("finish scan: %w", err)
	}
	if conn.Changes() != 1 {
		return fmt.Errorf("%w: %s", ErrScanNotOpen, scanID)
	}
	return nil
}

func (s *Store) ScanSession(ctx context.Context, scanID corpus.ScanSessionID) (corpus.ScanSession, error) {
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return corpus.ScanSession{}, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)
	return scanSessionConn(conn, scanID)
}

func scanSessionConn(conn *sqlite.Conn, scanID corpus.ScanSessionID) (corpus.ScanSession, error) {
	var scan corpus.ScanSession
	var found bool
	var startedText, finishedText string
	err := sqlitex.Execute(conn,
		"SELECT provider_id, root, status, started_at, COALESCE(finished_at, '') FROM scan_sessions WHERE scan_id = ?1",
		&sqlitex.ExecOptions{
			Args: []any{string(scanID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				found = true
				scan.ID = scanID
				scan.ProviderID = corpus.ProviderID(stmt.ColumnText(0))
				scan.Root = stmt.ColumnText(1)
				scan.Status = corpus.ScanStatus(stmt.ColumnText(2))
				startedText = stmt.ColumnText(3)
				finishedText = stmt.ColumnText(4)
				return nil
			},
		})
	if err != nil {
		return corpus.ScanSession{}, fmt.Errorf("query scan: %w", err)
	}
	if !found {
		return corpus.ScanSession{}, fmt.Errorf("%w: %s", ErrScanNotFound, scanID)
	}
	scan.StartedAt, err = time.Parse(time.RFC3339Nano, startedText)
	if err != nil {
		return corpus.ScanSession{}, fmt.Errorf("parse scan start: %w", err)
	}
	if finishedText != "" {
		scan.FinishedAt, err = time.Parse(time.RFC3339Nano, finishedText)
		if err != nil {
			return corpus.ScanSession{}, fmt.Errorf("parse scan finish: %w", err)
		}
	}
	return scan, nil
}

func (s *Store) Inventory(ctx context.Context, providerID corpus.ProviderID, root string) ([]corpus.InventoryEntry, error) {
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return nil, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)

	scanID, found, err := latestCompleteScanID(conn, providerID, root)
	if err != nil {
		return nil, err
	}
	if !found {
		return nil, nil
	}

	var entries []corpus.InventoryEntry
	err = sqlitex.Execute(conn,
		"SELECT o.observation_id, COALESCE(o.artifact_id, ''), COALESCE(o.revision_id, ''), o.assignment_state, l.provider_id, l.root, l.path, o.kind, o.size, o.modified_at FROM observations o JOIN locators l ON l.observation_id = o.observation_id WHERE o.scan_id = ?1 ORDER BY l.path, o.observation_id",
		&sqlitex.ExecOptions{
			Args: []any{string(scanID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				modifiedAt, err := time.Parse(time.RFC3339Nano, stmt.ColumnText(9))
				if err != nil {
					return err
				}
				entries = append(entries, corpus.InventoryEntry{
					ScanID:          scanID,
					ObservationID:   corpus.ObservationID(stmt.ColumnText(0)),
					ArtifactID:      corpus.ArtifactID(stmt.ColumnText(1)),
					RevisionID:      corpus.RevisionID(stmt.ColumnText(2)),
					AssignmentState: corpus.AssignmentState(stmt.ColumnText(3)),
					Locator: corpus.Locator{
						ProviderID: corpus.ProviderID(stmt.ColumnText(4)),
						Root:       stmt.ColumnText(5),
						Path:       stmt.ColumnText(6),
					},
					Kind:       corpus.EntryKind(stmt.ColumnText(7)),
					Size:       stmt.ColumnInt64(8),
					ModifiedAt: modifiedAt,
				})
				return nil
			},
		})
	if err != nil {
		return nil, fmt.Errorf("query inventory: %w", err)
	}
	return entries, nil
}

func (s *Store) CurrentArtifactLocators(ctx context.Context, providerID corpus.ProviderID, root string, artifactID corpus.ArtifactID) ([]corpus.Locator, error) {
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return nil, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)

	scanID, found, err := latestCompleteScanID(conn, providerID, root)
	if err != nil {
		return nil, err
	}
	if !found {
		return nil, nil
	}

	var locators []corpus.Locator
	err = sqlitex.Execute(conn,
		"SELECT l.provider_id, l.root, l.path FROM observations o JOIN locators l ON l.observation_id = o.observation_id WHERE o.scan_id = ?1 AND o.assignment_state = 'ASSIGNED' AND o.artifact_id = ?2 ORDER BY l.path",
		&sqlitex.ExecOptions{
			Args: []any{string(scanID), string(artifactID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				locators = append(locators, corpus.Locator{
					ProviderID: corpus.ProviderID(stmt.ColumnText(0)),
					Root:       stmt.ColumnText(1),
					Path:       stmt.ColumnText(2),
				})
				return nil
			},
		})
	if err != nil {
		return nil, fmt.Errorf("query current Artifact locators: %w", err)
	}
	return locators, nil
}

func latestCompleteScanID(conn *sqlite.Conn, providerID corpus.ProviderID, root string) (corpus.ScanSessionID, bool, error) {
	var scanID corpus.ScanSessionID
	var found bool
	err := sqlitex.Execute(conn,
		"SELECT scan_id FROM scan_sessions WHERE provider_id = ?1 AND root = ?2 AND status = 'COMPLETE' ORDER BY finished_at DESC, scan_id DESC LIMIT 1",
		&sqlitex.ExecOptions{
			Args: []any{string(providerID), root},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				found = true
				scanID = corpus.ScanSessionID(stmt.ColumnText(0))
				return nil
			},
		})
	if err != nil {
		return "", false, fmt.Errorf("query latest complete scan: %w", err)
	}
	return scanID, found, nil
}
