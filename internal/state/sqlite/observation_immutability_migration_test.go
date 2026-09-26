package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"

	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestQualifiedV19DatabaseMigratesToObservationEvidenceImmutabilityV20(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v19.db")
	v19 := sqlitemigration.Schema{
		AppID:      applicationID,
		Migrations: append([]string(nil), schema.Migrations[:19]...),
	}
	pool := sqlitemigration.NewPool(path, v19, sqlitemigration.Options{
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
		"provider_object_occurrences_no_update",
		"provider_object_occurrences_no_delete",
		"observations_no_update",
		"observations_no_delete",
		"locators_no_update",
		"locators_no_delete",
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
			t.Fatalf("v19→v20 migration missing %s", name)
		}
	}
}
