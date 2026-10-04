package sqlitestate

import (
	"context"
	"encoding/hex"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

const localIngestCommitAuthorizationFunction = "keelaryn_local_ingest_commit_authorized"

const (
	localIngestModeScan      = "SCAN"
	localIngestModeBootstrap = "BOOTSTRAP"
)

var (
	ErrInvalidLocalIngestCommit = errors.New("invalid local ingest commit")
	ErrLocalIngestReplayConflict = errors.New("local ingest replay conflicts with durable commit")
	ErrLocalIngestOpenScanExists = errors.New("open scan already exists for local ingest scope")
)

type localIngestCommitAuthorization struct {
	scanID             corpus.ScanSessionID
	providerID         corpus.ProviderID
	root               string
	startedAt          string
	mode               string
	fingerprintVersion string
	fingerprintSHA256  string
}

type LocalIngestCommitReceipt struct {
	Scan               corpus.ScanSession
	Bootstrap          bool
	FingerprintVersion string
	FingerprintSHA256  string
}

func (s *Store) registerLocalIngestCommitAuthorizationConn(conn *sqlite.Conn) error {
	auth := &localIngestCommitAuthorization{}
	if err := conn.CreateFunction(localIngestCommitAuthorizationFunction, &sqlite.FunctionImpl{
		NArgs: 7,
		Deterministic: false,
		AllowIndirect: true,
		Scalar: func(_ sqlite.Context, args []sqlite.Value) (sqlite.Value, error) {
			if auth.scanID != "" &&
				string(auth.scanID) == args[0].Text() &&
				string(auth.providerID) == args[1].Text() &&
				auth.root == args[2].Text() &&
				auth.startedAt == args[3].Text() &&
				auth.mode == args[4].Text() &&
				auth.fingerprintVersion == args[5].Text() &&
				auth.fingerprintSHA256 == args[6].Text() {
				return sqlite.IntegerValue(1), nil
			}
			return sqlite.IntegerValue(0), nil
		},
	}); err != nil {
		return fmt.Errorf("register local ingest commit authorization function: %w", err)
	}
	s.localIngestCommitAuthorizations.Store(conn, auth)
	return nil
}

func (s *Store) authorizeLocalIngestCommitConn(conn *sqlite.Conn, auth localIngestCommitAuthorization) (func(), error) {
	if auth.scanID == "" || auth.providerID == "" || auth.root == "" || auth.startedAt == "" ||
		(auth.mode != localIngestModeScan && auth.mode != localIngestModeBootstrap) ||
		auth.fingerprintVersion == "" || !validLocalIngestFingerprint(auth.fingerprintSHA256) {
		return nil, ErrInvalidLocalIngestCommit
	}
	value, ok := s.localIngestCommitAuthorizations.Load(conn)
	if !ok {
		return nil, fmt.Errorf("local ingest commit authorization state missing for connection")
	}
	state, ok := value.(*localIngestCommitAuthorization)
	if !ok || state == nil {
		return nil, fmt.Errorf("local ingest commit authorization state invalid")
	}
	if state.scanID != "" {
		return nil, fmt.Errorf("local ingest commit authorization already active")
	}
	*state = auth
	return func() { *state = localIngestCommitAuthorization{} }, nil
}

func validLocalIngestFingerprint(value string) bool {
	if len(value) != 64 || value != strings.ToLower(value) {
		return false
	}
	_, err := hex.DecodeString(value)
	return err == nil
}

func (s *Store) CommitLocalSnapshot(
	ctx context.Context,
	providerID corpus.ProviderID,
	root string,
	observedAt time.Time,
	fingerprintVersion string,
	fingerprintSHA256 string,
	inputs []corpus.ObservationRecordInput,
	finalValidate func(context.Context) error,
) (scan corpus.ScanSession, err error) {
	if providerID == "" || root == "" || observedAt.IsZero() || fingerprintVersion == "" ||
		!validLocalIngestFingerprint(fingerprintSHA256) || finalValidate == nil {
		return corpus.ScanSession{}, ErrInvalidLocalIngestCommit
	}
	for _, input := range inputs {
		if err := validateObservationInput(input); err != nil {
			return corpus.ScanSession{}, err
		}
		if input.AssignmentState != corpus.AssignmentUnresolved || input.ArtifactID != "" || input.RevisionID != "" {
			return corpus.ScanSession{}, fmt.Errorf("%w: local scan input must be unresolved", ErrInvalidObservation)
		}
		if err := requireLocalIngestInputScope(input, providerID, root); err != nil {
			return corpus.ScanSession{}, err
		}
	}

	conn, err := s.pool.Get(ctx)
	if err != nil {
		return corpus.ScanSession{}, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)
	end, err := sqlitex.ImmediateTransaction(conn)
	if err != nil {
		return corpus.ScanSession{}, fmt.Errorf("begin atomic local ingest: %w", err)
	}
	defer end(&err)

	if receipt, found, err := localIngestCommitReceiptConn(conn, providerID, root, observedAt, localIngestModeScan); err != nil {
		return corpus.ScanSession{}, err
	} else if found {
		if receipt.FingerprintVersion != fingerprintVersion || receipt.FingerprintSHA256 != fingerprintSHA256 {
			return corpus.ScanSession{}, ErrLocalIngestReplayConflict
		}
		return receipt.Scan, nil
	}
	if _, found, err := openScanForScopeConn(conn, providerID, root); err != nil {
		return corpus.ScanSession{}, err
	} else if found {
		return corpus.ScanSession{}, ErrLocalIngestOpenScanExists
	}

	scan, err = s.startScanConn(conn, providerID, root, observedAt)
	if err != nil {
		return corpus.ScanSession{}, err
	}
	for _, input := range inputs {
		if _, err := s.recordObservationConn(conn, scan.ID, input); err != nil {
			return corpus.ScanSession{}, err
		}
	}
	if err := finalValidate(ctx); err != nil {
		return corpus.ScanSession{}, err
	}
	if err := s.finishScanConn(conn, scan.ID, corpus.ScanComplete, observedAt, false); err != nil {
		return corpus.ScanSession{}, err
	}
	if err := s.insertLocalIngestCommitConn(conn, scan, localIngestModeScan, fingerprintVersion, fingerprintSHA256); err != nil {
		return corpus.ScanSession{}, err
	}
	scan.Status = corpus.ScanComplete
	scan.FinishedAt = observedAt.UTC()
	return scan, nil
}

func (s *Store) CommitBootstrapLocalSnapshot(
	ctx context.Context,
	providerID corpus.ProviderID,
	root string,
	observedAt time.Time,
	fingerprintVersion string,
	fingerprintSHA256 string,
	inputs []corpus.BootstrapObservationInput,
	finalValidate func(context.Context) error,
) (scan corpus.ScanSession, err error) {
	if providerID == "" || root == "" || observedAt.IsZero() || fingerprintVersion == "" ||
		!validLocalIngestFingerprint(fingerprintSHA256) || finalValidate == nil {
		return corpus.ScanSession{}, ErrInvalidLocalIngestCommit
	}
	for _, item := range inputs {
		if err := validateObservationInput(item.Observation); err != nil {
			return corpus.ScanSession{}, err
		}
		if item.Observation.AssignmentState != corpus.AssignmentUnresolved ||
			item.Observation.ArtifactID != "" || item.Observation.RevisionID != "" {
			return corpus.ScanSession{}, fmt.Errorf("%w: bootstrap input must be unresolved", ErrInvalidObservation)
		}
		if err := requireLocalIngestInputScope(item.Observation, providerID, root); err != nil {
			return corpus.ScanSession{}, err
		}
		if item.Evidence != nil {
			if err := corpus.ValidateContentEvidence(*item.Evidence); err != nil {
				return corpus.ScanSession{}, err
			}
		}
	}

	conn, err := s.pool.Get(ctx)
	if err != nil {
		return corpus.ScanSession{}, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)
	end, err := sqlitex.ImmediateTransaction(conn)
	if err != nil {
		return corpus.ScanSession{}, fmt.Errorf("begin atomic bootstrap ingest: %w", err)
	}
	defer end(&err)

	if receipt, found, err := localIngestCommitReceiptConn(conn, providerID, root, observedAt, localIngestModeBootstrap); err != nil {
		return corpus.ScanSession{}, err
	} else if found {
		if receipt.FingerprintVersion != fingerprintVersion || receipt.FingerprintSHA256 != fingerprintSHA256 {
			return corpus.ScanSession{}, ErrLocalIngestReplayConflict
		}
		return receipt.Scan, nil
	}
	if _, found, err := openScanForScopeConn(conn, providerID, root); err != nil {
		return corpus.ScanSession{}, err
	} else if found {
		return corpus.ScanSession{}, ErrLocalIngestOpenScanExists
	}

	scan, err = s.startBootstrapScanConn(conn, providerID, root, observedAt)
	if err != nil {
		return corpus.ScanSession{}, err
	}
	for _, item := range inputs {
		if _, err := s.adoptObservationInScanConn(conn, scan.ID, item.Observation, item.Evidence); err != nil {
			return corpus.ScanSession{}, err
		}
	}
	if err := finalValidate(ctx); err != nil {
		return corpus.ScanSession{}, err
	}
	if err := s.finishScanConn(conn, scan.ID, corpus.ScanComplete, observedAt, false); err != nil {
		return corpus.ScanSession{}, err
	}
	if err := s.insertLocalIngestCommitConn(conn, scan, localIngestModeBootstrap, fingerprintVersion, fingerprintSHA256); err != nil {
		return corpus.ScanSession{}, err
	}
	scan.Status = corpus.ScanComplete
	scan.FinishedAt = observedAt.UTC()
	return scan, nil
}

func requireLocalIngestInputScope(input corpus.ObservationRecordInput, providerID corpus.ProviderID, root string) error {
	if input.ProviderObject.ProviderID != providerID {
		return fmt.Errorf("%w: provider=%s expected=%s", ErrScanScopeMismatch, input.ProviderObject.ProviderID, providerID)
	}
	for _, locator := range input.Locators {
		if locator.ProviderID != providerID || locator.Root != root {
			return fmt.Errorf("%w: locator=%#v expected=%s/%s", ErrScanScopeMismatch, locator, providerID, root)
		}
	}
	return nil
}

func (s *Store) insertLocalIngestCommitConn(
	conn *sqlite.Conn,
	scan corpus.ScanSession,
	mode string,
	fingerprintVersion string,
	fingerprintSHA256 string,
) error {
	startedAt := scan.StartedAt.UTC().Format(time.RFC3339Nano)
	auth := localIngestCommitAuthorization{
		scanID: scan.ID,
		providerID: scan.ProviderID,
		root: scan.Root,
		startedAt: startedAt,
		mode: mode,
		fingerprintVersion: fingerprintVersion,
		fingerprintSHA256: fingerprintSHA256,
	}
	release, err := s.authorizeLocalIngestCommitConn(conn, auth)
	if err != nil {
		return err
	}
	writeErr := sqlitex.Execute(conn,
		"INSERT INTO local_ingest_commits (scan_id,provider_id,root,started_at,ingest_mode,snapshot_fingerprint_version,snapshot_fingerprint_sha256) VALUES (?1,?2,?3,?4,?5,?6,?7)",
		&sqlitex.ExecOptions{Args: []any{
			string(scan.ID), string(scan.ProviderID), scan.Root, startedAt, mode, fingerprintVersion, fingerprintSHA256,
		}})
	release()
	if writeErr != nil {
		return fmt.Errorf("insert local ingest commit receipt: %w", writeErr)
	}
	return nil
}

func localIngestCommitReceiptConn(
	conn *sqlite.Conn,
	providerID corpus.ProviderID,
	root string,
	observedAt time.Time,
	mode string,
) (LocalIngestCommitReceipt, bool, error) {
	var receipt LocalIngestCommitReceipt
	var scanID corpus.ScanSessionID
	found := false
	if err := sqlitex.Execute(conn,
		"SELECT scan_id,snapshot_fingerprint_version,snapshot_fingerprint_sha256 FROM local_ingest_commits WHERE provider_id=?1 AND root=?2 AND started_at=?3 AND ingest_mode=?4",
		&sqlitex.ExecOptions{
			Args: []any{string(providerID), root, observedAt.UTC().Format(time.RFC3339Nano), mode},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				found = true
				scanID = corpus.ScanSessionID(stmt.ColumnText(0))
				receipt.FingerprintVersion = stmt.ColumnText(1)
				receipt.FingerprintSHA256 = stmt.ColumnText(2)
				return nil
			},
		}); err != nil {
		return LocalIngestCommitReceipt{}, false, fmt.Errorf("query local ingest commit receipt: %w", err)
	}
	if !found {
		return LocalIngestCommitReceipt{}, false, nil
	}
	scan, err := scanSessionConn(conn, scanID)
	if err != nil {
		return LocalIngestCommitReceipt{}, false, err
	}
	if scan.Status != corpus.ScanComplete {
		return LocalIngestCommitReceipt{}, false, fmt.Errorf("%w: receipt scan %s is not COMPLETE", ErrInvalidLocalIngestCommit, scanID)
	}
	receipt.Scan = scan
	receipt.Bootstrap = mode == localIngestModeBootstrap
	return receipt, true, nil
}

func (s *Store) LocalIngestCommitAtBoundary(
	ctx context.Context,
	providerID corpus.ProviderID,
	root string,
	observedAt time.Time,
	bootstrap bool,
) (LocalIngestCommitReceipt, bool, error) {
	if providerID == "" || root == "" || observedAt.IsZero() {
		return LocalIngestCommitReceipt{}, false, ErrInvalidLocalIngestCommit
	}
	mode := localIngestModeScan
	if bootstrap {
		mode = localIngestModeBootstrap
	}
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return LocalIngestCommitReceipt{}, false, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)
	return localIngestCommitReceiptConn(conn, providerID, root, observedAt, mode)
}

// LatestBootstrapLocalIngestCommit returns the newest durable BOOTSTRAP receipt
// for one provider/root scope. Later ordinary SCAN receipts are intentionally
// excluded: they are observation evidence, not accepted runtime source authority.
func (s *Store) LatestBootstrapLocalIngestCommit(
	ctx context.Context,
	providerID corpus.ProviderID,
	root string,
) (LocalIngestCommitReceipt, bool, error) {
	if providerID == "" || root == "" {
		return LocalIngestCommitReceipt{}, false, ErrInvalidLocalIngestCommit
	}
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return LocalIngestCommitReceipt{}, false, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)
	return latestBootstrapLocalIngestCommitConn(conn, providerID, root)
}

func latestBootstrapLocalIngestCommitConn(
	conn *sqlite.Conn,
	providerID corpus.ProviderID,
	root string,
) (LocalIngestCommitReceipt, bool, error) {
	type candidate struct {
		receipt  LocalIngestCommitReceipt
		finished time.Time
		order    int64
		ordered  bool
	}
	var latestFinished time.Time
	var latest []candidate
	err := sqlitex.Execute(conn, `
SELECT
	c.scan_id,
	s.started_at,
	s.finished_at,
	c.snapshot_fingerprint_version,
	c.snapshot_fingerprint_sha256,
	a.completion_order
FROM local_ingest_commits c
JOIN scan_sessions s
  ON s.scan_id=c.scan_id
 AND s.provider_id=c.provider_id
 AND s.root=c.root
 AND s.started_at=c.started_at
JOIN bootstrap_scan_authorities b
  ON b.scan_id=c.scan_id
 AND b.proof_kind=?3
 AND b.proven_at=s.started_at
LEFT JOIN scan_completion_authorities a ON a.scan_id=c.scan_id
WHERE c.provider_id=?1
  AND c.root=?2
  AND c.ingest_mode='BOOTSTRAP'
  AND s.status='COMPLETE'
  AND s.finished_at IS NOT NULL
`, &sqlitex.ExecOptions{
		Args: []any{string(providerID), root, bootstrapNoPriorObservationHistoryProof},
		ResultFunc: func(stmt *sqlite.Stmt) error {
			scanID := corpus.ScanSessionID(stmt.ColumnText(0))
			started, err := time.Parse(time.RFC3339Nano, stmt.ColumnText(1))
			if err != nil {
				return fmt.Errorf("parse bootstrap receipt scan start %s: %w", scanID, err)
			}
			finished, err := time.Parse(time.RFC3339Nano, stmt.ColumnText(2))
			if err != nil {
				return fmt.Errorf("parse bootstrap receipt scan finish %s: %w", scanID, err)
			}
			current := candidate{
				receipt: LocalIngestCommitReceipt{
					Scan: corpus.ScanSession{
						ID: scanID, ProviderID: providerID, Root: root,
						Status: corpus.ScanComplete, StartedAt: started.UTC(), FinishedAt: finished.UTC(),
					},
					Bootstrap: true,
					FingerprintVersion: stmt.ColumnText(3),
					FingerprintSHA256: stmt.ColumnText(4),
				},
				finished: finished.UTC(),
			}
			if !stmt.ColumnIsNull(5) {
				current.order = stmt.ColumnInt64(5)
				current.ordered = true
			}
			if len(latest) == 0 || current.finished.After(latestFinished) {
				latestFinished = current.finished
				latest = []candidate{current}
			} else if current.finished.Equal(latestFinished) {
				latest = append(latest, current)
			}
			return nil
		},
	})
	if err != nil {
		return LocalIngestCommitReceipt{}, false, fmt.Errorf("query latest bootstrap local ingest receipt: %w", err)
	}
	if len(latest) == 0 {
		return LocalIngestCommitReceipt{}, false, nil
	}
	if len(latest) == 1 {
		return latest[0].receipt, true, nil
	}
	var selected candidate
	var hasOrdered bool
	for _, current := range latest {
		if current.ordered && (!hasOrdered || current.order > selected.order) {
			selected = current
			hasOrdered = true
		}
	}
	if hasOrdered {
		return selected.receipt, true, nil
	}
	return LocalIngestCommitReceipt{}, false, fmt.Errorf(
		"%w: bootstrap receipt provider=%s root=%s finished_at=%s candidates=%d",
		ErrAmbiguousScanAuthority,
		providerID,
		root,
		latestFinished.Format(time.RFC3339Nano),
		len(latest),
	)
}

func openScanForScopeConn(conn *sqlite.Conn, providerID corpus.ProviderID, root string) (corpus.ScanSession, bool, error) {
	var scanID corpus.ScanSessionID
	if err := sqlitex.Execute(conn,
		"SELECT scan_id FROM scan_sessions WHERE provider_id=?1 AND root=?2 AND status='OPEN' LIMIT 1",
		&sqlitex.ExecOptions{
			Args: []any{string(providerID), root},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				scanID = corpus.ScanSessionID(stmt.ColumnText(0))
				return nil
			},
		}); err != nil {
		return corpus.ScanSession{}, false, fmt.Errorf("query open scan for scope: %w", err)
	}
	if scanID == "" {
		return corpus.ScanSession{}, false, nil
	}
	scan, err := scanSessionConn(conn, scanID)
	if err != nil {
		return corpus.ScanSession{}, false, err
	}
	return scan, true, nil
}

func (s *Store) OpenScanForScope(ctx context.Context, providerID corpus.ProviderID, root string) (corpus.ScanSession, bool, error) {
	if providerID == "" || root == "" {
		return corpus.ScanSession{}, false, ErrInvalidScan
	}
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return corpus.ScanSession{}, false, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)
	return openScanForScopeConn(conn, providerID, root)
}
