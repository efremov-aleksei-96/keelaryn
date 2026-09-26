package sqlitestate

import (
	"context"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
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
	if err != nil { t.Fatal(err) }

	conn, err := store.pool.Get(ctx)
	if err != nil { t.Fatal(err) }

	insertBootstrapEvidence := func(objectID string) {
		t.Helper()
		if err := sqlitex.Execute(conn,
			"INSERT INTO gdrive_topology_evidence (generation_id, sequence, ordinal, evidence_kind, object_id, presence, parent_state, parent_id, drive_id) VALUES (?1,1,-1,'BOOTSTRAP',?2,'PRESENT','KNOWN',?3,'')",
			&sqlitex.ExecOptions{Args: []any{string(generation.ID), objectID, scope.Root}}); err != nil {
			t.Fatal(err)
		}
		if err := sqlitex.Execute(conn,
			"INSERT INTO gdrive_topology_nodes (generation_id, object_id, presence, parent_state, parent_id, drive_id, last_sequence, last_ordinal) VALUES (?1,?2,'PRESENT','KNOWN',?3,'',1,-1)",
			&sqlitex.ExecOptions{Args: []any{string(generation.ID), objectID, scope.Root}}); err != nil {
			t.Fatal(err)
		}
	}

	insertBootstrapEvidence("id-1")
	if err := sqlitex.Execute(conn,
		"INSERT INTO gdrive_topology_watermarks (generation_id, publication_sequence) VALUES (?1,1)",
		&sqlitex.ExecOptions{Args: []any{string(generation.ID)}}); err == nil {
		t.Fatal("incomplete bootstrap topology unexpectedly accepted watermark")
	}

	insertBootstrapEvidence("id-2")
	if err := sqlitex.Execute(conn,
		"INSERT INTO gdrive_topology_watermarks (generation_id, publication_sequence) VALUES (?1,1)",
		&sqlitex.ExecOptions{Args: []any{string(generation.ID)}}); err != nil {
		t.Fatal(err)
	}

	if err := sqlitex.Execute(conn,
		"INSERT INTO gdrive_managed_root_bindings (generation_id, managed_root_object_id, bound_sequence, created_at) VALUES (?1,'id-1',1,?2)",
		&sqlitex.ExecOptions{Args: []any{string(generation.ID), time.Now().UTC().Format(time.RFC3339Nano)}}); err != nil {
		t.Fatal(err)
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
	if _, err := store.PublishRemoteHistoryCycle(
		ctx, generation.ID, scope, "google-drive-history-universe:v1:test",
		1, "cursor-1", cycle, time.Now().UTC(),
	); err != nil {
		t.Fatal(err)
	}
	conn, err = store.pool.Get(ctx)
	if err != nil { t.Fatal(err) }
	defer store.pool.Put(conn)

	if err := sqlitex.Execute(conn,
		"UPDATE gdrive_topology_watermarks SET publication_sequence=2 WHERE generation_id=?1",
		&sqlitex.ExecOptions{Args: []any{string(generation.ID)}}); err == nil {
		t.Fatal("watermark advanced without topology evidence/projection")
	}

	if err := sqlitex.Execute(conn,
		"INSERT INTO gdrive_topology_evidence (generation_id, sequence, ordinal, evidence_kind, object_id, presence, parent_state, parent_id, drive_id) VALUES (?1,2,0,'UPSERT','id-2','PRESENT','KNOWN',?2,'')",
		&sqlitex.ExecOptions{Args: []any{string(generation.ID), scope.Root}}); err == nil {
		t.Fatal("forged topology evidence not matching RemoteHistory change unexpectedly succeeded")
	}

	if err := sqlitex.Execute(conn,
		"INSERT INTO gdrive_topology_evidence (generation_id, sequence, ordinal, evidence_kind, object_id, presence, parent_state, parent_id, drive_id) VALUES (?1,2,0,'UPSERT','id-1','PRESENT','KNOWN','folder-new','')",
		&sqlitex.ExecOptions{Args: []any{string(generation.ID)}}); err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"UPDATE gdrive_topology_nodes SET parent_id='folder-new', last_sequence=2, last_ordinal=0 WHERE generation_id=?1 AND object_id='id-1'",
		&sqlitex.ExecOptions{Args: []any{string(generation.ID)}}); err == nil {
		t.Fatal("topology node mutated while watermark remained active")
	}
	if err := sqlitex.Execute(conn,
		"DELETE FROM gdrive_topology_watermarks WHERE generation_id=?1",
		&sqlitex.ExecOptions{Args: []any{string(generation.ID)}}); err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"UPDATE gdrive_topology_nodes SET parent_id='folder-new', last_sequence=2, last_ordinal=0 WHERE generation_id=?1 AND object_id='id-1'",
		&sqlitex.ExecOptions{Args: []any{string(generation.ID)}}); err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO gdrive_topology_watermarks (generation_id, publication_sequence) VALUES (?1,2)",
		&sqlitex.ExecOptions{Args: []any{string(generation.ID)}}); err != nil {
		t.Fatal(err)
	}

	if err := sqlitex.Execute(conn,
		"DELETE FROM gdrive_topology_nodes WHERE generation_id=?1 AND object_id='id-1'",
		&sqlitex.ExecOptions{Args: []any{string(generation.ID)}}); err == nil {
		t.Fatal("current topology projection deleted while watermark remained authoritative")
	}

	if err := sqlitex.Execute(conn,
		"DELETE FROM gdrive_topology_watermarks WHERE generation_id=?1",
		&sqlitex.ExecOptions{Args: []any{string(generation.ID)}}); err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"DELETE FROM gdrive_topology_nodes WHERE generation_id=?1 AND object_id='id-1'",
		&sqlitex.ExecOptions{Args: []any{string(generation.ID)}}); err != nil {
		t.Fatalf("projection delete after watermark removal should permit rebuild: %v", err)
	}
}
