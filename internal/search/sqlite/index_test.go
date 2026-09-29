package sqlite_test

import (
	"context"
	"errors"
	"path/filepath"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/search"
	searchsqlite "github.com/efremov-aleksei-96/keelaryn/internal/search/sqlite"
	zsqlite "zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestReplaceSearchVerifyRebuildAndReopen(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "search.db")
	index, err := searchsqlite.Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	documents := []search.Document{
		searchDocument("art-1", "rev-1", "alpha beta gamma"),
		searchDocument("art-2", "rev-2", "delta epsilon"),
	}
	if err := index.ReplaceAll(ctx, documents); err != nil {
		t.Fatal(err)
	}
	if err := index.Verify(ctx); err != nil {
		t.Fatal(err)
	}
	assertSingleHit(t, index, "alpha gamma", "art-1", "rev-1")
	if err := index.RebuildFTS(ctx); err != nil {
		t.Fatal(err)
	}
	assertSingleHit(t, index, "alpha gamma", "art-1", "rev-1")
	if err := index.Close(); err != nil {
		t.Fatal(err)
	}

	index, err = searchsqlite.Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer index.Close()
	assertSingleHit(t, index, "delta", "art-2", "rev-2")

	if err := index.ReplaceAll(ctx, []search.Document{
		searchDocument("art-3", "rev-3", "zeta eta"),
	}); err != nil {
		t.Fatal(err)
	}
	hits, err := index.Search(ctx, "alpha", 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(hits) != 0 {
		t.Fatalf("old replacement document remained searchable: %#v", hits)
	}
	assertSingleHit(t, index, "zeta", "art-3", "rev-3")
}

func TestDuplicateReplacementRollsBackPriorCompleteIndex(t *testing.T) {
	ctx := context.Background()
	index, err := searchsqlite.Open(ctx, filepath.Join(t.TempDir(), "search.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer index.Close()

	baseline := searchDocument("art-1", "rev-1", "baseline token")
	if err := index.ReplaceAll(ctx, []search.Document{baseline}); err != nil {
		t.Fatal(err)
	}
	duplicate := baseline
	duplicate.Text = "different text"
	err = index.ReplaceAll(ctx, []search.Document{baseline, duplicate})
	if !errors.Is(err, searchsqlite.ErrDuplicateDocument) {
		t.Fatalf("error=%v want ErrDuplicateDocument", err)
	}
	assertSingleHit(t, index, "baseline", "art-1", "rev-1")
}

func TestLiteralQueryDoesNotExecuteFTSOperators(t *testing.T) {
	ctx := context.Background()
	index, err := searchsqlite.Open(ctx, filepath.Join(t.TempDir(), "search.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer index.Close()
	if err := index.ReplaceAll(ctx, []search.Document{
		searchDocument("art-1", "rev-1", "alpha OR beta"),
		searchDocument("art-2", "rev-2", "alpha only"),
	}); err != nil {
		t.Fatal(err)
	}
	assertSingleHit(t, index, "alpha OR beta", "art-1", "rev-1")
}

func TestOpenRejectsNewerSearchSchema(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "search.db")
	index, err := searchsqlite.Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	if err := index.Close(); err != nil {
		t.Fatal(err)
	}

	conn, err := zsqlite.OpenConn(path, zsqlite.OpenReadWrite)
	if err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.ExecuteTransient(conn, "PRAGMA user_version = 2", nil); err != nil {
		conn.Close()
		t.Fatal(err)
	}
	if err := conn.Close(); err != nil {
		t.Fatal(err)
	}

	_, err = searchsqlite.Open(ctx, path)
	if !errors.Is(err, searchsqlite.ErrUnsupportedSchemaVersion) {
		t.Fatalf("error=%v want ErrUnsupportedSchemaVersion", err)
	}
}

func searchDocument(artifactID corpus.ArtifactID, revisionID corpus.RevisionID, text string) search.Document {
	return search.Document{
		ArtifactID: artifactID,
		RevisionID: revisionID,
		ExtractorID: "builtin:text-utf8:v1",
		MediaType: "text/plain",
		Evidence: corpus.ContentEvidence{
			Algorithm: corpus.ContentAlgorithmSHA256,
			Digest:    "digest-" + string(revisionID),
			Size:      int64(len(text)),
		},
		Text: text,
	}
}

func assertSingleHit(
	t *testing.T,
	index *searchsqlite.Index,
	query string,
	artifactID corpus.ArtifactID,
	revisionID corpus.RevisionID,
) {
	t.Helper()
	hits, err := index.Search(context.Background(), query, 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(hits) != 1 || hits[0].ArtifactID != artifactID || hits[0].RevisionID != revisionID {
		t.Fatalf("query=%q hits=%#v want %s/%s", query, hits, artifactID, revisionID)
	}
}
