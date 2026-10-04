package local

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/contextbundle"
	"github.com/efremov-aleksei-96/keelaryn/internal/controlstorage"
	"github.com/efremov-aleksei-96/keelaryn/internal/ingest"
	providerlocalfs "github.com/efremov-aleksei-96/keelaryn/internal/provider/localfs"
	"github.com/efremov-aleksei-96/keelaryn/internal/search"
	searchsqlite "github.com/efremov-aleksei-96/keelaryn/internal/search/sqlite"
	sqlitestate "github.com/efremov-aleksei-96/keelaryn/internal/state/sqlite"
)

const protectedSearchCommitVerifyTimeout = 5 * time.Minute

type ProtectedIndexOptions struct {
	Root       string
	ControlDir string
	ObservedAt time.Time
	MaxBytes   int64
}

type ProtectedContextOptions struct {
	Root          string
	ReadRoot      string
	ControlDir    string
	Query         string
	Reason        string
	Limit         int
	MaxBytes      int64
	MaxTotalBytes int64
}

type ProtectedReadOnlyScope struct {
	Root       string
	ReadRoot   string
	ControlDir string
}

// ValidateProtectedScope resolves the same physical root/control boundary used
// by protected runtime operations without creating or modifying anything.
func ValidateProtectedScope(root, controlDir string) error {
	_, _, err := resolveProtectedLayout(root, controlDir)
	return err
}

// ValidateProtectedReadOnlyScope validates a complete existing protected
// runtime before a read-only server advertises tools. It performs no migration,
// repair, cache rebuild or durable write. Ordinary tool calls repeat their own
// protected/read-only validation so this startup check is fail-fast rather
// than a substitute for per-request authority checks.
func ValidateProtectedReadOnlyScope(ctx context.Context, root, controlDir string) error {
	_, err := ResolveProtectedReadOnlyScope(ctx, root, controlDir)
	return err
}

func ResolveProtectedReadOnlyScope(ctx context.Context, root, controlDir string) (ProtectedReadOnlyScope, error) {
	root, layout, err := resolveProtectedLayout(root, controlDir)
	if err != nil {
		return ProtectedReadOnlyScope{}, err
	}
	rootPhysical, err := filepath.EvalSymlinks(root)
	if err != nil {
		return ProtectedReadOnlyScope{}, fmt.Errorf("resolve physical corpus root: %w", err)
	}
	rootPhysical = filepath.Clean(rootPhysical)
	rootInfo, err := os.Stat(root)
	if err != nil {
		return ProtectedReadOnlyScope{}, fmt.Errorf("inspect corpus root: %w", err)
	}
	physicalInfo, err := os.Stat(rootPhysical)
	if err != nil {
		return ProtectedReadOnlyScope{}, fmt.Errorf("inspect physical corpus root: %w", err)
	}
	if !os.SameFile(rootInfo, physicalInfo) {
		return ProtectedReadOnlyScope{}, ErrRuntimeRootAlias
	}
	layout, err = controlstorage.OpenExisting(layout.Dir)
	if err != nil {
		return ProtectedReadOnlyScope{}, err
	}
	if err := sqlitestate.VerifyReadOnly(ctx, layout.StateDB); err != nil {
		return ProtectedReadOnlyScope{}, err
	}
	expected, err := expectedSearchBoundaryReadOnly(ctx, layout.StateDB, root)
	if err != nil {
		return ProtectedReadOnlyScope{}, err
	}
	if err := searchsqlite.VerifyReadOnly(ctx, layout.SearchDB); err != nil {
		return ProtectedReadOnlyScope{}, err
	}
	index, err := searchsqlite.OpenReadOnly(ctx, layout.SearchDB)
	if err != nil {
		return ProtectedReadOnlyScope{}, err
	}
	boundaryErr := index.VerifySourceBoundary(ctx, expected)
	closeErr := index.Close()
	if boundaryErr != nil {
		return ProtectedReadOnlyScope{}, boundaryErr
	}
	if closeErr != nil {
		return ProtectedReadOnlyScope{}, closeErr
	}
	if err := controlstorage.Verify(layout.Dir); err != nil {
		return ProtectedReadOnlyScope{}, err
	}
	return ProtectedReadOnlyScope{Root: root, ReadRoot: rootPhysical, ControlDir: layout.Dir}, nil
}

func expectedSearchBoundaryReadOnly(ctx context.Context, stateDB, root string) (searchsqlite.SourceBoundary, error) {
	state, err := sqlitestate.OpenReadOnly(ctx, stateDB)
	if err != nil {
		return searchsqlite.SourceBoundary{}, err
	}
	defer state.Close()
	scan, found, err := state.LatestCompleteScan(ctx, ProviderID, root)
	if err != nil {
		return searchsqlite.SourceBoundary{}, err
	}
	if !found {
		return searchsqlite.SourceBoundary{}, ErrRuntimeStateUnavailable
	}
	receipt, err := proveBootstrapReceiptReadOnly(ctx, state, scan)
	if err != nil {
		return searchsqlite.SourceBoundary{}, err
	}
	return searchsqlite.SourceBoundary{
		ProviderID:         ProviderID,
		Root:               scan.Root,
		ScanID:             scan.ID,
		StartedAt:          scan.StartedAt,
		FingerprintVersion: receipt.FingerprintVersion,
		FingerprintSHA256:  receipt.FingerprintSHA256,
	}, nil
}

// preflightProtectedSearchRecovery proves that existing non-rebuildable state
// is readable and, when a committed local bootstrap exists, that the current
// corpus still matches its exact durable receipt. It is intentionally
// read-only: callers use it before creating/acquiring the search mutation lock
// and repeat it after lock acquisition before discarding any derived staging.
func preflightProtectedSearchRecovery(ctx context.Context, root string, layout controlstorage.Layout) (err error) {
	if _, statErr := os.Lstat(layout.StateDB); statErr != nil {
		if !errors.Is(statErr, os.ErrNotExist) {
			return fmt.Errorf("inspect authoritative state database: %w", statErr)
		}
		// Missing non-rebuildable state is safe only for a truly fresh control
		// profile. Any SQLite sidecar or derived search family proves that
		// durable runtime work may already have existed, so silently creating a
		// new state.db could remint Artifact/Revision identity after metadata
		// loss. search.lock alone is harmless: it can survive a crash after
		// writer serialization but before the first state transaction.
		for _, path := range []string{
			layout.StateDB + "-journal",
			layout.StateDB + "-wal",
			layout.StateDB + "-shm",
			layout.SearchDB,
			layout.SearchDB + "-journal",
			layout.SearchDB + "-wal",
			layout.SearchDB + "-shm",
			layout.SearchStagingDB,
			layout.SearchStagingDB + "-journal",
			layout.SearchStagingDB + "-wal",
			layout.SearchStagingDB + "-shm",
		} {
			if _, err := os.Lstat(path); err == nil {
				return fmt.Errorf("%w: authoritative state missing with prior control artifact %s",
					ErrStateDatabaseNotFound, filepath.Base(path))
			} else if !errors.Is(err, os.ErrNotExist) {
				return fmt.Errorf("inspect control artifact %s: %w", filepath.Base(path), err)
			}
		}
		return nil
	}

	// Full read-only verification is the fail-closed authority gate for recovery.
	// Selected scan/receipt reads below are insufficient to detect localized
	// SQLite integrity or foreign-key corruption outside the active local scope.
	if err := sqlitestate.VerifyReadOnly(ctx, layout.StateDB); err != nil {
		return err
	}

	state, err := sqlitestate.OpenReadOnly(ctx, layout.StateDB)
	if err != nil {
		return err
	}
	defer func() {
		err = errors.Join(err, state.Close())
	}()

	scan, found, err := state.LatestCompleteScan(ctx, ProviderID, root)
	if err != nil {
		return err
	}
	if !found {
		return nil
	}
	receipt, err := proveBootstrapReceiptReadOnly(ctx, state, scan)
	if err != nil {
		return err
	}
	version, fingerprint, err := ingest.BootstrapLocalFSSnapshotFingerprint(
		ctx,
		providerlocalfs.New(ProviderID),
		root,
		scan.StartedAt,
	)
	if err != nil {
		return err
	}
	if version != receipt.FingerprintVersion || fingerprint != receipt.FingerprintSHA256 {
		return fmt.Errorf("%w: durable bootstrap receipt does not match current corpus", ErrCorpusChanged)
	}
	return nil
}

// BootstrapProtectedIndex is the executable control-storage boundary. It
// resolves the physical control parent and proves the control directory is
// outside the corpus before any directory or SQLite file can be created.
type protectedSearchRecoveryOps struct {
	discardStaging  func(controlstorage.Layout) error
	verifyCandidate func(context.Context, string, searchsqlite.SourceBoundary) error
	reconcileActive func(context.Context, controlstorage.Layout) error
	promote         func(controlstorage.Layout) error
}

func defaultProtectedSearchRecoveryOps() protectedSearchRecoveryOps {
	return protectedSearchRecoveryOps{
		discardStaging:  controlstorage.DiscardStagedSearchFamily,
		verifyCandidate: verifyProtectedSearchCandidate,
		reconcileActive: reconcileActiveSearchSQLiteFamily,
		promote:         controlstorage.PromoteStagedSearchAfterReconcile,
	}
}

func BootstrapProtectedIndex(ctx context.Context, options ProtectedIndexOptions) (IndexResult, error) {
	return bootstrapProtectedIndex(ctx, options, defaultProtectedSearchRecoveryOps())
}

func bootstrapProtectedIndex(
	ctx context.Context,
	options ProtectedIndexOptions,
	ops protectedSearchRecoveryOps,
) (result IndexResult, err error) {
	if options.ObservedAt.IsZero() || options.MaxBytes < 0 {
		return IndexResult{}, ErrInvalidOptions
	}
	root, layout, err := resolveProtectedLayout(options.Root, options.ControlDir)
	if err != nil {
		return IndexResult{}, err
	}
	layout, err = controlstorage.Prepare(layout.Dir)
	if err != nil {
		return IndexResult{}, err
	}

	// Fail before any search-recovery mutation when non-rebuildable state is
	// invalid or the already-committed corpus receipt no longer matches.
	if err := preflightProtectedSearchRecovery(ctx, root, layout); err != nil {
		return IndexResult{}, err
	}

	lock, err := controlstorage.AcquireSearchMutationLock(layout)
	if err != nil {
		return IndexResult{}, err
	}
	defer func() {
		err = errors.Join(err, lock.Close())
	}()

	// Re-prove after serialization so a state/corpus change that raced the
	// first preflight cannot authorize deletion of prior staging.
	if err := preflightProtectedSearchRecovery(ctx, root, layout); err != nil {
		return IndexResult{}, err
	}

	// Staging is rebuildable derived work, never query/result authority.
	// A prior staging family therefore means only that an earlier rebuild was
	// interrupted. Discard it under the process-crash-safe writer lock and
	// rebuild from freshly reconciled state/corpus evidence.
	if err := ops.discardStaging(layout); err != nil {
		return IndexResult{}, err
	}

	result, operationErr := BootstrapIndex(ctx, IndexOptions{
		Root: root, StateDB: layout.StateDB, SearchDB: layout.SearchStagingDB,
		ObservedAt: options.ObservedAt, MaxBytes: options.MaxBytes,
	})
	if operationErr != nil {
		verifyErr := controlstorage.Verify(layout.Dir)
		if verifyErr != nil {
			return IndexResult{}, errors.Join(operationErr, verifyErr)
		}
		return IndexResult{}, operationErr
	}

	expected, err := expectedSearchBoundaryReadOnly(ctx, layout.StateDB, root)
	if err != nil {
		return IndexResult{}, err
	}
	if err := ops.verifyCandidate(ctx, layout.SearchStagingDB, expected); err != nil {
		return IndexResult{}, err
	}
	if err := controlstorage.VerifyStandaloneSearchStaging(layout); err != nil {
		return IndexResult{}, err
	}
	if err := ops.reconcileActive(ctx, layout); err != nil {
		return IndexResult{}, err
	}
	if err := ctx.Err(); err != nil {
		return IndexResult{}, err
	}
	// Promotion is the commit boundary for derived search recovery. Once this
	// final cancellation gate has passed, caller cancellation must not turn a
	// completed promotion into a reported cancellation with staging already
	// consumed. Preserve context values but detach cancellation/deadline for
	// the bounded local commit verification phase.
	commitCtx, cancelCommitVerify := context.WithTimeout(
		context.WithoutCancel(ctx),
		protectedSearchCommitVerifyTimeout,
	)
	defer cancelCommitVerify()
	if err := ops.promote(layout); err != nil {
		return IndexResult{}, err
	}
	if err := ops.verifyCandidate(commitCtx, layout.SearchDB, expected); err != nil {
		return IndexResult{}, err
	}
	if err := controlstorage.Verify(layout.Dir); err != nil {
		return IndexResult{}, err
	}
	return result, nil
}

func reconcileActiveSearchSQLiteFamily(ctx context.Context, layout controlstorage.Layout) error {
	if _, err := os.Lstat(layout.SearchDB); err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil
		}
		return fmt.Errorf("inspect active search database: %w", err)
	}
	hasSidecar := false
	for _, suffix := range []string{"-journal", "-wal", "-shm"} {
		if _, err := os.Lstat(layout.SearchDB + suffix); err == nil {
			hasSidecar = true
			break
		} else if !errors.Is(err, os.ErrNotExist) {
			return fmt.Errorf("inspect active search sidecar: %w", err)
		}
	}
	if !hasSidecar {
		return nil
	}

	// Keep the SQLite family under its original names and let SQLite attempt
	// legitimate hot-journal/WAL recovery. Reconciliation never removes the
	// active family: all deletion is part of the subsequent promotion step,
	// after the caller's final cancellation gate.
	if err := ctx.Err(); err != nil {
		return err
	}
	index, openErr := searchsqlite.Open(ctx, layout.SearchDB)
	if openErr != nil {
		if ctxErr := ctx.Err(); ctxErr != nil {
			return errors.Join(
				fmt.Errorf("reconcile active search SQLite family: %w", openErr),
				ctxErr,
			)
		}
		if errors.Is(openErr, context.Canceled) || errors.Is(openErr, context.DeadlineExceeded) {
			return fmt.Errorf("reconcile active search SQLite family: %w", openErr)
		}
		// Non-cancellation failure classifies only this rebuildable derived
		// family as unreconciled. Do not delete it here: promotion owns exact
		// family disposal after the final cancellation gate.
		return nil
	}
	if err := index.Close(); err != nil {
		return fmt.Errorf("close reconciled active search SQLite family: %w", err)
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	return nil
}

func verifyProtectedSearchCandidate(
	ctx context.Context,
	path string,
	expected searchsqlite.SourceBoundary,
) error {
	if err := searchsqlite.VerifyReadOnly(ctx, path); err != nil {
		return err
	}
	index, err := searchsqlite.OpenReadOnly(ctx, path)
	if err != nil {
		return err
	}
	boundaryErr := index.VerifySourceBoundary(ctx, expected)
	closeErr := index.Close()
	return errors.Join(boundaryErr, closeErr)
}

func QueryProtected(ctx context.Context, controlDir, query string, limit int) ([]search.Hit, error) {
	if strings.TrimSpace(controlDir) == "" {
		return nil, ErrInvalidOptions
	}
	layout, err := controlstorage.OpenExisting(controlDir)
	if err != nil {
		return nil, err
	}
	lock, err := controlstorage.AcquireSearchMutationLock(layout)
	if err != nil {
		return nil, err
	}
	hits, operationErr := Query(ctx, layout.SearchDB, query, limit)
	verifyErr := controlstorage.Verify(layout.Dir)
	lockErr := lock.Close()
	if operationErr != nil || verifyErr != nil || lockErr != nil {
		return nil, errors.Join(operationErr, verifyErr, lockErr)
	}
	return hits, nil
}

func QueryProtectedReadOnly(ctx context.Context, controlDir, query string, limit int) ([]search.Hit, error) {
	if strings.TrimSpace(controlDir) == "" {
		return nil, ErrInvalidOptions
	}
	layout, err := controlstorage.OpenExisting(controlDir)
	if err != nil {
		return nil, err
	}
	hits, operationErr := QueryReadOnly(ctx, layout.SearchDB, query, limit)
	verifyErr := controlstorage.Verify(layout.Dir)
	if operationErr != nil {
		if verifyErr != nil {
			return nil, errors.Join(operationErr, verifyErr)
		}
		return nil, operationErr
	}
	if verifyErr != nil {
		return nil, verifyErr
	}
	return hits, nil
}

// QueryProtectedReadOnlyCurrent keeps the CLI search surface rootless without
// allowing search.db to become an authority. The cache boundary supplies only
// a candidate root; QueryProtectedReadOnlyBound re-derives the exact expected
// boundary from state.db and performs boundary+FTS read in one SQLite snapshot.
func QueryProtectedReadOnlyCurrent(ctx context.Context, controlDir, query string, limit int) ([]search.Hit, error) {
	if strings.TrimSpace(controlDir) == "" {
		return nil, ErrInvalidOptions
	}
	layout, err := controlstorage.OpenExisting(controlDir)
	if err != nil {
		return nil, err
	}
	index, err := searchsqlite.OpenReadOnly(ctx, layout.SearchDB)
	if err != nil {
		return nil, err
	}
	candidate, boundaryErr := index.StoredSourceBoundary(ctx)
	closeErr := index.Close()
	if boundaryErr != nil || closeErr != nil {
		return nil, errors.Join(boundaryErr, closeErr)
	}
	if _, err := os.Lstat(layout.StateDB); err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil, ErrStateDatabaseNotFound
		}
		return nil, fmt.Errorf("inspect authoritative state database: %w", err)
	}
	return QueryProtectedReadOnlyBound(ctx, candidate.Root, layout.Dir, query, limit)
}

func QueryProtectedReadOnlyBound(ctx context.Context, root, controlDir, query string, limit int) ([]search.Hit, error) {
	root, layout, err := resolveProtectedLayout(root, controlDir)
	if err != nil {
		return nil, err
	}
	layout, err = controlstorage.OpenExisting(layout.Dir)
	if err != nil {
		return nil, err
	}
	expectedBefore, err := expectedSearchBoundaryReadOnly(ctx, layout.StateDB, root)
	if err != nil {
		return nil, err
	}
	index, err := searchsqlite.OpenReadOnly(ctx, layout.SearchDB)
	if err != nil {
		return nil, err
	}
	hits, operationErr := index.SearchBound(ctx, expectedBefore, query, limit)
	closeErr := index.Close()
	if operationErr != nil {
		return nil, errors.Join(operationErr, closeErr)
	}
	if closeErr != nil {
		return nil, closeErr
	}
	expectedAfter, err := expectedSearchBoundaryReadOnly(ctx, layout.StateDB, root)
	if err != nil {
		return nil, err
	}
	if !expectedBefore.Equal(expectedAfter) {
		return nil, searchsqlite.ErrSourceBoundaryMismatch
	}
	if err := controlstorage.Verify(layout.Dir); err != nil {
		return nil, err
	}
	return hits, nil
}

func BuildProtectedContext(ctx context.Context, options ProtectedContextOptions) (contextbundle.Bundle, error) {
	if strings.TrimSpace(options.Query) == "" ||
		strings.TrimSpace(options.Reason) == "" ||
		options.Limit < 1 ||
		options.MaxBytes < 0 ||
		options.MaxTotalBytes < 0 {
		return contextbundle.Bundle{}, ErrInvalidOptions
	}
	root, layout, err := resolveProtectedLayout(options.Root, options.ControlDir)
	if err != nil {
		return contextbundle.Bundle{}, err
	}
	layout, err = controlstorage.OpenExisting(layout.Dir)
	if err != nil {
		return contextbundle.Bundle{}, err
	}
	lock, err := controlstorage.AcquireSearchMutationLock(layout)
	if err != nil {
		return contextbundle.Bundle{}, err
	}

	bundle, operationErr := BuildContext(ctx, ContextOptions{
		Root: root, StateDB: layout.StateDB, SearchDB: layout.SearchDB,
		Query: options.Query, Reason: options.Reason, Limit: options.Limit, MaxBytes: options.MaxBytes,
		MaxTotalBytes: options.MaxTotalBytes,
	})
	verifyErr := controlstorage.Verify(layout.Dir)
	lockErr := lock.Close()
	if operationErr != nil || verifyErr != nil || lockErr != nil {
		return contextbundle.Bundle{}, errors.Join(operationErr, verifyErr, lockErr)
	}
	return bundle, nil
}

func BuildProtectedContextReadOnly(ctx context.Context, options ProtectedContextOptions) (contextbundle.Bundle, error) {
	if strings.TrimSpace(options.Query) == "" ||
		strings.TrimSpace(options.Reason) == "" ||
		options.Limit < 1 ||
		options.MaxBytes < 0 ||
		options.MaxTotalBytes < 0 {
		return contextbundle.Bundle{}, ErrInvalidOptions
	}
	root, layout, err := resolveProtectedLayout(options.Root, options.ControlDir)
	if err != nil {
		return contextbundle.Bundle{}, err
	}
	layout, err = controlstorage.OpenExisting(layout.Dir)
	if err != nil {
		return contextbundle.Bundle{}, err
	}

	bundle, operationErr := BuildContextReadOnly(ctx, ContextOptions{
		Root: root, ReadRoot: options.ReadRoot, StateDB: layout.StateDB, SearchDB: layout.SearchDB,
		Query: options.Query, Reason: options.Reason, Limit: options.Limit, MaxBytes: options.MaxBytes,
		MaxTotalBytes: options.MaxTotalBytes,
	})
	verifyErr := controlstorage.Verify(layout.Dir)
	if operationErr != nil {
		if verifyErr != nil {
			return contextbundle.Bundle{}, errors.Join(operationErr, verifyErr)
		}
		return contextbundle.Bundle{}, operationErr
	}
	if verifyErr != nil {
		return contextbundle.Bundle{}, verifyErr
	}
	return bundle, nil
}

func BuildProtectedContextReadOnlyBound(ctx context.Context, options ProtectedContextOptions) (contextbundle.Bundle, error) {
	if strings.TrimSpace(options.Query) == "" ||
		strings.TrimSpace(options.Reason) == "" ||
		options.Limit < 1 ||
		options.MaxBytes < 0 ||
		options.MaxTotalBytes < 0 {
		return contextbundle.Bundle{}, ErrInvalidOptions
	}
	root, layout, err := resolveProtectedLayout(options.Root, options.ControlDir)
	if err != nil {
		return contextbundle.Bundle{}, err
	}
	layout, err = controlstorage.OpenExisting(layout.Dir)
	if err != nil {
		return contextbundle.Bundle{}, err
	}
	expectedBefore, err := expectedSearchBoundaryReadOnly(ctx, layout.StateDB, root)
	if err != nil {
		return contextbundle.Bundle{}, err
	}
	bundle, operationErr := BuildContextReadOnly(ctx, ContextOptions{
		Root: root, ReadRoot: options.ReadRoot, SearchBoundary: &expectedBefore,
		StateDB: layout.StateDB, SearchDB: layout.SearchDB,
		Query: options.Query, Reason: options.Reason, Limit: options.Limit,
		MaxBytes: options.MaxBytes, MaxTotalBytes: options.MaxTotalBytes,
	})
	if operationErr != nil {
		verifyErr := controlstorage.Verify(layout.Dir)
		if verifyErr != nil {
			return contextbundle.Bundle{}, errors.Join(operationErr, verifyErr)
		}
		return contextbundle.Bundle{}, operationErr
	}
	expectedAfter, err := expectedSearchBoundaryReadOnly(ctx, layout.StateDB, root)
	if err != nil {
		return contextbundle.Bundle{}, err
	}
	if !expectedBefore.Equal(expectedAfter) {
		return contextbundle.Bundle{}, searchsqlite.ErrSourceBoundaryMismatch
	}
	if err := controlstorage.Verify(layout.Dir); err != nil {
		return contextbundle.Bundle{}, err
	}
	return bundle, nil
}

func resolveProtectedLayout(root, controlDir string) (string, controlstorage.Layout, error) {
	if strings.TrimSpace(root) == "" || strings.TrimSpace(controlDir) == "" {
		return "", controlstorage.Layout{}, ErrInvalidOptions
	}
	rootAbs, err := filepath.Abs(root)
	if err != nil {
		return "", controlstorage.Layout{}, fmt.Errorf("resolve corpus root: %w", err)
	}
	rootAbs = filepath.Clean(rootAbs)
	info, err := os.Stat(rootAbs)
	if err != nil {
		return "", controlstorage.Layout{}, fmt.Errorf("inspect corpus root: %w", err)
	}
	if !info.IsDir() {
		return "", controlstorage.Layout{}, ErrInvalidOptions
	}
	rootPhysical, err := filepath.EvalSymlinks(rootAbs)
	if err != nil {
		return "", controlstorage.Layout{}, fmt.Errorf("resolve physical corpus root: %w", err)
	}
	rootPhysical = filepath.Clean(rootPhysical)

	layout, err := controlstorage.Resolve(controlDir)
	if err != nil {
		return "", controlstorage.Layout{}, err
	}
	if insidePath(rootAbs, layout.Dir) || insidePath(rootPhysical, layout.Dir) {
		return "", controlstorage.Layout{}, ErrRuntimeStateInCorpus
	}
	return rootAbs, layout, nil
}
