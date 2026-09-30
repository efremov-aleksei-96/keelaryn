package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestLocalIngestCommitReceiptRejectsDirectSQL(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "state.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	at := time.Date(2026, 9, 28, 9, 0, 0, 0, time.UTC)
	scan, err := store.StartScan(ctx, "localfs", "/root", at)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.CompleteScan(ctx, scan.ID, at); err != nil {
		t.Fatal(err)
	}

	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer store.pool.Put(conn)
	if err := sqlitex.Execute(conn,
		"INSERT INTO local_ingest_commits (scan_id,provider_id,root,started_at,ingest_mode,snapshot_fingerprint_version,snapshot_fingerprint_sha256) VALUES (?1,'localfs','/root',?2,'SCAN','localfs-snapshot:v1','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')",
		&sqlitex.ExecOptions{Args: []any{string(scan.ID), at.Format(time.RFC3339Nano)}}); err == nil {
		t.Fatal("direct local ingest commit receipt unexpectedly succeeded")
	}
}

func TestAtomicLocalIngestValidationFailureRollsBackAllDurableRows(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "state.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	at := time.Date(2026, 9, 28, 9, 5, 0, 0, time.UTC)
	input := corpus.ObservationRecordInput{
		ProviderObject: corpus.ProviderObject{ProviderID: "localfs", IdentityState: corpus.ObjectIdentityUnresolved},
		Locators: []corpus.Locator{{ProviderID: "localfs", Root: "/root", Path: "file.txt"}},
		AssignmentState: corpus.AssignmentUnresolved,
		ObservedAt: at,
		Kind: corpus.EntryRegularFile,
		Size: corpus.KnownSize(1),
		ModifiedAt: corpus.KnownModifiedAt(at),
	}
	_, err = store.CommitLocalSnapshot(
		ctx, "localfs", "/root", at, "localfs-snapshot:v1",
		"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		[]corpus.ObservationRecordInput{input},
		func(context.Context) error { return context.Canceled },
	)
	if err == nil {
		t.Fatal("validation failure unexpectedly committed local ingest")
	}
	if open, found, err := store.OpenScanForScope(ctx, "localfs", "/root"); err != nil {
		t.Fatal(err)
	} else if found {
		t.Fatalf("validation rollback left OPEN scan: %#v", open)
	}
	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer store.pool.Put(conn)
	for _, table := range []string{"scan_sessions", "provider_object_occurrences", "observations", "locators", "local_ingest_commits"} {
		var count int64
		if err := sqlitex.Execute(conn, "SELECT COUNT(*) FROM "+table, &sqlitex.ExecOptions{
			ResultFunc: func(stmt *sqlite.Stmt) error { count = stmt.ColumnInt64(0); return nil },
		}); err != nil {
			t.Fatal(err)
		}
		if count != 0 {
			t.Fatalf("%s count=%d after rollback", table, count)
		}
	}
}

func TestQualifiedV43DatabaseMigratesToAtomicLocalIngestV44(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v43.db")
	legacy := &Store{path: path}
	v43 := sqlitemigration.Schema{AppID: applicationID, Migrations: append([]string(nil), schema.Migrations[:43]...)}
	pool := sqlitemigration.NewPool(path, v43, sqlitemigration.Options{
		Flags: sqlite.OpenReadWrite | sqlite.OpenCreate,
		PoolSize: 1,
		PrepareConn: legacy.prepareConn,
	})
	legacy.pool = pool
	conn, err := pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	pool.Put(conn)
	if err := pool.Close(); err != nil {
		t.Fatal(err)
	}

	store, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	conn, err = store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer store.pool.Put(conn)

	for _, name := range []string{
		"local_ingest_commits",
		"local_ingest_commits_scope_guard_v44",
		"local_ingest_commits_application_guard_v44",
		"local_ingest_commits_no_update_v44",
		"local_ingest_commits_no_delete_v44",
	} {
		var found bool
		if err := sqlitex.Execute(conn,
			"SELECT 1 FROM sqlite_master WHERE name=?1 AND type IN ('table','trigger')",
			&sqlitex.ExecOptions{Args: []any{name}, ResultFunc: func(*sqlite.Stmt) error {
				found = true
				return nil
			}}); err != nil {
			t.Fatal(err)
		}
		if !found {
			t.Fatalf("v43→v44 migration missing %s", name)
		}
	}
}
