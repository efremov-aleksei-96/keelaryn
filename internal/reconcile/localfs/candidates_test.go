package localfs_test

import (
	"context"
	"os"
	"path/filepath"
	"reflect"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	reconcilelocalfs "github.com/efremov-aleksei-96/keelaryn/internal/reconcile/localfs"
	providerlocalfs "github.com/efremov-aleksei-96/keelaryn/internal/provider/localfs"
	sqlitestate "github.com/efremov-aleksei-96/keelaryn/internal/state/sqlite"
)

func TestSamePathCandidateRemainsAmbiguous(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	path := filepath.Join(root, "file.txt")
	writeFile(t, path, []byte("same"))

	store := openState(t)
	provider := providerlocalfs.New("localfs")
	bootstrap, err := provider.Snapshot(ctx, root)
	if err != nil {
		t.Fatal(err)
	}
	adoptSnapshot(t, store, bootstrap, time.Date(2026, 9, 25, 5, 0, 0, 0, time.UTC))

	current, err := provider.Snapshot(ctx, root)
	if err != nil {
		t.Fatal(err)
	}
	sets, err := reconcilelocalfs.Candidates(ctx, store, current)
	if err != nil {
		t.Fatal(err)
	}
	if len(sets) != 1 {
		t.Fatalf("sets=%#v", sets)
	}
	if sets[0].Resolution.State != corpus.CandidateSetAmbiguous || sets[0].Resolution.SelectedArtifactID != "" {
		t.Fatalf("same path resolved identity: %#v", sets[0])
	}
	if len(sets[0].Inputs) != 1 || len(sets[0].Inputs[0].Evidence) != 1 {
		t.Fatalf("candidate evidence=%#v", sets[0].Inputs)
	}
	if got := sets[0].Inputs[0].Evidence[0]; got.Source != "localfs:locator-overlap:file.txt" || got.Strength != corpus.EvidenceSupporting {
		t.Fatalf("locator evidence=%#v", got)
	}
}

func TestNoLocatorOverlapIsUnresolved(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	oldPath := filepath.Join(root, "old.txt")
	newPath := filepath.Join(root, "new.txt")
	writeFile(t, oldPath, []byte("x"))

	store := openState(t)
	provider := providerlocalfs.New("localfs")
	first, err := provider.Snapshot(ctx, root)
	if err != nil {
		t.Fatal(err)
	}
	adoptSnapshot(t, store, first, time.Date(2026, 9, 25, 6, 0, 0, 0, time.UTC))
	if err := os.Rename(oldPath, newPath); err != nil {
		t.Fatal(err)
	}

	current, err := provider.Snapshot(ctx, root)
	if err != nil {
		t.Fatal(err)
	}
	sets, err := reconcilelocalfs.Candidates(ctx, store, current)
	if err != nil {
		t.Fatal(err)
	}
	if len(sets) != 1 || sets[0].Resolution.State != corpus.CandidateSetUnresolved || len(sets[0].Inputs) != 0 {
		t.Fatalf("rename without locator overlap guessed candidate: %#v", sets)
	}
}

func TestHardLinkCurrentOccurrenceUnionsCandidatesAcrossLocators(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	a := filepath.Join(root, "a.bin")
	b := filepath.Join(root, "b.bin")
	writeFile(t, a, []byte("a"))
	writeFile(t, b, []byte("b"))

	store := openState(t)
	provider := providerlocalfs.New("localfs")
	first, err := provider.Snapshot(ctx, root)
	if err != nil {
		t.Fatal(err)
	}
	adoptSnapshot(t, store, first, time.Date(2026, 9, 25, 7, 0, 0, 0, time.UTC))

	if err := os.Remove(b); err != nil {
		t.Fatal(err)
	}
	if err := os.Link(a, b); err != nil {
		t.Skipf("hard links unavailable: %v", err)
	}

	current, err := provider.Snapshot(ctx, root)
	if err != nil {
		t.Fatal(err)
	}
	sets, err := reconcilelocalfs.Candidates(ctx, store, current)
	if err != nil {
		t.Fatal(err)
	}
	if len(sets) != 1 {
		t.Fatalf("current hard-link occurrence sets=%#v", sets)
	}
	if len(sets[0].Locators) != 2 || len(sets[0].Inputs) != 2 {
		t.Fatalf("hard-link candidate union=%#v", sets[0])
	}
	if sets[0].Resolution.State != corpus.CandidateSetAmbiguous {
		t.Fatalf("multiple plausible prior Artifacts not ambiguous: %#v", sets[0].Resolution)
	}
	if sets[0].Inputs[0].ArtifactID == sets[0].Inputs[1].ArtifactID {
		t.Fatal("two prior Artifacts collapsed into one candidate")
	}
}

func TestUnresolvedPriorInventoryDoesNotBecomeArtifactCandidate(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	writeFile(t, filepath.Join(root, "file.txt"), []byte("x"))

	store := openState(t)
	provider := providerlocalfs.New("localfs")
	snapshot, err := provider.Snapshot(ctx, root)
	if err != nil {
		t.Fatal(err)
	}
	at := time.Date(2026, 9, 25, 8, 0, 0, 0, time.UTC)
	scan, err := store.StartScan(ctx, "localfs", snapshot.Root(), at)
	if err != nil {
		t.Fatal(err)
	}
	obs := snapshot.Observations()[0]
	_, err = store.RecordObservationInScan(ctx, scan.ID, corpus.ObservationRecordInput{
		ProviderObject: obs.ProviderObject,
		Locators: []corpus.Locator{obs.Locator},
		AssignmentState: corpus.AssignmentUnresolved,
		ObservedAt: at,
		Kind: obs.Kind,
		Size: obs.Size,
		Mode: obs.Mode,
		ModifiedAt: obs.ModifiedAt,
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := store.CompleteScan(ctx, scan.ID, at); err != nil {
		t.Fatal(err)
	}

	current, err := provider.Snapshot(ctx, root)
	if err != nil {
		t.Fatal(err)
	}
	sets, err := reconcilelocalfs.Candidates(ctx, store, current)
	if err != nil {
		t.Fatal(err)
	}
	if len(sets) != 1 || len(sets[0].Inputs) != 0 || sets[0].Resolution.State != corpus.CandidateSetUnresolved {
		t.Fatalf("unresolved prior row became candidate: %#v", sets)
	}
}

func TestCandidateOrderAndSignalsAreDeterministic(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	a := filepath.Join(root, "a.bin")
	b := filepath.Join(root, "b.bin")
	writeFile(t, a, []byte("a"))
	writeFile(t, b, []byte("b"))

	store := openState(t)
	provider := providerlocalfs.New("localfs")
	first, err := provider.Snapshot(ctx, root)
	if err != nil {
		t.Fatal(err)
	}
	adoptSnapshot(t, store, first, time.Date(2026, 9, 25, 9, 0, 0, 0, time.UTC))

	if err := os.Remove(b); err != nil {
		t.Fatal(err)
	}
	if err := os.Link(a, b); err != nil {
		t.Skipf("hard links unavailable: %v", err)
	}
	current, err := provider.Snapshot(ctx, root)
	if err != nil {
		t.Fatal(err)
	}

	firstSets, err := reconcilelocalfs.Candidates(ctx, store, current)
	if err != nil {
		t.Fatal(err)
	}
	secondSets, err := reconcilelocalfs.Candidates(ctx, store, current)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(firstSets, secondSets) {
		t.Fatalf("candidate generation not deterministic:\nfirst=%#v\nsecond=%#v", firstSets, secondSets)
	}
}

func openState(t *testing.T) *sqlitestate.Store {
	t.Helper()
	store, err := sqlitestate.Open(context.Background(), filepath.Join(t.TempDir(), "state.db"))
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

func adoptSnapshot(t *testing.T, store *sqlitestate.Store, snapshot *providerlocalfs.Snapshot, at time.Time) {
	t.Helper()
	scan, err := store.StartBootstrapScan(context.Background(), snapshot.ProviderID(), snapshot.Root(), at)
	if err != nil {
		t.Fatal(err)
	}
	observations := snapshot.Observations()
	for _, observation := range observations {
		artifact, err := store.AdoptArtifact(context.Background())
		if err != nil {
			t.Fatal(err)
		}
		input := corpus.ObservationRecordInput{
			ProviderObject: observation.ProviderObject,
			Locators: []corpus.Locator{observation.Locator},
			ArtifactID: artifact.ID,
			AssignmentState: corpus.AssignmentAssigned,
			ObservedAt: at,
			Kind: observation.Kind,
			Size: observation.Size,
			Mode: observation.Mode,
			ModifiedAt: observation.ModifiedAt,
		}
		if _, err := store.RecordObservationInScan(context.Background(), scan.ID, input); err != nil {
			t.Fatal(err)
		}
	}
	if err := store.CompleteScan(context.Background(), scan.ID, at); err != nil {
		t.Fatal(err)
	}
}

func writeFile(t *testing.T, path string, content []byte) {
	t.Helper()
	if err := os.WriteFile(path, content, 0o600); err != nil {
		t.Fatal(err)
	}
}
