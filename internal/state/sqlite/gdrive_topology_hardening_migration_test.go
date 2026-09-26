package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"

	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestQualifiedV15DatabaseMigratesToTopologyProjectionHardeningV16(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v15.db")
	v15 := sqlitemigration.Schema{
		AppID: applicationID,
		Migrations: append([]string(nil), schema.Migrations[:15]...),
	}
	pool := sqlitemigration.NewPool(path, v15, sqlitemigration.Options{
		Flags: sqlite.OpenReadWrite | sqlite.OpenCreate,
		PoolSize: 1,
		PrepareConn: func(conn *sqlite.Conn) error {
			return sqlitex.ExecuteTransient(conn, "PRAGMA foreign_keys = ON", nil)
		},
	})
	conn, err := pool.Get(ctx)
	if err != nil { t.Fatal(err) }
	pool.Put(conn)
	if err := pool.Close(); err != nil { t.Fatal(err) }

	store, err := Open(ctx, path)
	if err != nil { t.Fatal(err) }
	defer store.Close()
	conn, err = store.pool.Get(ctx)
	if err != nil { t.Fatal(err) }
	defer store.pool.Put(conn)

	for _, trigger := range []string{
		"gdrive_topology_nodes_insert_requires_unwatermarked",
		"gdrive_topology_nodes_update_requires_unwatermarked",
	} {
		var exists bool
		if err := sqlitex.Execute(conn,
			"SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?1",
			&sqlitex.ExecOptions{
				Args: []any{trigger},
				ResultFunc: func(*sqlite.Stmt) error { exists = true; return nil },
			}); err != nil { t.Fatal(err) }
		if !exists {
			t.Fatalf("v15→v16 migration missing %s", trigger)
		}
	}
}
