package local_test

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"

	localruntime "github.com/efremov-aleksei-96/keelaryn/internal/runtime/local"
)

func TestBootstrapIndexRecoversCommittedEmptyCorpus(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	control := t.TempDir()
	options := localruntime.IndexOptions{
		Root: root,
		StateDB: filepath.Join(control, "state.db"),
		SearchDB: filepath.Join(control, "search.db"),
		ObservedAt: time.Date(2026, 9, 29, 19, 20, 0, 0, time.UTC),
		MaxBytes: 1024,
	}

	first, err := localruntime.BootstrapIndex(ctx, options)
	if err != nil {
		t.Fatal(err)
	}
	if first.ReusedScan || first.Indexed != 0 {
		t.Fatalf("first=%#v", first)
	}

	options.ObservedAt = options.ObservedAt.Add(time.Hour)
	second, err := localruntime.BootstrapIndex(ctx, options)
	if err != nil {
		t.Fatal(err)
	}
	if !second.ReusedScan || second.ScanID != first.ScanID {
		t.Fatalf("second=%#v first=%#v", second, first)
	}
}

func TestBootstrapIndexRejectsChangedCorpusAndPreservesSearch(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	control := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "one.txt"), []byte("stable searchable token"), 0o600); err != nil {
		t.Fatal(err)
	}
	options := localruntime.IndexOptions{
		Root: root,
		StateDB: filepath.Join(control, "state.db"),
		SearchDB: filepath.Join(control, "search.db"),
		ObservedAt: time.Date(2026, 9, 29, 19, 20, 0, 0, time.UTC),
		MaxBytes: 1024,
	}
	if _, err := localruntime.BootstrapIndex(ctx, options); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "two.txt"), []byte("new token"), 0o600); err != nil {
		t.Fatal(err)
	}
	options.ObservedAt = options.ObservedAt.Add(time.Hour)
	if _, err := localruntime.BootstrapIndex(ctx, options); !errors.Is(err, localruntime.ErrCorpusChanged) {
		t.Fatalf("error=%v want ErrCorpusChanged", err)
	}
	hits, err := localruntime.Query(ctx, options.SearchDB, "stable", 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(hits) != 1 {
		t.Fatalf("previous complete search cache was not preserved: %#v", hits)
	}
}

func TestQueryMissingSearchCacheDoesNotCreateDatabase(t *testing.T) {
	path := filepath.Join(t.TempDir(), "missing.db")
	_, err := localruntime.Query(context.Background(), path, "anything", 10)
	if !errors.Is(err, localruntime.ErrSearchCacheNotFound) {
		t.Fatalf("error=%v want ErrSearchCacheNotFound", err)
	}
	if _, statErr := os.Stat(path); !errors.Is(statErr, os.ErrNotExist) {
		t.Fatalf("query created missing search database: %v", statErr)
	}
}

func TestBootstrapIndexRejectsRuntimeDatabaseInsideCorpusBeforeMutation(t *testing.T) {
	root := t.TempDir()
	control := t.TempDir()
	statePath := filepath.Join(root, "state.db")
	_, err := localruntime.BootstrapIndex(context.Background(), localruntime.IndexOptions{
		Root: root,
		StateDB: statePath,
		SearchDB: filepath.Join(control, "search.db"),
		ObservedAt: time.Date(2026, 9, 29, 19, 20, 0, 0, time.UTC),
		MaxBytes: 1024,
	})
	if !errors.Is(err, localruntime.ErrRuntimeStateInCorpus) {
		t.Fatalf("error=%v want ErrRuntimeStateInCorpus", err)
	}
	if _, statErr := os.Stat(statePath); !errors.Is(statErr, os.ErrNotExist) {
		t.Fatalf("state database was created inside corpus: %v", statErr)
	}
}
