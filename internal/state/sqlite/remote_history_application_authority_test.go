package sqlitestate

import (
	"context"
	"errors"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestRemoteHistoryApplicationAuthorityRejectsStructurallyValidDirectSQL(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")
	base := time.Date(2026, 9, 27, 18, 0, 0, 0, time.UTC)

	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO remote_history_generations (generation_id,provider_id,identity_domain,stream_id,root,scope_policy_fingerprint,status,created_at,closed_at,closure_reason,current_sequence,committed_cursor) VALUES ('hgen_forged','drive','drive:user-1','drive:user-1:changes','root','scope-policy:v1:test','ACTIVE',?1,NULL,NULL,1,'cursor-forged')",
		&sqlitex.ExecOptions{Args: []any{base.Format(time.RFC3339Nano)}}); err == nil {
		store.pool.Put(conn)
		t.Fatal("direct RemoteHistory generation insert unexpectedly succeeded")
	}
	store.pool.Put(conn)

	generation, err := store.StartRemoteHistoryGeneration(ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), base)
	if err != nil {
		t.Fatal(err)
	}

	publication := remotehistory.HistoryPublication{
		GenerationID: generation.ID,
		Sequence: 2,
		Kind: remotehistory.HistoryPublicationIncremental,
		PreviousCursor: "cursor-1",
		CommittedCursor: "cursor-2",
		CommittedAt: base.Add(time.Minute),
		FingerprintVersion: remoteHistoryPublicationFingerprintVersion,
	}
	publication.FingerprintSHA256, err = incrementalPublicationFingerprint(publication, nil)
	if err != nil {
		t.Fatal(err)
	}

	conn, err = store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO remote_history_publications (generation_id,sequence,kind,previous_cursor,committed_cursor,committed_at,fingerprint_version,fingerprint_sha256) VALUES (?1,2,'INCREMENTAL','cursor-1','cursor-2',?2,?3,?4)",
		&sqlitex.ExecOptions{Args: []any{string(generation.ID), publication.CommittedAt.Format(time.RFC3339Nano), publication.FingerprintVersion, publication.FingerprintSHA256}}); err == nil {
		store.pool.Put(conn)
		t.Fatal("direct RemoteHistory publication insert with exact payload fingerprint unexpectedly succeeded")
	}
	if err := sqlitex.Execute(conn,
		"UPDATE remote_history_generations SET status='CLOSED',closed_at=?1,closure_reason='GAP' WHERE generation_id=?2",
		&sqlitex.ExecOptions{Args: []any{base.Add(2*time.Minute).Format(time.RFC3339Nano), string(generation.ID)}}); err == nil {
		store.pool.Put(conn)
		t.Fatal("direct RemoteHistory close unexpectedly succeeded")
	}
	if err := sqlitex.Execute(conn,
		"UPDATE provider_object_lifetime_segments SET last_present_sequence=2,last_present_ordinal=0 WHERE generation_id=?1 AND object_id='id-1' AND status='ACTIVE'",
		&sqlitex.ExecOptions{Args: []any{string(generation.ID)}}); err == nil {
		store.pool.Put(conn)
		t.Fatal("direct provider lifetime projection mutation unexpectedly succeeded")
	}
	store.pool.Put(conn)
}

func TestV40HistoricalRemoteHistoryFingerprintMismatchFailsClosed(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v40.db")
	legacy := &Store{path: path}
	v40 := sqlitemigration.Schema{AppID: applicationID, Migrations: append([]string(nil), schema.Migrations[:40]...)}
	pool := sqlitemigration.NewPool(path, v40, sqlitemigration.Options{
		Flags: sqlite.OpenReadWrite | sqlite.OpenCreate,
		PoolSize: 1,
		PrepareConn: legacy.prepareConn,
	})
	legacy.pool = pool
	conn, err := pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	base := time.Date(2026, 9, 27, 18, 5, 0, 0, time.UTC).Format(time.RFC3339Nano)
	if err := sqlitex.Execute(conn,
		"INSERT INTO remote_history_generations (generation_id,provider_id,identity_domain,stream_id,root,scope_policy_fingerprint,status,created_at,closed_at,closure_reason,current_sequence,committed_cursor) VALUES ('hgen_legacy_forged','drive','drive:user-1','drive:user-1:changes','root','scope-policy:v1:test','ACTIVE',?1,NULL,NULL,1,'cursor-1')",
		&sqlitex.ExecOptions{Args: []any{base}}); err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO remote_history_publications (generation_id,sequence,kind,previous_cursor,committed_cursor,committed_at,fingerprint_version,fingerprint_sha256) VALUES ('hgen_legacy_forged',1,'BOOTSTRAP','','cursor-1',?1,'remote-history-publication:v1','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')",
		&sqlitex.ExecOptions{Args: []any{base}}); err != nil {
		t.Fatal(err)
	}
	pool.Put(conn)
	if err := pool.Close(); err != nil {
		t.Fatal(err)
	}

	reopened, err := Open(ctx, path)
	if reopened != nil {
		_ = reopened.Close()
	}
	if !errors.Is(err, ErrRemoteHistoryHistoricalAuthorityInvalid) {
		t.Fatalf("Open error=%v want ErrRemoteHistoryHistoricalAuthorityInvalid", err)
	}
}

func TestQualifiedV40DatabaseMigratesToRemoteHistoryApplicationAuthorityV41(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v40-clean.db")
	legacy := &Store{path: path}
	v40 := sqlitemigration.Schema{AppID: applicationID, Migrations: append([]string(nil), schema.Migrations[:40]...)}
	pool := sqlitemigration.NewPool(path, v40, sqlitemigration.Options{
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

	for _, trigger := range []string{
		"remote_history_generations_insert_application_guard_v41",
		"remote_history_generations_update_application_guard_v41",
		"remote_history_publications_insert_application_guard_v41",
		"remote_history_bootstrap_membership_insert_application_guard_v41",
		"remote_history_publication_changes_insert_application_guard_v41",
		"remote_history_membership_insert_application_guard_v41",
		"remote_history_membership_update_application_guard_v41",
		"remote_history_membership_delete_application_guard_v41",
		"provider_lifetime_segments_insert_application_guard_v41",
		"provider_lifetime_segments_update_application_guard_v41",
	} {
		var found bool
		if err := sqlitex.Execute(conn,
			"SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?1",
			&sqlitex.ExecOptions{Args: []any{trigger}, ResultFunc: func(*sqlite.Stmt) error {
				found = true
				return nil
			}}); err != nil {
			t.Fatal(err)
		}
		if !found {
			t.Fatalf("v40→v41 migration missing %s", trigger)
		}
	}
}
