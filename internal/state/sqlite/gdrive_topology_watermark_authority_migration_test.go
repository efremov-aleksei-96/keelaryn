package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory/gdrive"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestQualifiedV33DatabaseMigratesToGoogleTopologyWatermarkAuthorityV34(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v33.db")
	store := openV33GoogleTopologyStore(t, path)
	scope := googleTopologyTestScope()
	_, err := store.StartGoogleDriveRemoteHistoryGeneration(
		ctx,
		scope,
		remotehistory.ScopePolicyFingerprint("google-drive-history-universe:v1:v34"),
		googleMembershipBootstrapBundle(scope, []gdrive.TopologyState{
			topologyPresent("id-1", corpus.ProviderObjectID(scope.Root)),
		}),
		time.Date(2026, 9, 27, 7, 30, 0, 0, time.UTC),
	)
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
	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer store.pool.Put(conn)
	for _, name := range []string{
		"gdrive_topology_watermark_delete_application_guard",
		"gdrive_topology_watermarks_no_update_v34",
	} {
		var found bool
		if err := sqlitex.Execute(conn,
			"SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?1",
			&sqlitex.ExecOptions{
				Args: []any{name},
				ResultFunc: func(*sqlite.Stmt) error { found = true; return nil },
			}); err != nil {
			t.Fatal(err)
		}
		if !found {
			t.Fatalf("v33→v34 migration missing %s", name)
		}
	}
}

func TestV34MigrationRejectsGoogleGenerationMissingCurrentTopologyWatermark(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v33-corrupt.db")
	store := openV33GoogleTopologyStore(t, path)
	scope := googleTopologyTestScope()
	generation, err := store.StartGoogleDriveRemoteHistoryGeneration(
		ctx,
		scope,
		remotehistory.ScopePolicyFingerprint("google-drive-history-universe:v1:v34-corrupt"),
		googleMembershipBootstrapBundle(scope, []gdrive.TopologyState{
			topologyPresent("id-1", corpus.ProviderObjectID(scope.Root)),
		}),
		time.Date(2026, 9, 27, 7, 40, 0, 0, time.UTC),
	)
	if err != nil {
		t.Fatal(err)
	}
	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"DELETE FROM gdrive_topology_watermarks WHERE generation_id=?1",
		&sqlitex.ExecOptions{Args: []any{string(generation.ID)}}); err != nil {
		store.pool.Put(conn)
		t.Fatal(err)
	}
	store.pool.Put(conn)
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}

	migrated, err := Open(ctx, path)
	if err == nil {
		_ = migrated.Close()
		t.Fatal("v34 migration unexpectedly accepted Google generation without current topology watermark")
	}
}

func TestV34GoogleTopologyWatermarkMutationRequiresApplicationAuthority(t *testing.T) {
	ctx := context.Background()
	fixture := newGoogleRemoteCompletionFixture(t)
	conn, err := fixture.store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer fixture.store.pool.Put(conn)

	if err := sqlitex.Execute(conn,
		"DELETE FROM gdrive_topology_watermarks WHERE generation_id=?1",
		&sqlitex.ExecOptions{Args: []any{string(fixture.generation.ID)}}); err == nil {
		t.Fatal("direct Google topology watermark delete unexpectedly succeeded")
	}
	if err := sqlitex.Execute(conn,
		"UPDATE gdrive_topology_watermarks SET publication_sequence=publication_sequence WHERE generation_id=?1",
		&sqlitex.ExecOptions{Args: []any{string(fixture.generation.ID)}}); err == nil {
		t.Fatal("direct Google topology watermark update unexpectedly succeeded")
	}

	release, err := fixture.store.authorizeGoogleTopologyWatermarkDeleteConn(
		conn, fixture.generation.ID, fixture.generation.CurrentSequence,
	)
	if err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"DELETE FROM gdrive_topology_watermarks WHERE generation_id=?1 AND publication_sequence=?2",
		&sqlitex.ExecOptions{Args: []any{string(fixture.generation.ID), int64(fixture.generation.CurrentSequence)}}); err != nil {
		release()
		t.Fatal(err)
	}
	release()
}

func openV33GoogleTopologyStore(t *testing.T, path string) *Store {
	t.Helper()
	partial := sqlitemigration.Schema{
		AppID: applicationID,
		Migrations: append([]string(nil), schema.Migrations[:33]...),
	}
	store := &Store{path: path}
	pool := sqlitemigration.NewPool(path, partial, sqlitemigration.Options{
		Flags: sqlite.OpenReadWrite | sqlite.OpenCreate,
		PoolSize: 1,
		PrepareConn: store.prepareConn,
	})
	store.pool = pool
	conn, err := pool.Get(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	pool.Put(conn)
	return store
}
