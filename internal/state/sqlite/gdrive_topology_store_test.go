package sqlitestate

import (
	"context"
	"errors"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory/gdrive"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestGoogleTopologyStoreBootstrapAndIncrementalAreAtomic(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := googleTopologyTestScope()
	fp := remotehistory.ScopePolicyFingerprint("google-drive-history-universe:v1:test")
	base := time.Date(2026, 9, 26, 21, 0, 0, 0, time.UTC)

	generation, err := store.StartGoogleDriveRemoteHistoryGeneration(
		ctx, scope, fp, googleTopologyBootstrapBundle(scope), base,
	)
	if err != nil {
		t.Fatal(err)
	}
	assertGoogleTopologyWatermark(t, store, generation.ID, 1)

	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	var bootstrapEvidence int64
	if err := sqlitex.Execute(conn,
		"SELECT COUNT(*) FROM gdrive_topology_evidence WHERE generation_id=?1 AND sequence=1",
		&sqlitex.ExecOptions{
			Args: []any{string(generation.ID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				bootstrapEvidence = stmt.ColumnInt64(0)
				return nil
			},
		}); err != nil {
		store.pool.Put(conn)
		t.Fatal(err)
	}
	store.pool.Put(conn)
	if bootstrapEvidence != 2 {
		t.Fatalf("bootstrap topology evidence=%d want=2", bootstrapEvidence)
	}

	cycle := gdrive.ChangeCycleBundle{
		History: remotehistory.ChangeCycle{
			StreamID:       scope.StreamID,
			Status:         remotehistory.CycleComplete,
			PreviousCursor: "cursor-1",
			NextCursor:     "cursor-2",
			Coverage:       corpus.ProviderHistoryContinuous,
			Changes: []remotehistory.RemoteChange{
				{Kind: remotehistory.ChangeUpsert, ObjectID: "id-1", State: googleTopologyObject(scope, "id-1")},
				{Kind: remotehistory.ChangeUpsert, ObjectID: "id-1", State: googleTopologyObject(scope, "id-1")},
				{Kind: remotehistory.ChangeRemoved, ObjectID: "id-2"},
			},
		},
		Topology: []gdrive.TopologyState{
			{ObjectID: "id-1", Presence: gdrive.TopologyPresent, ParentKnowledge: gdrive.ParentKnown, ParentObjectID: "folder-a"},
			{ObjectID: "id-1", Presence: gdrive.TopologyPresent, ParentKnowledge: gdrive.ParentKnown, ParentObjectID: "folder-b"},
			{ObjectID: "id-2", Presence: gdrive.TopologyUnavailable, ParentKnowledge: gdrive.ParentUnavailable},
		},
	}
	generation, err = store.PublishGoogleDriveRemoteHistoryCycle(
		ctx, generation.ID, scope, fp, 1, "cursor-1", cycle, base.Add(time.Minute),
	)
	if err != nil {
		t.Fatal(err)
	}
	if generation.CurrentSequence != 2 || generation.CommittedCursor != "cursor-2" {
		t.Fatalf("generation=%#v", generation)
	}
	assertGoogleTopologyWatermark(t, store, generation.ID, 2)

	conn, err = store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer store.pool.Put(conn)

	var (
		id1Parent      string
		id1Sequence    int64
		id1Ordinal     int64
		id2Presence    string
		id2Ordinal     int64
		changeEvidence int64
	)
	if err := sqlitex.Execute(conn,
		"SELECT parent_id,last_sequence,last_ordinal FROM gdrive_topology_nodes WHERE generation_id=?1 AND object_id='id-1'",
		&sqlitex.ExecOptions{
			Args: []any{string(generation.ID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				id1Parent = stmt.ColumnText(0)
				id1Sequence = stmt.ColumnInt64(1)
				id1Ordinal = stmt.ColumnInt64(2)
				return nil
			},
		}); err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"SELECT presence,last_ordinal FROM gdrive_topology_nodes WHERE generation_id=?1 AND object_id='id-2'",
		&sqlitex.ExecOptions{
			Args: []any{string(generation.ID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				id2Presence = stmt.ColumnText(0)
				id2Ordinal = stmt.ColumnInt64(1)
				return nil
			},
		}); err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"SELECT COUNT(*) FROM gdrive_topology_evidence WHERE generation_id=?1 AND sequence=2",
		&sqlitex.ExecOptions{
			Args: []any{string(generation.ID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				changeEvidence = stmt.ColumnInt64(0)
				return nil
			},
		}); err != nil {
		t.Fatal(err)
	}
	if id1Parent != "folder-b" || id1Sequence != 2 || id1Ordinal != 1 {
		t.Fatalf("id-1 node parent=%q sequence=%d ordinal=%d", id1Parent, id1Sequence, id1Ordinal)
	}
	if id2Presence != string(gdrive.TopologyUnavailable) || id2Ordinal != 2 {
		t.Fatalf("id-2 node presence=%q ordinal=%d", id2Presence, id2Ordinal)
	}
	if changeEvidence != 3 {
		t.Fatalf("incremental topology evidence=%d want=3", changeEvidence)
	}
}

func TestGoogleTopologySidecarFailureRollsBackRemoteHistory(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := googleTopologyTestScope()
	fp := remotehistory.ScopePolicyFingerprint("google-drive-history-universe:v1:test")

	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	triggerSQL := "CREATE TRIGGER test_fail_google_topology_evidence BEFORE INSERT ON gdrive_topology_evidence BEGIN SELECT RAISE(ABORT, 'injected topology failure'); END;"
	if err := sqlitex.ExecuteScript(conn, triggerSQL, nil); err != nil {
		store.pool.Put(conn)
		t.Fatal(err)
	}
	store.pool.Put(conn)

	if _, err := store.StartGoogleDriveRemoteHistoryGeneration(
		ctx, scope, fp, googleTopologyBootstrapBundle(scope), time.Now().UTC(),
	); err == nil {
		t.Fatal("injected topology failure unexpectedly committed bootstrap")
	}
	if _, found, err := store.ActiveRemoteHistoryGeneration(ctx, scope); err != nil {
		t.Fatal(err)
	} else if found {
		t.Fatal("RemoteHistory generation survived failed topology sidecar transaction")
	}
	if got := internalTableCount(t, store.Path(), "remote_history_generations"); got != 0 {
		t.Fatalf("remote_history_generations=%d want=0 after rollback", got)
	}
	if got := internalTableCount(t, store.Path(), "remote_history_publications"); got != 0 {
		t.Fatalf("remote_history_publications=%d want=0 after rollback", got)
	}
}

func TestGoogleTopologyStoreRejectsMisalignedBundleWithoutMutation(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := googleTopologyTestScope()
	fp := remotehistory.ScopePolicyFingerprint("google-drive-history-universe:v1:test")
	bundle := googleTopologyBootstrapBundle(scope)
	bundle.Topology[0].ObjectID = "wrong-object"

	_, err := store.StartGoogleDriveRemoteHistoryGeneration(ctx, scope, fp, bundle, time.Now().UTC())
	if !errors.Is(err, ErrGoogleDriveTopologyBundle) {
		t.Fatalf("error=%v want ErrGoogleDriveTopologyBundle", err)
	}
	if got := internalTableCount(t, store.Path(), "remote_history_generations"); got != 0 {
		t.Fatalf("misaligned bundle mutated history generations: %d", got)
	}
}

func TestGoogleTopologyWatermarkSurvivesReopen(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "state.db")
	store, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	scope := googleTopologyTestScope()
	fp := remotehistory.ScopePolicyFingerprint("google-drive-history-universe:v1:test")
	generation, err := store.StartGoogleDriveRemoteHistoryGeneration(
		ctx, scope, fp, googleTopologyBootstrapBundle(scope), time.Now().UTC(),
	)
	if err != nil {
		_ = store.Close()
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
	assertGoogleTopologyWatermark(t, store, generation.ID, 1)
}

func googleTopologyTestScope() remotehistory.Scope {
	return remotehistory.Scope{
		ProviderID:     gdrive.ProviderID,
		IdentityDomain: "google-drive:user:user-1",
		StreamID:       "google-drive:user:user-1:my-drive:changes",
		Root:           "my-drive-root-id",
	}
}

func googleTopologyObject(scope remotehistory.Scope, objectID corpus.ProviderObjectID) *remotehistory.RemoteObjectState {
	return &remotehistory.RemoteObjectState{
		ObjectID: objectID,
		Locators: []corpus.Locator{{
			ProviderID: scope.ProviderID,
			Root:       scope.Root,
			Path:       "file-id/" + string(objectID),
		}},
	}
}

func googleTopologyBootstrapBundle(scope remotehistory.Scope) gdrive.BootstrapBundle {
	return gdrive.BootstrapBundle{
		History: remotehistory.BootstrapResult{
			StreamID: scope.StreamID,
			Status:   remotehistory.BootstrapComplete,
			Cursor:   "cursor-1",
			Coverage: corpus.ProviderHistoryContinuous,
			Objects: []remotehistory.RemoteObjectState{
				*googleTopologyObject(scope, "id-1"),
				*googleTopologyObject(scope, "id-2"),
			},
		},
		Topology: []gdrive.TopologyState{
			{ObjectID: "id-1", Presence: gdrive.TopologyPresent, ParentKnowledge: gdrive.ParentKnown, ParentObjectID: corpus.ProviderObjectID(scope.Root)},
			{ObjectID: "id-2", Presence: gdrive.TopologyPresent, ParentKnowledge: gdrive.ParentKnown, ParentObjectID: corpus.ProviderObjectID(scope.Root)},
		},
	}
}

func assertGoogleTopologyWatermark(t *testing.T, store *Store, generationID remotehistory.HistoryGenerationID, want int64) {
	t.Helper()
	ctx := context.Background()
	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer store.pool.Put(conn)
	var got int64
	var found bool
	if err := sqlitex.Execute(conn,
		"SELECT publication_sequence FROM gdrive_topology_watermarks WHERE generation_id=?1",
		&sqlitex.ExecOptions{
			Args: []any{string(generationID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				found = true
				got = stmt.ColumnInt64(0)
				return nil
			},
		}); err != nil {
		t.Fatal(err)
	}
	if !found || got != want {
		t.Fatalf("topology watermark found=%v got=%d want=%d", found, got, want)
	}
}
