package sqlitestate

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory/gdrive"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestManagedRootMovePreservesBindingAndMembershipWithinSameLifetime(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := googleTopologyTestScope()
	fp := remotehistory.ScopePolicyFingerprint("google-drive-history-universe:v1:test")
	base := time.Date(2026, 9, 27, 3, 0, 0, 0, time.UTC)

	generation, err := store.StartGoogleDriveRemoteHistoryGeneration(
		ctx,
		scope,
		fp,
		googleMembershipBootstrapBundle(scope, []gdrive.TopologyState{
			topologyPresent("managed", corpus.ProviderObjectID(scope.Root)),
			topologyPresent("child", "managed"),
			topologyPresent("outside", corpus.ProviderObjectID(scope.Root)),
		}),
		base,
	)
	if err != nil {
		t.Fatal(err)
	}

	binding, err := store.BindGoogleDriveManagedRoot(
		ctx, generation.ID, "managed", base.Add(time.Second),
	)
	if err != nil {
		t.Fatal(err)
	}
	rootLifetimeBefore := lifetimeSegmentForObject(t, store, generation.ID, "managed")

	moveRoot := gdrive.ChangeCycleBundle{
		History: remotehistory.ChangeCycle{
			StreamID:       scope.StreamID,
			Status:         remotehistory.CycleComplete,
			PreviousCursor: "cursor-1",
			NextCursor:     "cursor-2",
			Coverage:       corpus.ProviderHistoryContinuous,
			Changes: []remotehistory.RemoteChange{{
				Kind:     remotehistory.ChangeUpsert,
				ObjectID: "managed",
				State:    googleTopologyObject(scope, "managed"),
			}},
		},
		Topology: []gdrive.TopologyState{
			topologyPresent("managed", "outside"),
		},
	}

	generation, err = store.PublishGoogleDriveRemoteHistoryCycle(
		ctx,
		generation.ID,
		scope,
		fp,
		1,
		"cursor-1",
		moveRoot,
		base.Add(2*time.Second),
	)
	if err != nil {
		t.Fatal(err)
	}

	got, err := store.GoogleDriveManagedRootMembership(
		ctx, generation.ID, 2, "managed", "child",
	)
	if err != nil {
		t.Fatal(err)
	}
	if got.State != gdrive.MembershipIn {
		t.Fatalf("child membership after managed-root move=%#v", got)
	}

	replayed, err := store.BindGoogleDriveManagedRoot(
		ctx, generation.ID, "managed", base.Add(3*time.Second),
	)
	if err != nil {
		t.Fatal(err)
	}
	if replayed != binding {
		t.Fatalf("managed-root binding changed after same-lifetime move: before=%#v after=%#v", binding, replayed)
	}

	rootLifetimeAfter := lifetimeSegmentForObject(t, store, generation.ID, "managed")
	if rootLifetimeAfter.ID != rootLifetimeBefore.ID || rootLifetimeAfter.Status != rootLifetimeBefore.Status {
		t.Fatalf("managed-root lifetime changed on move: before=%#v after=%#v", rootLifetimeBefore, rootLifetimeAfter)
	}
}

func TestVerifyGoogleDriveTopologyProjectionDetectsMaterializedDrift(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := googleTopologyTestScope()
	fp := remotehistory.ScopePolicyFingerprint("google-drive-history-universe:v1:test")
	base := time.Date(2026, 9, 27, 3, 30, 0, 0, time.UTC)

	generation, err := store.StartGoogleDriveRemoteHistoryGeneration(
		ctx,
		scope,
		fp,
		googleMembershipBootstrapBundle(scope, []gdrive.TopologyState{
			topologyPresent("managed", corpus.ProviderObjectID(scope.Root)),
			topologyPresent("child", "managed"),
		}),
		base,
	)
	if err != nil {
		t.Fatal(err)
	}

	if err := store.VerifyGoogleDriveTopologyProjection(ctx, generation.ID, 1); err != nil {
		t.Fatalf("valid projection verification failed: %v", err)
	}

	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.ExecuteScript(conn,
		"DROP TRIGGER gdrive_topology_nodes_update_requires_unwatermarked; "+
			"DROP TRIGGER gdrive_topology_nodes_update_guard;",
		nil,
	); err != nil {
		store.pool.Put(conn)
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"UPDATE gdrive_topology_nodes SET parent_id='forged-parent' WHERE generation_id=?1 AND object_id='child'",
		&sqlitex.ExecOptions{Args: []any{string(generation.ID)}},
	); err != nil {
		store.pool.Put(conn)
		t.Fatal(err)
	}
	store.pool.Put(conn)

	err = store.VerifyGoogleDriveTopologyProjection(ctx, generation.ID, 1)
	if !errors.Is(err, ErrGoogleDriveTopologyVerification) {
		t.Fatalf("drift verification error=%v want ErrGoogleDriveTopologyVerification", err)
	}
}


func TestVerifyGoogleDriveTopologyProjectionRejectsEvidenceWithoutHistorySource(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := googleTopologyTestScope()
	fp := remotehistory.ScopePolicyFingerprint("google-drive-history-universe:v1:test")

	generation, err := store.StartGoogleDriveRemoteHistoryGeneration(
		ctx,
		scope,
		fp,
		googleMembershipBootstrapBundle(scope, []gdrive.TopologyState{
			topologyPresent("managed", corpus.ProviderObjectID(scope.Root)),
		}),
		time.Now().UTC(),
	)
	if err != nil {
		t.Fatal(err)
	}

	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.ExecuteScript(conn,
		"DROP TRIGGER gdrive_topology_evidence_insert_guard; "+
			"DROP TRIGGER gdrive_topology_nodes_insert_requires_unwatermarked; "+
			"DROP TRIGGER gdrive_topology_nodes_insert_guard;",
		nil,
	); err != nil {
		store.pool.Put(conn)
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO gdrive_topology_evidence (generation_id,sequence,ordinal,evidence_kind,object_id,presence,parent_state,parent_id,drive_id) VALUES (?1,1,-1,'BOOTSTRAP','forged','PRESENT','KNOWN',?2,'')",
		&sqlitex.ExecOptions{Args: []any{string(generation.ID), scope.Root}},
	); err != nil {
		store.pool.Put(conn)
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO gdrive_topology_nodes (generation_id,object_id,presence,parent_state,parent_id,drive_id,last_sequence,last_ordinal) VALUES (?1,'forged','PRESENT','KNOWN',?2,'',1,-1)",
		&sqlitex.ExecOptions{Args: []any{string(generation.ID), scope.Root}},
	); err != nil {
		store.pool.Put(conn)
		t.Fatal(err)
	}
	store.pool.Put(conn)

	err = store.VerifyGoogleDriveTopologyProjection(ctx, generation.ID, 1)
	if !errors.Is(err, ErrGoogleDriveTopologyVerification) {
		t.Fatalf("forged evidence verification error=%v want ErrGoogleDriveTopologyVerification", err)
	}
}
