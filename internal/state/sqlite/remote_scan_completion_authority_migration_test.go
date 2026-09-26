package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"

	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestQualifiedV23DatabaseMigratesToApplicationGuardedRemoteCompletionV24(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v23.db")
	v23 := sqlitemigration.Schema{
		AppID:      applicationID,
		Migrations: append([]string(nil), schema.Migrations[:23]...),
	}
	pool := sqlitemigration.NewPool(path, v23, sqlitemigration.Options{
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

	var found bool
	if err := sqlitex.Execute(conn,
		"SELECT 1 FROM sqlite_master WHERE name='remote_scan_session_complete_application_guard' AND type='trigger'",
		&sqlitex.ExecOptions{ResultFunc: func(*sqlite.Stmt) error {
			found = true
			return nil
		}}); err != nil {
		t.Fatal(err)
	}
	if !found {
		t.Fatal("v23→v24 migration missing application completion guard")
	}
}
