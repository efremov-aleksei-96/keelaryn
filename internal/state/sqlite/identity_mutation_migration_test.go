package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"

	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestQualifiedV5DatabaseMigratesToIdentityHardeningV6(t *testing.T) {
	ctx:=context.Background(); path:=filepath.Join(t.TempDir(),"v5.db")
	v5:=sqlitemigration.Schema{AppID:applicationID,Migrations:append([]string(nil),schema.Migrations[:5]...)}
	pool:=sqlitemigration.NewPool(path,v5,sqlitemigration.Options{
		Flags:sqlite.OpenReadWrite|sqlite.OpenCreate,PoolSize:1,
		PrepareConn:func(conn *sqlite.Conn) error { return sqlitex.ExecuteTransient(conn,"PRAGMA foreign_keys = ON",nil) },
	})
	conn,err:=pool.Get(ctx); if err!=nil { t.Fatal(err) }; pool.Put(conn)
	if err=pool.Close(); err!=nil { t.Fatal(err) }
	store,err:=Open(ctx,path); if err!=nil { t.Fatal(err) }; defer store.Close()
	conn,err=store.pool.Get(ctx); if err!=nil { t.Fatal(err) }; defer store.pool.Put(conn)
	for _,table:=range []string{"identity_authority_sets","identity_authority_candidates","identity_mutation_requests"} {
		var exists bool
		if err:=sqlitex.Execute(conn,"SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?1",&sqlitex.ExecOptions{
			Args:[]any{table},ResultFunc:func(stmt *sqlite.Stmt) error { exists=true; return nil },
		}); err!=nil { t.Fatal(err) }
		if !exists { t.Fatalf("v5→v6 migration did not create %s",table) }
	}
}
