package sqlite

import (
	"context"
	"path/filepath"
	"testing"

	"zombiezen.com/go/sqlite"
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
}
