package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"

	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestQualifiedV8DatabaseMigratesToRemoteHistoryHardeningV9(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v8.db")
	v8 := sqlitemigration.Schema{AppID: applicationID, Migrations: append([]string(nil), schema.Migrations[:8]...)}
	pool := sqlitemigration.NewPool(path, v8, sqlitemigration.Options{
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

	for _, trigger := range []string{
		"remote_history_publications_insert_guard",
		"remote_history_publication_changes_insert_guard",
		"remote_history_membership_insert_guard",
		"remote_history_membership_update_guard",
		"remote_history_membership_delete_guard",
		"remote_history_generations_update_guard",
	} {
		var exists bool
		if err := sqlitex.Execute(conn,
			"SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?1",
			&sqlitex.ExecOptions{
				Args: []any{trigger},
				ResultFunc: func(*sqlite.Stmt) error { exists = true; return nil },
			}); err != nil {
			t.Fatal(err)
		}
		if !exists {
			t.Fatalf("v8→v9 migration did not create %s", trigger)
		}
	}
}
