package sqlitestate

import (
	"context"
	"errors"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestRemoteManagedRootRejectsGenericComplete(t *testing.T) {
	ctx := context.Background()
	fixture, remoteScan, _ := qualifiedGoogleRemoteScan(t)
	store := fixture.store
	if _, _, err := store.CompleteRemoteHistoryScan(ctx, remoteScan.ID, fixture.base.Add(2*time.Minute)); err != nil {
		t.Fatal(err)
	}

	generic, err := store.StartScan(ctx, remoteScan.ProviderID, fixture.scanRoot, fixture.base.Add(3*time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	if err := store.CompleteScan(ctx, generic.ID, fixture.base.Add(4*time.Minute)); !errors.Is(err, ErrRemoteHistoryRootRequiresSourceBoundScan) {
		t.Fatalf("generic remote-root completion error=%v want ErrRemoteHistoryRootRequiresSourceBoundScan", err)
	}
	got, err := store.ScanSession(ctx, generic.ID)
	if err != nil {
		t.Fatal(err)
	}
	if got.Status != corpus.ScanOpen {
		t.Fatalf("rejected generic completion mutated scan: %#v", got)
	}

	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	err = sqlitex.Execute(conn,
		"UPDATE scan_sessions SET status='COMPLETE', finished_at=?1 WHERE scan_id=?2",
		&sqlitex.ExecOptions{Args: []any{
			fixture.base.Add(4 * time.Minute).Format(time.RFC3339Nano),
			string(generic.ID),
		}})
	store.pool.Put(conn)
	if err == nil {
		t.Fatal("direct SQL generic completion on remote-managed root unexpectedly succeeded")
	}
	if err := store.AbortScan(ctx, generic.ID, fixture.base.Add(5*time.Minute)); err != nil {
		t.Fatal(err)
	}
}

func TestCompletedRemoteSourceCannotBeDuplicatedByDirectSQL(t *testing.T) {
	ctx := context.Background()
	fixture, first, source := qualifiedGoogleRemoteScan(t)
	store := fixture.store
	if _, _, err := store.CompleteRemoteHistoryScan(ctx, first.ID, fixture.base.Add(2*time.Minute)); err != nil {
		t.Fatal(err)
	}

	bypass, err := store.StartScan(ctx, first.ProviderID, fixture.scanRoot, fixture.base.Add(3*time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	err = sqlitex.Execute(conn,
		"INSERT INTO remote_scan_sources (scan_id, generation_id, publication_sequence, source_scope_id, materialization_policy_id, snapshot_fingerprint_version, snapshot_fingerprint_sha256) VALUES (?1,?2,?3,?4,?5,?6,?7)",
		&sqlitex.ExecOptions{Args: []any{
			string(bypass.ID),
			string(source.GenerationID),
			int64(source.PublicationSequence),
			source.SourceScopeID,
			source.MaterializationPolicyID,
			source.SnapshotFingerprintVersion,
			source.SnapshotFingerprintSHA256,
		}})
	store.pool.Put(conn)
	if err == nil {
		t.Fatal("direct SQL duplicate of COMPLETE remote source unexpectedly succeeded")
	}
	if _, err := store.RemoteHistoryScanSource(ctx, bypass.ID); !errors.Is(err, ErrRemoteHistoryScanSourceNotFound) {
		t.Fatalf("rejected duplicate left source sidecar: %v", err)
	}
	if err := store.AbortScan(ctx, bypass.ID, fixture.base.Add(4*time.Minute)); err != nil {
		t.Fatal(err)
	}
}

func TestTerminalScanRejectsObservationAndLocatorAppend(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "state.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	base := time.Date(2026, 9, 27, 14, 0, 0, 0, time.UTC)
	scan, err := store.StartScan(ctx, "provider", "root", base)
	if err != nil {
		t.Fatal(err)
	}
	recorded, err := store.RecordObservationInScan(ctx, scan.ID, corpus.ObservationRecordInput{
		ProviderObject: corpus.ProviderObject{ProviderID: "provider", ID: "object-1", IdentityState: corpus.ObjectIdentityObserved},
		Locators: []corpus.Locator{{ProviderID: "provider", Root: "root", Path: "path-1"}},
		AssignmentState: corpus.AssignmentUnresolved,
		ObservedAt: base,
		Kind: corpus.EntryRegularFile,
		Size: corpus.KnownSize(1),
		Mode: corpus.KnownMode(0o600),
		ModifiedAt: corpus.KnownModifiedAt(base),
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := store.CompleteScan(ctx, scan.ID, base.Add(time.Second)); err != nil {
		t.Fatal(err)
	}

	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	errObservation := sqlitex.Execute(conn,
		"INSERT INTO observations (observation_id, occurrence_id, artifact_id, revision_id, assignment_state, observed_at, kind, size, mode, modified_at, scan_id) VALUES ('obs_after_complete', ?1, NULL, NULL, 'UNRESOLVED', ?2, 'REGULAR_FILE', 1, 384, ?2, ?3)",
		&sqlitex.ExecOptions{Args: []any{
			string(recorded.ProviderObjectOccurrenceID),
			base.Add(2 * time.Second).Format(time.RFC3339Nano),
			string(scan.ID),
		}})
	errLocator := sqlitex.Execute(conn,
		"INSERT INTO locators (locator_id, observation_id, provider_id, root, path) VALUES ('loc_after_complete', ?1, 'provider', 'root', 'path-2')",
		&sqlitex.ExecOptions{Args: []any{string(recorded.ID)}})
	store.pool.Put(conn)
	if errObservation == nil {
		t.Fatal("observation append after COMPLETE unexpectedly succeeded")
	}
	if errLocator == nil {
		t.Fatal("locator append after COMPLETE unexpectedly succeeded")
	}

	inventory, err := store.Inventory(ctx, "provider", "root")
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory) != 1 || inventory[0].ObservationID != recorded.ID || inventory[0].Locator.Path != "path-1" {
		t.Fatalf("terminal scan inventory mutated after rejected append: %#v", inventory)
	}
}
