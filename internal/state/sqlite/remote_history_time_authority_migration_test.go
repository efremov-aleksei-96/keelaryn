package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestQualifiedV25DatabaseMigratesToCausalRemoteHistoryTimeAuthorityV26(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v25.db")
	pool := openV25RemoteHistoryTimePool(t, path)
	if err := pool.Close(); err != nil {
		t.Fatal(err)
	}
	store, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer store.pool.Put(conn)
	for _, name := range []string{
		"remote_history_publication_time_insert_guard",
		"remote_scan_source_causal_time_insert_guard",
	} {
		var found bool
		if err := sqlitex.Execute(conn,
			"SELECT 1 FROM sqlite_master WHERE name=?1 AND type='trigger'",
			&sqlitex.ExecOptions{
				Args: []any{name},
				ResultFunc: func(*sqlite.Stmt) error { found = true; return nil },
			}); err != nil {
			t.Fatal(err)
		}
		if !found {
			t.Fatalf("v25→v26 migration missing %s", name)
		}
	}
}

func TestV26MigrationRejectsExistingBackdatedRemoteHistoryPublication(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v25.db")
	pool := openV25RemoteHistoryTimePool(t, path)
	conn, err := pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	scope := remoteHistoryTestScope()
	base := time.Date(2026, 9, 27, 22, 0, 0, 0, time.UTC)
	if err := sqlitex.Execute(conn,
		"INSERT INTO remote_history_generations (generation_id,provider_id,identity_domain,stream_id,root,scope_policy_fingerprint,status,created_at,closed_at,closure_reason,current_sequence,committed_cursor) VALUES ('hgen_v26_bad',?1,?2,?3,?4,?5,'ACTIVE',?6,NULL,NULL,1,'cursor-1')",
		&sqlitex.ExecOptions{Args: []any{
			string(scope.ProviderID), scope.IdentityDomain, string(scope.StreamID), scope.Root,
			string(remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")),
			base.UTC().Format(time.RFC3339Nano),
		}}); err != nil {
		pool.Put(conn); t.Fatal(err)
	}
	for seq, at := range []time.Time{base, base.Add(-time.Nanosecond)} {
		kind := "BOOTSTRAP"
		previous := ""
		committed := "cursor-1"
		if seq == 1 {
			kind = "INCREMENTAL"
			previous = "cursor-1"
			committed = "cursor-2"
		}
		if err := sqlitex.Execute(conn,
			"INSERT INTO remote_history_publications (generation_id,sequence,kind,previous_cursor,committed_cursor,committed_at,fingerprint_version,fingerprint_sha256) VALUES ('hgen_v26_bad',?1,?2,?3,?4,?5,'remote-history-publication:v1',?6)",
			&sqlitex.ExecOptions{Args: []any{
				int64(seq + 1), kind, previous, committed, at.UTC().Format(time.RFC3339Nano),
				"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
			}}); err != nil {
			pool.Put(conn); t.Fatal(err)
		}
	}
	pool.Put(conn)
	if err := pool.Close(); err != nil {
		t.Fatal(err)
	}
	store, err := Open(ctx, path)
	if err == nil {
		_ = store.Close()
		t.Fatal("v26 migration unexpectedly accepted backdated publication")
	}
}

func openV25RemoteHistoryTimePool(t *testing.T, path string) *sqlitemigration.Pool {
	t.Helper()
	partial := sqlitemigration.Schema{
		AppID:      applicationID,
		Migrations: append([]string(nil), schema.Migrations[:25]...),
	}
	pool := sqlitemigration.NewPool(path, partial, sqlitemigration.Options{
		Flags:    sqlite.OpenReadWrite | sqlite.OpenCreate,
		PoolSize: 1,
		PrepareConn: func(conn *sqlite.Conn) error {
			return sqlitex.ExecuteTransient(conn, "PRAGMA foreign_keys = ON", nil)
		},
	})
	conn, err := pool.Get(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	pool.Put(conn)
	return pool
}

var _ = corpus.ProviderID("")
