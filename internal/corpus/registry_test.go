package corpus_test

import (
	"errors"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
)

func TestArtifactRegistryAdoptNewCreatesProcessLocalIdentity(t *testing.T) {
	registry := corpus.NewArtifactRegistry()

	first := registry.AdoptNew()
	second := registry.AdoptNew()

	if first.State != corpus.AssignmentAssigned || second.State != corpus.AssignmentAssigned {
		t.Fatalf("unexpected assignment states: first=%#v second=%#v", first, second)
	}
	if first.ArtifactID == "" || second.ArtifactID == "" {
		t.Fatal("adoption did not allocate Artifact identity")
	}
	if first.ArtifactID == second.ArtifactID {
		t.Fatalf("two new objects share Artifact ID %q", first.ArtifactID)
	}
	if registry.Count() != 2 {
		t.Fatalf("count=%d, want 2", registry.Count())
	}
}

func TestArtifactRegistryConfirmedSamePreservesArtifact(t *testing.T) {
	registry := corpus.NewArtifactRegistry()
	adopted := registry.AdoptNew()

	got, err := registry.Reconcile(adopted.ArtifactID, corpus.ContinuityDecision{
		State: corpus.ContinuityConfirmedSame,
	})
	if err != nil {
		t.Fatal(err)
	}
	if got.State != corpus.AssignmentAssigned {
		t.Fatalf("state=%q, want ASSIGNED", got.State)
	}
	if got.ArtifactID != adopted.ArtifactID {
		t.Fatalf("artifact=%q, want preserved %q", got.ArtifactID, adopted.ArtifactID)
	}
	if registry.Count() != 1 {
		t.Fatalf("confirmed same mutated artifact count to %d", registry.Count())
	}
}

func TestArtifactRegistryConfirmedDistinctCreatesNewArtifact(t *testing.T) {
	registry := corpus.NewArtifactRegistry()
	adopted := registry.AdoptNew()

	got, err := registry.Reconcile(adopted.ArtifactID, corpus.ContinuityDecision{
		State: corpus.ContinuityConfirmedDistinct,
	})
	if err != nil {
		t.Fatal(err)
	}
	if got.State != corpus.AssignmentAssigned {
		t.Fatalf("state=%q, want ASSIGNED", got.State)
	}
	if got.ArtifactID == adopted.ArtifactID {
		t.Fatalf("distinct object reused Artifact %q", got.ArtifactID)
	}
	if len(got.CandidateArtifactIDs) != 1 || got.CandidateArtifactIDs[0] != adopted.ArtifactID {
		t.Fatalf("candidates=%#v, want previous Artifact", got.CandidateArtifactIDs)
	}
	if registry.Count() != 2 {
		t.Fatalf("count=%d, want 2", registry.Count())
	}
}

func TestArtifactRegistryAmbiguousDoesNotMutateIdentity(t *testing.T) {
	registry := corpus.NewArtifactRegistry()
	adopted := registry.AdoptNew()
	before := registry.Count()

	got, err := registry.Reconcile(adopted.ArtifactID, corpus.ContinuityDecision{
		State: corpus.ContinuityAmbiguous,
	})
	if err != nil {
		t.Fatal(err)
	}
	if got.State != corpus.AssignmentUnresolved {
		t.Fatalf("state=%q, want UNRESOLVED", got.State)
	}
	if got.ArtifactID != "" {
		t.Fatalf("ambiguous result guessed Artifact %q", got.ArtifactID)
	}
	if len(got.CandidateArtifactIDs) != 1 || got.CandidateArtifactIDs[0] != adopted.ArtifactID {
		t.Fatalf("candidates=%#v", got.CandidateArtifactIDs)
	}
	if registry.Count() != before {
		t.Fatalf("ambiguous decision mutated registry: before=%d after=%d", before, registry.Count())
	}
}

func TestArtifactRegistryUnresolvedDoesNotMutateIdentity(t *testing.T) {
	registry := corpus.NewArtifactRegistry()
	adopted := registry.AdoptNew()
	before := registry.Count()

	got, err := registry.Reconcile(adopted.ArtifactID, corpus.ContinuityDecision{
		State: corpus.ContinuityUnresolved,
	})
	if err != nil {
		t.Fatal(err)
	}
	if got.State != corpus.AssignmentUnresolved || got.ArtifactID != "" {
		t.Fatalf("unexpected unresolved assignment: %#v", got)
	}
	if registry.Count() != before {
		t.Fatalf("unresolved decision mutated registry: before=%d after=%d", before, registry.Count())
	}
}

func TestArtifactRegistryRejectsUnknownCandidate(t *testing.T) {
	registry := corpus.NewArtifactRegistry()

	_, err := registry.Reconcile("missing", corpus.ContinuityDecision{
		State: corpus.ContinuityConfirmedSame,
	})
	if !errors.Is(err, corpus.ErrArtifactNotFound) {
		t.Fatalf("error=%v, want ErrArtifactNotFound", err)
	}
	if registry.Count() != 0 {
		t.Fatalf("failed reconcile mutated registry: count=%d", registry.Count())
	}
}

func TestArtifactRegistryRejectsUnknownDecisionWithoutMutation(t *testing.T) {
	registry := corpus.NewArtifactRegistry()
	adopted := registry.AdoptNew()
	before := registry.Count()

	_, err := registry.Reconcile(adopted.ArtifactID, corpus.ContinuityDecision{
		State: corpus.ContinuityDecisionState("BROKEN"),
	})
	if !errors.Is(err, corpus.ErrUnknownContinuityDecision) {
		t.Fatalf("error=%v, want ErrUnknownContinuityDecision", err)
	}
	if registry.Count() != before {
		t.Fatalf("unknown decision mutated registry: before=%d after=%d", before, registry.Count())
	}
}
