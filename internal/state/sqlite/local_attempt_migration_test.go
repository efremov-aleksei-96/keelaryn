package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"

	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestQualifiedV46DatabaseMigratesToLocalAttemptProvenanceV47(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v46.db")
	store := &Store{path: path}
	v46 := sqlitemigration.Schema{
		AppID: applicationID,
		Migrations: append([]string(nil), schema.Migrations[:46]...),
	}
	pool := sqlitemigration.NewPool(path, v46, sqlitemigration.Options{
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

	for _, object := range []struct {
		name string
		typeName string
	}{
		{"local_attempt_sources", "table"},
		{"local_attempt_sources_scope_guard_v47", "trigger"},
		{"local_attempt_sources_application_guard_v47", "trigger"},
		{"local_attempt_sources_no_update_v47", "trigger"},
		{"local_attempt_sources_no_delete_v47", "trigger"},
		{"local_attempt_scan_complete_guard_v47", "trigger"},
		{"local_attempt_scan_abort_guard_v47", "trigger"},
		{"local_attempt_observation_forbidden_v47", "trigger"},
		{"local_attempt_identity_mutation_forbidden_v47", "trigger"},
	} {
		var found bool
		if err := sqlitex.Execute(conn,
			"SELECT 1 FROM sqlite_master WHERE name=?1 AND type=?2",
			&sqlitex.ExecOptions{
				Args: []any{object.name, object.typeName},
				ResultFunc: func(*sqlite.Stmt) error { found = true; return nil },
			}); err != nil {
			t.Fatal(err)
		}
		if !found {
			t.Fatalf("v46→v47 migration missing %s", object.name)
		}
	}
	var count int64
	if err := sqlitex.Execute(conn, "SELECT COUNT(*) FROM local_attempt_sources", &sqlitex.ExecOptions{
		ResultFunc: func(stmt *sqlite.Stmt) error { count = stmt.ColumnInt64(0); return nil },
	}); err != nil {
		t.Fatal(err)
	}
	if count != 0 {
		t.Fatalf("v46→v47 migration synthesized %d local attempt sources", count)
	}
}
