package corpus_test

import (
	"errors"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
)

func TestRevisionTrackerFirstObservationCreatesRevision(t *testing.T) {
	registry := corpus.NewArtifactRegistry()
	artifact := registry.AdoptNew().ArtifactID
	tracker := corpus.NewRevisionTracker(registry)

	got, err := tracker.Observe(artifact, evidence("aaa", 3))
	if err != nil {
		t.Fatal(err)
	}
	if !got.Created || got.Current.Sequence != 1 || got.Current.Revision.ID == "" {
		t.Fatalf("unexpected first revision: %#v", got)
	}
	if got.Current.Revision.ArtifactID != artifact {
		t.Fatalf("revision ArtifactID=%q, want %q", got.Current.Revision.ArtifactID, artifact)
	}
	if string(got.Current.Revision.ID) == got.Current.Evidence.Digest {
		t.Fatal("Revision identity collapsed into content digest")
	}
}

func TestRevisionTrackerUnchangedEvidenceReusesCurrentRevision(t *testing.T) {
	registry := corpus.NewArtifactRegistry()
	artifact := registry.AdoptNew().ArtifactID
	tracker := corpus.NewRevisionTracker(registry)

	first, err := tracker.Observe(artifact, evidence("aaa", 3))
	if err != nil {
		t.Fatal(err)
	}
	second, err := tracker.Observe(artifact, evidence("aaa", 3))
	if err != nil {
		t.Fatal(err)
	}

	if second.Created {
		t.Fatal("unchanged content created a new Revision")
	}
	if second.Current.Revision.ID != first.Current.Revision.ID {
		t.Fatalf("unchanged content changed Revision: first=%q second=%q", first.Current.Revision.ID, second.Current.Revision.ID)
	}
	if len(tracker.History(artifact)) != 1 {
		t.Fatalf("history len=%d, want 1", len(tracker.History(artifact)))
	}
}

func TestRevisionTrackerChangedEvidenceCreatesNewRevision(t *testing.T) {
	registry := corpus.NewArtifactRegistry()
	artifact := registry.AdoptNew().ArtifactID
	tracker := corpus.NewRevisionTracker(registry)

	first, err := tracker.Observe(artifact, evidence("aaa", 3))
	if err != nil {
		t.Fatal(err)
	}
	second, err := tracker.Observe(artifact, evidence("bbb", 3))
	if err != nil {
		t.Fatal(err)
	}

	if !second.Created || second.Current.Sequence != 2 {
		t.Fatalf("changed content did not create revision 2: %#v", second)
	}
	if second.Current.Revision.ID == first.Current.Revision.ID {
		t.Fatal("changed content reused Revision identity")
	}
}

func TestRevisionTrackerReturnToOldBytesCreatesThirdRevision(t *testing.T) {
	registry := corpus.NewArtifactRegistry()
	artifact := registry.AdoptNew().ArtifactID
	tracker := corpus.NewRevisionTracker(registry)

	a1, err := tracker.Observe(artifact, evidence("digest-a", 10))
	if err != nil {
		t.Fatal(err)
	}
	b, err := tracker.Observe(artifact, evidence("digest-b", 11))
	if err != nil {
		t.Fatal(err)
	}
	a2, err := tracker.Observe(artifact, evidence("digest-a", 10))
	if err != nil {
		t.Fatal(err)
	}

	if a2.Current.Sequence != 3 {
		t.Fatalf("sequence=%d, want 3", a2.Current.Sequence)
	}
	if a2.Current.Revision.ID == a1.Current.Revision.ID || a2.Current.Revision.ID == b.Current.Revision.ID {
		t.Fatalf("A→B→A reused old Revision identity: a1=%q b=%q a2=%q", a1.Current.Revision.ID, b.Current.Revision.ID, a2.Current.Revision.ID)
	}
	history := tracker.History(artifact)
	if len(history) != 3 {
		t.Fatalf("history len=%d, want 3", len(history))
	}
	if history[0].Evidence.Digest != history[2].Evidence.Digest {
		t.Fatal("test did not actually return to old bytes")
	}
}

func TestRevisionTrackerAlgorithmChangeFailsWithoutMutation(t *testing.T) {
	registry := corpus.NewArtifactRegistry()
	artifact := registry.AdoptNew().ArtifactID
	tracker := corpus.NewRevisionTracker(registry)

	first, err := tracker.Observe(artifact, evidence("aaa", 3))
	if err != nil {
		t.Fatal(err)
	}
	before := tracker.History(artifact)

	_, err = tracker.Observe(artifact, corpus.ContentEvidence{
		Algorithm: "blake3",
		Digest:    "aaa",
		Size:      3,
	})
	if !errors.Is(err, corpus.ErrContentEvidenceNotComparable) {
		t.Fatalf("error=%v, want ErrContentEvidenceNotComparable", err)
	}
	after := tracker.History(artifact)
	if len(after) != len(before) || after[0].Revision.ID != first.Current.Revision.ID {
		t.Fatalf("algorithm mismatch mutated revisions: before=%#v after=%#v", before, after)
	}
}

func TestRevisionTrackerUnknownArtifactFails(t *testing.T) {
	tracker := corpus.NewRevisionTracker(corpus.NewArtifactRegistry())
	_, err := tracker.Observe("missing", evidence("aaa", 3))
	if !errors.Is(err, corpus.ErrArtifactNotFound) {
		t.Fatalf("error=%v, want ErrArtifactNotFound", err)
	}
}

func evidence(digest string, size int64) corpus.ContentEvidence {
	return corpus.ContentEvidence{
		Algorithm: corpus.ContentAlgorithmSHA256,
		Digest:    digest,
		Size:      size,
	}
}
