package sqlitestate

import (
	"context"
	"errors"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestLocalAttemptStartReplayConflictAndGuardedAbort(t *testing.T) {
	ctx := context.Background()
	store := openLocalAttemptStore(t)
	predecessor := localAttemptBootstrapReceipt(t, store)
	started := predecessor.Scan.FinishedAt.Add(time.Minute)
	fingerprint := strings.Repeat("b", 64)

	first, replayed, err := store.StartLocalAttempt(
		ctx, predecessor, started, LocalAttemptSourceFingerprintVersion, fingerprint,
	)
	if err != nil {
		t.Fatal(err)
	}
	if replayed || first.Scan.Status != corpus.ScanOpen {
		t.Fatalf("first attempt=%#v replayed=%v", first, replayed)
	}

	second, replayed, err := store.StartLocalAttempt(
		ctx, predecessor, started, LocalAttemptSourceFingerprintVersion, fingerprint,
	)
	if err != nil {
		t.Fatal(err)
	}
	if !replayed || second.Scan.ID != first.Scan.ID {
		t.Fatalf("exact replay created a different attempt: first=%s second=%s replayed=%v", first.Scan.ID, second.Scan.ID, replayed)
	}

	if _, _, err := store.StartLocalAttempt(
		ctx, predecessor, started, LocalAttemptSourceFingerprintVersion, strings.Repeat("c", 64),
	); !errors.Is(err, ErrLocalAttemptReplayConflict) {
		t.Fatalf("conflicting replay error=%v, want ErrLocalAttemptReplayConflict", err)
	}

	if err := store.CompleteScan(ctx, first.Scan.ID, started.Add(time.Minute)); !errors.Is(err, ErrLocalAttemptRequiresGuardedCompletion) {
		t.Fatalf("generic complete error=%v, want guarded completion error", err)
	}
	if err := store.AbortScan(ctx, first.Scan.ID, started.Add(time.Minute)); !errors.Is(err, ErrLocalAttemptRequiresGuardedAbort) {
		t.Fatalf("generic abort error=%v, want guarded abort error", err)
	}

	aborted, replayed, err := store.AbortLocalAttempt(ctx, first.Scan.ID, started.Add(time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	if replayed || aborted.Scan.Status != corpus.ScanAborted {
		t.Fatalf("aborted attempt=%#v replayed=%v", aborted, replayed)
	}
	again, replayed, err := store.AbortLocalAttempt(ctx, first.Scan.ID, started.Add(time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	if !replayed || again.Scan.ID != first.Scan.ID {
		t.Fatalf("abort replay=%#v replayed=%v", again, replayed)
	}
	if _, _, err := store.StartLocalAttempt(
		ctx, predecessor, started, LocalAttemptSourceFingerprintVersion, fingerprint,
	); !errors.Is(err, ErrLocalAttemptReplayClosed) {
		t.Fatalf("closed replay error=%v, want ErrLocalAttemptReplayClosed", err)
	}

	next, replayed, err := store.StartLocalAttempt(
		ctx, predecessor, started.Add(2*time.Minute), LocalAttemptSourceFingerprintVersion, strings.Repeat("d", 64),
	)
	if err != nil {
		t.Fatal(err)
	}
	if replayed || next.Scan.ID == first.Scan.ID {
		t.Fatalf("fresh retry did not create a new OPEN attempt: %#v", next)
	}
}


func TestLocalAttemptRejectsNonLocalProviderReceipt(t *testing.T) {
	ctx := context.Background()
	store := openLocalAttemptStore(t)
	at := time.Date(2026, 10, 4, 10, 0, 0, 0, time.UTC)
	scan, err := store.CommitBootstrapLocalSnapshot(
		ctx, "other-provider", "/corpus", at,
		qualifiedLocalBootstrapFingerprintVersion, strings.Repeat("a", 64), nil,
		func(context.Context) error { return nil },
	)
	if err != nil {
		t.Fatal(err)
	}
	receipt, found, err := store.LocalIngestCommitAtBoundary(ctx, "other-provider", scan.Root, at, true)
	if err != nil {
		t.Fatal(err)
	}
	if !found {
		t.Fatal("other-provider bootstrap receipt not found")
	}
	if _, _, err := store.StartLocalAttempt(
		ctx, receipt, at.Add(time.Minute),
		LocalAttemptSourceFingerprintVersion, strings.Repeat("b", 64),
	); !errors.Is(err, ErrInvalidLocalAttemptSource) {
		t.Fatalf("non-LocalFS attempt error=%v, want ErrInvalidLocalAttemptSource", err)
	}
}

func TestLocalAttemptRejectsNonCurrentPredecessorAndRawSQLProvenance(t *testing.T) {
	ctx := context.Background()
	store := openLocalAttemptStore(t)
	predecessor := localAttemptBootstrapReceipt(t, store)
	started := predecessor.Scan.FinishedAt.Add(time.Minute)

	forged := predecessor
	forged.FingerprintSHA256 = strings.Repeat("f", 64)
	if _, _, err := store.StartLocalAttempt(
		ctx, forged, started, LocalAttemptSourceFingerprintVersion, strings.Repeat("b", 64),
	); !errors.Is(err, ErrLocalAttemptPredecessorNotCurrent) {
		t.Fatalf("forged predecessor error=%v, want ErrLocalAttemptPredecessorNotCurrent", err)
	}

	scan, err := store.StartScan(ctx, predecessor.Scan.ProviderID, predecessor.Scan.Root, started)
	if err != nil {
		t.Fatal(err)
	}
	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	err = sqlitex.Execute(conn, `
INSERT INTO local_attempt_sources (
	scan_id,provider_id,root,started_at,
	predecessor_scan_id,predecessor_started_at,
	predecessor_fingerprint_version,predecessor_fingerprint_sha256,
	snapshot_fingerprint_version,snapshot_fingerprint_sha256
) VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10)`, &sqlitex.ExecOptions{Args: []any{
		string(scan.ID), string(scan.ProviderID), scan.Root, scan.StartedAt.Format(time.RFC3339Nano),
		string(predecessor.Scan.ID), predecessor.Scan.StartedAt.Format(time.RFC3339Nano),
		predecessor.FingerprintVersion, predecessor.FingerprintSHA256,
		LocalAttemptSourceFingerprintVersion, strings.Repeat("b", 64),
	}})
	store.pool.Put(conn)
	if err == nil {
		t.Fatal("raw SQL minted local attempt provenance without application authority")
	}
	if err := store.AbortScan(ctx, scan.ID, started.Add(time.Minute)); err != nil {
		t.Fatal(err)
	}
}

func TestLocalAttemptHistoricalVerifierRejectsCorruptSourceVersion(t *testing.T) {
	ctx := context.Background()
	store := openLocalAttemptStore(t)
	predecessor := localAttemptBootstrapReceipt(t, store)
	started := predecessor.Scan.FinishedAt.Add(time.Minute)
	source, _, err := store.StartLocalAttempt(
		ctx, predecessor, started, LocalAttemptSourceFingerprintVersion, strings.Repeat("b", 64),
	)
	if err != nil {
		t.Fatal(err)
	}

	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.ExecuteTransient(conn, "DROP TRIGGER local_attempt_sources_no_update_v47", nil); err != nil {
		store.pool.Put(conn)
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"UPDATE local_attempt_sources SET snapshot_fingerprint_version='unsupported:v1' WHERE scan_id=?1",
		&sqlitex.ExecOptions{Args: []any{string(source.Scan.ID)}}); err != nil {
		store.pool.Put(conn)
		t.Fatal(err)
	}
	if err := verifyLocalAttemptHistoricalAuthorityConn(conn); !errors.Is(err, ErrInvalidLocalAttemptHistoricalAuthority) {
		store.pool.Put(conn)
		t.Fatalf("verify error=%v, want ErrInvalidLocalAttemptHistoricalAuthority", err)
	}
	store.pool.Put(conn)
}

func openLocalAttemptStore(t *testing.T) *Store {
	t.Helper()
	store, err := Open(context.Background(), filepath.Join(t.TempDir(), "state.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := store.Close(); err != nil {
			t.Error(err)
		}
	})
	return store
}

func localAttemptBootstrapReceipt(t *testing.T, store *Store) LocalIngestCommitReceipt {
	t.Helper()
	ctx := context.Background()
	at := time.Date(2026, 10, 4, 10, 0, 0, 0, time.UTC)
	scan, err := store.CommitBootstrapLocalSnapshot(
		ctx,
		"localfs",
		"/corpus",
		at,
		qualifiedLocalBootstrapFingerprintVersion,
		strings.Repeat("a", 64),
		nil,
		func(context.Context) error { return nil },
	)
	if err != nil {
		t.Fatal(err)
	}
	receipt, found, err := store.LocalIngestCommitAtBoundary(ctx, "localfs", scan.Root, at, true)
	if err != nil {
		t.Fatal(err)
	}
	if !found {
		t.Fatal("bootstrap receipt not found")
	}
	return receipt
}

func TestLocalAttemptSourceTableRejectsMutation(t *testing.T) {
	ctx := context.Background()
	store := openLocalAttemptStore(t)
	predecessor := localAttemptBootstrapReceipt(t, store)
	source, _, err := store.StartLocalAttempt(
		ctx,
		predecessor,
		predecessor.Scan.FinishedAt.Add(time.Minute),
		LocalAttemptSourceFingerprintVersion,
		strings.Repeat("b", 64),
	)
	if err != nil {
		t.Fatal(err)
	}
	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer store.pool.Put(conn)
	if err := sqlitex.Execute(conn,
		"UPDATE local_attempt_sources SET snapshot_fingerprint_sha256=?1 WHERE scan_id=?2",
		&sqlitex.ExecOptions{Args: []any{strings.Repeat("c", 64), string(source.Scan.ID)}}); err == nil {
		t.Fatal("immutable local attempt source accepted UPDATE")
	}
	if err := sqlitex.Execute(conn,
		"DELETE FROM local_attempt_sources WHERE scan_id=?1",
		&sqlitex.ExecOptions{Args: []any{string(source.Scan.ID)}}); err == nil {
		t.Fatal("immutable local attempt source accepted DELETE")
	}
}

var _ = sqlite.OpenReadOnly
