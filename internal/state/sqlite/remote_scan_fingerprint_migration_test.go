package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"

	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestQualifiedV18DatabaseMigratesToRemoteScanFingerprintConsistencyV19(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v18.db")
	v18 := sqlitemigration.Schema{
		AppID:      applicationID,
		Migrations: append([]string(nil), schema.Migrations[:18]...),
	}
	pool := sqlitemigration.NewPool(path, v18, sqlitemigration.Options{
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
		"SELECT 1 FROM sqlite_master WHERE name='remote_scan_source_fingerprint_consistency_guard' AND type='trigger'",
		&sqlitex.ExecOptions{ResultFunc: func(*sqlite.Stmt) error {
			found = true
			return nil
		}}); err != nil {
		t.Fatal(err)
	}
	if !found {
		t.Fatal("v18→v19 migration missing remote scan fingerprint consistency guard")
	}
}
