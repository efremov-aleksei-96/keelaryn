package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"
	"time"

	"zombiezen.com/go/sqlite/sqlitex"
)

func TestScanSessionSQLiteLifecycleAuthority(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "state.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	base := time.Date(2026, 9, 27, 15, 0, 0, 0, time.UTC)
	scan, err := store.StartScan(ctx, "provider", "root", base)
	if err != nil {
		t.Fatal(err)
	}

	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		name  string
		query string
		args  []any
	}{
		{"provider rewrite", "UPDATE scan_sessions SET provider_id='tampered' WHERE scan_id=?1", []any{string(scan.ID)}},
		{"root rewrite", "UPDATE scan_sessions SET root='tampered' WHERE scan_id=?1", []any{string(scan.ID)}},
		{"start rewrite", "UPDATE scan_sessions SET started_at='2026-01-01T00:00:00Z' WHERE scan_id=?1", []any{string(scan.ID)}},
		{"finish before start", "UPDATE scan_sessions SET status='COMPLETE', finished_at=?1 WHERE scan_id=?2", []any{base.Add(-time.Second).Format(time.RFC3339Nano), string(scan.ID)}},
		{"delete open", "DELETE FROM scan_sessions WHERE scan_id=?1", []any{string(scan.ID)}},
		{"direct terminal insert", "INSERT INTO scan_sessions (scan_id, provider_id, root, status, started_at, finished_at) VALUES ('scan_direct_complete','provider','root-2','COMPLETE',?1,?2)", []any{base.Format(time.RFC3339Nano), base.Add(time.Second).Format(time.RFC3339Nano)}},
	} {
		if err := sqlitex.Execute(conn, tc.query, &sqlitex.ExecOptions{Args: tc.args}); err == nil {
			store.pool.Put(conn)
			t.Fatalf("%s unexpectedly succeeded", tc.name)
		}
	}
	store.pool.Put(conn)

	if err := store.CompleteScan(ctx, scan.ID, base.Add(time.Second)); err != nil {
		t.Fatal(err)
	}

	conn, err = store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"UPDATE scan_sessions SET status='OPEN', finished_at=NULL WHERE scan_id=?1",
		&sqlitex.ExecOptions{Args: []any{string(scan.ID)}}); err == nil {
		store.pool.Put(conn)
		t.Fatal("terminal scan reopened by direct SQL")
	}
	if err := sqlitex.Execute(conn,
		"DELETE FROM scan_sessions WHERE scan_id=?1",
		&sqlitex.ExecOptions{Args: []any{string(scan.ID)}}); err == nil {
		store.pool.Put(conn)
		t.Fatal("terminal scan deleted by direct SQL")
	}
	store.pool.Put(conn)

	aborted, err := store.StartScan(ctx, "provider", "root-3", base.Add(2*time.Second))
	if err != nil {
		t.Fatal(err)
	}
	if err := store.AbortScan(ctx, aborted.ID, base.Add(3*time.Second)); err != nil {
		t.Fatal(err)
	}
}

func TestScanSessionSQLiteRejectsMalformedOpenInsert(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "state.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer store.pool.Put(conn)

	for _, tc := range []struct {
		name  string
		query string
	}{
		{"empty provider", "INSERT INTO scan_sessions (scan_id, provider_id, root, status, started_at, finished_at) VALUES ('scan_bad_provider','','root','OPEN','2026-09-27T15:00:00Z',NULL)"},
		{"empty root", "INSERT INTO scan_sessions (scan_id, provider_id, root, status, started_at, finished_at) VALUES ('scan_bad_root','provider','','OPEN','2026-09-27T15:00:00Z',NULL)"},
		{"bad start", "INSERT INTO scan_sessions (scan_id, provider_id, root, status, started_at, finished_at) VALUES ('scan_bad_time','provider','root','OPEN','not-a-time',NULL)"},
	} {
		if err := sqlitex.Execute(conn, tc.query, nil); err == nil {
			t.Fatalf("%s unexpectedly succeeded", tc.name)
		}
	}
}
