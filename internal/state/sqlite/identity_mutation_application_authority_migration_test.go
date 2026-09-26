package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"

	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestQualifiedV26DatabaseMigratesToIdentityMutationApplicationAuthorityV27(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v26.db")
	partial := sqlitemigration.Schema{
		AppID: applicationID,
		Migrations: append([]string(nil), schema.Migrations[:26]...),
	}
	seedStore := &Store{path: path}
	pool := sqlitemigration.NewPool(path, partial, sqlitemigration.Options{
		Flags: sqlite.OpenReadWrite | sqlite.OpenCreate,
		PoolSize: 1,
		PrepareConn: seedStore.prepareConn,
	})
	seedStore.pool = pool
	conn, err := pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	pool.Put(conn)
	if err := pool.Close(); err != nil {
		t.Fatal(err)
	}

	store, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	conn, err = store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer store.pool.Put(conn)
	for _, name := range []string{
		"source_bound_assigned_observation_application_guard",
		"source_bound_continuity_application_guard",
		"source_bound_admission_application_guard",
		"source_bound_identity_mutation_receipt_application_guard",
		"provider_lifetime_binding_application_guard",
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
			t.Fatalf("v26→v27 migration missing %s", name)
		}
	}
}
