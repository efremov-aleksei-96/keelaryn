package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"

	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestQualifiedV13DatabaseMigratesToPolicyAwareAdmissionV14(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v13.db")
	v13 := sqlitemigration.Schema{
		AppID: applicationID,
		Migrations: append([]string(nil), schema.Migrations[:13]...),
	}
	pool := sqlitemigration.NewPool(path, v13, sqlitemigration.Options{
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

	var nakedBindingFK bool
	if err := sqlitex.Execute(conn, "PRAGMA foreign_key_list(accepted_artifact_admissions)", &sqlitex.ExecOptions{
		ResultFunc: func(stmt *sqlite.Stmt) error {
			if stmt.ColumnText(2) == "provider_artifact_bindings" {
				nakedBindingFK = true
			}
			return nil
		},
	}); err != nil { t.Fatal(err) }
	if nakedBindingFK {
		t.Fatal("v13→v14 migration retained legacy naked-binding foreign key")
	}

	for _, trigger := range []string{
		"accepted_admission_binding_guard",
		"accepted_artifact_admissions_no_update",
		"accepted_artifact_admissions_no_delete",
	} {
		var exists bool
		if err := sqlitex.Execute(conn,
			"SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?1",
			&sqlitex.ExecOptions{
				Args: []any{trigger},
				ResultFunc: func(*sqlite.Stmt) error { exists = true; return nil },
			}); err != nil { t.Fatal(err) }
		if !exists { t.Fatalf("v13→v14 migration missing trigger %s", trigger) }
	}
}
