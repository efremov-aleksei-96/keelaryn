package sqlitestate

import (
	"context"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory/gdrive"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestGoogleDriveTopologySchemaFailsClosedAndSupportsSafeRebuild(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := remotehistory.Scope{
		ProviderID:     "google-drive",
		IdentityDomain: "google-drive:user:user-1",
		StreamID:       "google-drive:user:user-1:my-drive:changes",
		Root:           "my-drive-root-id",
	}
	bootstrap := remotehistory.BootstrapResult{
		StreamID: scope.StreamID,
		Status:   remotehistory.BootstrapComplete,
		Cursor:   "cursor-1",
		Coverage: corpus.ProviderHistoryContinuous,
		Objects: []remotehistory.RemoteObjectState{
			{ObjectID: "id-1", Locators: []corpus.Locator{{ProviderID: scope.ProviderID, Root: scope.Root, Path: "file-id/id-1"}}},
			{ObjectID: "id-2", Locators: []corpus.Locator{{ProviderID: scope.ProviderID, Root: scope.Root, Path: "file-id/id-2"}}},
		},
	}
	generation, err := store.StartRemoteHistoryGeneration(
		ctx, scope, "google-drive-history-universe:v1:test", bootstrap,
		time.Date(2026, 9, 26, 20, 0, 0, 0, time.UTC),
	)
	if err != nil {
		t.Fatal(err)
	}

	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	connHeld := true
	defer func() {
		if connHeld {
			store.pool.Put(conn)
		}
	}()

	bootstrapTopology := map[corpus.ProviderObjectID]gdrive.TopologyState{
		"id-1": {ObjectID: "id-1", Presence: gdrive.TopologyPresent, ParentKnowledge: gdrive.ParentKnown, ParentObjectID: corpus.ProviderObjectID(scope.Root), DriveID: "drive-a"},
		"id-2": {ObjectID: "id-2", Presence: gdrive.TopologyPresent, ParentKnowledge: gdrive.ParentKnown, ParentObjectID: corpus.ProviderObjectID(scope.Root), DriveID: "drive-a"},
	}
	releaseBootstrap, err := store.authorizeGoogleDriveTopologyWriteConn(conn, googleDriveTopologyWriteAuthorization{
		phase: googleDriveTopologyWriteBootstrap,
		generationID: generation.ID,
		sequence: 1,
		entries: googleBootstrapTopologyAuthorizationEntries(bootstrapTopology),
	})
	if err != nil {
		t.Fatal(err)
	}
	insertBootstrapEvidence := func(objectID corpus.ProviderObjectID) {
		t.Helper()
		state := bootstrapTopology[objectID]
		if err := insertGoogleTopologyEvidenceConn(conn, generation.ID, 1, -1, gdrive.TopologyEvidenceBootstrap, state); err != nil {
			t.Fatal(err)
		}
		if err := upsertGoogleTopologyNodeConn(conn, generation.ID, 1, -1, state); err != nil {
			t.Fatal(err)
		}
	}

	insertBootstrapEvidence("id-1")
	if err := insertGoogleTopologyWatermarkConn(conn, generation.ID, 1); err == nil {
		t.Fatal("incomplete bootstrap topology unexpectedly accepted watermark")
	}
	insertBootstrapEvidence("id-2")
	if err := insertGoogleTopologyWatermarkConn(conn, generation.ID, 1); err != nil {
		t.Fatal(err)
	}
	releaseBootstrap()

	bindingAt := time.Date(2026, 9, 26, 20, 0, 1, 0, time.UTC)
	releaseBinding, err := store.authorizeGoogleDriveTopologyWriteConn(conn, googleDriveTopologyWriteAuthorization{
		phase: googleDriveTopologyWriteManagedRoot,
		generationID: generation.ID,
		sequence: 1,
		managedRootObjectID: "id-1",
		createdAt: bindingAt.Format(time.RFC3339Nano),
	})
	if err != nil {
		t.Fatal(err)
	}
	writeErr := sqlitex.Execute(conn,
		"INSERT INTO gdrive_managed_root_bindings (generation_id, managed_root_object_id, bound_sequence, created_at) VALUES (?1,'id-1',1,?2)",
		&sqlitex.ExecOptions{Args: []any{string(generation.ID), bindingAt.Format(time.RFC3339Nano)}})
	releaseBinding()
	if writeErr != nil {
		t.Fatal(writeErr)
	}
	if err := sqlitex.Execute(conn,
		"UPDATE gdrive_managed_root_bindings SET managed_root_object_id='id-2' WHERE generation_id=?1 AND managed_root_object_id='id-1'",
		&sqlitex.ExecOptions{Args: []any{string(generation.ID)}}); err == nil {
		t.Fatal("managed-root binding update unexpectedly succeeded")
	}

	cycle := remotehistory.ChangeCycle{
		StreamID:       scope.StreamID,
		Status:         remotehistory.CycleComplete,
		PreviousCursor: "cursor-1",
		NextCursor:     "cursor-2",
		Coverage:       corpus.ProviderHistoryContinuous,
		Changes: []remotehistory.RemoteChange{{
			Kind:     remotehistory.ChangeUpsert,
			ObjectID: "id-1",
			State: &remotehistory.RemoteObjectState{
				ObjectID: "id-1",
				Locators: []corpus.Locator{{ProviderID: scope.ProviderID, Root: scope.Root, Path: "file-id/id-1"}},
			},
		}},
	}
	store.pool.Put(conn)
	connHeld = false
	if _, err := store.publishRemoteHistoryCycleWithSidecar(
		ctx, generation.ID, scope, "google-drive-history-universe:v1:test",
		1, "cursor-1", cycle, time.Date(2026, 9, 26, 20, 1, 0, 0, time.UTC),
		func(*sqlite.Conn, remotehistory.HistoryGeneration, remotehistory.HistoryPublicationSequence, []remotehistory.RemoteChange) error {
			return nil
		},
	); err != nil {
		t.Fatal(err)
	}
	conn, err = store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	connHeld = true

	incrementalState := gdrive.TopologyState{
		ObjectID: "id-1",
		Presence: gdrive.TopologyPresent,
		ParentKnowledge: gdrive.ParentKnown,
		ParentObjectID: "folder-new",
		DriveID: "drive-a",
	}
	releaseIncremental, err := store.authorizeGoogleDriveTopologyWriteConn(conn, googleDriveTopologyWriteAuthorization{
		phase: googleDriveTopologyWriteIncremental,
		generationID: generation.ID,
		sequence: 2,
		entries: googleIncrementalTopologyAuthorizationEntries(cycle.Changes, []gdrive.TopologyState{incrementalState}),
	})
	if err != nil {
		t.Fatal(err)
	}

	if err := sqlitex.Execute(conn,
		"UPDATE gdrive_topology_watermarks SET publication_sequence=2 WHERE generation_id=?1",
		&sqlitex.ExecOptions{Args: []any{string(generation.ID)}}); err == nil {
		t.Fatal("watermark advanced without topology evidence/projection")
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO gdrive_topology_evidence (generation_id, sequence, ordinal, evidence_kind, object_id, presence, parent_state, parent_id, drive_id) VALUES (?1,2,0,'UPSERT','id-2','PRESENT','KNOWN',?2,'drive-a')",
		&sqlitex.ExecOptions{Args: []any{string(generation.ID), scope.Root}}); err == nil {
		t.Fatal("forged topology evidence outside validated bundle unexpectedly succeeded")
	}
	if err := insertGoogleTopologyEvidenceConn(conn, generation.ID, 2, 0, gdrive.TopologyEvidenceUpsert, incrementalState); err != nil {
		t.Fatal(err)
	}
	if err := upsertGoogleTopologyNodeConn(conn, generation.ID, 2, 0, incrementalState); err == nil {
		t.Fatal("topology node mutated while watermark remained active")
	}

	deleteWatermark := func(sequence remotehistory.HistoryPublicationSequence) {
		t.Helper()
		release, err := store.authorizeGoogleTopologyWatermarkDeleteConn(conn, generation.ID, sequence)
		if err != nil {
			t.Fatal(err)
		}
		err = sqlitex.Execute(conn,
			"DELETE FROM gdrive_topology_watermarks WHERE generation_id=?1 AND publication_sequence=?2",
			&sqlitex.ExecOptions{Args: []any{string(generation.ID), int64(sequence)}})
		release()
		if err != nil {
			t.Fatal(err)
		}
	}

	deleteWatermark(1)
	if err := upsertGoogleTopologyNodeConn(conn, generation.ID, 2, 0, incrementalState); err != nil {
		t.Fatal(err)
	}
	if err := insertGoogleTopologyWatermarkConn(conn, generation.ID, 2); err != nil {
		t.Fatal(err)
	}
	releaseIncremental()

	if err := sqlitex.Execute(conn,
		"DELETE FROM gdrive_topology_nodes WHERE generation_id=?1 AND object_id='id-1'",
		&sqlitex.ExecOptions{Args: []any{string(generation.ID)}}); err == nil {
		t.Fatal("current topology projection deleted while watermark remained authoritative")
	}
	deleteWatermark(2)
	if err := sqlitex.Execute(conn,
		"DELETE FROM gdrive_topology_nodes WHERE generation_id=?1 AND object_id='id-1'",
		&sqlitex.ExecOptions{Args: []any{string(generation.ID)}}); err != nil {
		t.Fatalf("projection delete after watermark removal should permit rebuild: %v", err)
	}
}
