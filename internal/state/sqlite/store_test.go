package sqlitestate_test

import (
	"context"
	"errors"
	"path/filepath"
	"strings"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	sqlitestate "github.com/efremov-aleksei-96/keelaryn/internal/state/sqlite"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestStoreReopenPreservesArtifactAndRevision(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "state.db")

	store, err := sqlitestate.Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	artifact, err := store.AdoptArtifact(ctx)
	if err != nil {
		t.Fatal(err)
	}
	revision, err := store.ObserveRevision(ctx, artifact.ID, evidence("a", 1))
	if err != nil {
		t.Fatal(err)
	}
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}

	store, err = sqlitestate.Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	exists, err := store.ArtifactExists(ctx, artifact.ID)
	if err != nil {
		t.Fatal(err)
	}
	if !exists {
		t.Fatalf("Artifact %q was lost after reopen", artifact.ID)
	}
	history, err := store.RevisionHistory(ctx, artifact.ID)
	if err != nil {
		t.Fatal(err)
	}
	if len(history) != 1 || history[0].Revision.ID != revision.Current.Revision.ID {
		t.Fatalf("history after reopen=%#v, want Revision %q", history, revision.Current.Revision.ID)
	}
}

func TestStoreUnchangedEvidenceIsIdempotent(t *testing.T) {
	ctx := context.Background()
	store := openStore(t)
	artifact, err := store.AdoptArtifact(ctx)
	if err != nil {
		t.Fatal(err)
	}

	first, err := store.ObserveRevision(ctx, artifact.ID, evidence("same", 4))
	if err != nil {
		t.Fatal(err)
	}
	second, err := store.ObserveRevision(ctx, artifact.ID, evidence("same", 4))
	if err != nil {
		t.Fatal(err)
	}

	if !first.Created || second.Created {
		t.Fatalf("created flags first=%v second=%v", first.Created, second.Created)
	}
	if first.Current.Revision.ID != second.Current.Revision.ID {
		t.Fatalf("unchanged evidence changed Revision ID: %q -> %q", first.Current.Revision.ID, second.Current.Revision.ID)
	}
	history, err := store.RevisionHistory(ctx, artifact.ID)
	if err != nil {
		t.Fatal(err)
	}
	if len(history) != 1 {
		t.Fatalf("history len=%d, want 1", len(history))
	}
}

func TestStoreReturnToOldBytesCreatesThirdRevision(t *testing.T) {
	ctx := context.Background()
	store := openStore(t)
	artifact, err := store.AdoptArtifact(ctx)
	if err != nil {
		t.Fatal(err)
	}

	a1, err := store.ObserveRevision(ctx, artifact.ID, evidence("A", 1))
	if err != nil {
		t.Fatal(err)
	}
	b, err := store.ObserveRevision(ctx, artifact.ID, evidence("B", 1))
	if err != nil {
		t.Fatal(err)
	}
	a2, err := store.ObserveRevision(ctx, artifact.ID, evidence("A", 1))
	if err != nil {
		t.Fatal(err)
	}

	if a2.Current.Sequence != 3 {
		t.Fatalf("sequence=%d, want 3", a2.Current.Sequence)
	}
	if a2.Current.Revision.ID == a1.Current.Revision.ID || a2.Current.Revision.ID == b.Current.Revision.ID {
		t.Fatalf("A→B→A reused old Revision identity")
	}
	history, err := store.RevisionHistory(ctx, artifact.ID)
	if err != nil {
		t.Fatal(err)
	}
	if len(history) != 3 {
		t.Fatalf("history len=%d, want 3", len(history))
	}
}

func TestStoreRejectsWrongApplicationID(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "foreign.db")

	conn, err := sqlite.OpenConn(path, sqlite.OpenReadWrite, sqlite.OpenCreate)
	if err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.ExecuteTransient(conn, "PRAGMA application_id = 123456;", nil); err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.ExecuteTransient(conn, "CREATE TABLE foreign_table (id INTEGER);", nil); err != nil {
		t.Fatal(err)
	}
	if err := conn.Close(); err != nil {
		t.Fatal(err)
	}

	store, err := sqlitestate.Open(ctx, path)
	if store != nil {
		_ = store.Close()
	}
	if err == nil {
		t.Fatal("opening foreign application database unexpectedly succeeded")
	}
	if !strings.Contains(err.Error(), "application_id") {
		t.Fatalf("error=%v, want application_id guard failure", err)
	}
}

func TestStoreMigrationIsIdempotent(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "state.db")
	for i := 0; i < 3; i++ {
		store, err := sqlitestate.Open(ctx, path)
		if err != nil {
			t.Fatalf("open %d: %v", i, err)
		}
		if err := store.Close(); err != nil {
			t.Fatalf("close %d: %v", i, err)
		}
	}
}

func TestStoreUnknownArtifactDoesNotCreateRevision(t *testing.T) {
	ctx := context.Background()
	store := openStore(t)

	_, err := store.ObserveRevision(ctx, "art_missing", evidence("x", 1))
	if !errors.Is(err, corpus.ErrArtifactNotFound) {
		t.Fatalf("error=%v, want ErrArtifactNotFound", err)
	}
	history, err := store.RevisionHistory(ctx, "art_missing")
	if err != nil {
		t.Fatal(err)
	}
	if len(history) != 0 {
		t.Fatalf("unknown Artifact gained revisions: %#v", history)
	}
}

func TestStoreAlgorithmChangeFailsWithoutMutation(t *testing.T) {
	ctx := context.Background()
	store := openStore(t)
	artifact, err := store.AdoptArtifact(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.ObserveRevision(ctx, artifact.ID, evidence("x", 1)); err != nil {
		t.Fatal(err)
	}

	_, err = store.ObserveRevision(ctx, artifact.ID, corpus.ContentEvidence{
		Algorithm: "blake3",
		Digest:    "x",
		Size:      1,
	})
	if !errors.Is(err, corpus.ErrContentEvidenceNotComparable) {
		t.Fatalf("error=%v, want ErrContentEvidenceNotComparable", err)
	}
	history, err := store.RevisionHistory(ctx, artifact.ID)
	if err != nil {
		t.Fatal(err)
	}
	if len(history) != 1 {
		t.Fatalf("algorithm mismatch mutated history: %#v", history)
	}
}

func TestStoreSchemaContainsOnlyIdentityTables(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "state.db")
	store, err := sqlitestate.Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}

	conn, err := sqlite.OpenConn(path, sqlite.OpenReadOnly)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()

	var names []string
	err = sqlitex.Execute(conn,
		"SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name",
		&sqlitex.ExecOptions{ResultFunc: func(stmt *sqlite.Stmt) error {
			names = append(names, stmt.ColumnText(0))
			return nil
		}})
	if err != nil {
		t.Fatal(err)
	}
	if got, want := strings.Join(names, ","), "accepted_artifact_admissions,accepted_continuity_decisions,artifacts,identity_authority_candidates,identity_authority_sets,identity_mutation_requests,locators,observations,provider_artifact_bindings,provider_lifetime_artifact_bindings,provider_object_lifetime_segments,provider_object_occurrences,remote_history_bootstrap_membership,remote_history_generations,remote_history_membership,remote_history_publication_changes,remote_history_publications,revisions,scan_sessions"; got != want {
		t.Fatalf("tables=%q, want %q", got, want)
	}
}

func TestStoreDurableIDsAreNotContentHashes(t *testing.T) {
	ctx := context.Background()
	store := openStore(t)
	artifact, err := store.AdoptArtifact(ctx)
	if err != nil {
		t.Fatal(err)
	}
	revision, err := store.ObserveRevision(ctx, artifact.ID, evidence("deadbeef", 8))
	if err != nil {
		t.Fatal(err)
	}

	if string(artifact.ID) == "deadbeef" {
		t.Fatal("ArtifactID collapsed into content digest")
	}
	if string(revision.Current.Revision.ID) == "deadbeef" {
		t.Fatal("RevisionID collapsed into content digest")
	}
	if !strings.HasPrefix(string(artifact.ID), "art_") || !strings.HasPrefix(string(revision.Current.Revision.ID), "rev_") {
		t.Fatalf("unexpected durable ID formats artifact=%q revision=%q", artifact.ID, revision.Current.Revision.ID)
	}
}

func openStore(t *testing.T) *sqlitestate.Store {
	t.Helper()
	store, err := sqlitestate.Open(context.Background(), filepath.Join(t.TempDir(), "state.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := store.Close(); err != nil {
			t.Error(err)
		}
	})
	return store
}

func evidence(digest string, size int64) corpus.ContentEvidence {
	return corpus.ContentEvidence{
		Algorithm: corpus.ContentAlgorithmSHA256,
		Digest:    digest,
		Size:      size,
	}
}
