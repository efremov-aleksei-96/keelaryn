package local

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/efremov-aleksei-96/keelaryn/internal/contextbundle"
	contextlocalfs "github.com/efremov-aleksei-96/keelaryn/internal/contextbundle/localfs"
	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/extract"
	extractlocalfs "github.com/efremov-aleksei-96/keelaryn/internal/extract/localfs"
	"github.com/efremov-aleksei-96/keelaryn/internal/ingest"
	providerlocalfs "github.com/efremov-aleksei-96/keelaryn/internal/provider/localfs"
	"github.com/efremov-aleksei-96/keelaryn/internal/search"
	sqlitestate "github.com/efremov-aleksei-96/keelaryn/internal/state/sqlite"
)

var (
	ErrStateDatabaseNotFound      = errors.New("state database does not exist")
	ErrRuntimeStateUnavailable    = errors.New("no complete local runtime state")
	ErrSearchHitNotCurrent        = errors.New("search hit does not match current inventory")
	ErrSearchHitExtractorMismatch = errors.New("search hit extractor is not supported by local ContextBundle runtime")
	ErrContextProvenanceMismatch  = errors.New("ContextBundle provenance does not match search hit")
)

type ContextOptions struct {
	Root          string
	ReadRoot      string
	StateDB       string
	SearchDB      string
	Query         string
	Reason        string
	Limit         int
	MaxBytes      int64
	MaxTotalBytes int64
}

// BuildContext composes literal FTS hits with the current durable Inventory and
// the already-qualified local ContextBundle builder.
//
// Search is selection assistance only: every hit must still match the exact
// current Artifact+Revision before the corpus is read. The bundle remains
// ephemeral/rebuildable and no search ranking becomes durable identity state.
func BuildContext(ctx context.Context, options ContextOptions) (contextbundle.Bundle, error) {
	root, stateDB, searchDB, err := validateContextOptions(options)
	if err != nil {
		return contextbundle.Bundle{}, err
	}

	state, err := sqlitestate.Open(ctx, stateDB)
	if err != nil {
		return contextbundle.Bundle{}, err
	}
	defer state.Close()

	provider := providerlocalfs.New(ProviderID)
	scan, found, err := state.LatestCompleteScan(ctx, ProviderID, root)
	if err != nil {
		return contextbundle.Bundle{}, err
	}
	if !found {
		return contextbundle.Bundle{}, ErrRuntimeStateUnavailable
	}

	// Re-prove the exact immutable bootstrap/source boundary before any
	// ContextBundle corpus reads.
	if _, err := replayBootstrap(ctx, state, provider, scan); err != nil {
		return contextbundle.Bundle{}, err
	}

	hits, err := Query(ctx, searchDB, options.Query, options.Limit)
	if err != nil {
		return contextbundle.Bundle{}, err
	}
	inventory, err := state.Inventory(ctx, ProviderID, scan.Root)
	if err != nil {
		return contextbundle.Bundle{}, err
	}
	selections, err := selectionsForHits(hits, inventory, options.Reason, options.MaxBytes)
	if err != nil {
		return contextbundle.Bundle{}, err
	}

	bundle, err := buildContextBundle(ctx, state, provider, selections, options.MaxTotalBytes)
	if err != nil {
		return contextbundle.Bundle{}, err
	}
	if err := verifyBundleAgainstHits(bundle, hits); err != nil {
		return contextbundle.Bundle{}, err
	}

	// A change to any part of the observed root during bundle construction,
	// including an unrelated addition/removal, invalidates the task context.
	if _, err := replayBootstrap(ctx, state, provider, scan); err != nil {
		return contextbundle.Bundle{}, err
	}
	return bundle, nil
}


func BuildContextReadOnly(ctx context.Context, options ContextOptions) (contextbundle.Bundle, error) {
	root, stateDB, searchDB, err := validateContextOptions(options)
	if err != nil {
		return contextbundle.Bundle{}, err
	}
	readRoot, err := resolveContextReadRoot(options.ReadRoot, root)
	if err != nil {
		return contextbundle.Bundle{}, err
	}

	state, err := sqlitestate.OpenReadOnly(ctx, stateDB)
	if err != nil {
		return contextbundle.Bundle{}, err
	}
	defer state.Close()

	provider := providerlocalfs.New(ProviderID)
	scan, found, err := state.LatestCompleteScan(ctx, ProviderID, root)
	if err != nil {
		return contextbundle.Bundle{}, err
	}
	if !found {
		return contextbundle.Bundle{}, ErrRuntimeStateUnavailable
	}

	// Re-prove the exact immutable bootstrap/source boundary before any
	// ContextBundle corpus reads.
	if err := proveBootstrapReadOnlyAtRoot(ctx, state, provider, scan, readRoot); err != nil {
		return contextbundle.Bundle{}, err
	}

	hits, err := QueryReadOnly(ctx, searchDB, options.Query, options.Limit)
	if err != nil {
		return contextbundle.Bundle{}, err
	}
	inventory, err := state.Inventory(ctx, ProviderID, scan.Root)
	if err != nil {
		return contextbundle.Bundle{}, err
	}
	selections, err := selectionsForHits(hits, inventory, options.Reason, options.MaxBytes)
	if err != nil {
		return contextbundle.Bundle{}, err
	}

	bundle, err := buildContextBundleAtRoot(ctx, state, provider, selections, readRoot, options.MaxTotalBytes)
	if err != nil {
		return contextbundle.Bundle{}, err
	}
	if err := verifyBundleAgainstHits(bundle, hits); err != nil {
		return contextbundle.Bundle{}, err
	}

	// A change to any part of the observed root during bundle construction,
	// including an unrelated addition/removal, invalidates the task context.
	if err := proveBootstrapReadOnlyAtRoot(ctx, state, provider, scan, readRoot); err != nil {
		return contextbundle.Bundle{}, err
	}
	return bundle, nil
}

func buildContextBundle(
	ctx context.Context,
	state *sqlitestate.Store,
	provider *providerlocalfs.Provider,
	selections []contextbundle.Selection,
	maxTotalBytes int64,
) (contextbundle.Bundle, error) {
	if maxTotalBytes > 0 {
		return contextlocalfs.BuildWithTotalMaxBytes(ctx, state, provider, selections, maxTotalBytes)
	}
	return contextlocalfs.Build(ctx, state, provider, selections)
}

func proveBootstrapReceiptReadOnly(
	ctx context.Context,
	state *sqlitestate.Store,
	expected corpus.ScanSession,
) (sqlitestate.LocalIngestCommitReceipt, error) {
	receipt, found, err := state.LocalIngestCommitAtBoundary(
		ctx,
		ProviderID,
		expected.Root,
		expected.StartedAt,
		true,
	)
	if err != nil {
		return sqlitestate.LocalIngestCommitReceipt{}, fmt.Errorf("read durable bootstrap receipt: %w", err)
	}
	if !found || receipt.Scan.ID != expected.ID {
		return sqlitestate.LocalIngestCommitReceipt{}, fmt.Errorf(
			"%w: expected=%s receipt_found=%t receipt=%s",
			ErrBootstrapReplayMismatch, expected.ID, found, receipt.Scan.ID,
		)
	}
	return receipt, nil
}

func buildContextBundleAtRoot(
	ctx context.Context,
	state *sqlitestate.Store,
	provider *providerlocalfs.Provider,
	selections []contextbundle.Selection,
	readRoot string,
	maxTotalBytes int64,
) (contextbundle.Bundle, error) {
	if maxTotalBytes > 0 {
		return contextlocalfs.BuildWithTotalMaxBytesAtRoot(ctx, state, provider, selections, readRoot, maxTotalBytes)
	}
	return contextlocalfs.BuildAtRoot(ctx, state, provider, selections, readRoot)
}

func proveBootstrapReadOnly(
	ctx context.Context,
	state *sqlitestate.Store,
	provider *providerlocalfs.Provider,
	expected corpus.ScanSession,
) error {
	return proveBootstrapReadOnlyAtRoot(ctx, state, provider, expected, expected.Root)
}

func proveBootstrapReadOnlyAtRoot(
	ctx context.Context,
	state *sqlitestate.Store,
	provider *providerlocalfs.Provider,
	expected corpus.ScanSession,
	readRoot string,
) error {
	version, fingerprint, err := ingest.BootstrapLocalFSSnapshotFingerprintAtRoot(
		ctx,
		provider,
		readRoot,
		expected.Root,
		expected.StartedAt,
	)
	if err != nil {
		return fmt.Errorf("reconcile durable bootstrap read-only: %w", err)
	}
	receipt, err := proveBootstrapReceiptReadOnly(ctx, state, expected)
	if err != nil {
		return err
	}
	if receipt.FingerprintVersion != version || receipt.FingerprintSHA256 != fingerprint {
		return fmt.Errorf("%w: bootstrap fingerprint mismatch", ErrCorpusChanged)
	}
	return nil
}

func selectionsForHits(
	hits []search.Hit,
	inventory []corpus.InventoryEntry,
	reason string,
	maxBytes int64,
) ([]contextbundle.Selection, error) {
	type key struct {
		artifact corpus.ArtifactID
		revision corpus.RevisionID
	}
	current := make(map[key]corpus.InventoryEntry)
	for _, entry := range inventory {
		if entry.AssignmentState != corpus.AssignmentAssigned ||
			entry.ArtifactID == "" ||
			entry.RevisionID == "" ||
			entry.Kind != corpus.EntryRegularFile {
			continue
		}
		k := key{artifact: entry.ArtifactID, revision: entry.RevisionID}
		if _, exists := current[k]; !exists {
			// Inventory is already ordered by locator path. Choosing the first
			// current locator is a deterministic read-locator choice only; it
			// does not participate in Artifact identity.
			current[k] = entry
		}
	}

	selections := make([]contextbundle.Selection, 0, len(hits))
	for _, hit := range hits {
		if hit.ExtractorID != extractlocalfs.ExtractorID {
			return nil, fmt.Errorf("%w: artifact=%s revision=%s extractor=%s",
				ErrSearchHitExtractorMismatch, hit.ArtifactID, hit.RevisionID, hit.ExtractorID)
		}
		entry, ok := current[key{artifact: hit.ArtifactID, revision: hit.RevisionID}]
		if !ok {
			return nil, fmt.Errorf("%w: artifact=%s revision=%s",
				ErrSearchHitNotCurrent, hit.ArtifactID, hit.RevisionID)
		}
		selections = append(selections, contextbundle.Selection{
			Entry: entry, Reason: reason, MaxBytes: maxBytes,
		})
	}
	return selections, nil
}

func verifyBundleAgainstHits(bundle contextbundle.Bundle, hits []search.Hit) error {
	if len(bundle.Items) != len(hits) {
		return fmt.Errorf("%w: items=%d hits=%d", ErrContextProvenanceMismatch, len(bundle.Items), len(hits))
	}
	for i := range hits {
		item := bundle.Items[i]
		hit := hits[i]
		if item.ArtifactID != hit.ArtifactID ||
			item.RevisionID != hit.RevisionID ||
			item.ExtractorID != hit.ExtractorID {
			return fmt.Errorf("%w: index=%d", ErrContextProvenanceMismatch, i)
		}
		switch item.Status {
		case extract.StatusExtracted, extract.StatusOpaque:
			if item.Evidence != hit.Evidence {
				return fmt.Errorf("%w: evidence index=%d", ErrContextProvenanceMismatch, i)
			}
		case extract.StatusUnsupported, extract.StatusLimitExceeded:
			// These qualified bounded outcomes intentionally carry no fresh
			// ContentEvidence. Exact Artifact/Revision/extractor provenance is
			// still preserved; no text is returned.
			if item.Text != "" || item.Evidence != (corpus.ContentEvidence{}) {
				return fmt.Errorf("%w: bounded outcome index=%d", ErrContextProvenanceMismatch, i)
			}
		case extract.StatusStaleRevision:
			return fmt.Errorf("%w: artifact=%s revision=%s",
				ErrCorpusChanged, item.ArtifactID, item.RevisionID)
		default:
			return fmt.Errorf("%w: unexpected status=%s index=%d",
				ErrContextProvenanceMismatch, item.Status, i)
		}
	}
	return nil
}

func resolveContextReadRoot(value, authorityRoot string) (string, error) {
	if strings.TrimSpace(value) == "" {
		return authorityRoot, nil
	}
	readRoot, err := filepath.Abs(value)
	if err != nil {
		return "", fmt.Errorf("resolve corpus read root: %w", err)
	}
	readRoot = filepath.Clean(readRoot)
	info, err := os.Stat(readRoot)
	if err != nil {
		return "", fmt.Errorf("inspect corpus read root: %w", err)
	}
	if !info.IsDir() {
		return "", ErrInvalidOptions
	}
	return readRoot, nil
}

func validateContextOptions(options ContextOptions) (root, stateDB, searchDB string, err error) {
	if strings.TrimSpace(options.Root) == "" ||
		strings.TrimSpace(options.StateDB) == "" ||
		strings.TrimSpace(options.SearchDB) == "" ||
		strings.TrimSpace(options.Query) == "" ||
		strings.TrimSpace(options.Reason) == "" ||
		options.Limit < 1 ||
		options.MaxBytes < 0 ||
		options.MaxTotalBytes < 0 {
		return "", "", "", ErrInvalidOptions
	}

	root, err = filepath.Abs(options.Root)
	if err != nil {
		return "", "", "", fmt.Errorf("resolve corpus root: %w", err)
	}
	root = filepath.Clean(root)
	if info, statErr := os.Stat(root); statErr != nil {
		return "", "", "", fmt.Errorf("inspect corpus root: %w", statErr)
	} else if !info.IsDir() {
		return "", "", "", ErrInvalidOptions
	}

	stateDB, err = filepath.Abs(options.StateDB)
	if err != nil {
		return "", "", "", fmt.Errorf("resolve state database: %w", err)
	}
	searchDB, err = filepath.Abs(options.SearchDB)
	if err != nil {
		return "", "", "", fmt.Errorf("resolve search database: %w", err)
	}
	stateDB, searchDB = filepath.Clean(stateDB), filepath.Clean(searchDB)

	if stateDB == searchDB || sameExistingFile(stateDB, searchDB) {
		return "", "", "", ErrRuntimeDatabaseAlias
	}
	if insidePath(root, stateDB) || insidePath(root, searchDB) {
		return "", "", "", ErrRuntimeStateInCorpus
	}

	stateInfo, err := os.Stat(stateDB)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return "", "", "", ErrStateDatabaseNotFound
		}
		return "", "", "", fmt.Errorf("inspect state database: %w", err)
	}
	if stateInfo.IsDir() {
		return "", "", "", ErrInvalidOptions
	}

	searchInfo, err := os.Stat(searchDB)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return "", "", "", ErrSearchCacheNotFound
		}
		return "", "", "", fmt.Errorf("inspect search database: %w", err)
	}
	if searchInfo.IsDir() {
		return "", "", "", ErrInvalidOptions
	}
	return root, stateDB, searchDB, nil
}
