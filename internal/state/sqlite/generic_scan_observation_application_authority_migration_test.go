package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"

	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestQualifiedV39DatabaseMigratesToGenericScanObservationAuthorityV40(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v39.db")
	store := &Store{path: path}
	v39 := sqlitemigration.Schema{
		AppID: applicationID,
		Migrations: append([]string(nil), schema.Migrations[:39]...),
	}
	pool := sqlitemigration.NewPool(path, v39, sqlitemigration.Options{
		Flags: sqlite.OpenReadWrite | sqlite.OpenCreate,
		PoolSize: 1,
		PrepareConn: store.prepareConn,
	})
	store.pool = pool
	conn, err := pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	pool.Put(conn)
	if err := pool.Close(); err != nil {
		t.Fatal(err)
	}

	migrated, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer migrated.Close()
	conn, err = migrated.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer migrated.pool.Put(conn)

	for _, name := range []string{
		"scan_sessions_insert_application_guard_v40",
		"scan_sessions_lifecycle_application_guard_v40",
		"provider_object_occurrences_insert_application_guard_v40",
		"observations_insert_application_guard_v40",
		"locators_insert_application_guard_v40",
	} {
		var found bool
		if err := sqlitex.Execute(conn,
			"SELECT 1 FROM sqlite_master WHERE name=?1 AND type='trigger'",
			&sqlitex.ExecOptions{Args: []any{name}, ResultFunc: func(*sqlite.Stmt) error {
				found = true
				return nil
			}}); err != nil {
			t.Fatal(err)
		}
		if !found {
			t.Fatalf("v39→v40 migration missing %s", name)
		}
	}
}
