package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"

	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestQualifiedV7DatabaseMigratesToRemoteHistoryV8(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v7.db")
	v7 := sqlitemigration.Schema{AppID: applicationID, Migrations: append([]string(nil), schema.Migrations[:7]...)}
	pool := sqlitemigration.NewPool(path, v7, sqlitemigration.Options{
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

	for _, table := range []string{
		"remote_history_generations",
		"remote_history_publications",
		"remote_history_bootstrap_membership",
		"remote_history_publication_changes",
		"remote_history_membership",
	} {
		var exists bool
		if err := sqlitex.Execute(conn,
			"SELECT 1 FROM sqlite_master WHERE type='table' AND name=?1",
			&sqlitex.ExecOptions{
				Args: []any{table},
				ResultFunc: func(*sqlite.Stmt) error { exists = true; return nil },
			}); err != nil {
			t.Fatal(err)
		}
		if !exists {
			t.Fatalf("v7→v8 migration did not create %s", table)
		}
	}
}
