package sqlitestate

import (
	"context"
	"errors"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestRemoteHistoryBootstrapAndIncrementalPublicationAreAtomic(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")
	t1 := time.Date(2026, 9, 26, 10, 0, 0, 0, time.UTC)

	generation, err := store.StartRemoteHistoryGeneration(ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), t1)
	if err != nil {
		t.Fatal(err)
	}
	if generation.Status != remotehistory.HistoryGenerationActive || generation.CurrentSequence != 1 || generation.CommittedCursor != "cursor-1" {
		t.Fatalf("generation=%#v", generation)
	}

	cycle := remotehistory.ChangeCycle{
		StreamID:       scope.StreamID,
		Status:         remotehistory.CycleComplete,
		PreviousCursor: "cursor-1",
		NextCursor:     "cursor-2",
		Coverage:       corpus.ProviderHistoryContinuous,
		Changes: []remotehistory.RemoteChange{
			historyUpsert(scope, "id-1", "renamed.txt"),
			{Kind: remotehistory.ChangeRemoved, ObjectID: "id-2"},
			historyUpsert(scope, "id-3", "new.txt"),
		},
	}
	generation, err = store.PublishRemoteHistoryCycle(ctx, generation.ID, scope, fp, 1, "cursor-1", cycle, t1.Add(time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	if generation.CurrentSequence != 2 || generation.CommittedCursor != "cursor-2" {
		t.Fatalf("published generation=%#v", generation)
	}
	membership, err := store.RemoteHistoryMembership(ctx, generation.ID)
	if err != nil {
		t.Fatal(err)
	}
	if len(membership) != 2 ||
		membership[0].Object.ObjectID != "id-1" || membership[0].Object.Locators[0].Path != "renamed.txt" ||
		membership[1].Object.ObjectID != "id-3" {
		t.Fatalf("incremental membership=%#v", membership)
	}
	publications, err := store.RemoteHistoryPublications(ctx, generation.ID)
	if err != nil {
		t.Fatal(err)
	}
	if len(publications) != 2 ||
		publications[0].Kind != remotehistory.HistoryPublicationBootstrap ||
		publications[1].Kind != remotehistory.HistoryPublicationIncremental ||
		publications[1].PreviousCursor != "cursor-1" ||
		publications[1].CommittedCursor != "cursor-2" ||
		publications[0].FingerprintSHA256 == "" ||
		publications[1].FingerprintSHA256 == "" {
		t.Fatalf("publications=%#v", publications)
	}
}

func TestRemoteHistoryStaleReplayFailsWithoutMutation(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")
	generation, err := store.StartRemoteHistoryGeneration(ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), time.Now())
	if err != nil {
		t.Fatal(err)
	}
	cycle := remotehistory.ChangeCycle{
		StreamID:       scope.StreamID,
		Status:         remotehistory.CycleComplete,
		PreviousCursor: "cursor-1",
		NextCursor:     "cursor-2",
		Coverage:       corpus.ProviderHistoryContinuous,
		Changes:        []remotehistory.RemoteChange{historyUpsert(scope, "id-3", "new.txt")},
	}
	if _, err := store.PublishRemoteHistoryCycle(ctx, generation.ID, scope, fp, 1, "cursor-1", cycle, time.Now().Add(time.Second)); err != nil {
		t.Fatal(err)
	}
	_, err = store.PublishRemoteHistoryCycle(ctx, generation.ID, scope, fp, 1, "cursor-1", cycle, time.Now().Add(2*time.Second))
	if !errors.Is(err, ErrHistoryPublicationConflict) {
		t.Fatalf("replay error=%v", err)
	}
	publications, _ := store.RemoteHistoryPublications(ctx, generation.ID)
	if len(publications) != 2 {
		t.Fatalf("stale replay appended publication: %#v", publications)
	}
}

func TestRemoteHistoryTrustBreakClosesGenerationAndRebootstrapUsesNewID(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")
	g1, err := store.StartRemoteHistoryGeneration(ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), time.Now())
	if err != nil {
		t.Fatal(err)
	}
	gap := remotehistory.ChangeCycle{
		StreamID:       scope.StreamID,
		Status:         remotehistory.CycleGap,
		PreviousCursor: "cursor-1",
		NextCursor:     "cursor-1",
		Coverage:       corpus.ProviderHistoryUnknown,
	}
	closed, err := store.CloseRemoteHistoryGeneration(ctx, g1.ID, scope, fp, 1, "cursor-1", gap, time.Now().Add(time.Second))
	if err != nil {
		t.Fatal(err)
	}
	if closed.Status != remotehistory.HistoryGenerationClosed || closed.ClosureReason != remotehistory.HistoryClosureGap || closed.CommittedCursor != "cursor-1" {
		t.Fatalf("closed=%#v", closed)
	}
	_, err = store.PublishRemoteHistoryCycle(ctx, g1.ID, scope, fp, 1, "cursor-1", remotehistory.ChangeCycle{
		StreamID:       scope.StreamID,
		Status:         remotehistory.CycleComplete,
		PreviousCursor: "cursor-1",
		NextCursor:     "cursor-2",
		Coverage:       corpus.ProviderHistoryContinuous,
	}, time.Now().Add(2*time.Second))
	if !errors.Is(err, ErrHistoryGenerationClosed) {
		t.Fatalf("closed generation publish error=%v", err)
	}
	g2, err := store.StartRemoteHistoryGeneration(ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-9"), time.Now().Add(3*time.Second))
	if err != nil {
		t.Fatal(err)
	}
	if g2.ID == g1.ID {
		t.Fatal("rebootstrap reused HistoryGenerationID")
	}
}

func TestRemoteHistoryInterruptedCycleCannotCloseGeneration(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")
	generation, err := store.StartRemoteHistoryGeneration(ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), time.Now())
	if err != nil {
		t.Fatal(err)
	}
	interrupted := remotehistory.ChangeCycle{
		StreamID:       scope.StreamID,
		Status:         remotehistory.CycleInterrupted,
		PreviousCursor: "cursor-1",
		NextCursor:     "cursor-1",
		Coverage:       corpus.ProviderHistoryUnknown,
	}
	_, err = store.CloseRemoteHistoryGeneration(ctx, generation.ID, scope, fp, 1, "cursor-1", interrupted, time.Now().Add(time.Second))
	if !errors.Is(err, remotehistory.ErrInvalidHistoryFailure) {
		t.Fatalf("interrupted close error=%v", err)
	}
	current, err := store.RemoteHistoryGeneration(ctx, generation.ID)
	if err != nil {
		t.Fatal(err)
	}
	if current.Status != remotehistory.HistoryGenerationActive || current.CommittedCursor != "cursor-1" || current.CurrentSequence != 1 {
		t.Fatalf("interruption changed authority: %#v", current)
	}
}

func TestRemoteHistoryScopeMismatchDoesNotMutateGeneration(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")
	generation, err := store.StartRemoteHistoryGeneration(ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), time.Now())
	if err != nil {
		t.Fatal(err)
	}
	wrong := scope
	wrong.Root = "other-root"
	cycle := remotehistory.ChangeCycle{
		StreamID:       scope.StreamID,
		Status:         remotehistory.CycleComplete,
		PreviousCursor: "cursor-1",
		NextCursor:     "cursor-2",
		Coverage:       corpus.ProviderHistoryContinuous,
	}
	_, err = store.PublishRemoteHistoryCycle(ctx, generation.ID, wrong, fp, 1, "cursor-1", cycle, time.Now().Add(time.Second))
	if err == nil {
		t.Fatal("scope mismatch unexpectedly succeeded")
	}
	current, err := store.RemoteHistoryGeneration(ctx, generation.ID)
	if err != nil {
		t.Fatal(err)
	}
	if current.CurrentSequence != 1 || current.CommittedCursor != "cursor-1" || current.Status != remotehistory.HistoryGenerationActive {
		t.Fatalf("scope mismatch mutated generation: %#v", current)
	}
}

func TestRemoteHistoryEvidenceRowsAreSQLiteImmutable(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")
	generation, err := store.StartRemoteHistoryGeneration(ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), time.Now())
	if err != nil {
		t.Fatal(err)
	}
	cycle := remotehistory.ChangeCycle{
		StreamID:       scope.StreamID,
		Status:         remotehistory.CycleComplete,
		PreviousCursor: "cursor-1",
		NextCursor:     "cursor-2",
		Coverage:       corpus.ProviderHistoryContinuous,
		Changes:        []remotehistory.RemoteChange{historyUpsert(scope, "id-3", "c.txt")},
	}
	if _, err := store.PublishRemoteHistoryCycle(ctx, generation.ID, scope, fp, 1, "cursor-1", cycle, time.Now().Add(time.Second)); err != nil {
		t.Fatal(err)
	}

	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer store.pool.Put(conn)

	for name, query := range map[string]string{
		"publication update": "UPDATE remote_history_publications SET committed_cursor='tamper' WHERE generation_id='" + string(generation.ID) + "'",
		"publication delete": "DELETE FROM remote_history_publications WHERE generation_id='" + string(generation.ID) + "'",
		"bootstrap update": "UPDATE remote_history_bootstrap_membership SET locators_json='[]' WHERE generation_id='" + string(generation.ID) + "'",
		"bootstrap delete": "DELETE FROM remote_history_bootstrap_membership WHERE generation_id='" + string(generation.ID) + "'",
		"change update": "UPDATE remote_history_publication_changes SET object_id='tamper' WHERE generation_id='" + string(generation.ID) + "'",
		"change delete": "DELETE FROM remote_history_publication_changes WHERE generation_id='" + string(generation.ID) + "'",
	} {
		t.Run(name, func(t *testing.T) {
			if err := sqlitex.Execute(conn, query, nil); err == nil {
				t.Fatal("immutable history evidence mutation unexpectedly succeeded")
			}
		})
	}
}

func TestRemoteHistoryDoesNotCreateObservationsOrIdentityAuthority(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")
	if _, err := store.StartRemoteHistoryGeneration(ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), time.Now()); err != nil {
		t.Fatal(err)
	}
	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer store.pool.Put(conn)
	for _, table := range []string{"observations", "identity_authority_sets", "artifacts", "revisions"} {
		var count int64
		if err := sqlitex.Execute(conn, "SELECT COUNT(*) FROM "+table, &sqlitex.ExecOptions{
			ResultFunc: func(stmt *sqlite.Stmt) error { count = stmt.ColumnInt64(0); return nil },
		}); err != nil {
			t.Fatal(err)
		}
		if count != 0 {
			t.Fatalf("%s count=%d, want 0", table, count)
		}
	}
}

func TestRemoteHistoryReopenPreservesGenerationMembershipAndCursor(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "state.db")
	store, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")
	generation, err := store.StartRemoteHistoryGeneration(ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), time.Now())
	if err != nil {
		t.Fatal(err)
	}
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}
	store, err = Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	got, err := store.RemoteHistoryGeneration(ctx, generation.ID)
	if err != nil {
		t.Fatal(err)
	}
	membership, err := store.RemoteHistoryMembership(ctx, generation.ID)
	if err != nil {
		t.Fatal(err)
	}
	if got.CommittedCursor != "cursor-1" || got.CurrentSequence != 1 || len(membership) != 2 {
		t.Fatalf("reopened generation=%#v membership=%#v", got, membership)
	}
}

func openStoreInternal(t *testing.T) *Store {
	t.Helper()
	store, err := Open(context.Background(), filepath.Join(t.TempDir(), "state.db"))
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

func remoteHistoryTestScope() remotehistory.Scope {
	return remotehistory.Scope{
		ProviderID:     "drive",
		IdentityDomain: "drive:user-1",
		StreamID:       "drive:user-1:changes",
		Root:           "root",
	}
}

func remoteHistoryBootstrap(scope remotehistory.Scope, cursor remotehistory.HistoryCursor) remotehistory.BootstrapResult {
	return remotehistory.BootstrapResult{
		StreamID: scope.StreamID,
		Status:   remotehistory.BootstrapComplete,
		Cursor:   cursor,
		Coverage: corpus.ProviderHistoryContinuous,
		Objects: []remotehistory.RemoteObjectState{
			{ObjectID: "id-2", Locators: []corpus.Locator{{ProviderID: scope.ProviderID, Root: scope.Root, Path: "b.txt"}}},
			{ObjectID: "id-1", Locators: []corpus.Locator{{ProviderID: scope.ProviderID, Root: scope.Root, Path: "a.txt"}}},
		},
	}
}

func historyUpsert(scope remotehistory.Scope, id corpus.ProviderObjectID, path string) remotehistory.RemoteChange {
	return remotehistory.RemoteChange{
		Kind:     remotehistory.ChangeUpsert,
		ObjectID: id,
		State: &remotehistory.RemoteObjectState{
			ObjectID: id,
			Locators: []corpus.Locator{{ProviderID: scope.ProviderID, Root: scope.Root, Path: path}},
		},
	}
}
