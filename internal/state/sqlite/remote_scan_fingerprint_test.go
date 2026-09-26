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
	store := openStoreInternal(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")
	base := time.Date(2026, 9, 27, 9, 0, 0, 0, time.UTC)
	generation, err := store.StartRemoteHistoryGeneration(
		ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), base,
	)
	if err != nil {
		t.Fatal(err)
	}
	scanRoot := "drive:user-1:managed:fingerprint-consistency"
	sourceA := remoteScanSourceInput(generation.ID, 1, "managed-consistency", remoteScanFingerprintA)
	scan, replayed, err := store.StartRemoteHistoryScan(ctx, scanRoot, sourceA, base.Add(time.Second))
	if err != nil {
		t.Fatal(err)
	}
	if replayed {
		t.Fatal("new scan unexpectedly replayed")
	}
	if _, _, err := store.CompleteRemoteHistoryScan(ctx, scan.ID, base.Add(2*time.Second)); err != nil {
		t.Fatal(err)
	}

	sourceB := remoteScanSourceInput(generation.ID, 1, "managed-consistency", remoteScanFingerprintB)
	if _, _, err := store.StartRemoteHistoryScan(ctx, scanRoot, sourceB, base.Add(3*time.Second)); !errors.Is(err, ErrRemoteHistoryScanSourceConflict) {
		t.Fatalf("different fingerprint after COMPLETE error=%v want ErrRemoteHistoryScanSourceConflict", err)
	}
}

func TestRemoteScanFingerprintConsistencySQLiteGuardRejectsDirectBypass(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")
	base := time.Date(2026, 9, 27, 10, 0, 0, 0, time.UTC)
	generation, err := store.StartRemoteHistoryGeneration(
		ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), base,
	)
	if err != nil {
		t.Fatal(err)
	}
	scanRoot := "drive:user-1:managed:fingerprint-sqlite"
	sourceA := remoteScanSourceInput(generation.ID, 1, "managed-sqlite", remoteScanFingerprintA)
	first, _, err := store.StartRemoteHistoryScan(ctx, scanRoot, sourceA, base.Add(time.Second))
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err := store.CompleteRemoteHistoryScan(ctx, first.ID, base.Add(2*time.Second)); err != nil {
		t.Fatal(err)
	}

	bypassScan, err := store.StartScan(ctx, scope.ProviderID, scanRoot, base.Add(3*time.Second))
	if err != nil {
		t.Fatal(err)
	}
	sourceB := remoteScanSourceInput(generation.ID, 1, "managed-sqlite", remoteScanFingerprintB)

	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	err = sqlitex.Execute(conn,
		"INSERT INTO remote_scan_sources (scan_id, generation_id, publication_sequence, source_scope_id, materialization_policy_id, snapshot_fingerprint_version, snapshot_fingerprint_sha256) VALUES (?1,?2,?3,?4,?5,?6,?7)",
		&sqlitex.ExecOptions{Args: []any{
			string(bypassScan.ID),
			string(sourceB.GenerationID),
			int64(sourceB.PublicationSequence),
			sourceB.SourceScopeID,
			sourceB.MaterializationPolicyID,
			sourceB.SnapshotFingerprintVersion,
			sourceB.SnapshotFingerprintSHA256,
		}})
	store.pool.Put(conn)
	if err == nil {
		t.Fatal("direct conflicting remote scan source insert unexpectedly succeeded")
	}
	if _, err := store.RemoteHistoryScanSource(ctx, bypassScan.ID); !errors.Is(err, ErrRemoteHistoryScanSourceNotFound) {
		t.Fatalf("rejected direct insert left source sidecar: %v", err)
	}
	if err := store.AbortScan(ctx, bypassScan.ID, base.Add(4*time.Second)); err != nil {
		t.Fatal(err)
	}
}
