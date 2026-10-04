package sqlitestate

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
)

func TestLatestBootstrapLocalIngestCommitIgnoresLaterScanAndOrdersEmptyBootstraps(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	base := time.Date(2026, 10, 4, 12, 0, 0, 0, time.UTC)
	validate := func(context.Context) error { return nil }

	first, err := store.CommitBootstrapLocalSnapshot(
		ctx, "localfs", "/root", base, "localfs-snapshot:v1", strings.Repeat("a", 64), nil, validate,
	)
	if err != nil {
		t.Fatal(err)
	}
	second, err := store.CommitBootstrapLocalSnapshot(
		ctx, "localfs", "/root", base.Add(time.Minute), "localfs-snapshot:v1", strings.Repeat("b", 64), nil, validate,
	)
	if err != nil {
		t.Fatal(err)
	}
	if first.ID == second.ID {
		t.Fatal("empty bootstrap replay unexpectedly reused a different boundary")
	}
	unsupported, err := store.CommitBootstrapLocalSnapshot(
		ctx, "localfs", "/root", base.Add(2*time.Minute), "localfs-snapshot:future", strings.Repeat("c", 64), nil, validate,
	)
	if err != nil {
		t.Fatal(err)
	}
	ordinary, err := store.CommitLocalSnapshot(
		ctx, "localfs", "/root", base.Add(3*time.Minute), "localfs-snapshot:v1", strings.Repeat("d", 64), nil, validate,
	)
	if err != nil {
		t.Fatal(err)
	}

	receipt, found, err := store.LatestBootstrapLocalIngestCommit(ctx, "localfs", "/root", "localfs-snapshot:v1")
	if err != nil {
		t.Fatal(err)
	}
	if !found || !receipt.Bootstrap || receipt.Scan.ID != second.ID {
		t.Fatalf("qualified bootstrap receipt=%#v found=%v want second=%s unsupported=%s", receipt, found, second.ID, unsupported.ID)
	}
	latest, found, err := store.LatestCompleteScan(ctx, "localfs", "/root")
	if err != nil {
		t.Fatal(err)
	}
	if !found || latest.ID != ordinary.ID {
		t.Fatalf("generic latest=%#v found=%v want ordinary=%s", latest, found, ordinary.ID)
	}
}

func TestInventoryAtScanPreservesHistoricalAcceptedInventory(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	base := time.Date(2026, 10, 4, 12, 10, 0, 0, time.UTC)
	validate := func(context.Context) error { return nil }
	bootstrapInput := corpus.BootstrapObservationInput{Observation: corpus.ObservationRecordInput{
		ProviderObject: corpus.ProviderObject{ProviderID: "localfs", IdentityState: corpus.ObjectIdentityUnresolved},
		Locators: []corpus.Locator{{ProviderID: "localfs", Root: "/root", Path: "file.bin"}},
		AssignmentState: corpus.AssignmentUnresolved,
		ObservedAt: base,
		Kind: corpus.EntryOther,
		Size: corpus.KnownSize(0),
		Mode: corpus.KnownMode(0o600),
		ModifiedAt: corpus.KnownModifiedAt(base),
	}}
	bootstrap, err := store.CommitBootstrapLocalSnapshot(
		ctx, "localfs", "/root", base, "localfs-snapshot:v1", strings.Repeat("d", 64),
		[]corpus.BootstrapObservationInput{bootstrapInput}, validate,
	)
	if err != nil {
		t.Fatal(err)
	}
	laterAt := base.Add(time.Minute)
	unresolved := bootstrapInput.Observation
	unresolved.ObservedAt = laterAt
	later, err := store.CommitLocalSnapshot(
		ctx, "localfs", "/root", laterAt, "localfs-snapshot:v1", strings.Repeat("e", 64),
		[]corpus.ObservationRecordInput{unresolved}, validate,
	)
	if err != nil {
		t.Fatal(err)
	}

	current, err := store.Inventory(ctx, "localfs", "/root")
	if err != nil {
		t.Fatal(err)
	}
	if len(current) != 1 || current[0].ScanID != later.ID || current[0].AssignmentState != corpus.AssignmentUnresolved {
		t.Fatalf("generic current inventory=%#v", current)
	}
	accepted, err := store.InventoryAtScan(ctx, bootstrap.ID)
	if err != nil {
		t.Fatal(err)
	}
	if len(accepted) != 1 || accepted[0].ScanID != bootstrap.ID ||
		accepted[0].AssignmentState != corpus.AssignmentAssigned || accepted[0].ArtifactID == "" {
		t.Fatalf("bootstrap inventory=%#v", accepted)
	}

	open, err := store.StartScan(ctx, "localfs", "/other", laterAt.Add(time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.InventoryAtScan(ctx, open.ID); !errors.Is(err, ErrScanNotComplete) {
		t.Fatalf("OPEN exact inventory error=%v want ErrScanNotComplete", err)
	}
}
