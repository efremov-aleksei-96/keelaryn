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
	ErrInvalidScan            = errors.New("invalid scan session")
	ErrScanNotFound           = errors.New("scan session not found")
	ErrScanNotOpen            = errors.New("scan session is not open")\n\tErrScanNotComplete        = errors.New("scan session is not complete")
	ErrScanScopeMismatch      = errors.New("observation does not match scan scope")
	ErrAmbiguousScanAuthority = errors.New("ambiguous current COMPLETE scan authority")
)

func (s *Store) StartScan(ctx context.Context, providerID corpus.ProviderID, root string, startedAt time.Time) (corpus.ScanSession, error) {
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return corpus.ScanSession{}, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)
	return s.startScanConn(conn, providerID, root, startedAt)
}

func (s *Store) startScanConn(
	conn *sqlite.Conn,
	providerID corpus.ProviderID,
	root string,
	startedAt time.Time,
) (corpus.ScanSession, error) {
	if providerID == "" || root == "" || startedAt.IsZero() {
		return corpus.ScanSession{}, ErrInvalidScan
	}
	scan := corpus.ScanSession{
		ID:         corpus.ScanSessionID("scan_" + uuid.NewString()),
		ProviderID: providerID,
		Root:       root,
		Status:     corpus.ScanOpen,
		StartedAt:  startedAt.UTC(),
	}
	startedText := scan.StartedAt.Format(time.RFC3339Nano)
	release, err := s.authorizeScanWriteConn(conn, scanWriteAuthorization{
		phase:      "START",
		scanID:     scan.ID,
		providerID: scan.ProviderID,
		root:       scan.Root,
		status:     scan.Status,
		startedAt:  startedText,
	})
	if err != nil {
		return corpus.ScanSession{}, err
	}
	writeErr := sqlitex.Execute(conn,
		"INSERT INTO scan_sessions (scan_id, provider_id, root, status, started_at, finished_at) VALUES (?1, ?2, ?3, 'OPEN', ?4, NULL)",
		&sqlitex.ExecOptions{Args: []any{
			string(scan.ID),
			string(scan.ProviderID),
			scan.Root,
			startedText,
		}})
	release()
	if writeErr != nil {
		return corpus.ScanSession{}, fmt.Errorf("insert scan session: %w", writeErr)
	}
	return scan, nil
}

func (s *Store) RecordObservationInScan(ctx context.Context, scanID corpus.ScanSessionID, input corpus.ObservationRecordInput) (out corpus.ObservationRecord, err error) {
	if err := validateObservationInput(input); err != nil {
		return corpus.ObservationRecord{}, err
	}
	if input.AssignmentState != corpus.AssignmentUnresolved {
		return corpus.ObservationRecord{}, fmt.Errorf("%w: scan Observation recording is unresolved-only", ErrInvalidObservation)
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
	return s.recordObservationConn(conn, scanID, input)
}

func (s *Store) CompleteScan(ctx context.Context, scanID corpus.ScanSessionID, finishedAt time.Time) error {
	return s.finishScan(ctx, scanID, corpus.ScanComplete, finishedAt, false)
}

func (s *Store) AbortScan(ctx context.Context, scanID corpus.ScanSessionID, finishedAt time.Time) error {
	return s.finishScan(ctx, scanID, corpus.ScanAborted, finishedAt, true)
}

func (s *Store) finishScan(
	ctx context.Context,
	scanID corpus.ScanSessionID,
	status corpus.ScanStatus,
	finishedAt time.Time,
	allowRemoteCompletion bool,
) (err error) {
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
	return s.finishScanConn(conn, scanID, status, finishedAt, allowRemoteCompletion)
}

func (s *Store) finishScanConn(
	conn *sqlite.Conn,
	scanID corpus.ScanSessionID,
	status corpus.ScanStatus,
	finishedAt time.Time,
	allowRemoteCompletion bool,
) error {
	if scanID == "" || finishedAt.IsZero() || (status != corpus.ScanComplete && status != corpus.ScanAborted) {
		return ErrInvalidScan
	}
	scan, err := scanSessionConn(conn, scanID)
	if err != nil {
		return err
	}
	if scan.Status != corpus.ScanOpen {
		return fmt.Errorf("%w: %s", ErrScanNotOpen, scanID)
	}
	if status == corpus.ScanComplete && !allowRemoteCompletion {
		remote, err := remoteScanSourceExistsConn(conn, scanID)
		if err != nil {
			return err
		}
		if remote {
			return ErrRemoteHistoryScanRequiresGuardedCompletion
		}
		remoteRoot, err := remoteScanAuthorityExistsForRootConn(conn, scan.ProviderID, scan.Root)
		if err != nil {
			return err
		}
		if remoteRoot {
			return ErrRemoteHistoryRootRequiresSourceBoundScan
		}
	}
	if finishedAt.UTC().Before(scan.StartedAt) {
		return fmt.Errorf("%w: finish before start", ErrInvalidScan)
	}
	finishedText := finishedAt.UTC().Format(time.RFC3339Nano)
	release, err := s.authorizeScanWriteConn(conn, scanWriteAuthorization{
		phase:      "FINISH",
		scanID:     scanID,
		providerID: scan.ProviderID,
		root:       scan.Root,
		status:     status,
		startedAt:  scan.StartedAt.UTC().Format(time.RFC3339Nano),
		finishedAt: finishedText,
	})
	if err != nil {
		return err
	}
	writeErr := sqlitex.Execute(conn,
		"UPDATE scan_sessions SET status = ?1, finished_at = ?2 WHERE scan_id = ?3 AND status = 'OPEN'",
		&sqlitex.ExecOptions{Args: []any{
			string(status),
			finishedText,
			string(scanID),
		}})
	release()
	if writeErr != nil {
		return fmt.Errorf("finish scan: %w", writeErr)
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

// LatestCompleteScan returns the current COMPLETE scan authority for one
// provider/root scope without mutating state. It is used by runtime recovery
// to distinguish "bootstrap never committed" from "bootstrap committed and a
// later derived step was interrupted", including an empty corpus.
func (s *Store) LatestCompleteScan(
	ctx context.Context,
	providerID corpus.ProviderID,
	root string,
) (corpus.ScanSession, bool, error) {
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return corpus.ScanSession{}, false, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)

	scanID, found, err := latestCompleteScanID(conn, providerID, root)
	if err != nil {
		return corpus.ScanSession{}, false, err
	}
	if !found {
		return corpus.ScanSession{}, false, nil
	}
	scan, err := scanSessionConn(conn, scanID)
	if err != nil {
		return corpus.ScanSession{}, false, err
	}
	return scan, true, nil
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
	return inventoryAtScanConn(conn, scanID)
}

// InventoryAtScan reads inventory from one exact COMPLETE scan without
// interpreting that scan as the current provider/root authority.
func (s *Store) InventoryAtScan(ctx context.Context, scanID corpus.ScanSessionID) ([]corpus.InventoryEntry, error) {
	if scanID == "" {
		return nil, ErrInvalidScan
	}
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return nil, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)

	scan, err := scanSessionConn(conn, scanID)
	if err != nil {
		return nil, err
	}
	if scan.Status != corpus.ScanComplete {
		return nil, fmt.Errorf("%w: %s status=%s", ErrScanNotComplete, scanID, scan.Status)
	}
	return inventoryAtScanConn(conn, scanID)
}

func inventoryAtScanConn(conn *sqlite.Conn, scanID corpus.ScanSessionID) ([]corpus.InventoryEntry, error) {
	var entries []corpus.InventoryEntry
	err := sqlitex.Execute(conn,
		"SELECT o.observation_id, COALESCE(o.artifact_id, ''), COALESCE(o.revision_id, ''), o.assignment_state, l.provider_id, l.root, l.path, o.kind, o.size, o.size_known, o.mode, o.mode_known, o.modified_at, o.modified_at_known FROM observations o JOIN locators l ON l.observation_id = o.observation_id WHERE o.scan_id = ?1 ORDER BY l.path, o.observation_id",
		&sqlitex.ExecOptions{
			Args: []any{string(scanID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				var size *int64
				if stmt.ColumnInt64(9) == 1 {
					size = corpus.KnownSize(stmt.ColumnInt64(8))
				}
				var mode *uint32
				if stmt.ColumnInt64(11) == 1 {
					mode = corpus.KnownMode(uint32(stmt.ColumnInt64(10)))
				}
				var modifiedAt *time.Time
				if stmt.ColumnInt64(13) == 1 {
					parsed, err := time.Parse(time.RFC3339Nano, stmt.ColumnText(12))
					if err != nil {
						return err
					}
					modifiedAt = corpus.KnownModifiedAt(parsed)
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
					Size:       size,
					Mode:       mode,
					ModifiedAt: modifiedAt,
				})
				return nil
			},
		})
	if err != nil {
		return nil, fmt.Errorf("query inventory for scan %s: %w", scanID, err)
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
	type candidate struct {
		id       corpus.ScanSessionID
		finished time.Time
		order    int64
		ordered  bool
	}
	var latestFinished time.Time
	var latest []candidate

	err := sqlitex.Execute(conn,
		"SELECT s.scan_id, s.finished_at, c.completion_order FROM scan_sessions s LEFT JOIN scan_completion_authorities c ON c.scan_id=s.scan_id WHERE s.provider_id=?1 AND s.root=?2 AND s.status='COMPLETE'",
		&sqlitex.ExecOptions{
			Args: []any{string(providerID), root},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				id := corpus.ScanSessionID(stmt.ColumnText(0))
				finished, err := time.Parse(time.RFC3339Nano, stmt.ColumnText(1))
				if err != nil {
					return fmt.Errorf("parse COMPLETE scan finish %s: %w", id, err)
				}
				current := candidate{id: id, finished: finished}
				if !stmt.ColumnIsNull(2) {
					current.order = stmt.ColumnInt64(2)
					current.ordered = true
				}
				if len(latest) == 0 || finished.After(latestFinished) {
					latestFinished = finished
					latest = []candidate{current}
				} else if finished.Equal(latestFinished) {
					latest = append(latest, current)
				}
				return nil
			},
		})
	if err != nil {
		return "", false, fmt.Errorf("query latest complete scan: %w", err)
	}
	if len(latest) == 0 {
		return "", false, nil
	}
	if len(latest) == 1 {
		return latest[0].id, true, nil
	}

	var ordered candidate
	var hasOrdered bool
	for _, current := range latest {
		if current.ordered && (!hasOrdered || current.order > ordered.order) {
			ordered = current
			hasOrdered = true
		}
	}
	if hasOrdered {
		return ordered.id, true, nil
	}
	return "", false, fmt.Errorf(
		"%w: provider=%s root=%s finished_at=%s candidates=%d",
		ErrAmbiguousScanAuthority,
		providerID,
		root,
		latestFinished.UTC().Format(time.RFC3339Nano),
		len(latest),
	)
}
