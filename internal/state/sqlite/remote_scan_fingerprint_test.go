package sqlitestate

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestRemoteHistoryScanRejectsDifferentFingerprintAfterComplete(t *testing.T) {
	ctx := context.Background()
	fixture, scan, source := qualifiedGoogleRemoteScan(t)
	if _, _, err := fixture.store.CompleteRemoteHistoryScan(ctx, scan.ID, fixture.base.Add(2*time.Minute)); err != nil {
		t.Fatal(err)
	}

	conflict := source.RemoteScanSourceInput
	conflict.SnapshotFingerprintSHA256 = remoteScanFingerprintB
	if _, _, err := fixture.store.StartRemoteHistoryScan(
		ctx, fixture.scanRoot, conflict, fixture.base.Add(3*time.Minute),
	); !errors.Is(err, ErrRemoteHistoryScanSourceConflict) {
		t.Fatalf("different fingerprint after COMPLETE error=%v want ErrRemoteHistoryScanSourceConflict", err)
	}
}

func TestRemoteScanFingerprintConsistencySQLiteGuardRejectsDirectBypass(t *testing.T) {
	ctx := context.Background()
	fixture, first, source := qualifiedGoogleRemoteScan(t)
	store := fixture.store
	if _, _, err := store.CompleteRemoteHistoryScan(ctx, first.ID, fixture.base.Add(2*time.Minute)); err != nil {
		t.Fatal(err)
	}

	bypassScan, err := store.StartScan(ctx, first.ProviderID, fixture.scanRoot, fixture.base.Add(3*time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	conflict := source.RemoteScanSourceInput
	conflict.SnapshotFingerprintSHA256 = remoteScanFingerprintB

	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	err = sqlitex.Execute(conn,
		"INSERT INTO remote_scan_sources (scan_id, generation_id, publication_sequence, source_scope_id, materialization_policy_id, snapshot_fingerprint_version, snapshot_fingerprint_sha256) VALUES (?1,?2,?3,?4,?5,?6,?7)",
		&sqlitex.ExecOptions{Args: []any{
			string(bypassScan.ID),
			string(conflict.GenerationID),
			int64(conflict.PublicationSequence),
			conflict.SourceScopeID,
			conflict.MaterializationPolicyID,
			conflict.SnapshotFingerprintVersion,
			conflict.SnapshotFingerprintSHA256,
		}})
	store.pool.Put(conn)
	if err == nil {
		t.Fatal("direct conflicting remote scan source insert unexpectedly succeeded")
	}
	if _, err := store.RemoteHistoryScanSource(ctx, bypassScan.ID); !errors.Is(err, ErrRemoteHistoryScanSourceNotFound) {
		t.Fatalf("rejected direct insert left source sidecar: %v", err)
	}
	if err := store.AbortScan(ctx, bypassScan.ID, fixture.base.Add(4*time.Minute)); err != nil {
		t.Fatal(err)
	}
}
