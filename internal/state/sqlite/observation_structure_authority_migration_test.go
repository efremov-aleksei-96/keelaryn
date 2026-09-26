package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"

	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestQualifiedV22DatabaseMigratesToObservationStructureAuthorityV23(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v22.db")
	v22 := sqlitemigration.Schema{
		AppID:      applicationID,
		Migrations: append([]string(nil), schema.Migrations[:22]...),
	}
	pool := sqlitemigration.NewPool(path, v22, sqlitemigration.Options{
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

	for _, object := range []struct {
		name string
		typeName string
	}{
		{"observations_occurrence_one_to_one", "index"},
		{"provider_object_occurrences_insert_structure_guard", "trigger"},
		{"observations_insert_structure_guard", "trigger"},
		{"observations_scan_observed_object_unique_guard", "trigger"},
		{"locators_insert_structure_guard", "trigger"},
		{"locators_scan_path_unique_guard", "trigger"},
		{"scan_sessions_complete_observation_coverage_guard", "trigger"},
	} {
		var found bool
		if err := sqlitex.Execute(conn,
			"SELECT 1 FROM sqlite_master WHERE name=?1 AND type=?2",
			&sqlitex.ExecOptions{
				Args: []any{object.name, object.typeName},
				ResultFunc: func(*sqlite.Stmt) error {
					found = true
					return nil
				},
			}); err != nil {
			t.Fatal(err)
		}
		if !found {
			t.Fatalf("v22→v23 migration missing %s", object.name)
		}
	}
}
