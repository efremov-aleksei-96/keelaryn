package ingest_test

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/ingest"
	"github.com/efremov-aleksei-96/keelaryn/internal/provider/localfs"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory/gdrive"
	sqlitestate "github.com/efremov-aleksei-96/keelaryn/internal/state/sqlite"
)

func TestLocalFSBootstrapThenOrdinaryScanAtSameTimeUsesLaterCompletionAuthority(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "file.txt"), []byte("same"), 0o600); err != nil {
		t.Fatal(err)
	}
	store := openStore(t)
	provider := localfs.New("localfs")
	at := fixedTime()

	first, err := ingest.BootstrapLocalFS(ctx, store, provider, root, at)
	if err != nil {
		t.Fatal(err)
	}
	firstInventory, err := store.Inventory(ctx, "localfs", first.Root)
	if err != nil {
		t.Fatal(err)
	}
	if len(firstInventory) != 1 || firstInventory[0].ArtifactID == "" {
		t.Fatalf("bootstrap inventory=%#v", firstInventory)
	}
	bootstrapArtifact := firstInventory[0].ArtifactID

	second, err := ingest.LocalFS(ctx, store, provider, root, at)
	if err != nil {
		t.Fatal(err)
	}
	if second.ID == first.ID {
		t.Fatal("ordinary scan reused bootstrap scan identity")
	}
	inventory, err := store.Inventory(ctx, "localfs", second.Root)
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory) != 1 ||
		inventory[0].ScanID != second.ID ||
		inventory[0].AssignmentState != corpus.AssignmentUnresolved ||
		inventory[0].ArtifactID != "" {
		t.Fatalf("same-time later scan did not become current: %#v", inventory)
	}
	locators, err := store.CurrentArtifactLocators(ctx, "localfs", second.Root, bootstrapArtifact)
	if err != nil {
		t.Fatal(err)
	}
	if len(locators) != 0 {
		t.Fatalf("stale bootstrap Artifact remained current after same-time later scan: %#v", locators)
	}
}

func TestRemoteMetadataEqualTimeNewPublicationFailsClosed(t *testing.T) {
	ctx := context.Background()
	fixture := newGoogleRemoteFixture(t, "account-A", false)
	at := fixture.base.Add(time.Minute)
	baseline := fixture.snapshot(
		remoteMetadataEntry("managed", corpus.EntryOther, 0, 0, fixture.base),
		remoteMetadataEntry("child", corpus.EntryRegularFile, 7, 0, fixture.base.Add(time.Second)),
	)
	first, replayed, err := ingest.MaterializeRemoteMetadata(ctx, fixture.store, fixture.projection, baseline, at)
	if err != nil {
		t.Fatal(err)
	}
	if replayed {
		t.Fatal("first remote materialization unexpectedly replayed")
	}

	cycle := gdrive.ChangeCycleBundle{History: remotehistory.ChangeCycle{
		StreamID:       fixture.scope.StreamID,
		Status:         remotehistory.CycleComplete,
		PreviousCursor: "cursor-1",
		NextCursor:     "cursor-2",
		Coverage:       corpus.ProviderHistoryContinuous,
	}}
	if _, err := fixture.store.PublishGoogleDriveRemoteHistoryCycle(
		ctx,
		fixture.generation.ID,
		fixture.scope,
		fixture.scopeFingerprint,
		1,
		"cursor-1",
		cycle,
		at,
	); err != nil {
		t.Fatal(err)
	}

	changed := fixture.snapshot(
		remoteMetadataEntry("managed", corpus.EntryOther, 0, 0, fixture.base),
		remoteMetadataEntry("child", corpus.EntryRegularFile, 99, 0, fixture.base.Add(time.Second)),
	)
	changed.PublicationSequence = 2
	failed, _, err := ingest.MaterializeRemoteMetadata(ctx, fixture.store, fixture.projection, changed, at)
	if !errors.Is(err, sqlitestate.ErrRemoteHistoryScanCompletionNotNewest) {
		t.Fatalf("equal-time remote completion error=%v want ErrRemoteHistoryScanCompletionNotNewest", err)
	}
	if failed.ID == "" {
		t.Fatal("equal-time remote attempt did not establish a reconciliable scan")
	}

	inventory, err := fixture.store.Inventory(ctx, gdrive.ProviderID, fixture.scanRoot)
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory) != 2 {
		t.Fatalf("inventory=%#v", inventory)
	}
	for _, item := range inventory {
		if item.ScanID != first.ID {
			t.Fatalf("equal-time rejected remote attempt replaced current scan: %#v", item)
		}
		if item.Locator.Path == "file-id/child" && item.Size != 7 {
			t.Fatalf("equal-time rejected remote attempt leaked changed metadata: %#v", item)
		}
	}
}
