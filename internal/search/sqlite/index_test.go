package sqlite_test

import (
	"context"
	"errors"
	"path/filepath"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/extract"
	"github.com/efremov-aleksei-96/keelaryn/internal/search"
	searchsqlite "github.com/efremov-aleksei-96/keelaryn/internal/search/sqlite"
	zsqlite "zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

type revisionReader map[corpus.ArtifactID][]corpus.RevisionRecord

func (r revisionReader) RevisionHistory(_ context.Context, artifactID corpus.ArtifactID) ([]corpus.RevisionRecord, error) {
	return append([]corpus.RevisionRecord(nil), r[artifactID]...), nil
}

func TestReplaceSearchVerifyRebuildAndReopen(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "search.db")
	index, err := searchsqlite.Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	results := []extract.Result{
		searchExtraction("art-1", "rev-1", "alpha beta gamma"),
		searchExtraction("art-2", "rev-2", "delta epsilon"),
	}
	if err := index.ReplaceAll(ctx, revisionsFor(results), results); err != nil {
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

	replacement := []extract.Result{searchExtraction("art-3", "rev-3", "zeta eta")}
	if err := index.ReplaceAll(ctx, revisionsFor(replacement), replacement); err != nil {
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

func TestDuplicateReplacementPreservesPriorCompleteIndex(t *testing.T) {
	ctx := context.Background()
	index, err := searchsqlite.Open(ctx, filepath.Join(t.TempDir(), "search.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer index.Close()

	baseline := searchExtraction("art-1", "rev-1", "baseline token")
	if err := index.ReplaceAll(ctx, revisionsFor([]extract.Result{baseline}), []extract.Result{baseline}); err != nil {
		t.Fatal(err)
	}
	duplicate := baseline
	duplicate.Text = "different text"
	results := []extract.Result{baseline, duplicate}
	err = index.ReplaceAll(ctx, revisionsFor(results), results)
	if !errors.Is(err, searchsqlite.ErrDuplicateDocument) {
		t.Fatalf("error=%v want ErrDuplicateDocument", err)
	}
	assertSingleHit(t, index, "baseline", "art-1", "rev-1")
}

func TestRevisionMismatchPreservesPriorCompleteIndex(t *testing.T) {
	ctx := context.Background()
	index, err := searchsqlite.Open(ctx, filepath.Join(t.TempDir(), "search.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer index.Close()

	baseline := searchExtraction("art-1", "rev-1", "baseline token")
	reader := revisionsFor([]extract.Result{baseline})
	if err := index.ReplaceAll(ctx, reader, []extract.Result{baseline}); err != nil {
		t.Fatal(err)
	}
	bad := searchExtraction("art-2", "rev-2", "replacement")
	err = index.ReplaceAll(ctx, reader, []extract.Result{bad})
	if !errors.Is(err, search.ErrExtractionRevisionMismatch) {
		t.Fatalf("error=%v want ErrExtractionRevisionMismatch", err)
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
	results := []extract.Result{
		searchExtraction("art-1", "rev-1", "alpha OR beta"),
		searchExtraction("art-2", "rev-2", "alpha only"),
	}
	if err := index.ReplaceAll(ctx, revisionsFor(results), results); err != nil {
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

func searchExtraction(artifactID corpus.ArtifactID, revisionID corpus.RevisionID, text string) extract.Result {
	return extract.Result{
		Status:      extract.StatusExtracted,
		ArtifactID:  artifactID,
		RevisionID:  revisionID,
		ExtractorID: "builtin:text-utf8:v1",
		MediaType:   "text/plain",
		Evidence: corpus.ContentEvidence{
			Algorithm: corpus.ContentAlgorithmSHA256,
			Digest:    "digest-" + string(revisionID),
			Size:      int64(len(text)),
		},
		Text: text,
	}
}

func revisionsFor(results []extract.Result) revisionReader {
	out := revisionReader{}
	seen := map[string]bool{}
	nextSequence := map[corpus.ArtifactID]uint64{}
	for _, result := range results {
		key := string(result.ArtifactID) + "\x00" + string(result.RevisionID)
		if seen[key] {
			continue
		}
		seen[key] = true
		nextSequence[result.ArtifactID]++
		out[result.ArtifactID] = append(out[result.ArtifactID], corpus.RevisionRecord{
			Revision: corpus.Revision{ID: result.RevisionID, ArtifactID: result.ArtifactID},
			Sequence: nextSequence[result.ArtifactID],
			Evidence: result.Evidence,
		})
	}
	return out
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
