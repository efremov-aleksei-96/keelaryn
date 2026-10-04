package sqlitestate

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

const (
	LocalAttemptSourceFingerprintVersion       = "localfs-attempt-source:v1"
	qualifiedLocalBootstrapFingerprintVersion = "localfs-snapshot:v1"
	qualifiedLocalAttemptProviderID            = corpus.ProviderID("localfs")

	localAttemptSourceAuthorizationFunction = "keelaryn_local_attempt_source_authorized_v47"
	localAttemptAbortAuthorizationFunction  = "keelaryn_local_attempt_abort_authorized_v47"
)

var (
	ErrInvalidLocalAttemptSource              = errors.New("invalid local attempt source")
	ErrLocalAttemptSourceNotFound             = errors.New("local attempt source not found")
	ErrLocalAttemptReplayConflict             = errors.New("local attempt replay conflicts with durable source")
	ErrLocalAttemptReplayClosed               = errors.New("local attempt replay targets a terminal attempt")
	ErrLocalAttemptPredecessorNotCurrent      = errors.New("local attempt predecessor is not the current accepted source")
	ErrLocalAttemptRequiresGuardedCompletion  = errors.New("source-bound local attempt requires guarded accepted publication")
	ErrLocalAttemptRequiresGuardedAbort       = errors.New("source-bound local attempt requires guarded abort")
	ErrLocalAttemptAbortUnsafe                = errors.New("local attempt abort is unsafe after attempt mutation")
	ErrLocalAttemptAbortConflict              = errors.New("local attempt abort conflicts with durable terminal boundary")
	ErrInvalidLocalAttemptHistoricalAuthority = errors.New("invalid historical local attempt authority")
)

type LocalAttemptSource struct {
	Scan                          corpus.ScanSession
	PredecessorScanID             corpus.ScanSessionID
	PredecessorStartedAt          time.Time
	PredecessorFingerprintVersion string
	PredecessorFingerprintSHA256  string
	FingerprintVersion            string
	FingerprintSHA256             string
}

type localAttemptSourceAuthorization struct {
	scanID                        corpus.ScanSessionID
	providerID                    corpus.ProviderID
	root                          string
	startedAt                     string
	predecessorScanID             corpus.ScanSessionID
	predecessorStartedAt          string
	predecessorFingerprintVersion string
	predecessorFingerprintSHA256  string
	fingerprintVersion            string
	fingerprintSHA256             string
}

type localAttemptAbortAuthorization struct {
	scanID     corpus.ScanSessionID
	finishedAt string
}

func (s *Store) registerLocalAttemptAuthorizationsConn(conn *sqlite.Conn) error {
	sourceAuth := &localAttemptSourceAuthorization{}
	if err := conn.CreateFunction(localAttemptSourceAuthorizationFunction, &sqlite.FunctionImpl{
		NArgs: 10, Deterministic: false, AllowIndirect: true,
		Scalar: func(_ sqlite.Context, args []sqlite.Value) (sqlite.Value, error) {
			if sourceAuth.scanID != "" &&
				string(sourceAuth.scanID) == args[0].Text() &&
				string(sourceAuth.providerID) == args[1].Text() &&
				sourceAuth.root == args[2].Text() &&
				sourceAuth.startedAt == args[3].Text() &&
				string(sourceAuth.predecessorScanID) == args[4].Text() &&
				sourceAuth.predecessorStartedAt == args[5].Text() &&
				sourceAuth.predecessorFingerprintVersion == args[6].Text() &&
				sourceAuth.predecessorFingerprintSHA256 == args[7].Text() &&
				sourceAuth.fingerprintVersion == args[8].Text() &&
				sourceAuth.fingerprintSHA256 == args[9].Text() {
				return sqlite.IntegerValue(1), nil
			}
			return sqlite.IntegerValue(0), nil
		},
	}); err != nil {
		return fmt.Errorf("register local attempt source authorization function: %w", err)
	}
	s.localAttemptSourceAuthorizations.Store(conn, sourceAuth)

	abortAuth := &localAttemptAbortAuthorization{}
	if err := conn.CreateFunction(localAttemptAbortAuthorizationFunction, &sqlite.FunctionImpl{
		NArgs: 2, Deterministic: false, AllowIndirect: true,
		Scalar: func(_ sqlite.Context, args []sqlite.Value) (sqlite.Value, error) {
			if abortAuth.scanID != "" &&
				string(abortAuth.scanID) == args[0].Text() &&
				abortAuth.finishedAt == args[1].Text() {
				return sqlite.IntegerValue(1), nil
			}
			return sqlite.IntegerValue(0), nil
		},
	}); err != nil {
		return fmt.Errorf("register local attempt abort authorization function: %w", err)
	}
	s.localAttemptAbortAuthorizations.Store(conn, abortAuth)
	return nil
}

func (s *Store) authorizeLocalAttemptSourceConn(conn *sqlite.Conn, auth localAttemptSourceAuthorization) (func(), error) {
	if auth.scanID == "" || auth.providerID == "" || auth.root == "" || auth.startedAt == "" ||
		auth.predecessorScanID == "" || auth.predecessorStartedAt == "" ||
		auth.predecessorFingerprintVersion != qualifiedLocalBootstrapFingerprintVersion ||
		!validLocalIngestFingerprint(auth.predecessorFingerprintSHA256) ||
		auth.fingerprintVersion != LocalAttemptSourceFingerprintVersion ||
		!validLocalIngestFingerprint(auth.fingerprintSHA256) {
		return nil, ErrInvalidLocalAttemptSource
	}
	value, ok := s.localAttemptSourceAuthorizations.Load(conn)
	if !ok {
		return nil, fmt.Errorf("local attempt source authorization state missing for connection")
	}
	state, ok := value.(*localAttemptSourceAuthorization)
	if !ok || state == nil {
		return nil, fmt.Errorf("local attempt source authorization state invalid")
	}
	if state.scanID != "" {
		return nil, fmt.Errorf("local attempt source authorization already active")
	}
	*state = auth
	return func() { *state = localAttemptSourceAuthorization{} }, nil
}

func (s *Store) authorizeLocalAttemptAbortConn(conn *sqlite.Conn, scanID corpus.ScanSessionID, finishedAt string) (func(), error) {
	if scanID == "" || finishedAt == "" {
		return nil, ErrInvalidLocalAttemptSource
	}
	value, ok := s.localAttemptAbortAuthorizations.Load(conn)
	if !ok {
		return nil, fmt.Errorf("local attempt abort authorization state missing for connection")
	}
	state, ok := value.(*localAttemptAbortAuthorization)
	if !ok || state == nil {
		return nil, fmt.Errorf("local attempt abort authorization state invalid")
	}
	if state.scanID != "" {
		return nil, fmt.Errorf("local attempt abort authorization already active")
	}
	state.scanID = scanID
	state.finishedAt = finishedAt
	return func() { *state = localAttemptAbortAuthorization{} }, nil
}

func (s *Store) localAttemptAbortAuthorizedConn(conn *sqlite.Conn, scanID corpus.ScanSessionID, finishedAt string) bool {
	value, ok := s.localAttemptAbortAuthorizations.Load(conn)
	if !ok {
		return false
	}
	state, ok := value.(*localAttemptAbortAuthorization)
	return ok && state != nil && state.scanID == scanID && state.finishedAt == finishedAt
}

func (s *Store) StartLocalAttempt(
	ctx context.Context,
	predecessor LocalIngestCommitReceipt,
	startedAt time.Time,
	fingerprintVersion string,
	fingerprintSHA256 string,
) (source LocalAttemptSource, replayed bool, err error) {
	if !validLocalAttemptRequest(predecessor, startedAt, fingerprintVersion, fingerprintSHA256) {
		return LocalAttemptSource{}, false, ErrInvalidLocalAttemptSource
	}
	startedAt = startedAt.UTC()

	conn, err := s.pool.Get(ctx)
	if err != nil {
		return LocalAttemptSource{}, false, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)

	end, err := sqlitex.ImmediateTransaction(conn)
	if err != nil {
		return LocalAttemptSource{}, false, fmt.Errorf("begin local attempt start transaction: %w", err)
	}
	defer end(&err)

	if existing, found, err := localAttemptSourceAtBoundaryConn(
		conn, predecessor.Scan.ProviderID, predecessor.Scan.Root, startedAt,
	); err != nil {
		return LocalAttemptSource{}, false, err
	} else if found {
		if !localAttemptRequestMatches(existing, predecessor, fingerprintVersion, fingerprintSHA256) {
			return LocalAttemptSource{}, false, ErrLocalAttemptReplayConflict
		}
		if existing.Scan.Status != corpus.ScanOpen {
			return LocalAttemptSource{}, false, ErrLocalAttemptReplayClosed
		}
		return existing, true, nil
	}

	current, found, err := latestBootstrapLocalIngestCommitConn(
		conn,
		predecessor.Scan.ProviderID,
		predecessor.Scan.Root,
		qualifiedLocalBootstrapFingerprintVersion,
	)
	if err != nil {
		return LocalAttemptSource{}, false, err
	}
	if !found || !sameQualifiedBootstrapReceipt(current, predecessor) {
		return LocalAttemptSource{}, false, ErrLocalAttemptPredecessorNotCurrent
	}

	if open, found, err := openScanForScopeConn(conn, predecessor.Scan.ProviderID, predecessor.Scan.Root); err != nil {
		return LocalAttemptSource{}, false, err
	} else if found {
		return LocalAttemptSource{}, false, fmt.Errorf(
			"%w: unresolved scan=%s provider=%s root=%s",
			ErrLocalAttemptReplayConflict, open.ID, open.ProviderID, open.Root,
		)
	}

	scan, err := s.startScanConn(conn, predecessor.Scan.ProviderID, predecessor.Scan.Root, startedAt)
	if err != nil {
		return LocalAttemptSource{}, false, err
	}
	source = LocalAttemptSource{
		Scan:                          scan,
		PredecessorScanID:             predecessor.Scan.ID,
		PredecessorStartedAt:          predecessor.Scan.StartedAt.UTC(),
		PredecessorFingerprintVersion: predecessor.FingerprintVersion,
		PredecessorFingerprintSHA256:  predecessor.FingerprintSHA256,
		FingerprintVersion:            fingerprintVersion,
		FingerprintSHA256:             fingerprintSHA256,
	}
	if err := s.insertLocalAttemptSourceConn(conn, source); err != nil {
		return LocalAttemptSource{}, false, err
	}
	return source, false, nil
}

func validLocalAttemptRequest(
	predecessor LocalIngestCommitReceipt,
	startedAt time.Time,
	fingerprintVersion string,
	fingerprintSHA256 string,
) bool {
	return predecessor.Bootstrap &&
		predecessor.Scan.ID != "" &&
		predecessor.Scan.ProviderID == qualifiedLocalAttemptProviderID &&
		predecessor.Scan.Root != "" &&
		predecessor.Scan.Status == corpus.ScanComplete &&
		!predecessor.Scan.StartedAt.IsZero() &&
		!predecessor.Scan.FinishedAt.IsZero() &&
		predecessor.FingerprintVersion == qualifiedLocalBootstrapFingerprintVersion &&
		validLocalIngestFingerprint(predecessor.FingerprintSHA256) &&
		!startedAt.IsZero() &&
		startedAt.UTC().After(predecessor.Scan.FinishedAt.UTC()) &&
		fingerprintVersion == LocalAttemptSourceFingerprintVersion &&
		validLocalIngestFingerprint(fingerprintSHA256)
}

func sameQualifiedBootstrapReceipt(left, right LocalIngestCommitReceipt) bool {
	return left.Bootstrap && right.Bootstrap &&
		left.Scan.ID == right.Scan.ID &&
		left.Scan.ProviderID == right.Scan.ProviderID &&
		left.Scan.Root == right.Scan.Root &&
		left.Scan.Status == corpus.ScanComplete &&
		right.Scan.Status == corpus.ScanComplete &&
		left.Scan.StartedAt.Equal(right.Scan.StartedAt) &&
		left.Scan.FinishedAt.Equal(right.Scan.FinishedAt) &&
		left.FingerprintVersion == right.FingerprintVersion &&
		left.FingerprintSHA256 == right.FingerprintSHA256
}

func localAttemptRequestMatches(
	source LocalAttemptSource,
	predecessor LocalIngestCommitReceipt,
	fingerprintVersion string,
	fingerprintSHA256 string,
) bool {
	return source.Scan.ProviderID == predecessor.Scan.ProviderID &&
		source.Scan.Root == predecessor.Scan.Root &&
		source.PredecessorScanID == predecessor.Scan.ID &&
		source.PredecessorStartedAt.Equal(predecessor.Scan.StartedAt) &&
		source.PredecessorFingerprintVersion == predecessor.FingerprintVersion &&
		source.PredecessorFingerprintSHA256 == predecessor.FingerprintSHA256 &&
		source.FingerprintVersion == fingerprintVersion &&
		source.FingerprintSHA256 == fingerprintSHA256
}

func (s *Store) insertLocalAttemptSourceConn(conn *sqlite.Conn, source LocalAttemptSource) error {
	auth := localAttemptSourceAuthorization{
		scanID: source.Scan.ID,
		providerID: source.Scan.ProviderID,
		root: source.Scan.Root,
		startedAt: source.Scan.StartedAt.UTC().Format(time.RFC3339Nano),
		predecessorScanID: source.PredecessorScanID,
		predecessorStartedAt: source.PredecessorStartedAt.UTC().Format(time.RFC3339Nano),
		predecessorFingerprintVersion: source.PredecessorFingerprintVersion,
		predecessorFingerprintSHA256: source.PredecessorFingerprintSHA256,
		fingerprintVersion: source.FingerprintVersion,
		fingerprintSHA256: source.FingerprintSHA256,
	}
	release, err := s.authorizeLocalAttemptSourceConn(conn, auth)
	if err != nil {
		return err
	}
	writeErr := sqlitex.Execute(conn, `
INSERT INTO local_attempt_sources (
	scan_id,provider_id,root,started_at,
	predecessor_scan_id,predecessor_started_at,
	predecessor_fingerprint_version,predecessor_fingerprint_sha256,
	snapshot_fingerprint_version,snapshot_fingerprint_sha256
) VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10)`,
		&sqlitex.ExecOptions{Args: []any{
			string(auth.scanID), string(auth.providerID), auth.root, auth.startedAt,
			string(auth.predecessorScanID), auth.predecessorStartedAt,
			auth.predecessorFingerprintVersion, auth.predecessorFingerprintSHA256,
			auth.fingerprintVersion, auth.fingerprintSHA256,
		}})
	release()
	if writeErr != nil {
		return fmt.Errorf("insert local attempt source: %w", writeErr)
	}
	return nil
}

func (s *Store) LocalAttemptSource(ctx context.Context, scanID corpus.ScanSessionID) (LocalAttemptSource, error) {
	if scanID == "" {
		return LocalAttemptSource{}, ErrInvalidLocalAttemptSource
	}
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return LocalAttemptSource{}, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)
	source, found, err := localAttemptSourceConn(conn, scanID)
	if err != nil {
		return LocalAttemptSource{}, err
	}
	if !found {
		return LocalAttemptSource{}, fmt.Errorf("%w: %s", ErrLocalAttemptSourceNotFound, scanID)
	}
	return source, nil
}

func localAttemptSourceConn(conn *sqlite.Conn, scanID corpus.ScanSessionID) (LocalAttemptSource, bool, error) {
	var source LocalAttemptSource
	var predecessorStarted string
	var found bool
	err := sqlitex.Execute(conn, `
SELECT predecessor_scan_id,predecessor_started_at,
       predecessor_fingerprint_version,predecessor_fingerprint_sha256,
       snapshot_fingerprint_version,snapshot_fingerprint_sha256
FROM local_attempt_sources WHERE scan_id=?1`,
		&sqlitex.ExecOptions{
			Args: []any{string(scanID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				found = true
				source.PredecessorScanID = corpus.ScanSessionID(stmt.ColumnText(0))
				predecessorStarted = stmt.ColumnText(1)
				source.PredecessorFingerprintVersion = stmt.ColumnText(2)
				source.PredecessorFingerprintSHA256 = stmt.ColumnText(3)
				source.FingerprintVersion = stmt.ColumnText(4)
				source.FingerprintSHA256 = stmt.ColumnText(5)
				return nil
			},
		})
	if err != nil {
		return LocalAttemptSource{}, false, fmt.Errorf("query local attempt source: %w", err)
	}
	if !found {
		return LocalAttemptSource{}, false, nil
	}
	source.PredecessorStartedAt, err = time.Parse(time.RFC3339Nano, predecessorStarted)
	if err != nil {
		return LocalAttemptSource{}, false, fmt.Errorf("parse local attempt predecessor start: %w", err)
	}
	source.Scan, err = scanSessionConn(conn, scanID)
	if err != nil {
		return LocalAttemptSource{}, false, err
	}
	return source, true, nil
}

func localAttemptSourceAtBoundaryConn(
	conn *sqlite.Conn,
	providerID corpus.ProviderID,
	root string,
	startedAt time.Time,
) (LocalAttemptSource, bool, error) {
	var scanID corpus.ScanSessionID
	if err := sqlitex.Execute(conn,
		"SELECT scan_id FROM local_attempt_sources WHERE provider_id=?1 AND root=?2 AND started_at=?3",
		&sqlitex.ExecOptions{
			Args: []any{string(providerID), root, startedAt.UTC().Format(time.RFC3339Nano)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				scanID = corpus.ScanSessionID(stmt.ColumnText(0))
				return nil
			},
		}); err != nil {
		return LocalAttemptSource{}, false, fmt.Errorf("query local attempt boundary: %w", err)
	}
	if scanID == "" {
		return LocalAttemptSource{}, false, nil
	}
	return localAttemptSourceConn(conn, scanID)
}

func localAttemptSourceExistsConn(conn *sqlite.Conn, scanID corpus.ScanSessionID) (bool, error) {
	var found bool
	if err := sqlitex.Execute(conn,
		"SELECT 1 FROM local_attempt_sources WHERE scan_id=?1 LIMIT 1",
		&sqlitex.ExecOptions{
			Args: []any{string(scanID)},
			ResultFunc: func(*sqlite.Stmt) error { found = true; return nil },
		}); err != nil {
		return false, fmt.Errorf("query local attempt source existence: %w", err)
	}
	return found, nil
}

func (s *Store) AbortLocalAttempt(
	ctx context.Context,
	scanID corpus.ScanSessionID,
	finishedAt time.Time,
) (source LocalAttemptSource, replayed bool, err error) {
	if scanID == "" || finishedAt.IsZero() {
		return LocalAttemptSource{}, false, ErrInvalidLocalAttemptSource
	}
	finishedAt = finishedAt.UTC()
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return LocalAttemptSource{}, false, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)
	end, err := sqlitex.ImmediateTransaction(conn)
	if err != nil {
		return LocalAttemptSource{}, false, fmt.Errorf("begin local attempt abort transaction: %w", err)
	}
	defer end(&err)

	source, found, err := localAttemptSourceConn(conn, scanID)
	if err != nil {
		return LocalAttemptSource{}, false, err
	}
	if !found {
		return LocalAttemptSource{}, false, fmt.Errorf("%w: %s", ErrLocalAttemptSourceNotFound, scanID)
	}
	if source.Scan.Status == corpus.ScanAborted {
		if source.Scan.FinishedAt.Equal(finishedAt) {
			return source, true, nil
		}
		return LocalAttemptSource{}, false, ErrLocalAttemptAbortConflict
	}
	if source.Scan.Status != corpus.ScanOpen {
		return LocalAttemptSource{}, false, fmt.Errorf("%w: %s", ErrScanNotOpen, scanID)
	}
	if finishedAt.Before(source.Scan.StartedAt) {
		return LocalAttemptSource{}, false, ErrInvalidLocalAttemptSource
	}
	unsafe, err := localAttemptHasMutationConn(conn, scanID)
	if err != nil {
		return LocalAttemptSource{}, false, err
	}
	if unsafe {
		return LocalAttemptSource{}, false, ErrLocalAttemptAbortUnsafe
	}

	finishedText := finishedAt.Format(time.RFC3339Nano)
	release, err := s.authorizeLocalAttemptAbortConn(conn, scanID, finishedText)
	if err != nil {
		return LocalAttemptSource{}, false, err
	}
	defer release()
	if err := s.finishScanConn(conn, scanID, corpus.ScanAborted, finishedAt, true); err != nil {
		return LocalAttemptSource{}, false, err
	}
	source.Scan.Status = corpus.ScanAborted
	source.Scan.FinishedAt = finishedAt
	return source, false, nil
}

func localAttemptHasMutationConn(conn *sqlite.Conn, scanID corpus.ScanSessionID) (bool, error) {
	var found bool
	err := sqlitex.Execute(conn, `
SELECT 1
FROM observations o
LEFT JOIN identity_mutation_requests r ON r.observation_id=o.observation_id
WHERE o.scan_id=?1
LIMIT 1`, &sqlitex.ExecOptions{
		Args: []any{string(scanID)},
		ResultFunc: func(*sqlite.Stmt) error { found = true; return nil },
	})
	if err != nil {
		return false, fmt.Errorf("query local attempt mutation state: %w", err)
	}
	return found, nil
}

func verifyLocalAttemptHistoricalAuthorityConn(conn *sqlite.Conn) error {
	var invalid corpus.ScanSessionID
	err := sqlitex.Execute(conn, `
SELECT a.scan_id
FROM local_attempt_sources a
LEFT JOIN scan_sessions s ON s.scan_id=a.scan_id
LEFT JOIN scan_sessions p ON p.scan_id=a.predecessor_scan_id
LEFT JOIN local_ingest_commits c ON c.scan_id=a.predecessor_scan_id
LEFT JOIN bootstrap_scan_authorities b
  ON b.scan_id=a.predecessor_scan_id
 AND b.proof_kind='NO_PRIOR_OBSERVATION_HISTORY:v1'
 AND b.proven_at=a.predecessor_started_at
WHERE a.provider_id<>'localfs'
   OR s.scan_id IS NULL
   OR s.provider_id<>a.provider_id
   OR s.root<>a.root
   OR s.started_at<>a.started_at
   OR s.status NOT IN ('OPEN','ABORTED')
   OR a.predecessor_fingerprint_version<>'localfs-snapshot:v1'
   OR a.snapshot_fingerprint_version<>'localfs-attempt-source:v1'
   OR p.scan_id IS NULL
   OR p.provider_id<>a.provider_id
   OR p.root<>a.root
   OR p.started_at<>a.predecessor_started_at
   OR p.status<>'COMPLETE'
   OR p.finished_at IS NULL
   OR keelaryn_utc_rfc3339nano_after(a.started_at,p.finished_at)<>1
   OR c.scan_id IS NULL
   OR c.provider_id<>a.provider_id
   OR c.root<>a.root
   OR c.started_at<>a.predecessor_started_at
   OR c.ingest_mode<>'BOOTSTRAP'
   OR c.snapshot_fingerprint_version<>a.predecessor_fingerprint_version
   OR c.snapshot_fingerprint_sha256<>a.predecessor_fingerprint_sha256
   OR b.scan_id IS NULL
   OR EXISTS (SELECT 1 FROM observations o WHERE o.scan_id=a.scan_id)
   OR EXISTS (SELECT 1 FROM local_ingest_commits terminal WHERE terminal.scan_id=a.scan_id)
LIMIT 1`, &sqlitex.ExecOptions{
		ResultFunc: func(stmt *sqlite.Stmt) error {
			invalid = corpus.ScanSessionID(stmt.ColumnText(0))
			return nil
		},
	})
	if err != nil {
		return fmt.Errorf("verify historical local attempt authority: %w", err)
	}
	if invalid != "" {
		return fmt.Errorf("%w: scan=%s", ErrInvalidLocalAttemptHistoricalAuthority, invalid)
	}
	return nil
}
