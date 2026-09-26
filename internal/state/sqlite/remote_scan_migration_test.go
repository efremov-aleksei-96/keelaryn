package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"

	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestQualifiedV16DatabaseMigratesToRemoteScanSourceV17(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v16.db")
	v16 := sqlitemigration.Schema{
		AppID: applicationID,
		Migrations: append([]string(nil), schema.Migrations[:16]...),
	}
	pool := sqlitemigration.NewPool(path, v16, sqlitemigration.Options{
		Flags: sqlite.OpenReadWrite | sqlite.OpenCreate,
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

	for _, name := range []string{
		"remote_scan_sources",
		"remote_scan_sources_insert_guard",
		"remote_scan_sources_no_update",
		"remote_scan_sources_no_delete",
	} {
		var found bool
		if err := sqlitex.Execute(conn,
			"SELECT 1 FROM sqlite_master WHERE name=?1 AND type IN ('table','trigger')",
			&sqlitex.ExecOptions{
				Args: []any{name},
				ResultFunc: func(*sqlite.Stmt) error {
					found = true
					return nil
				},
			}); err != nil {
			t.Fatal(err)
		}
		if !found {
			t.Fatalf("v16→v17 migration missing %s", name)
		}
	}
}


func TestQualifiedV17DatabaseMigratesToRemoteScanSessionHardeningV18(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v17.db")
	v17 := sqlitemigration.Schema{
		AppID: applicationID,
		Migrations: append([]string(nil), schema.Migrations[:17]...),
	}
	pool := sqlitemigration.NewPool(path, v17, sqlitemigration.Options{
		Flags: sqlite.OpenReadWrite | sqlite.OpenCreate,
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

	for _, name := range []string{
		"remote_scan_session_update_guard",
		"remote_scan_session_complete_source_guard",
	} {
		var found bool
		if err := sqlitex.Execute(conn,
			"SELECT 1 FROM sqlite_master WHERE name=?1 AND type='trigger'",
			&sqlitex.ExecOptions{
				Args: []any{name},
				ResultFunc: func(*sqlite.Stmt) error {
					found = true
					return nil
				},
			}); err != nil {
			t.Fatal(err)
		}
		if !found {
			t.Fatalf("v17→v18 migration missing %s", name)
		}
	}
}
