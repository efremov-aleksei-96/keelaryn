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
