package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"

	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestQualifiedV11DatabaseMigratesToLifetimeAcceptanceV12(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v11.db")
	v11 := sqlitemigration.Schema{
		AppID: applicationID,
		Migrations: append([]string(nil), schema.Migrations[:11]...),
	}
	pool := sqlitemigration.NewPool(path, v11, sqlitemigration.Options{
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

	v12 := sqlitemigration.Schema{
		AppID: applicationID,
		Migrations: append([]string(nil), schema.Migrations[:12]...),
	}
	pool = sqlitemigration.NewPool(path, v12, sqlitemigration.Options{
		Flags: sqlite.OpenReadWrite | sqlite.OpenCreate,
		PoolSize: 1,
		PrepareConn: func(conn *sqlite.Conn) error {
			return sqlitex.ExecuteTransient(conn, "PRAGMA foreign_keys = ON", nil)
		},
	})
	conn, err = pool.Get(ctx)
	if err != nil { t.Fatal(err) }
	defer pool.Put(conn)
	defer pool.Close()

	for table, column := range map[string]string{
		"accepted_continuity_decisions": "lifetime_segment_id",
		"accepted_artifact_admissions": "lifetime_segment_id",
	} {
		var found bool
		if err := sqlitex.Execute(conn, "PRAGMA table_info("+table+")", &sqlitex.ExecOptions{
			ResultFunc: func(stmt *sqlite.Stmt) error {
				if stmt.ColumnText(1) == column { found = true }
				return nil
			},
		}); err != nil { t.Fatal(err) }
		if !found { t.Fatalf("v11→v12 migration missing %s.%s", table, column) }
	}

	for _, trigger := range []string{
		"accepted_continuity_lifetime_guard",
		"accepted_admission_lifetime_guard",
	} {
		var exists bool
		if err := sqlitex.Execute(conn,
			"SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?1",
			&sqlitex.ExecOptions{
				Args: []any{trigger},
				ResultFunc: func(*sqlite.Stmt) error { exists = true; return nil },
			}); err != nil { t.Fatal(err) }
		if !exists { t.Fatalf("v11→v12 migration missing trigger %s", trigger) }
	}
}
