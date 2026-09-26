package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"

	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestQualifiedV21DatabaseMigratesToScanSessionLifecycleAuthorityV22(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v21.db")
	v21 := sqlitemigration.Schema{
		AppID:      applicationID,
		Migrations: append([]string(nil), schema.Migrations[:21]...),
	}
	pool := sqlitemigration.NewPool(path, v21, sqlitemigration.Options{
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

	for _, name := range []string{
		"scan_sessions_insert_requires_open",
		"scan_sessions_lifecycle_update_guard",
		"scan_sessions_no_delete",
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
			t.Fatalf("v21→v22 migration missing %s", name)
		}
	}
}
