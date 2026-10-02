package sqlite

import (
	"context"
	"path/filepath"
	"testing"

	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestSearchCacheSecureDeleteIsEnabled(t *testing.T) {
	ctx := context.Background()
	index, err := Open(ctx, filepath.Join(t.TempDir(), "search.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer index.Close()

	conn, err := index.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer index.pool.Put(conn)

	var core int64
	if err := sqlitex.ExecuteTransient(conn, "PRAGMA secure_delete", &sqlitex.ExecOptions{
		ResultFunc: func(stmt *sqlite.Stmt) error {
			core = stmt.ColumnInt64(0)
			return nil
		},
	}); err != nil {
		t.Fatal(err)
	}
	if core != 1 {
		t.Fatalf("PRAGMA secure_delete=%d want 1", core)
	}

	var fts int64
	var found bool
	if err := sqlitex.Execute(conn,
		"SELECT v FROM search_documents_fts_config WHERE k='secure-delete'",
		&sqlitex.ExecOptions{ResultFunc: func(stmt *sqlite.Stmt) error {
			found = true
			fts = stmt.ColumnInt64(0)
			return nil
		}}); err != nil {
		t.Fatal(err)
	}
	if !found || fts != 1 {
		t.Fatalf("FTS5 secure-delete found=%v value=%d want true/1", found, fts)
	}

	var pending int64
	var upgradeFound bool
	if err := sqlitex.Execute(conn,
		"SELECT vacuum_pending FROM search_security_upgrade WHERE id=1",
		&sqlitex.ExecOptions{ResultFunc: func(stmt *sqlite.Stmt) error {
			upgradeFound = true
			pending = stmt.ColumnInt64(0)
			return nil
		}}); err != nil {
		t.Fatal(err)
	}
	if !upgradeFound || pending != 0 {
		t.Fatalf("security upgrade found=%v pending=%d want true/0", upgradeFound, pending)
	}
}


func TestSearchSecurityUpgradeFromV1CompletesOneTimeVacuum(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "search.db")

	legacy := schema
	legacy.Migrations = legacy.Migrations[:1]
	pool := sqlitemigration.NewPool(path, legacy, sqlitemigration.Options{
		Flags:    sqlite.OpenReadWrite | sqlite.OpenCreate,
		PoolSize: 1,
	})
	conn, err := pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.ExecuteTransient(conn, "PRAGMA secure_delete = OFF;", nil); err != nil {
		pool.Put(conn)
		pool.Close()
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO search_documents (artifact_id,revision_id,extractor_id,media_type,content_algorithm,content_digest,content_size,text) VALUES ('art-old','rev-old','builtin:text-utf8:v1','text/plain','sha256','legacy',18,'legacy secret text')",
		nil); err != nil {
		pool.Put(conn)
		pool.Close()
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn, "DELETE FROM search_documents WHERE artifact_id='art-old'", nil); err != nil {
		pool.Put(conn)
		pool.Close()
		t.Fatal(err)
	}
	pool.Put(conn)
	if err := pool.Close(); err != nil {
		t.Fatal(err)
	}

	index, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer index.Close()
	if err := index.Verify(ctx); err != nil {
		t.Fatal(err)
	}

	conn, err = index.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer index.pool.Put(conn)
	var version int64
	if err := sqlitex.ExecuteTransient(conn, "PRAGMA user_version;", &sqlitex.ExecOptions{
		ResultFunc: func(stmt *sqlite.Stmt) error {
			version = stmt.ColumnInt64(0)
			return nil
		},
	}); err != nil {
		t.Fatal(err)
	}
	if version != 4 {
		t.Fatalf("user_version=%d want 4", version)
	}
}
