package corpus_test

import (
	"errors"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
)

func TestOccurrenceIdentityCompleteEmptyUniverseResolvesNew(t *testing.T) {
	candidates, err := corpus.ResolveCandidateSet(nil)
	if err != nil {
		t.Fatal(err)
	}
	proof := completeProof("obj-new")
	got, err := corpus.ResolveOccurrenceIdentity(candidates, &proof)
	if err != nil {
		t.Fatal(err)
	}
	if got.State != corpus.OccurrenceIdentityResolvedNew || got.SelectedArtifactID != "" {
		t.Fatalf("resolution=%#v", got)
	}
	if err := corpus.ValidateOccurrenceIdentityResolution(got); err != nil {
		t.Fatal(err)
	}
}

func TestOccurrenceIdentityCompleteAllDistinctResolvesNew(t *testing.T) {
	candidates, err := corpus.ResolveCandidateSet([]corpus.ArtifactCandidateInput{{
		ArtifactID: "art_old",
		Evidence: []corpus.DecisionEvidence{{
			Source:    "provider:test",
			Direction: corpus.DirectionSupportsDistinct,
			Strength:  corpus.EvidenceConclusive,
		}},
	}})
	if err != nil {
		t.Fatal(err)
	}
	proof := completeProof("obj-copy")
	got, err := corpus.ResolveOccurrenceIdentity(candidates, &proof)
	if err != nil {
		t.Fatal(err)
	}
	if got.State != corpus.OccurrenceIdentityResolvedNew {
		t.Fatalf("resolution=%#v", got)
	}
}

func TestOccurrenceIdentityUnknownUniverseNeverResolvesNew(t *testing.T) {
	candidates, err := corpus.ResolveCandidateSet(nil)
	if err != nil {
		t.Fatal(err)
	}
	proof := completeProof("obj-new")
	proof.Coverage = corpus.CandidateUniverseUnknown
	proof.EvidenceRefs = nil
	got, err := corpus.ResolveOccurrenceIdentity(candidates, &proof)
	if err != nil {
		t.Fatal(err)
	}
	if got.State != corpus.OccurrenceIdentityUnresolved {
		t.Fatalf("resolution=%#v", got)
	}
}

func TestOccurrenceIdentityPlausibleCandidateStaysAmbiguous(t *testing.T) {
	candidates, err := corpus.ResolveCandidateSet([]corpus.ArtifactCandidateInput{{
		ArtifactID: "art_old",
		Evidence: []corpus.DecisionEvidence{{
			Source:    "supporting",
			Direction: corpus.DirectionSupportsSame,
			Strength:  corpus.EvidenceSupporting,
		}},
	}})
	if err != nil {
		t.Fatal(err)
	}
	proof := completeProof("obj-new")
	got, err := corpus.ResolveOccurrenceIdentity(candidates, &proof)
	if err != nil {
		t.Fatal(err)
	}
	if got.State != corpus.OccurrenceIdentityAmbiguous {
		t.Fatalf("resolution=%#v", got)
	}
}

func TestOccurrenceIdentityResolvedSameWinsWithoutInventingNew(t *testing.T) {
	candidates, err := corpus.ResolveCandidateSet([]corpus.ArtifactCandidateInput{{
		ArtifactID: "art_old",
		Evidence: []corpus.DecisionEvidence{{
			Source:    "provider:test",
			Direction: corpus.DirectionSupportsSame,
			Strength:  corpus.EvidenceConclusive,
		}},
	}})
	if err != nil {
		t.Fatal(err)
	}
	proof := completeProof("obj-old")
	got, err := corpus.ResolveOccurrenceIdentity(candidates, &proof)
	if err != nil {
		t.Fatal(err)
	}
	if got.State != corpus.OccurrenceIdentityResolvedSame || got.SelectedArtifactID != "art_old" {
		t.Fatalf("resolution=%#v", got)
	}
}

func TestOccurrenceIdentityRejectsForgedResolvedNew(t *testing.T) {
	candidates, err := corpus.ResolveCandidateSet(nil)
	if err != nil {
		t.Fatal(err)
	}
	proof := completeProof("obj-new")
	proof.Coverage = corpus.CandidateUniverseUnknown
	proof.EvidenceRefs = nil
	forged := corpus.OccurrenceIdentityResolution{
		State:      corpus.OccurrenceIdentityResolvedNew,
		Candidates: candidates,
		Universe:   &proof,
	}
	if !errors.Is(corpus.ValidateOccurrenceIdentityResolution(forged), corpus.ErrInvalidOccurrenceIdentityResolution) {
		t.Fatal("forged resolution unexpectedly validated")
	}
}

func completeProof(objectID corpus.ProviderObjectID) corpus.CandidateUniverseProof {
	return corpus.CandidateUniverseProof{
		PolicyID:        "test:complete:v1",
		ProviderID:      "drive",
		IdentityDomain:  "drive:test-account",
		ScopeID:         "drive-root",
		CurrentObjectID: objectID,
		Coverage:        corpus.CandidateUniverseComplete,
		EvidenceRefs:    []string{"baseline:1", "cursor:2"},
	}
}
