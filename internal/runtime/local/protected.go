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
	"github.com/efremov-aleksei-96/keelaryn/internal/search"
	searchsqlite "github.com/efremov-aleksei-96/keelaryn/internal/search/sqlite"
	sqlitestate "github.com/efremov-aleksei-96/keelaryn/internal/state/sqlite"
)

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

// BootstrapProtectedIndex is the executable control-storage boundary. It
// resolves the physical control parent and proves the control directory is
// outside the corpus before any directory or SQLite file can be created.
func BootstrapProtectedIndex(ctx context.Context, options ProtectedIndexOptions) (result IndexResult, err error) {
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

	lock, err := controlstorage.AcquireSearchMutationLock(layout)
	if err != nil {
		return IndexResult{}, err
	}
	defer func() {
		err = errors.Join(err, lock.Close())
	}()

	// Staging is rebuildable derived work, never query/result authority.
	// A prior staging family therefore means only that an earlier rebuild was
	// interrupted. Discard it under the process-crash-safe writer lock and
	// rebuild from freshly reconciled state/corpus evidence.
	if err := controlstorage.DiscardStagedSearchFamily(layout); err != nil {
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
	if err := verifyProtectedSearchCandidate(ctx, layout.SearchStagingDB, expected); err != nil {
		return IndexResult{}, err
	}
	if err := controlstorage.VerifyStandaloneSearchStaging(layout); err != nil {
		return IndexResult{}, err
	}
	if err := controlstorage.PromoteStagedSearch(layout); err != nil {
		return IndexResult{}, err
	}
	if err := verifyProtectedSearchCandidate(ctx, layout.SearchDB, expected); err != nil {
		return IndexResult{}, err
	}
	if err := controlstorage.Verify(layout.Dir); err != nil {
		return IndexResult{}, err
	}
	return result, nil
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
	hits, operationErr := Query(ctx, layout.SearchDB, query, limit)
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

	bundle, operationErr := BuildContext(ctx, ContextOptions{
		Root: root, StateDB: layout.StateDB, SearchDB: layout.SearchDB,
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
