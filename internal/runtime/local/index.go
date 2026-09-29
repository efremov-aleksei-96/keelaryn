package local

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/extract"
	extractlocalfs "github.com/efremov-aleksei-96/keelaryn/internal/extract/localfs"
	"github.com/efremov-aleksei-96/keelaryn/internal/ingest"
	providerlocalfs "github.com/efremov-aleksei-96/keelaryn/internal/provider/localfs"
	"github.com/efremov-aleksei-96/keelaryn/internal/search"
	searchsqlite "github.com/efremov-aleksei-96/keelaryn/internal/search/sqlite"
	sqlitestate "github.com/efremov-aleksei-96/keelaryn/internal/state/sqlite"
)

var (
	ErrInvalidOptions        = errors.New("invalid local runtime options")
	ErrRuntimeStateInCorpus  = errors.New("runtime state path is inside scanned corpus")
	ErrRuntimeDatabaseAlias  = errors.New("state and search databases resolve to the same path")
	ErrCorpusChanged         = errors.New("corpus changed after durable observation")
)

const ProviderID corpus.ProviderID = "localfs"

type IndexOptions struct {
	Root       string
	StateDB    string
	SearchDB   string
	ObservedAt time.Time
	MaxBytes   int64
}

type IndexResult struct {
	ScanID        corpus.ScanSessionID `json:"scan_id"`
	Root          string               `json:"root"`
	ReusedScan    bool                 `json:"reused_scan"`
	Indexed       int                  `json:"indexed"`
	Unsupported   int                  `json:"unsupported"`
	Opaque        int                  `json:"opaque"`
	LimitExceeded int                  `json:"limit_exceeded"`
}

// BootstrapIndex composes the first useful local runtime path. It is a P0
// development-spike surface, not production/user-runtime qualification.
//
// Durable state is reconciled before mutation: if a COMPLETE bootstrap already
// exists, it is reused and the derived search cache is rebuilt. This makes an
// interruption after the state commit but before search publication safe to
// retry without blind bootstrap.
func BootstrapIndex(ctx context.Context, options IndexOptions) (IndexResult, error) {
	root, stateDB, searchDB, err := validateOptions(options)
	if err != nil {
		return IndexResult{}, err
	}

	state, err := sqlitestate.Open(ctx, stateDB)
	if err != nil {
		return IndexResult{}, err
	}
	defer state.Close()

	provider := providerlocalfs.New(ProviderID)
	scan, found, err := state.LatestCompleteScan(ctx, ProviderID, root)
	if err != nil {
		return IndexResult{}, err
	}
	reused := found
	if !found {
		scan, err = ingest.BootstrapLocalFS(ctx, state, provider, root, options.ObservedAt.UTC())
		if err != nil {
			return IndexResult{}, err
		}
	}

	inventory, err := state.Inventory(ctx, ProviderID, scan.Root)
	if err != nil {
		return IndexResult{}, err
	}

	result := IndexResult{ScanID: scan.ID, Root: scan.Root, ReusedScan: reused}
	extractions := make([]extract.Result, 0, len(inventory))
	for _, entry := range inventory {
		if entry.AssignmentState != corpus.AssignmentAssigned ||
			entry.ArtifactID == "" ||
			entry.RevisionID == "" ||
			entry.Kind != corpus.EntryRegularFile {
			continue
		}
		extracted, err := extractlocalfs.Extract(ctx, state, provider, entry, options.MaxBytes)
		if err != nil {
			return IndexResult{}, err
		}
		switch extracted.Status {
		case extract.StatusExtracted:
			extractions = append(extractions, extracted)
			result.Indexed++
		case extract.StatusUnsupported:
			result.Unsupported++
		case extract.StatusOpaque:
			result.Opaque++
		case extract.StatusLimitExceeded:
			result.LimitExceeded++
		case extract.StatusStaleRevision:
			return IndexResult{}, fmt.Errorf("%w: artifact=%s revision=%s locator=%s",
				ErrCorpusChanged, entry.ArtifactID, entry.RevisionID, entry.Locator.Path)
		default:
			return IndexResult{}, fmt.Errorf("unexpected extraction status %q", extracted.Status)
		}
	}

	index, err := searchsqlite.Open(ctx, searchDB)
	if err != nil {
		return IndexResult{}, err
	}
	defer index.Close()
	if err := index.ReplaceAll(ctx, state, extractions); err != nil {
		return IndexResult{}, err
	}
	if err := index.Verify(ctx); err != nil {
		return IndexResult{}, err
	}
	return result, nil
}

func Query(ctx context.Context, searchDB, query string, limit int) ([]search.Hit, error) {
	if strings.TrimSpace(searchDB) == "" {
		return nil, ErrInvalidOptions
	}
	index, err := searchsqlite.Open(ctx, searchDB)
	if err != nil {
		return nil, err
	}
	defer index.Close()
	return index.Search(ctx, query, limit)
}

func validateOptions(options IndexOptions) (root, stateDB, searchDB string, err error) {
	if strings.TrimSpace(options.Root) == "" ||
		strings.TrimSpace(options.StateDB) == "" ||
		strings.TrimSpace(options.SearchDB) == "" ||
		options.ObservedAt.IsZero() ||
		options.MaxBytes < 0 {
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

	if stateDB == searchDB {
		return "", "", "", ErrRuntimeDatabaseAlias
	}
	if insidePath(root, stateDB) || insidePath(root, searchDB) {
		return "", "", "", ErrRuntimeStateInCorpus
	}
	if sameExistingFile(stateDB, searchDB) {
		return "", "", "", ErrRuntimeDatabaseAlias
	}
	for _, path := range []string{stateDB, searchDB} {
		info, statErr := os.Stat(filepath.Dir(path))
		if statErr != nil {
			return "", "", "", fmt.Errorf("inspect runtime database parent: %w", statErr)
		}
		if !info.IsDir() {
			return "", "", "", ErrInvalidOptions
		}
	}
	return root, stateDB, searchDB, nil
}

func insidePath(root, candidate string) bool {
	rel, err := filepath.Rel(root, candidate)
	if err != nil {
		return false
	}
	if rel == "." {
		return true
	}
	parent := ".." + string(os.PathSeparator)
	return rel != ".." && !strings.HasPrefix(rel, parent) && !filepath.IsAbs(rel)
}

func sameExistingFile(left, right string) bool {
	leftInfo, leftErr := os.Stat(left)
	rightInfo, rightErr := os.Stat(right)
	return leftErr == nil && rightErr == nil && os.SameFile(leftInfo, rightInfo)
}
