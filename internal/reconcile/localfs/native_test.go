package localfs_test

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	reconcilelocalfs "github.com/efremov-aleksei-96/keelaryn/internal/reconcile/localfs"
	providerlocalfs "github.com/efremov-aleksei-96/keelaryn/internal/provider/localfs"
)

func TestNativeRenameDiscoversPriorArtifactButRemainsAmbiguous(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	oldPath := filepath.Join(root, "before.txt")
	newPath := filepath.Join(root, "after.txt")
	writeFile(t, oldPath, []byte("same"))

	store := openState(t)
	provider := providerlocalfs.New("localfs")
	previous, err := provider.Snapshot(ctx, root)
	if err != nil {
		t.Fatal(err)
	}
	at := time.Date(2026, 9, 25, 13, 0, 0, 0, time.UTC)
	adoptSnapshot(t, store, previous, at)
	prior, err := store.Inventory(ctx, "localfs", previous.Root())
	if err != nil {
		t.Fatal(err)
	}
	priorArtifact := prior[0].ArtifactID

	if err := os.Rename(oldPath, newPath); err != nil {
		t.Fatal(err)
	}
	current, err := provider.Snapshot(ctx, root)
	if err != nil {
		t.Fatal(err)
	}
	base, err := reconcilelocalfs.Candidates(ctx, store, current)
	if err != nil {
		t.Fatal(err)
	}
	if len(base) != 1 || base[0].Resolution.State != corpus.CandidateSetUnresolved {
		t.Fatalf("locator-only rename unexpectedly had candidate: %#v", base)
	}

	enriched, err := reconcilelocalfs.EnrichNativeCandidates(previous, current, prior, base)
	if err != nil {
		t.Fatal(err)
	}
	if len(enriched) != 1 || len(enriched[0].Inputs) != 1 {
		t.Fatalf("native rename candidate=%#v", enriched)
	}
	if enriched[0].Inputs[0].ArtifactID != priorArtifact {
		t.Fatalf("candidate=%q, want %q", enriched[0].Inputs[0].ArtifactID, priorArtifact)
	}
	if enriched[0].Resolution.State != corpus.CandidateSetAmbiguous || enriched[0].Resolution.SelectedArtifactID != "" {
		t.Fatalf("native match resolved identity: %#v", enriched[0].Resolution)
	}
	signal := enriched[0].Inputs[0].Evidence[0]
	if signal.Strength != corpus.EvidenceSupporting || signal.Direction != corpus.DirectionSupportsSame {
		t.Fatalf("native signal=%#v", signal)
	}
}

func TestDeleteRecreateNeverResolvesFromNativeEvidence(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	path := filepath.Join(root, "file.txt")
	writeFile(t, path, []byte("old"))

	store := openState(t)
	provider := providerlocalfs.New("localfs")
	previous, err := provider.Snapshot(ctx, root)
	if err != nil {
		t.Fatal(err)
	}
	at := time.Date(2026, 9, 25, 14, 0, 0, 0, time.UTC)
	adoptSnapshot(t, store, previous, at)
	prior, err := store.Inventory(ctx, "localfs", previous.Root())
	if err != nil {
		t.Fatal(err)
	}

	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	writeFile(t, path, []byte("new"))
	current, err := provider.Snapshot(ctx, root)
	if err != nil {
		t.Fatal(err)
	}
	base, err := reconcilelocalfs.Candidates(ctx, store, current)
	if err != nil {
		t.Fatal(err)
	}
	enriched, err := reconcilelocalfs.EnrichNativeCandidates(previous, current, prior, base)
	if err != nil {
		t.Fatal(err)
	}
	if len(enriched) != 1 {
		t.Fatalf("enriched=%#v", enriched)
	}
	if enriched[0].Resolution.State == corpus.CandidateSetResolvedSame || enriched[0].Resolution.SelectedArtifactID != "" {
		t.Fatalf("delete+recreate was falsely resolved: %#v", enriched[0].Resolution)
	}
}

func TestNativeHardLinkGroupPreservesMultiplePriorArtifacts(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	a := filepath.Join(root, "a.bin")
	b := filepath.Join(root, "b.bin")
	writeFile(t, a, []byte("same object"))
	if err := os.Link(a, b); err != nil {
		t.Skipf("hard links unavailable: %v", err)
	}

	store := openState(t)
	provider := providerlocalfs.New("localfs")
	previous, err := provider.Snapshot(ctx, root)
	if err != nil {
		t.Fatal(err)
	}
	at := time.Date(2026, 9, 25, 15, 0, 0, 0, time.UTC)
	// Test helper deliberately assigns each locator a different Artifact,
	// while the Snapshot correctly knows both locators are one physical object.
	adoptSnapshot(t, store, previous, at)
	prior, err := store.Inventory(ctx, "localfs", previous.Root())
	if err != nil {
		t.Fatal(err)
	}
	if len(prior) != 2 || prior[0].ArtifactID == prior[1].ArtifactID {
		t.Fatalf("test setup did not create two prior Artifacts: %#v", prior)
	}

	current, err := provider.Snapshot(ctx, root)
	if err != nil {
		t.Fatal(err)
	}
	base, err := reconcilelocalfs.Candidates(ctx, store, current)
	if err != nil {
		t.Fatal(err)
	}
	enriched, err := reconcilelocalfs.EnrichNativeCandidates(previous, current, prior, base)
	if err != nil {
		t.Fatal(err)
	}
	if len(enriched) != 1 || len(enriched[0].Inputs) != 2 {
		t.Fatalf("multiple prior mappings were lost: %#v", enriched)
	}
	if enriched[0].Resolution.State != corpus.CandidateSetAmbiguous {
		t.Fatalf("multiple native candidates resolved: %#v", enriched[0].Resolution)
	}
}

func TestNativeBindingRejectsDifferentSnapshotScope(t *testing.T) {
	previousRoot := t.TempDir()
	currentRoot := t.TempDir()
	writeFile(t, filepath.Join(previousRoot, "file.txt"), []byte("x"))
	writeFile(t, filepath.Join(currentRoot, "file.txt"), []byte("x"))

	provider := providerlocalfs.New("localfs")
	previous, err := provider.Snapshot(context.Background(), previousRoot)
	if err != nil {
		t.Fatal(err)
	}
	current, err := provider.Snapshot(context.Background(), currentRoot)
	if err != nil {
		t.Fatal(err)
	}
	_, err = reconcilelocalfs.EnrichNativeCandidates(previous, current, nil, nil)
	if !errors.Is(err, reconcilelocalfs.ErrInvalidNativeSnapshotBinding) {
		t.Fatalf("error=%v, want ErrInvalidNativeSnapshotBinding", err)
	}
}

func TestNativeBindingRejectsInventoryNotMatchingPreviousSnapshot(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	path := filepath.Join(root, "file.txt")
	writeFile(t, path, []byte("x"))
	store := openState(t)
	provider := providerlocalfs.New("localfs")
	previous, err := provider.Snapshot(ctx, root)
	if err != nil {
		t.Fatal(err)
	}
	at := time.Date(2026, 9, 25, 16, 0, 0, 0, time.UTC)
	adoptSnapshot(t, store, previous, at)
	prior, err := store.Inventory(ctx, "localfs", previous.Root())
	if err != nil {
		t.Fatal(err)
	}
	prior[0].Size++

	current, err := provider.Snapshot(ctx, root)
	if err != nil {
		t.Fatal(err)
	}
	base, err := reconcilelocalfs.Candidates(ctx, store, current)
	if err != nil {
		t.Fatal(err)
	}
	_, err = reconcilelocalfs.EnrichNativeCandidates(previous, current, prior, base)
	if !errors.Is(err, reconcilelocalfs.ErrInvalidNativeSnapshotBinding) {
		t.Fatalf("error=%v, want ErrInvalidNativeSnapshotBinding", err)
	}
}
