package sqlite_test

import (
	"context"
	"errors"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/extract"
	searchsqlite "github.com/efremov-aleksei-96/keelaryn/internal/search/sqlite"
)

func TestBoundReplacementPersistsExactSourceBoundary(t *testing.T) {
	ctx := context.Background()
	index, err := searchsqlite.Open(ctx, filepath.Join(t.TempDir(), "search.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer index.Close()

	result := searchExtraction("art-bound", "rev-bound", "bound search cache")
	boundary := searchsqlite.SourceBoundary{
		ProviderID: "localfs",
		Root: filepath.Join(t.TempDir(), "root"),
		ScanID: "scan-bound",
		StartedAt: time.Date(2026, 10, 2, 12, 0, 0, 123, time.UTC),
		FingerprintVersion: "localfs-snapshot:v1",
		FingerprintSHA256: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
	}
	if err := index.ReplaceAllBound(ctx, revisionsFor([]extract.Result{result}), []extract.Result{result}, boundary); err != nil {
		t.Fatal(err)
	}
	if err := index.VerifySourceBoundary(ctx, boundary); err != nil {
		t.Fatal(err)
	}

	wrong := boundary
	wrong.ScanID = corpus.ScanSessionID("scan-other")
	if err := index.VerifySourceBoundary(ctx, wrong); !errors.Is(err, searchsqlite.ErrSourceBoundaryMismatch) {
		t.Fatalf("wrong boundary error=%v", err)
	}

	if err := index.ReplaceAll(ctx, revisionsFor([]extract.Result{result}), []extract.Result{result}); err != nil {
		t.Fatal(err)
	}
	if err := index.VerifySourceBoundary(ctx, boundary); !errors.Is(err, searchsqlite.ErrSourceBoundaryMismatch) {
		t.Fatalf("unbound replacement retained stale boundary: %v", err)
	}
}


func TestSearchBoundUsesMatchingSourceBoundary(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "search.db")
	index, err := searchsqlite.Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	result := searchExtraction("art-search-bound", "rev-search-bound", "transactional boundary token")
	boundary := searchsqlite.SourceBoundary{
		ProviderID: "localfs",
		Root: filepath.Join(t.TempDir(), "root"),
		ScanID: "scan-search-bound",
		StartedAt: time.Date(2026, 10, 2, 13, 0, 0, 0, time.UTC),
		FingerprintVersion: "localfs-snapshot:v1",
		FingerprintSHA256: "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
	}
	if err := index.ReplaceAllBound(ctx, revisionsFor([]extract.Result{result}), []extract.Result{result}, boundary); err != nil {
		index.Close()
		t.Fatal(err)
	}
	if err := index.Close(); err != nil {
		t.Fatal(err)
	}

	reader, err := searchsqlite.OpenReadOnly(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer reader.Close()
	hits, err := reader.SearchBound(ctx, boundary, "transactional token", 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(hits) != 1 || hits[0].ArtifactID != "art-search-bound" || hits[0].RevisionID != "rev-search-bound" {
		t.Fatalf("hits=%#v", hits)
	}
	wrong := boundary
	wrong.FingerprintSHA256 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
	if _, err := reader.SearchBound(ctx, wrong, "transactional token", 10); !errors.Is(err, searchsqlite.ErrSourceBoundaryMismatch) {
		t.Fatalf("wrong-boundary error=%v want ErrSourceBoundaryMismatch", err)
	}
}
