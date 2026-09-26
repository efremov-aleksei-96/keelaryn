package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"

	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestQualifiedV10DatabaseMigratesToLifetimeBindingsV11(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v10.db")
	v10 := sqlitemigration.Schema{AppID: applicationID, Migrations: append([]string(nil), schema.Migrations[:10]...)}
	pool := sqlitemigration.NewPool(path, v10, sqlitemigration.Options{
		Flags:    sqlite.OpenReadWrite | sqlite.OpenCreate,
		PoolSize: 1,
		PrepareConn: func(conn *sqlite.Conn) error {
			return sqlitex.ExecuteTransient(conn, "PRAGMA foreign_keys = ON", nil)
		},
	})
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

	var tableExists bool
	if err := sqlitex.Execute(conn,
		"SELECT 1 FROM sqlite_master WHERE type='table' AND name='provider_lifetime_artifact_bindings'",
		&sqlitex.ExecOptions{ResultFunc: func(*sqlite.Stmt) error {
			tableExists = true
			return nil
		}}); err != nil {
		t.Fatal(err)
	}
	if !tableExists {
		t.Fatal("v10→v11 migration did not create provider_lifetime_artifact_bindings")
	}
	for _, trigger := range []string{
		"remote_history_authority_insert_guard",
		"provider_lifetime_artifact_bindings_insert_guard",
		"provider_lifetime_artifact_bindings_no_update",
		"provider_lifetime_artifact_bindings_no_delete",
	} {
		var exists bool
		if err := sqlitex.Execute(conn,
			"SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?1",
			&sqlitex.ExecOptions{
				Args: []any{trigger},
				ResultFunc: func(*sqlite.Stmt) error {
					exists = true
					return nil
				},
			}); err != nil {
			t.Fatal(err)
		}
		if !exists {
			t.Fatalf("v10→v11 migration did not create %s", trigger)
		}
	}
}
