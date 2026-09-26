package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"

	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestQualifiedV12DatabaseMigratesToAcceptedDecisionHardeningV13(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v12.db")
	v12 := sqlitemigration.Schema{
		AppID: applicationID,
		Migrations: append([]string(nil), schema.Migrations[:12]...),
	}
	pool := sqlitemigration.NewPool(path, v12, sqlitemigration.Options{
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

	for _, trigger := range []string{
		"accepted_continuity_decisions_no_update",
		"accepted_continuity_decisions_no_delete",
		"accepted_artifact_admissions_no_update",
		"accepted_artifact_admissions_no_delete",
		"provider_artifact_bindings_remote_history_forbidden",
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
			t.Fatalf("v12→v13 migration did not create %s", trigger)
		}
	}
}
