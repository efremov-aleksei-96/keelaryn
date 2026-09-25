package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"

	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestQualifiedV6DatabaseMigratesToAuthoritySealingV7(t *testing.T) {
	ctx:=context.Background(); path:=filepath.Join(t.TempDir(),"v6.db")
	v6:=sqlitemigration.Schema{AppID:applicationID,Migrations:append([]string(nil),schema.Migrations[:6]...)}
	pool:=sqlitemigration.NewPool(path,v6,sqlitemigration.Options{
		Flags:sqlite.OpenReadWrite|sqlite.OpenCreate,PoolSize:1,
		PrepareConn:func(conn *sqlite.Conn) error { return sqlitex.ExecuteTransient(conn,"PRAGMA foreign_keys = ON",nil) },
	})
	conn,err:=pool.Get(ctx); if err!=nil { t.Fatal(err) }; pool.Put(conn)
	if err=pool.Close(); err!=nil { t.Fatal(err) }

	store,err:=Open(ctx,path); if err!=nil { t.Fatal(err) }; defer store.Close()
	conn,err=store.pool.Get(ctx); if err!=nil { t.Fatal(err) }; defer store.pool.Put(conn)

	var sealedColumn bool
	if err:=sqlitex.Execute(conn,"SELECT 1 FROM pragma_table_info('identity_authority_sets') WHERE name='sealed_at'",&sqlitex.ExecOptions{
		ResultFunc:func(*sqlite.Stmt) error { sealedColumn=true; return nil },
	}); err!=nil { t.Fatal(err) }
	if !sealedColumn { t.Fatal("v6→v7 migration did not add sealed_at") }

	for _,trigger:=range []string{
		"identity_authority_sets_no_delete",
		"identity_authority_sets_update_guard",
		"identity_authority_candidates_no_update",
		"identity_authority_candidates_no_delete",
		"identity_authority_candidates_no_insert_after_seal",
		"identity_mutation_requests_no_update",
		"identity_mutation_requests_no_delete",
	} {
		var exists bool
		if err:=sqlitex.Execute(conn,"SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?1",&sqlitex.ExecOptions{
			Args:[]any{trigger},ResultFunc:func(*sqlite.Stmt) error { exists=true; return nil },
		}); err!=nil { t.Fatal(err) }
		if !exists { t.Fatalf("missing v7 trigger %s",trigger) }
	}
}
