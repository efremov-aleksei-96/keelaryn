package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestQualifiedV27DatabaseMigratesToIdentityCausalTimeAuthorityV28(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v27.db")
	store := openV27IdentityCausalTimeStore(t, path)
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}
	store, err := Open(ctx, path)
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
		"remote_history_authority_causal_time_insert_guard",
		"source_bound_assigned_observation_time_guard",
		"source_bound_continuity_causal_time_guard",
		"source_bound_admission_causal_time_guard",
		"source_bound_identity_mutation_receipt_causal_time_guard",
		"provider_lifetime_binding_causal_time_guard",
	} {
		var found bool
		if err := sqlitex.Execute(conn,
			"SELECT 1 FROM sqlite_master WHERE name=?1 AND type='trigger'",
			&sqlitex.ExecOptions{
				Args: []any{name},
				ResultFunc: func(*sqlite.Stmt) error { found = true; return nil },
			}); err != nil {
			t.Fatal(err)
		}
		if !found {
			t.Fatalf("v27→v28 migration missing %s", name)
		}
	}
}

func TestV28MigrationRejectsExistingBackdatedRemoteIdentityAuthority(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v27.db")
	store := openV27IdentityCausalTimeStore(t, path)
	scope := remoteHistoryTestScope()
	base := time.Date(2026, 9, 28, 0, 0, 0, 0, time.UTC)
	generation, err := store.StartRemoteHistoryGeneration(
		ctx,
		scope,
		remotehistory.ScopePolicyFingerprint("scope-policy:v1:v28-migration"),
		remoteHistoryBootstrap(scope, "cursor-1"),
		base,
	)
	if err != nil {
		t.Fatal(err)
	}
	segments, err := store.RemoteHistoryLifetimeSegments(ctx, generation.ID)
	if err != nil {
		t.Fatal(err)
	}
	segment := findLatestLifetimeSegment(segments, "id-1")
	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	end, err := sqlitex.ImmediateTransaction(conn)
	if err != nil {
		store.pool.Put(conn)
		t.Fatal(err)
	}
	set, err := buildRemoteHistoryIdentityAuthorityConn(conn, generation.ID, segment.ID, base)
	if err != nil {
		end(&err)
		store.pool.Put(conn)
		t.Fatal(err)
	}
	set.CreatedAt = base.Add(-time.Nanosecond)
	if err = store.insertIdentityAuthoritySetConn(conn, set); err != nil {
		end(&err)
		store.pool.Put(conn)
		t.Fatal(err)
	}
	end(&err)
	store.pool.Put(conn)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}
	migrated, err := Open(ctx, path)
	if err == nil {
		_ = migrated.Close()
		t.Fatal("v28 migration unexpectedly accepted backdated RemoteHistory identity authority")
	}
}

func openV27IdentityCausalTimeStore(t *testing.T, path string) *Store {
	t.Helper()
	partial := sqlitemigration.Schema{
		AppID: applicationID,
		Migrations: append([]string(nil), schema.Migrations[:27]...),
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
