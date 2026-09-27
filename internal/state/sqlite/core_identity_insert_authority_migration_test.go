package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"

	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestQualifiedV34DatabaseMigratesToCoreIdentityInsertAuthorityV35(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v34.db")
	store := openV34CoreIdentityStore(t, path)
	conn, err := store.pool.Get(ctx)
	if err != nil { t.Fatal(err) }
	if err := sqlitex.Execute(conn, "INSERT INTO artifacts (artifact_id) VALUES ('art_v34')", nil); err != nil {
		store.pool.Put(conn); t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO revisions (revision_id,artifact_id,sequence,content_algorithm,content_digest,content_size) VALUES ('rev_v34_1','art_v34',1,'sha256','one',1),('rev_v34_2','art_v34',2,'sha256','two',1)",
		nil); err != nil {
		store.pool.Put(conn); t.Fatal(err)
	}
	store.pool.Put(conn)
	if err := store.Close(); err != nil { t.Fatal(err) }

	store, err = Open(ctx, path)
	if err != nil { t.Fatal(err) }
	defer store.Close()
	conn, err = store.pool.Get(ctx)
	if err != nil { t.Fatal(err) }
	defer store.pool.Put(conn)
	for _, name := range []string{
		"artifacts_insert_application_guard",
		"revisions_insert_application_guard",
		"provider_artifact_bindings_insert_application_guard",
	} {
		var found bool
		if err := sqlitex.Execute(conn, "SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?1",
			&sqlitex.ExecOptions{Args: []any{name}, ResultFunc: func(*sqlite.Stmt) error { found = true; return nil }}); err != nil {
			t.Fatal(err)
		}
		if !found { t.Fatalf("v34→v35 migration missing %s", name) }
	}
}

func TestV35MigrationRejectsNoncontiguousHistoricalRevisionSequence(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v34-gap.db")
	store := openV34CoreIdentityStore(t, path)
	conn, err := store.pool.Get(ctx)
	if err != nil { t.Fatal(err) }
	if err := sqlitex.Execute(conn, "INSERT INTO artifacts (artifact_id) VALUES ('art_gap_v34')", nil); err != nil {
		store.pool.Put(conn); t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO revisions (revision_id,artifact_id,sequence,content_algorithm,content_digest,content_size) VALUES ('rev_gap_v34','art_gap_v34',2,'sha256','gap',1)",
		nil); err != nil {
		store.pool.Put(conn); t.Fatal(err)
	}
	store.pool.Put(conn)
	if err := store.Close(); err != nil { t.Fatal(err) }
	migrated, err := Open(ctx, path)
	if err == nil {
		_ = migrated.Close()
		t.Fatal("v35 migration unexpectedly accepted noncontiguous historical Revision sequence")
	}
}

func openV34CoreIdentityStore(t *testing.T, path string) *Store {
	t.Helper()
	partial := sqlitemigration.Schema{AppID: applicationID, Migrations: append([]string(nil), schema.Migrations[:34]...)}
	store := &Store{path: path}
	pool := sqlitemigration.NewPool(path, partial, sqlitemigration.Options{
		Flags: sqlite.OpenReadWrite | sqlite.OpenCreate, PoolSize: 1, PrepareConn: store.prepareConn,
	})
	store.pool = pool
	conn, err := pool.Get(context.Background())
	if err != nil { t.Fatal(err) }
	pool.Put(conn)
	return store
}
