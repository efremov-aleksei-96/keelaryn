package sqlitestate

import (
	"context"
	"testing"
	"time"

	"zombiezen.com/go/sqlite/sqlitex"
)

func TestBootstrapScanAuthorityRejectsDirectSQLAndIsImmutable(t *testing.T) {
	ctx := context.Background()
	store := openInternalStore(t)
	at := time.Date(2026, 9, 27, 16, 0, 0, 0, time.UTC)

	normal, err := store.StartScan(ctx, "localfs", "/normal", at)
	if err != nil {
		t.Fatal(err)
	}
	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	err = sqlitex.Execute(conn,
		"INSERT INTO bootstrap_scan_authorities (scan_id, proof_kind, proven_at) VALUES (?1, ?2, ?3)",
		&sqlitex.ExecOptions{Args: []any{
			string(normal.ID),
			bootstrapNoPriorObservationHistoryProof,
			normal.StartedAt.Format(time.RFC3339Nano),
		}})
	store.pool.Put(conn)
	if err == nil {
		t.Fatal("direct bootstrap scan authority insert unexpectedly succeeded")
	}

	bootstrap, err := store.StartBootstrapScan(ctx, "localfs", "/bootstrap", at.Add(time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	conn, err = store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"UPDATE bootstrap_scan_authorities SET proven_at=proven_at WHERE scan_id=?1",
		&sqlitex.ExecOptions{Args: []any{string(bootstrap.ID)}}); err == nil {
		store.pool.Put(conn)
		t.Fatal("bootstrap scan authority update unexpectedly succeeded")
	}
	if err := sqlitex.Execute(conn,
		"DELETE FROM bootstrap_scan_authorities WHERE scan_id=?1",
		&sqlitex.ExecOptions{Args: []any{string(bootstrap.ID)}}); err == nil {
		store.pool.Put(conn)
		t.Fatal("bootstrap scan authority delete unexpectedly succeeded")
	}
	store.pool.Put(conn)
}
