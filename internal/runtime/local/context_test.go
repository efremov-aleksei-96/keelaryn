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

func TestBuildContextPreservesSearchOrderAndExactProvenance(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	control := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "a.txt"), []byte("shared needle alpha"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "b.md"), []byte("shared needle beta"), 0o600); err != nil {
		t.Fatal(err)
	}
	indexOptions := localruntime.IndexOptions{
		Root: root,
		StateDB: filepath.Join(control, "state.db"),
		SearchDB: filepath.Join(control, "search.db"),
		ObservedAt: time.Date(2026, 9, 29, 20, 0, 0, 0, time.UTC),
		MaxBytes: 1024,
	}
	if _, err := localruntime.BootstrapIndex(ctx, indexOptions); err != nil {
		t.Fatal(err)
	}
	hits, err := localruntime.Query(ctx, indexOptions.SearchDB, "shared needle", 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(hits) != 2 {
		t.Fatalf("hits=%#v", hits)
	}

	bundle, err := localruntime.BuildContext(ctx, localruntime.ContextOptions{
		Root: root, StateDB: indexOptions.StateDB, SearchDB: indexOptions.SearchDB,
		Query: "shared needle", Reason: "answer task from exact current sources",
		Limit: 10, MaxBytes: 1024,
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(bundle.Items) != len(hits) {
		t.Fatalf("items=%#v hits=%#v", bundle.Items, hits)
	}
	for i := range hits {
		if bundle.Items[i].ArtifactID != hits[i].ArtifactID ||
			bundle.Items[i].RevisionID != hits[i].RevisionID ||
			bundle.Items[i].ExtractorID != hits[i].ExtractorID ||
			bundle.Items[i].Evidence != hits[i].Evidence {
			t.Fatalf("item %d=%#v hit=%#v", i, bundle.Items[i], hits[i])
		}
		if bundle.Items[i].Reason != "answer task from exact current sources" ||
			bundle.Items[i].Text == "" {
			t.Fatalf("item %d=%#v", i, bundle.Items[i])
		}
	}
}

func TestBuildContextPreservesLimitExceededOutcome(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	control := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte("searchable bounded context"), 0o600); err != nil {
		t.Fatal(err)
	}
	indexOptions := localruntime.IndexOptions{
		Root: root,
		StateDB: filepath.Join(control, "state.db"),
		SearchDB: filepath.Join(control, "search.db"),
		ObservedAt: time.Date(2026, 9, 29, 20, 0, 0, 0, time.UTC),
		MaxBytes: 1024,
	}
	if _, err := localruntime.BootstrapIndex(ctx, indexOptions); err != nil {
		t.Fatal(err)
	}

	bundle, err := localruntime.BuildContext(ctx, localruntime.ContextOptions{
		Root: root, StateDB: indexOptions.StateDB, SearchDB: indexOptions.SearchDB,
		Query: "searchable", Reason: "bounded task", Limit: 10, MaxBytes: 4,
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(bundle.Items) != 1 ||
		bundle.Items[0].Status != "LIMIT_EXCEEDED" ||
		bundle.Items[0].ArtifactID == "" ||
		bundle.Items[0].RevisionID == "" ||
		bundle.Items[0].ExtractorID == "" ||
		bundle.Items[0].Text != "" ||
		bundle.Items[0].Evidence.Digest != "" {
		t.Fatalf("bundle=%#v", bundle)
	}
}

func TestBuildContextRejectsChangedRootWithoutReturningStaleBundle(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	control := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte("stable context token"), 0o600); err != nil {
		t.Fatal(err)
	}
	indexOptions := localruntime.IndexOptions{
		Root: root,
		StateDB: filepath.Join(control, "state.db"),
		SearchDB: filepath.Join(control, "search.db"),
		ObservedAt: time.Date(2026, 9, 29, 20, 0, 0, 0, time.UTC),
		MaxBytes: 1024,
	}
	if _, err := localruntime.BootstrapIndex(ctx, indexOptions); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "added.txt"), []byte("later"), 0o600); err != nil {
		t.Fatal(err)
	}

	_, err := localruntime.BuildContext(ctx, localruntime.ContextOptions{
		Root: root, StateDB: indexOptions.StateDB, SearchDB: indexOptions.SearchDB,
		Query: "stable", Reason: "task", Limit: 10, MaxBytes: 1024,
	})
	if !errors.Is(err, localruntime.ErrCorpusChanged) {
		t.Fatalf("error=%v want ErrCorpusChanged", err)
	}
}

func TestBuildContextMissingStateDoesNotCreateDatabase(t *testing.T) {
	root := t.TempDir()
	control := t.TempDir()
	searchDB := filepath.Join(control, "search.db")
	// The search path need not be valid because state absence must fail first.
	if err := os.WriteFile(searchDB, []byte("placeholder"), 0o600); err != nil {
		t.Fatal(err)
	}
	stateDB := filepath.Join(control, "missing-state.db")
	_, err := localruntime.BuildContext(context.Background(), localruntime.ContextOptions{
		Root: root, StateDB: stateDB, SearchDB: searchDB,
		Query: "x", Reason: "task", Limit: 1, MaxBytes: 1,
	})
	if !errors.Is(err, localruntime.ErrStateDatabaseNotFound) {
		t.Fatalf("error=%v want ErrStateDatabaseNotFound", err)
	}
	if _, statErr := os.Stat(stateDB); !errors.Is(statErr, os.ErrNotExist) {
		t.Fatalf("context path created missing state database: %v", statErr)
	}
}
