package localfs_test

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	reconcilelocalfs "github.com/efremov-aleksei-96/keelaryn/internal/reconcile/localfs"
	providerlocalfs "github.com/efremov-aleksei-96/keelaryn/internal/provider/localfs"
	sqlitestate "github.com/efremov-aleksei-96/keelaryn/internal/state/sqlite"
)

func TestContentEqualAddsSupportingEvidenceButRemainsAmbiguous(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	writeFile(t, filepath.Join(root, "file.txt"), []byte("abc"))
	store := openState(t)
	provider := providerlocalfs.New("localfs")

	publishAdoptedPath(t, store, "file.txt", root, time.Date(2026, 9, 25, 10, 0, 0, 0, time.UTC), &corpus.ContentEvidence{
		Algorithm: corpus.ContentAlgorithmSHA256,
		Digest:    "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
		Size:      3,
	})

	snapshot, err := provider.Snapshot(ctx, root)
	if err != nil {
		t.Fatal(err)
	}
	sets, err := reconcilelocalfs.Candidates(ctx, store, snapshot)
	if err != nil {
		t.Fatal(err)
	}
	got, err := reconcilelocalfs.EnrichContent(ctx, store, snapshot, sets[0])
	if err != nil {
		t.Fatal(err)
	}
	if got.Evidence == nil || got.Evidence.Digest != "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad" {
		t.Fatalf("sample evidence=%#v", got.Evidence)
	}
	if got.Set.Resolution.State != corpus.CandidateSetAmbiguous || got.Set.Resolution.SelectedArtifactID != "" {
		t.Fatalf("content equality resolved identity: %#v", got.Set.Resolution)
	}
	if len(got.Set.Inputs) != 1 || len(got.Set.Inputs[0].Evidence) != 2 {
		t.Fatalf("expected locator+content evidence: %#v", got.Set.Inputs)
	}
	last := got.Set.Inputs[0].Evidence[1]
	if last.Source != "localfs:content-equal:sha256" || last.Strength != corpus.EvidenceSupporting {
		t.Fatalf("content signal=%#v", last)
	}
}

func TestContentMismatchAddsNoDistinctEvidence(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	writeFile(t, filepath.Join(root, "file.txt"), []byte("current"))
	store := openState(t)
	provider := providerlocalfs.New("localfs")

	publishAdoptedPath(t, store, "file.txt", root, time.Date(2026, 9, 25, 11, 0, 0, 0, time.UTC), &corpus.ContentEvidence{
		Algorithm: corpus.ContentAlgorithmSHA256,
		Digest:    "different",
		Size:      9,
	})

	snapshot, err := provider.Snapshot(ctx, root)
	if err != nil {
		t.Fatal(err)
	}
	sets, err := reconcilelocalfs.Candidates(ctx, store, snapshot)
	if err != nil {
		t.Fatal(err)
	}
	got, err := reconcilelocalfs.EnrichContent(ctx, store, snapshot, sets[0])
	if err != nil {
		t.Fatal(err)
	}
	if len(got.Set.Inputs[0].Evidence) != 1 {
		t.Fatalf("content mismatch added evidence: %#v", got.Set.Inputs[0].Evidence)
	}
	if got.Set.Inputs[0].Evidence[0].Direction != corpus.DirectionSupportsSame {
		t.Fatalf("locator evidence changed: %#v", got.Set.Inputs[0].Evidence)
	}
	if got.Set.Resolution.State != corpus.CandidateSetAmbiguous {
		t.Fatalf("mismatch incorrectly eliminated candidate: %#v", got.Set.Resolution)
	}
}

func TestCandidateWithoutRevisionAddsNoContentSignal(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	writeFile(t, filepath.Join(root, "link-like.txt"), []byte("abc"))
	store := openState(t)
	provider := providerlocalfs.New("localfs")

	publishAdoptedPath(t, store, "link-like.txt", root, time.Date(2026, 9, 25, 12, 0, 0, 0, time.UTC), nil)

	snapshot, err := provider.Snapshot(ctx, root)
	if err != nil {
		t.Fatal(err)
	}
	sets, err := reconcilelocalfs.Candidates(ctx, store, snapshot)
	if err != nil {
		t.Fatal(err)
	}
	got, err := reconcilelocalfs.EnrichContent(ctx, store, snapshot, sets[0])
	if err != nil {
		t.Fatal(err)
	}
	if len(got.Set.Inputs[0].Evidence) != 1 {
		t.Fatalf("candidate without Revision gained content signal: %#v", got.Set.Inputs)
	}
}

func TestNoCandidatesDoesNotReadCurrentFile(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	path := filepath.Join(root, "new.txt")
	writeFile(t, path, []byte("x"))
	store := openState(t)
	snapshot, err := providerlocalfs.New("localfs").Snapshot(ctx, root)
	if err != nil {
		t.Fatal(err)
	}
	sets, err := reconcilelocalfs.Candidates(ctx, store, snapshot)
	if err != nil {
		t.Fatal(err)
	}
	if len(sets) != 1 || len(sets[0].Inputs) != 0 {
		t.Fatalf("expected empty candidate set: %#v", sets)
	}
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}

	got, err := reconcilelocalfs.EnrichContent(ctx, store, snapshot, sets[0])
	if err != nil {
		t.Fatalf("empty candidate enrichment attempted file read: %v", err)
	}
	if got.Evidence != nil || got.Set.Resolution.State != corpus.CandidateSetUnresolved {
		t.Fatalf("unexpected empty enrichment=%#v", got)
	}
}

func TestEnrichmentRejectsLocatorSetNotMatchingOneCurrentGroup(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	writeFile(t, filepath.Join(root, "a.txt"), []byte("a"))
	writeFile(t, filepath.Join(root, "b.txt"), []byte("b"))
	store := openState(t)
	snapshot, err := providerlocalfs.New("localfs").Snapshot(ctx, root)
	if err != nil {
		t.Fatal(err)
	}

	fake := corpus.OccurrenceCandidateSet{
		Kind: corpus.EntryRegularFile,
		Locators: []corpus.Locator{
			{ProviderID: "localfs", Root: snapshot.Root(), Path: "a.txt"},
			{ProviderID: "localfs", Root: snapshot.Root(), Path: "b.txt"},
		},
		Inputs: []corpus.ArtifactCandidateInput{{
			ArtifactID: "art_fake",
			Evidence: []corpus.DecisionEvidence{{
				Source: "test",
				Direction: corpus.DirectionSupportsSame,
				Strength: corpus.EvidenceSupporting,
			}},
		}},
	}
	_, err = reconcilelocalfs.EnrichContent(ctx, store, snapshot, fake)
	if !errors.Is(err, reconcilelocalfs.ErrInvalidContentCandidateSet) {
		t.Fatalf("error=%v, want ErrInvalidContentCandidateSet", err)
	}
}

func TestEnrichmentRejectsNonRegularSetWithCandidates(t *testing.T) {
	snapshotRoot := t.TempDir()
	target := filepath.Join(t.TempDir(), "target")
	writeFile(t, target, []byte("x"))
	link := filepath.Join(snapshotRoot, "link")
	if err := os.Symlink(target, link); err != nil {
		t.Skipf("symlink unavailable: %v", err)
	}
	snapshot, err := providerlocalfs.New("localfs").Snapshot(context.Background(), snapshotRoot)
	if err != nil {
		t.Fatal(err)
	}
	fake := corpus.OccurrenceCandidateSet{
		Kind: corpus.EntrySymlink,
		Locators: []corpus.Locator{{
			ProviderID: "localfs",
			Root: snapshot.Root(),
			Path: "link",
		}},
		Inputs: []corpus.ArtifactCandidateInput{{ArtifactID: "art_fake"}},
	}
	_, err = reconcilelocalfs.EnrichContent(context.Background(), emptyRevisionReader{}, snapshot, fake)
	if !errors.Is(err, reconcilelocalfs.ErrInvalidContentCandidateSet) {
		t.Fatalf("error=%v, want ErrInvalidContentCandidateSet", err)
	}
}

type emptyRevisionReader struct{}

func (emptyRevisionReader) RevisionHistory(context.Context, corpus.ArtifactID) ([]corpus.RevisionRecord, error) {
	return nil, nil
}

func publishAdoptedPath(t *testing.T, store *sqlitestate.Store, path, root string, at time.Time, evidence *corpus.ContentEvidence) {
	t.Helper()
	scan, err := store.StartBootstrapScan(context.Background(), "localfs", root, at)
	if err != nil {
		t.Fatal(err)
	}
	size := int64(1)
	if evidence != nil {
		size = evidence.Size
	}
	_, err = store.AdoptObservationInScan(context.Background(), scan.ID, corpus.ObservationRecordInput{
		ProviderObject: corpus.ProviderObject{
			ProviderID:    "localfs",
			IdentityState: corpus.ObjectIdentityUnresolved,
		},
		Locators: []corpus.Locator{{
			ProviderID: "localfs",
			Root:       root,
			Path:       path,
		}},
		AssignmentState: corpus.AssignmentUnresolved,
		ObservedAt:      at,
		Kind:            corpus.EntryRegularFile,
		Size:            size,
		Mode:            0o600,
		ModifiedAt:      at,
	}, evidence)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.CompleteScan(context.Background(), scan.ID, at); err != nil {
		t.Fatal(err)
	}
}
