package ingest_test

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/ingest"
	"github.com/efremov-aleksei-96/keelaryn/internal/provider/localfs"
	sqlitestate "github.com/efremov-aleksei-96/keelaryn/internal/state/sqlite"
)

func TestBootstrapLocalFSAdoptsArtifactAndRevision(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	mustWrite(t, filepath.Join(root, "file.txt"), []byte("abc"))
	store := openStore(t)

	scan, err := ingest.BootstrapLocalFS(ctx, store, localfs.New("localfs"), root, fixedTime())
	if err != nil {
		t.Fatal(err)
	}
	inventory, err := store.Inventory(ctx, "localfs", scan.Root)
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory) != 1 {
		t.Fatalf("inventory=%#v", inventory)
	}
	entry := inventory[0]
	if entry.AssignmentState != corpus.AssignmentAssigned || entry.ArtifactID == "" || entry.RevisionID == "" {
		t.Fatalf("bootstrap did not assign Artifact/Revision: %#v", entry)
	}
	history, err := store.RevisionHistory(ctx, entry.ArtifactID)
	if err != nil {
		t.Fatal(err)
	}
	if len(history) != 1 || history[0].Revision.ID != entry.RevisionID {
		t.Fatalf("revision history=%#v", history)
	}
	if history[0].Evidence.Digest != "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad" {
		t.Fatalf("digest=%q", history[0].Evidence.Digest)
	}
}

func TestBootstrapLocalFSHardLinksShareArtifactAndRevision(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	original := filepath.Join(root, "original.bin")
	hardlink := filepath.Join(root, "hardlink.bin")
	mustWrite(t, original, []byte("abc"))
	if err := os.Link(original, hardlink); err != nil {
		t.Skipf("hard links unavailable: %v", err)
	}
	store := openStore(t)

	scan, err := ingest.BootstrapLocalFS(ctx, store, localfs.New("localfs"), root, fixedTime())
	if err != nil {
		t.Fatal(err)
	}
	inventory, err := store.Inventory(ctx, "localfs", scan.Root)
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory) != 2 {
		t.Fatalf("inventory=%#v", inventory)
	}
	if inventory[0].ObservationID != inventory[1].ObservationID ||
		inventory[0].ArtifactID != inventory[1].ArtifactID ||
		inventory[0].RevisionID != inventory[1].RevisionID {
		t.Fatalf("hard links split identity: %#v", inventory)
	}
}

func TestBootstrapLocalFSIdenticalCopiesGetDistinctArtifacts(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	content := []byte("same bytes")
	mustWrite(t, filepath.Join(root, "a.bin"), content)
	mustWrite(t, filepath.Join(root, "b.bin"), content)
	store := openStore(t)

	scan, err := ingest.BootstrapLocalFS(ctx, store, localfs.New("localfs"), root, fixedTime())
	if err != nil {
		t.Fatal(err)
	}
	inventory, err := store.Inventory(ctx, "localfs", scan.Root)
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory) != 2 {
		t.Fatalf("inventory=%#v", inventory)
	}
	if inventory[0].ArtifactID == inventory[1].ArtifactID {
		t.Fatal("byte-identical copies collapsed into one Artifact")
	}
	h0, err := store.RevisionHistory(ctx, inventory[0].ArtifactID)
	if err != nil {
		t.Fatal(err)
	}
	h1, err := store.RevisionHistory(ctx, inventory[1].ArtifactID)
	if err != nil {
		t.Fatal(err)
	}
	if h0[0].Evidence.Digest != h1[0].Evidence.Digest {
		t.Fatal("test files are not actually content-identical")
	}
}

func TestBootstrapLocalFSSymlinkGetsArtifactWithoutRevision(t *testing.T) {
	ctx := context.Background()
	base := t.TempDir()
	root := filepath.Join(base, "root")
	outside := filepath.Join(base, "outside.txt")
	if err := os.MkdirAll(root, 0o755); err != nil {
		t.Fatal(err)
	}
	mustWrite(t, outside, []byte("outside"))
	if err := os.Symlink(outside, filepath.Join(root, "link")); err != nil {
		t.Skipf("symlink unavailable: %v", err)
	}
	store := openStore(t)

	scan, err := ingest.BootstrapLocalFS(ctx, store, localfs.New("localfs"), root, fixedTime())
	if err != nil {
		t.Fatal(err)
	}
	inventory, err := store.Inventory(ctx, "localfs", scan.Root)
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory) != 1 {
		t.Fatalf("inventory=%#v", inventory)
	}
	if inventory[0].ArtifactID == "" || inventory[0].RevisionID != "" || inventory[0].Kind != corpus.EntrySymlink {
		t.Fatalf("symlink identity=%#v", inventory[0])
	}
}

func TestBootstrapLocalFSRefusesExistingObservationHistory(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	mustWrite(t, filepath.Join(root, "file.txt"), []byte("x"))
	store := openStore(t)
	provider := localfs.New("localfs")

	if _, err := ingest.BootstrapLocalFS(ctx, store, provider, root, fixedTime()); err != nil {
		t.Fatal(err)
	}
	_, err := ingest.BootstrapLocalFS(ctx, store, provider, root, fixedTime().Add(1))
	if !errors.Is(err, sqlitestate.ErrObservationHistoryExists) {
		t.Fatalf("error=%v, want ErrObservationHistoryExists", err)
	}
}

func TestLaterOrdinaryScanDoesNotAutoReuseBootstrapArtifact(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	mustWrite(t, filepath.Join(root, "file.txt"), []byte("same"))
	store := openStore(t)
	provider := localfs.New("localfs")

	first, err := ingest.BootstrapLocalFS(ctx, store, provider, root, fixedTime())
	if err != nil {
		t.Fatal(err)
	}
	firstInventory, err := store.Inventory(ctx, "localfs", first.Root)
	if err != nil {
		t.Fatal(err)
	}
	artifactID := firstInventory[0].ArtifactID

	second, err := ingest.LocalFS(ctx, store, provider, root, fixedTime().Add(1))
	if err != nil {
		t.Fatal(err)
	}
	secondInventory, err := store.Inventory(ctx, "localfs", second.Root)
	if err != nil {
		t.Fatal(err)
	}
	if len(secondInventory) != 1 || secondInventory[0].AssignmentState != corpus.AssignmentUnresolved || secondInventory[0].ArtifactID != "" {
		t.Fatalf("later scan guessed continuity: %#v", secondInventory)
	}
	locators, err := store.CurrentArtifactLocators(ctx, "localfs", second.Root, artifactID)
	if err != nil {
		t.Fatal(err)
	}
	if len(locators) != 0 {
		t.Fatalf("stale bootstrap Artifact locator survived unresolved scan: %#v", locators)
	}
}
