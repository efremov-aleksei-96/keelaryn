package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"

	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestQualifiedV14DatabaseMigratesToGoogleTopologyV15(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v14.db")
	v14 := sqlitemigration.Schema{
		AppID: applicationID,
		Migrations: append([]string(nil), schema.Migrations[:14]...),
	}
	pool := sqlitemigration.NewPool(path, v14, sqlitemigration.Options{
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

	for _, table := range []string{
		"gdrive_topology_evidence",
		"gdrive_topology_nodes",
		"gdrive_topology_watermarks",
		"gdrive_managed_root_bindings",
	} {
		var exists bool
		if err := sqlitex.Execute(conn,
			"SELECT 1 FROM sqlite_master WHERE type='table' AND name=?1",
			&sqlitex.ExecOptions{
				Args: []any{table},
				ResultFunc: func(*sqlite.Stmt) error { exists = true; return nil },
			}); err != nil { t.Fatal(err) }
		if !exists { t.Fatalf("v14→v15 migration missing table %s", table) }
	}

	for _, trigger := range []string{
		"gdrive_topology_evidence_insert_guard",
		"gdrive_topology_evidence_no_update",
		"gdrive_topology_evidence_no_delete",
		"gdrive_topology_nodes_insert_guard",
		"gdrive_topology_nodes_update_guard",
		"gdrive_topology_nodes_delete_guard",
		"gdrive_topology_watermark_insert_guard",
		"gdrive_topology_watermark_update_guard",
		"gdrive_topology_watermark_update_coverage_guard",
		"gdrive_managed_root_binding_insert_guard",
		"gdrive_managed_root_bindings_no_update",
		"gdrive_managed_root_bindings_no_delete",
	} {
		var exists bool
		if err := sqlitex.Execute(conn,
			"SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?1",
			&sqlitex.ExecOptions{
				Args: []any{trigger},
				ResultFunc: func(*sqlite.Stmt) error { exists = true; return nil },
			}); err != nil { t.Fatal(err) }
		if !exists { t.Fatalf("v14→v15 migration missing trigger %s", trigger) }
	}
}
