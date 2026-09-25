package sqlitestate_test

import (
	"context"
	"errors"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	sqlitestate "github.com/efremov-aleksei-96/keelaryn/internal/state/sqlite"
)

func TestOpenScanDoesNotChangeInventory(t *testing.T) {
	ctx := context.Background()
	store := openStore(t)
	artifact := mustArtifact(t, store)
	base := time.Date(2026, 9, 25, 4, 0, 0, 0, time.UTC)

	first := mustStartScan(t, store, "localfs", "/corpus", base)
	mustRecordAssigned(t, store, first.ID, artifact.ID, "old.txt", base)
	if err := store.CompleteScan(ctx, first.ID, base.Add(time.Minute)); err != nil {
		t.Fatal(err)
	}

	open := mustStartScan(t, store, "localfs", "/corpus", base.Add(2*time.Minute))
	if _, err := store.RecordObservationInScan(ctx, open.ID, unresolvedScanObservation("new.txt", base.Add(2*time.Minute))); err != nil {
		t.Fatal(err)
	}

	inventory, err := store.Inventory(ctx, "localfs", "/corpus")
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory) != 1 || inventory[0].Locator.Path != "old.txt" {
		t.Fatalf("OPEN scan changed inventory: %#v", inventory)
	}
	locators, err := store.CurrentArtifactLocators(ctx, "localfs", "/corpus", artifact.ID)
	if err != nil {
		t.Fatal(err)
	}
	if len(locators) != 1 || locators[0].Path != "old.txt" {
		t.Fatalf("OPEN scan changed current locator: %#v", locators)
	}
}

func TestAbortedScanDoesNotChangeInventory(t *testing.T) {
	ctx := context.Background()
	store := openStore(t)
	artifact := mustArtifact(t, store)
	base := time.Date(2026, 9, 25, 5, 0, 0, 0, time.UTC)

	first := mustStartScan(t, store, "localfs", "/corpus", base)
	mustRecordAssigned(t, store, first.ID, artifact.ID, "old.txt", base)
	if err := store.CompleteScan(ctx, first.ID, base.Add(time.Minute)); err != nil {
		t.Fatal(err)
	}

	next := mustStartScan(t, store, "localfs", "/corpus", base.Add(2*time.Minute))
	if _, err := store.RecordObservationInScan(ctx, next.ID, unresolvedScanObservation("partial.txt", base.Add(2*time.Minute))); err != nil {
		t.Fatal(err)
	}
	if err := store.AbortScan(ctx, next.ID, base.Add(3*time.Minute)); err != nil {
		t.Fatal(err)
	}

	inventory, err := store.Inventory(ctx, "localfs", "/corpus")
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory) != 1 || inventory[0].Locator.Path != "old.txt" {
		t.Fatalf("ABORTED scan changed inventory: %#v", inventory)
	}
}

func TestLatestCompleteScanReplacesInventoryAndClearsStaleArtifactLocator(t *testing.T) {
	ctx := context.Background()
	store := openStore(t)
	artifact := mustArtifact(t, store)
	base := time.Date(2026, 9, 25, 6, 0, 0, 0, time.UTC)

	first := mustStartScan(t, store, "localfs", "/corpus", base)
	mustRecordAssigned(t, store, first.ID, artifact.ID, "old.txt", base)
	if err := store.CompleteScan(ctx, first.ID, base.Add(time.Minute)); err != nil {
		t.Fatal(err)
	}

	second := mustStartScan(t, store, "localfs", "/corpus", base.Add(2*time.Minute))
	if _, err := store.RecordObservationInScan(ctx, second.ID, unresolvedScanObservation("old.txt", base.Add(2*time.Minute))); err != nil {
		t.Fatal(err)
	}
	if err := store.CompleteScan(ctx, second.ID, base.Add(3*time.Minute)); err != nil {
		t.Fatal(err)
	}

	inventory, err := store.Inventory(ctx, "localfs", "/corpus")
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory) != 1 || inventory[0].Locator.Path != "old.txt" || inventory[0].AssignmentState != corpus.AssignmentUnresolved {
		t.Fatalf("latest COMPLETE inventory=%#v", inventory)
	}
	locators, err := store.CurrentArtifactLocators(ctx, "localfs", "/corpus", artifact.ID)
	if err != nil {
		t.Fatal(err)
	}
	if len(locators) != 0 {
		t.Fatalf("stale Artifact locator survived newer unresolved COMPLETE scan: %#v", locators)
	}
}

func TestEmptyCompleteScanMeansEmptyInventory(t *testing.T) {
	ctx := context.Background()
	store := openStore(t)
	artifact := mustArtifact(t, store)
	base := time.Date(2026, 9, 25, 7, 0, 0, 0, time.UTC)

	first := mustStartScan(t, store, "localfs", "/corpus", base)
	mustRecordAssigned(t, store, first.ID, artifact.ID, "old.txt", base)
	if err := store.CompleteScan(ctx, first.ID, base.Add(time.Minute)); err != nil {
		t.Fatal(err)
	}

	second := mustStartScan(t, store, "localfs", "/corpus", base.Add(2*time.Minute))
	if err := store.CompleteScan(ctx, second.ID, base.Add(3*time.Minute)); err != nil {
		t.Fatal(err)
	}

	inventory, err := store.Inventory(ctx, "localfs", "/corpus")
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory) != 0 {
		t.Fatalf("empty COMPLETE scan did not clear inventory: %#v", inventory)
	}
	locators, err := store.CurrentArtifactLocators(ctx, "localfs", "/corpus", artifact.ID)
	if err != nil {
		t.Fatal(err)
	}
	if len(locators) != 0 {
		t.Fatalf("empty COMPLETE scan did not clear current locator: %#v", locators)
	}
}

func TestObservationCannotBeAddedAfterScanComplete(t *testing.T) {
	ctx := context.Background()
	store := openStore(t)
	base := time.Date(2026, 9, 25, 8, 0, 0, 0, time.UTC)
	scan := mustStartScan(t, store, "localfs", "/corpus", base)
	if err := store.CompleteScan(ctx, scan.ID, base.Add(time.Minute)); err != nil {
		t.Fatal(err)
	}

	_, err := store.RecordObservationInScan(ctx, scan.ID, unresolvedScanObservation("late.txt", base.Add(2*time.Minute)))
	if !errors.Is(err, sqlitestate.ErrScanNotOpen) {
		t.Fatalf("error=%v, want ErrScanNotOpen", err)
	}
}

func TestOnlyOneOpenScanPerProviderRoot(t *testing.T) {
	ctx := context.Background()
	store := openStore(t)
	base := time.Date(2026, 9, 25, 9, 0, 0, 0, time.UTC)
	first := mustStartScan(t, store, "localfs", "/corpus", base)

	if _, err := store.StartScan(ctx, "localfs", "/corpus", base.Add(time.Minute)); err == nil {
		t.Fatal("second OPEN scan for same provider/root unexpectedly succeeded")
	}
	if err := store.AbortScan(ctx, first.ID, base.Add(2*time.Minute)); err != nil {
		t.Fatal(err)
	}
	if _, err := store.StartScan(ctx, "localfs", "/corpus", base.Add(3*time.Minute)); err != nil {
		t.Fatalf("new scan after abort: %v", err)
	}
}

func TestScanEnforcesProviderAndRootScope(t *testing.T) {
	ctx := context.Background()
	store := openStore(t)
	base := time.Date(2026, 9, 25, 10, 0, 0, 0, time.UTC)
	scan := mustStartScan(t, store, "localfs", "/corpus", base)

	wrongProvider := unresolvedScanObservation("file.txt", base)
	wrongProvider.ProviderObject.ProviderID = "drive"
	wrongProvider.Locators[0].ProviderID = "drive"
	if _, err := store.RecordObservationInScan(ctx, scan.ID, wrongProvider); !errors.Is(err, sqlitestate.ErrScanScopeMismatch) {
		t.Fatalf("provider mismatch error=%v", err)
	}

	wrongRoot := unresolvedScanObservation("file.txt", base)
	wrongRoot.Locators[0].Root = "/other"
	if _, err := store.RecordObservationInScan(ctx, scan.ID, wrongRoot); !errors.Is(err, sqlitestate.ErrScanScopeMismatch) {
		t.Fatalf("root mismatch error=%v", err)
	}
}

func TestScanAndInventorySurviveReopen(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "state.db")
	store, err := sqlitestate.Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	base := time.Date(2026, 9, 25, 11, 0, 0, 0, time.UTC)
	scan := mustStartScan(t, store, "localfs", "/corpus", base)
	if _, err := store.RecordObservationInScan(ctx, scan.ID, unresolvedScanObservation("file.txt", base)); err != nil {
		t.Fatal(err)
	}
	if err := store.CompleteScan(ctx, scan.ID, base.Add(time.Minute)); err != nil {
		t.Fatal(err)
	}
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}

	store, err = sqlitestate.Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	gotScan, err := store.ScanSession(ctx, scan.ID)
	if err != nil {
		t.Fatal(err)
	}
	if gotScan.Status != corpus.ScanComplete {
		t.Fatalf("status=%q, want COMPLETE", gotScan.Status)
	}
	inventory, err := store.Inventory(ctx, "localfs", "/corpus")
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory) != 1 || inventory[0].Locator.Path != "file.txt" {
		t.Fatalf("inventory after reopen=%#v", inventory)
	}
}

func TestDifferentRootsHaveIndependentAuthority(t *testing.T) {
	ctx := context.Background()
	store := openStore(t)
	base := time.Date(2026, 9, 25, 12, 0, 0, 0, time.UTC)

	a := mustStartScan(t, store, "localfs", "/a", base)
	inputA := unresolvedScanObservation("a.txt", base)
	inputA.Locators[0].Root = "/a"
	if _, err := store.RecordObservationInScan(ctx, a.ID, inputA); err != nil {
		t.Fatal(err)
	}
	if err := store.CompleteScan(ctx, a.ID, base.Add(time.Minute)); err != nil {
		t.Fatal(err)
	}

	b := mustStartScan(t, store, "localfs", "/b", base.Add(2*time.Minute))
	inputB := unresolvedScanObservation("b.txt", base.Add(2*time.Minute))
	inputB.Locators[0].Root = "/b"
	if _, err := store.RecordObservationInScan(ctx, b.ID, inputB); err != nil {
		t.Fatal(err)
	}
	if err := store.CompleteScan(ctx, b.ID, base.Add(3*time.Minute)); err != nil {
		t.Fatal(err)
	}

	invA, err := store.Inventory(ctx, "localfs", "/a")
	if err != nil {
		t.Fatal(err)
	}
	invB, err := store.Inventory(ctx, "localfs", "/b")
	if err != nil {
		t.Fatal(err)
	}
	if len(invA) != 1 || invA[0].Locator.Path != "a.txt" || len(invB) != 1 || invB[0].Locator.Path != "b.txt" {
		t.Fatalf("independent roots broken: A=%#v B=%#v", invA, invB)
	}
}

func mustStartScan(t *testing.T, store *sqlitestate.Store, providerID corpus.ProviderID, root string, at time.Time) corpus.ScanSession {
	t.Helper()
	scan, err := store.StartScan(context.Background(), providerID, root, at)
	if err != nil {
		t.Fatal(err)
	}
	return scan
}

func mustArtifact(t *testing.T, store *sqlitestate.Store) corpus.Artifact {
	t.Helper()
	artifact, err := store.AdoptArtifact(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	return artifact
}

func mustRecordAssigned(t *testing.T, store *sqlitestate.Store, scanID corpus.ScanSessionID, artifactID corpus.ArtifactID, path string, at time.Time) corpus.ObservationRecord {
	t.Helper()
	input := unresolvedScanObservation(path, at)
	input.ArtifactID = artifactID
	input.AssignmentState = corpus.AssignmentAssigned
	record, err := store.RecordObservationInScan(context.Background(), scanID, input)
	if err != nil {
		t.Fatal(err)
	}
	return record
}

func unresolvedScanObservation(path string, at time.Time) corpus.ObservationRecordInput {
	return corpus.ObservationRecordInput{
		ProviderObject: corpus.ProviderObject{
			ProviderID:    "localfs",
			IdentityState: corpus.ObjectIdentityUnresolved,
		},
		Locators: []corpus.Locator{{
			ProviderID: "localfs",
			Root:       "/corpus",
			Path:       path,
		}},
		AssignmentState: corpus.AssignmentUnresolved,
		ObservedAt:      at,
		Kind:            corpus.EntryRegularFile,
		Size:            4,
		Mode:            0o600,
		ModifiedAt:      at.Add(-time.Minute),
	}
}
