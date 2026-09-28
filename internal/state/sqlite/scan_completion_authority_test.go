package sqlitestate

import (
	"context"
	"errors"
	"path/filepath"
	"testing"
	"time"

	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestV45HistoricalEqualTimeScansFailClosedUntilSequencedCompletion(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v44.db")
	legacy := &Store{path: path}
	v44 := sqlitemigration.Schema{
		AppID: applicationID,
		Migrations: append([]string(nil), schema.Migrations[:44]...),
	}
	pool := sqlitemigration.NewPool(path, v44, sqlitemigration.Options{
		Flags: sqlite.OpenReadWrite | sqlite.OpenCreate,
		PoolSize: 1,
		PrepareConn: legacy.prepareConn,
	})
	legacy.pool = pool
	at := time.Date(2026, 9, 28, 10, 0, 0, 0, time.UTC)

	first, err := legacy.StartScan(ctx, "localfs", "/root", at)
	if err != nil {
		t.Fatal(err)
	}
	if err := legacy.CompleteScan(ctx, first.ID, at); err != nil {
		t.Fatal(err)
	}
	second, err := legacy.StartScan(ctx, "localfs", "/root", at)
	if err != nil {
		t.Fatal(err)
	}
	if err := legacy.CompleteScan(ctx, second.ID, at); err != nil {
		t.Fatal(err)
	}
	if err := pool.Close(); err != nil {
		t.Fatal(err)
	}

	store, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	if _, err := store.Inventory(ctx, "localfs", "/root"); !errors.Is(err, ErrAmbiguousScanAuthority) {
		t.Fatalf("historical equal-time Inventory error=%v want ErrAmbiguousScanAuthority", err)
	}

	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{
		"scan_completion_authorities",
		"scan_completion_authorities_scope_guard_v45",
		"scan_completion_authorities_application_guard_v45",
		"scan_sessions_record_completion_authority_v45",
		"scan_completion_authorities_no_update_v45",
		"scan_completion_authorities_no_delete_v45",
	} {
		var found bool
		if err := sqlitex.Execute(conn,
			"SELECT 1 FROM sqlite_master WHERE name=?1 AND type IN ('table','trigger')",
			&sqlitex.ExecOptions{Args: []any{name}, ResultFunc: func(*sqlite.Stmt) error {
				found = true
				return nil
			}}); err != nil {
			store.pool.Put(conn)
			t.Fatal(err)
		}
		if !found {
			store.pool.Put(conn)
			t.Fatalf("v44→v45 migration missing %s", name)
		}
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO scan_completion_authorities (scan_id) VALUES (?1)",
		&sqlitex.ExecOptions{Args: []any{string(first.ID)}}); err == nil {
		store.pool.Put(conn)
		t.Fatal("direct historical completion-authority insertion unexpectedly succeeded")
	}
	store.pool.Put(conn)

	third, err := store.StartScan(ctx, "localfs", "/root", at)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.CompleteScan(ctx, third.ID, at); err != nil {
		t.Fatal(err)
	}
	conn, err = store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	latest, found, err := latestCompleteScanID(conn, "localfs", "/root")
	store.pool.Put(conn)
	if err != nil {
		t.Fatal(err)
	}
	if !found || latest != third.ID {
		t.Fatalf("latest scan=%s found=%v want sequenced %s", latest, found, third.ID)
	}
}

func TestV45CompletionOrderIsImmutableAndMonotonic(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	at := time.Date(2026, 9, 28, 10, 5, 0, 0, time.UTC)

	var orders []int64
	for i := 0; i < 2; i++ {
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
		var order int64
		if err := sqlitex.Execute(conn,
			"SELECT completion_order FROM scan_completion_authorities WHERE scan_id=?1",
			&sqlitex.ExecOptions{Args: []any{string(scan.ID)}, ResultFunc: func(stmt *sqlite.Stmt) error {
				order = stmt.ColumnInt64(0)
				return nil
			}}); err != nil {
			store.pool.Put(conn)
			t.Fatal(err)
		}
		store.pool.Put(conn)
		orders = append(orders, order)
	}
	if orders[0] <= 0 || orders[1] <= orders[0] {
		t.Fatalf("completion orders=%v want strictly increasing", orders)
	}
}
