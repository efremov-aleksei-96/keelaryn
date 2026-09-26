package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"

	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestQualifiedV9DatabaseMigratesToLifetimeSegmentsV10(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v9.db")
	v9 := sqlitemigration.Schema{AppID: applicationID, Migrations: append([]string(nil), schema.Migrations[:9]...)}
	pool := sqlitemigration.NewPool(path, v9, sqlitemigration.Options{
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
		"SELECT 1 FROM sqlite_master WHERE type='table' AND name='provider_object_lifetime_segments'",
		&sqlitex.ExecOptions{ResultFunc: func(*sqlite.Stmt) error {
			tableExists = true
			return nil
		}}); err != nil {
		t.Fatal(err)
	}
	if !tableExists {
		t.Fatal("v9→v10 migration did not create provider_object_lifetime_segments")
	}

	for _, trigger := range []string{
		"provider_lifetime_segments_no_delete",
		"provider_lifetime_segments_update_guard",
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
			t.Fatalf("v9→v10 migration did not create %s", trigger)
		}
	}
}
