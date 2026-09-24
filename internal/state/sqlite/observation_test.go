package sqlitestate_test

import (
	"context"
	"errors"
	"path/filepath"
	"reflect"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	sqlitestate "github.com/efremov-aleksei-96/keelaryn/internal/state/sqlite"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestUnresolvedObservationPersistsAcrossReopenWithMultipleLocators(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "state.db")
	store, err := sqlitestate.Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}

	input := unresolvedObservationInput()
	input.Locators = []corpus.Locator{
		{ProviderID: "localfs", Root: "/corpus", Path: "original.bin"},
		{ProviderID: "localfs", Root: "/corpus", Path: "hardlink.bin"},
	}
	recorded, err := store.RecordObservation(ctx, input)
	if err != nil {
		t.Fatal(err)
	}
	if recorded.ArtifactID != "" || recorded.RevisionID != "" {
		t.Fatalf("unresolved observation was assigned identity: %#v", recorded)
	}
	if recorded.ProviderObjectOccurrenceID == "" || recorded.ID == "" {
		t.Fatalf("missing record identities: %#v", recorded)
	}
	if len(recorded.Locators) != 2 {
		t.Fatalf("locators=%d, want 2", len(recorded.Locators))
	}
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}

	store, err = sqlitestate.Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	got, err := store.Observation(ctx, recorded.ID)
	if err != nil {
		t.Fatal(err)
	}
	if got.AssignmentState != corpus.AssignmentUnresolved || got.ArtifactID != "" || got.RevisionID != "" {
		t.Fatalf("reopened unresolved state changed: %#v", got)
	}
	if got.ProviderObject.IdentityState != corpus.ObjectIdentityUnresolved || got.ProviderObject.ID != "" {
		t.Fatalf("provider identity was invented: %#v", got.ProviderObject)
	}
	gotPaths := []string{got.Locators[0].Locator.Path, got.Locators[1].Locator.Path}
	wantPaths := []string{"hardlink.bin", "original.bin"}
	if !reflect.DeepEqual(gotPaths, wantPaths) {
		t.Fatalf("paths=%#v, want %#v", gotPaths, wantPaths)
	}
}

func TestAssignedObservationPersistsArtifactAndRevision(t *testing.T) {
	ctx := context.Background()
	store := openStore(t)
	artifact, err := store.AdoptArtifact(ctx)
	if err != nil {
		t.Fatal(err)
	}
	revision, err := store.ObserveRevision(ctx, artifact.ID, evidence("digest", 6))
	if err != nil {
		t.Fatal(err)
	}

	input := unresolvedObservationInput()
	input.ProviderObject = corpus.ProviderObject{
		ProviderID:    "drive",
		ID:            "file-123",
		IdentityState: corpus.ObjectIdentityObserved,
	}
	input.Locators = []corpus.Locator{{ProviderID: "drive", Root: "root-1", Path: "Docs/report.pdf"}}
	input.ArtifactID = artifact.ID
	input.RevisionID = revision.Current.Revision.ID
	input.AssignmentState = corpus.AssignmentAssigned

	recorded, err := store.RecordObservation(ctx, input)
	if err != nil {
		t.Fatal(err)
	}
	got, err := store.Observation(ctx, recorded.ID)
	if err != nil {
		t.Fatal(err)
	}
	if got.ArtifactID != artifact.ID || got.RevisionID != revision.Current.Revision.ID {
		t.Fatalf("assignment mismatch: %#v", got)
	}
	if got.ProviderObject.ID != "file-123" || got.ProviderObject.IdentityState != corpus.ObjectIdentityObserved {
		t.Fatalf("provider object mismatch: %#v", got.ProviderObject)
	}
}

func TestSameLocatorCanAppearInSeparateObservationsWithoutBecomingIdentity(t *testing.T) {
	ctx := context.Background()
	store := openStore(t)
	input := unresolvedObservationInput()

	first, err := store.RecordObservation(ctx, input)
	if err != nil {
		t.Fatal(err)
	}
	second, err := store.RecordObservation(ctx, input)
	if err != nil {
		t.Fatal(err)
	}

	if first.ID == second.ID || first.ProviderObjectOccurrenceID == second.ProviderObjectOccurrenceID {
		t.Fatal("separate observations collapsed into one identity")
	}
	if first.Locators[0].ID == second.Locators[0].ID {
		t.Fatal("same path collapsed Locator record identity")
	}
}

func TestObservationRejectsProviderMismatchWithoutMutation(t *testing.T) {
	ctx := context.Background()
	store := openStore(t)
	input := unresolvedObservationInput()
	input.Locators[0].ProviderID = "other"

	_, err := store.RecordObservation(ctx, input)
	if !errors.Is(err, sqlitestate.ErrInvalidObservation) {
		t.Fatalf("error=%v, want ErrInvalidObservation", err)
	}
}

func TestObservationRejectsUnknownArtifact(t *testing.T) {
	ctx := context.Background()
	store := openStore(t)
	input := unresolvedObservationInput()
	input.AssignmentState = corpus.AssignmentAssigned
	input.ArtifactID = "art_missing"

	_, err := store.RecordObservation(ctx, input)
	if !errors.Is(err, corpus.ErrArtifactNotFound) {
		t.Fatalf("error=%v, want ErrArtifactNotFound", err)
	}
}

func TestObservationRejectsRevisionFromDifferentArtifact(t *testing.T) {
	ctx := context.Background()
	store := openStore(t)
	first, err := store.AdoptArtifact(ctx)
	if err != nil {
		t.Fatal(err)
	}
	second, err := store.AdoptArtifact(ctx)
	if err != nil {
		t.Fatal(err)
	}
	revision, err := store.ObserveRevision(ctx, first.ID, evidence("x", 1))
	if err != nil {
		t.Fatal(err)
	}

	input := unresolvedObservationInput()
	input.AssignmentState = corpus.AssignmentAssigned
	input.ArtifactID = second.ID
	input.RevisionID = revision.Current.Revision.ID

	_, err = store.RecordObservation(ctx, input)
	if !errors.Is(err, sqlitestate.ErrRevisionArtifactMismatch) {
		t.Fatalf("error=%v, want ErrRevisionArtifactMismatch", err)
	}
}

func TestObservationMigrationUpgradesQualifiedV1Database(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v1.db")

	conn, err := sqlite.OpenConn(path, sqlite.OpenReadWrite, sqlite.OpenCreate)
	if err != nil {
		t.Fatal(err)
	}
	for _, query := range []string{
		"PRAGMA application_id = 1263293017",
		"CREATE TABLE artifacts (artifact_id TEXT PRIMARY KEY NOT NULL) STRICT",
		"CREATE TABLE revisions (revision_id TEXT PRIMARY KEY NOT NULL, artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id) ON DELETE RESTRICT, sequence INTEGER NOT NULL CHECK (sequence >= 1), content_algorithm TEXT NOT NULL, content_digest TEXT NOT NULL, content_size INTEGER NOT NULL CHECK (content_size >= 0), UNIQUE (artifact_id, sequence)) STRICT",
		"CREATE INDEX revisions_artifact_sequence ON revisions (artifact_id, sequence)",
		"PRAGMA user_version = 1",
	} {
		if err := sqlitex.ExecuteTransient(conn, query, nil); err != nil {
			t.Fatalf("prepare v1 query %q: %v", query, err)
		}
	}
	if err := conn.Close(); err != nil {
		t.Fatal(err)
	}

	store, err := sqlitestate.Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if _, err := store.RecordObservation(ctx, unresolvedObservationInput()); err != nil {
		t.Fatalf("record after v1→v2 migration: %v", err)
	}
}

func TestObservationNotFound(t *testing.T) {
	store := openStore(t)
	_, err := store.Observation(context.Background(), "obs_missing")
	if !errors.Is(err, sqlitestate.ErrObservationNotFound) {
		t.Fatalf("error=%v, want ErrObservationNotFound", err)
	}
}

func unresolvedObservationInput() corpus.ObservationRecordInput {
	observed := time.Date(2026, 9, 25, 0, 0, 0, 0, time.UTC)
	return corpus.ObservationRecordInput{
		ProviderObject: corpus.ProviderObject{
			ProviderID:    "localfs",
			IdentityState: corpus.ObjectIdentityUnresolved,
		},
		Locators: []corpus.Locator{{
			ProviderID: "localfs",
			Root:       "/corpus",
			Path:       "file.bin",
		}},
		AssignmentState: corpus.AssignmentUnresolved,
		ObservedAt:      observed,
		Kind:            corpus.EntryRegularFile,
		Size:            4,
		Mode:            0o600,
		ModifiedAt:      observed.Add(-time.Minute),
	}
}
