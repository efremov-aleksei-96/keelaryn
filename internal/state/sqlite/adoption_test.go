package sqlitestate_test

import (
	"context"
	"errors"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	sqlitestate "github.com/efremov-aleksei-96/keelaryn/internal/state/sqlite"
)

func TestStartBootstrapScanRefusesObservationHistory(t *testing.T) {
	ctx := context.Background()
	store := openStore(t)
	at := fixedScanTime()

	first, err := store.StartBootstrapScan(ctx, "localfs", "/corpus", at)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.RecordObservationInScan(ctx, first.ID, unresolvedScanObservation("file.txt", at)); err != nil {
		t.Fatal(err)
	}
	if err := store.AbortScan(ctx, first.ID, at); err != nil {
		t.Fatal(err)
	}

	_, err = store.StartBootstrapScan(ctx, "localfs", "/corpus", at.Add(1))
	if !errors.Is(err, sqlitestate.ErrObservationHistoryExists) {
		t.Fatalf("error=%v, want ErrObservationHistoryExists", err)
	}
}

func TestAdoptObservationInScanIsAtomicPerOccurrence(t *testing.T) {
	ctx := context.Background()
	store := openStore(t)
	at := fixedScanTime()

	scan, err := store.StartBootstrapScan(ctx, "localfs", "/corpus", at)
	if err != nil {
		t.Fatal(err)
	}
	input := unresolvedScanObservation("file.txt", at)
	evidence := corpus.ContentEvidence{
		Algorithm: corpus.ContentAlgorithmSHA256,
		Digest:    "abc",
		Size:      input.Size + 1,
	}
	_, err = store.AdoptObservationInScan(ctx, scan.ID, input, &evidence)
	if !errors.Is(err, sqlitestate.ErrInvalidObservation) {
		t.Fatalf("error=%v, want ErrInvalidObservation", err)
	}

	inventory, err := store.Inventory(ctx, "localfs", "/corpus")
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory) != 0 {
		t.Fatalf("OPEN bootstrap affected inventory: %#v", inventory)
	}

	valid := corpus.ContentEvidence{
		Algorithm: corpus.ContentAlgorithmSHA256,
		Digest:    "abcd",
		Size:      input.Size,
	}
	record, err := store.AdoptObservationInScan(ctx, scan.ID, input, &valid)
	if err != nil {
		t.Fatal(err)
	}
	if record.ArtifactID == "" || record.RevisionID == "" || record.AssignmentState != corpus.AssignmentAssigned {
		t.Fatalf("adopted record=%#v", record)
	}
}

func fixedScanTime() time.Time {
	return time.Date(2026, 9, 25, 9, 0, 0, 0, time.UTC)
}
