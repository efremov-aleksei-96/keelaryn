package sqlitestate

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

var (
	ErrRemoteHistoryScanSourceNotFound            = errors.New("remote history scan source not found")
	ErrRemoteHistoryScanSourceConflict            = errors.New("remote history scan source conflicts with existing OPEN scan")
	ErrRemoteHistoryScanSourceAdvanced            = errors.New("remote history scan source publication is no longer current")
	ErrRemoteHistoryScanSourceClosed              = errors.New("remote history scan source generation is closed")
	ErrRemoteHistoryScanRequiresGuardedCompletion = errors.New("source-bound remote scan requires guarded completion")
)

func (s *Store) StartRemoteHistoryScan(
	ctx context.Context,
	scanRoot string,
	source remotehistory.RemoteScanSourceInput,
	startedAt time.Time,
) (scan corpus.ScanSession, replayed bool, err error) {
	if scanRoot == "" || startedAt.IsZero() {
		return corpus.ScanSession{}, false, ErrInvalidScan
	}
	if err := remotehistory.ValidateRemoteScanSourceInput(source); err != nil {
		return corpus.ScanSession{}, false, err
	}

	conn, err := s.pool.Get(ctx)
	if err != nil {
		return corpus.ScanSession{}, false, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)

	end, err := sqlitex.ImmediateTransaction(conn)
	if err != nil {
		return corpus.ScanSession{}, false, fmt.Errorf("begin remote scan start transaction: %w", err)
	}
	defer end(&err)

	if existing, found, err := matchingRemoteHistoryScanConn(conn, scanRoot, source); err != nil {
		return corpus.ScanSession{}, false, err
	} else if found {
		return existing, true, nil
	}

	generation, err := remoteHistoryGenerationConn(conn, source.GenerationID)
	if err != nil {
		return corpus.ScanSession{}, false, err
	}
	if generation.Status != remotehistory.HistoryGenerationActive {
		return corpus.ScanSession{}, false, ErrRemoteHistoryScanSourceClosed
	}
	if generation.CurrentSequence != source.PublicationSequence {
		return corpus.ScanSession{}, false, ErrRemoteHistoryScanSourceAdvanced
	}
	if open, found, err := openScanForProviderRootConn(conn, generation.Scope.ProviderID, scanRoot); err != nil {
		return corpus.ScanSession{}, false, err
	} else if found {
		return corpus.ScanSession{}, false, fmt.Errorf(
			"%w: scan=%s provider=%s root=%s",
			ErrRemoteHistoryScanSourceConflict,
			open.ID,
			open.ProviderID,
			open.Root,
		)
	}

	scan, err = startScanConn(conn, generation.Scope.ProviderID, scanRoot, startedAt.UTC())
	if err != nil {
		return corpus.ScanSession{}, false, err
	}
	binding := remotehistory.RemoteScanSource{
		ScanID:                scan.ID,
		RemoteScanSourceInput: source,
	}
	if err := insertRemoteScanSourceConn(conn, binding); err != nil {
		return corpus.ScanSession{}, false, err
	}
	return scan, false, nil
}

func (s *Store) RemoteHistoryScanSource(
	ctx context.Context,
	scanID corpus.ScanSessionID,
) (remotehistory.RemoteScanSource, error) {
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return remotehistory.RemoteScanSource{}, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)

	source, found, err := remoteScanSourceConn(conn, scanID)
	if err != nil {
		return remotehistory.RemoteScanSource{}, err
	}
	if !found {
		return remotehistory.RemoteScanSource{}, fmt.Errorf("%w: %s", ErrRemoteHistoryScanSourceNotFound, scanID)
	}
	return source, nil
}

func (s *Store) ReconcileRemoteHistoryScan(
	ctx context.Context,
	scanID corpus.ScanSessionID,
) (remotehistory.RemoteScanSourceState, error) {
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return "", fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)

	source, found, err := remoteScanSourceConn(conn, scanID)
	if err != nil {
		return "", err
	}
	if !found {
		return "", fmt.Errorf("%w: %s", ErrRemoteHistoryScanSourceNotFound, scanID)
	}
	generation, err := remoteHistoryGenerationConn(conn, source.GenerationID)
	if err != nil {
		return "", err
	}
	if generation.Status == remotehistory.HistoryGenerationClosed {
		return remotehistory.RemoteScanSourceClosed, nil
	}
	if generation.CurrentSequence == source.PublicationSequence {
		return remotehistory.RemoteScanSourceCurrent, nil
	}
	if generation.CurrentSequence > source.PublicationSequence {
		return remotehistory.RemoteScanSourceAdvanced, nil
	}
	return "", fmt.Errorf(
		"%w: generation=%s current=%d source=%d",
		ErrRemoteHistoryScanSourceAdvanced,
		generation.ID,
		generation.CurrentSequence,
		source.PublicationSequence,
	)
}

func (s *Store) CompleteRemoteHistoryScan(
	ctx context.Context,
	scanID corpus.ScanSessionID,
	finishedAt time.Time,
) (scan corpus.ScanSession, replayed bool, err error) {
	if scanID == "" || finishedAt.IsZero() {
		return corpus.ScanSession{}, false, ErrInvalidScan
	}
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return corpus.ScanSession{}, false, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)

	end, err := sqlitex.ImmediateTransaction(conn)
	if err != nil {
		return corpus.ScanSession{}, false, fmt.Errorf("begin remote scan completion transaction: %w", err)
	}
	defer end(&err)

	scan, err = scanSessionConn(conn, scanID)
	if err != nil {
		return corpus.ScanSession{}, false, err
	}
	source, found, err := remoteScanSourceConn(conn, scanID)
	if err != nil {
		return corpus.ScanSession{}, false, err
	}
	if !found {
		return corpus.ScanSession{}, false, fmt.Errorf("%w: %s", ErrRemoteHistoryScanSourceNotFound, scanID)
	}
	if scan.Status == corpus.ScanComplete {
		return scan, true, nil
	}
	if scan.Status != corpus.ScanOpen {
		return corpus.ScanSession{}, false, fmt.Errorf("%w: %s", ErrScanNotOpen, scanID)
	}

	generation, err := remoteHistoryGenerationConn(conn, source.GenerationID)
	if err != nil {
		return corpus.ScanSession{}, false, err
	}
	if generation.Status != remotehistory.HistoryGenerationActive {
		return corpus.ScanSession{}, false, ErrRemoteHistoryScanSourceClosed
	}
	if generation.CurrentSequence != source.PublicationSequence {
		return corpus.ScanSession{}, false, ErrRemoteHistoryScanSourceAdvanced
	}
	if err := finishScanConn(conn, scanID, corpus.ScanComplete, finishedAt.UTC(), true); err != nil {
		return corpus.ScanSession{}, false, err
	}
	scan.Status = corpus.ScanComplete
	scan.FinishedAt = finishedAt.UTC()
	return scan, false, nil
}

func insertRemoteScanSourceConn(conn *sqlite.Conn, source remotehistory.RemoteScanSource) error {
	if source.ScanID == "" {
		return remotehistory.ErrInvalidRemoteScanSource
	}
	if err := remotehistory.ValidateRemoteScanSourceInput(source.RemoteScanSourceInput); err != nil {
		return err
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO remote_scan_sources (scan_id, generation_id, publication_sequence, source_scope_id, materialization_policy_id, snapshot_fingerprint_version, snapshot_fingerprint_sha256) VALUES (?1,?2,?3,?4,?5,?6,?7)",
		&sqlitex.ExecOptions{Args: []any{
			string(source.ScanID),
			string(source.GenerationID),
			int64(source.PublicationSequence),
			source.SourceScopeID,
			source.MaterializationPolicyID,
			source.SnapshotFingerprintVersion,
			source.SnapshotFingerprintSHA256,
		}}); err != nil {
		return fmt.Errorf("insert remote scan source: %w", err)
	}
	return nil
}

func remoteScanSourceConn(
	conn *sqlite.Conn,
	scanID corpus.ScanSessionID,
) (remotehistory.RemoteScanSource, bool, error) {
	var source remotehistory.RemoteScanSource
	var found bool
	if err := sqlitex.Execute(conn,
		"SELECT generation_id, publication_sequence, source_scope_id, materialization_policy_id, snapshot_fingerprint_version, snapshot_fingerprint_sha256 FROM remote_scan_sources WHERE scan_id=?1",
		&sqlitex.ExecOptions{
			Args: []any{string(scanID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				found = true
				source = remotehistory.RemoteScanSource{
					ScanID: scanID,
					RemoteScanSourceInput: remotehistory.RemoteScanSourceInput{
						GenerationID:               remotehistory.HistoryGenerationID(stmt.ColumnText(0)),
						PublicationSequence:        remotehistory.HistoryPublicationSequence(stmt.ColumnInt64(1)),
						SourceScopeID:              stmt.ColumnText(2),
						MaterializationPolicyID:    stmt.ColumnText(3),
						SnapshotFingerprintVersion: stmt.ColumnText(4),
						SnapshotFingerprintSHA256:  stmt.ColumnText(5),
					},
				}
				return nil
			},
		}); err != nil {
		return remotehistory.RemoteScanSource{}, false, fmt.Errorf("query remote scan source: %w", err)
	}
	if found {
		if err := remotehistory.ValidateRemoteScanSourceInput(source.RemoteScanSourceInput); err != nil {
			return remotehistory.RemoteScanSource{}, false, err
		}
	}
	return source, found, nil
}

func remoteScanSourceExistsConn(conn *sqlite.Conn, scanID corpus.ScanSessionID) (bool, error) {
	var found bool
	if err := sqlitex.Execute(conn,
		"SELECT 1 FROM remote_scan_sources WHERE scan_id=?1 LIMIT 1",
		&sqlitex.ExecOptions{
			Args: []any{string(scanID)},
			ResultFunc: func(*sqlite.Stmt) error {
				found = true
				return nil
			},
		}); err != nil {
		return false, fmt.Errorf("query remote scan source existence: %w", err)
	}
	return found, nil
}

func matchingRemoteHistoryScanConn(
	conn *sqlite.Conn,
	scanRoot string,
	source remotehistory.RemoteScanSourceInput,
) (corpus.ScanSession, bool, error) {
	var candidates []corpus.ScanSession
	var startedTexts []string
	var finishedTexts []string
	if err := sqlitex.Execute(conn,
		"SELECT s.scan_id,s.provider_id,s.status,s.started_at,COALESCE(s.finished_at,'') FROM remote_scan_sources r JOIN scan_sessions s ON s.scan_id=r.scan_id WHERE s.root=?1 AND s.status IN ('OPEN','COMPLETE') AND r.generation_id=?2 AND r.publication_sequence=?3 AND r.source_scope_id=?4 AND r.materialization_policy_id=?5 AND r.snapshot_fingerprint_version=?6 AND r.snapshot_fingerprint_sha256=?7",
		&sqlitex.ExecOptions{
			Args: []any{
				scanRoot,
				string(source.GenerationID),
				int64(source.PublicationSequence),
				source.SourceScopeID,
				source.MaterializationPolicyID,
				source.SnapshotFingerprintVersion,
				source.SnapshotFingerprintSHA256,
			},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				var scan corpus.ScanSession
				scan.ID = corpus.ScanSessionID(stmt.ColumnText(0))
				scan.ProviderID = corpus.ProviderID(stmt.ColumnText(1))
				scan.Root = scanRoot
				scan.Status = corpus.ScanStatus(stmt.ColumnText(2))
				candidates = append(candidates, scan)
				startedTexts = append(startedTexts, stmt.ColumnText(3))
				finishedTexts = append(finishedTexts, stmt.ColumnText(4))
				return nil
			},
		}); err != nil {
		return corpus.ScanSession{}, false, fmt.Errorf("query remote scan replay: %w", err)
	}

	var best corpus.ScanSession
	var bestStarted time.Time
	var bestFound bool
	for i := range candidates {
		started, err := time.Parse(time.RFC3339Nano, startedTexts[i])
		if err != nil {
			return corpus.ScanSession{}, false, fmt.Errorf("parse replay scan start: %w", err)
		}
		candidates[i].StartedAt = started
		if finishedTexts[i] != "" {
			finished, err := time.Parse(time.RFC3339Nano, finishedTexts[i])
			if err != nil {
				return corpus.ScanSession{}, false, fmt.Errorf("parse replay scan finish: %w", err)
			}
			candidates[i].FinishedAt = finished
		}
		if !bestFound ||
			(candidates[i].Status == corpus.ScanComplete && best.Status != corpus.ScanComplete) ||
			(candidates[i].Status == best.Status &&
				(started.After(bestStarted) || (started.Equal(bestStarted) && candidates[i].ID > best.ID))) {
			best = candidates[i]
			bestStarted = started
			bestFound = true
		}
	}
	return best, bestFound, nil
}

func openScanForProviderRootConn(
	conn *sqlite.Conn,
	providerID corpus.ProviderID,
	root string,
) (corpus.ScanSession, bool, error) {
	var scan corpus.ScanSession
	var startedText string
	var found bool
	if err := sqlitex.Execute(conn,
		"SELECT scan_id,started_at FROM scan_sessions WHERE provider_id=?1 AND root=?2 AND status='OPEN' LIMIT 1",
		&sqlitex.ExecOptions{
			Args: []any{string(providerID), root},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				found = true
				scan.ID = corpus.ScanSessionID(stmt.ColumnText(0))
				scan.ProviderID = providerID
				scan.Root = root
				scan.Status = corpus.ScanOpen
				startedText = stmt.ColumnText(1)
				return nil
			},
		}); err != nil {
		return corpus.ScanSession{}, false, fmt.Errorf("query OPEN scan: %w", err)
	}
	if found {
		parsed, err := time.Parse(time.RFC3339Nano, startedText)
		if err != nil {
			return corpus.ScanSession{}, false, fmt.Errorf("parse OPEN scan start: %w", err)
		}
		scan.StartedAt = parsed
	}
	return scan, found, nil
}
