package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"
	"time"

	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestQualifiedV35DatabaseMigratesToIdentityAuthorityCreationAuthorityV36(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v35.db")
	store := openV35IdentityAuthorityCreationStore(t, path)
	if err := store.Close(); err != nil { t.Fatal(err) }
	migrated, err := Open(ctx, path)
	if err != nil { t.Fatal(err) }
	defer migrated.Close()
	conn, err := migrated.pool.Get(ctx)
	if err != nil { t.Fatal(err) }
	defer migrated.pool.Put(conn)
	for _, name := range []string{
		"identity_authority_sets_insert_application_guard_v36",
		"identity_authority_candidates_insert_application_guard_v36",
		"identity_authority_sets_seal_application_guard_v36",
	} {
		var found bool
		if err := sqlitex.Execute(conn,
			"SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?1",
			&sqlitex.ExecOptions{
				Args: []any{name},
				ResultFunc: func(*sqlite.Stmt) error { found = true; return nil },
			}); err != nil { t.Fatal(err) }
		if !found { t.Fatalf("v35→v36 migration missing %s", name) }
	}
}

func TestV36MigrationRejectsExistingUnsealedIdentityAuthority(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v35-unsealed.db")
	store := openV35IdentityAuthorityCreationStore(t, path)
	conn, err := store.pool.Get(ctx)
	if err != nil { t.Fatal(err) }
	at := time.Date(2026, 9, 27, 12, 40, 0, 0, time.UTC).Format(time.RFC3339Nano)
	if err := sqlitex.Execute(conn,
		"INSERT INTO identity_authority_sets (authority_set_id,policy_id,provider_id,identity_domain,scope_id,current_object_id,universe_coverage,generation_id,lifetime_segment_id,source_refs_json,created_at,sealed_at) VALUES ('auth_unsealed_v35','test:v1','drive','domain','root','obj','UNKNOWN',NULL,NULL,'[\"source\"]',?1,NULL)",
		&sqlitex.ExecOptions{Args: []any{at}}); err != nil {
		store.pool.Put(conn); t.Fatal(err)
	}
	store.pool.Put(conn)
	if err := store.Close(); err != nil { t.Fatal(err) }
	migrated, err := Open(ctx, path)
	if err == nil {
		_ = migrated.Close()
		t.Fatal("v36 migration unexpectedly accepted unsealed identity authority")
	}
}

func openV35IdentityAuthorityCreationStore(t *testing.T, path string) *Store {
	t.Helper()
	partial := sqlitemigration.Schema{
		AppID: applicationID,
		Migrations: append([]string(nil), schema.Migrations[:35]...),
	}
	store := &Store{path:path}
	pool := sqlitemigration.NewPool(path, partial, sqlitemigration.Options{
		Flags: sqlite.OpenReadWrite | sqlite.OpenCreate,
		PoolSize: 1,
		PrepareConn: store.prepareConn,
	})
	store.pool=pool
	conn, err := pool.Get(context.Background())
	if err != nil { t.Fatal(err) }
	pool.Put(conn)
	return store
}
