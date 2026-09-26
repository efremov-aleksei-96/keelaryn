package corpus_test

import (
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
)

func TestIdentityAuthorityHistoryReferencesMustBePaired(t *testing.T) {
	base := corpus.IdentityAuthoritySet{
		ID:               "authority-1",
		PolicyID:         "test:v1",
		ProviderID:       "drive",
		IdentityDomain:   "drive:user",
		ScopeID:          "root",
		CurrentObjectID:  "object-1",
		UniverseCoverage: corpus.CandidateUniverseUnknown,
		SourceRefs:       []string{"source"},
		CreatedAt:        time.Date(2026, 9, 26, 20, 0, 0, 0, time.UTC),
	}
	if err := corpus.ValidateIdentityAuthoritySet(base); err != nil {
		t.Fatal(err)
	}
	onlyGeneration := base
	onlyGeneration.GenerationID = "generation-1"
	if err := corpus.ValidateIdentityAuthoritySet(onlyGeneration); err == nil {
		t.Fatal("GenerationID without LifetimeSegmentID unexpectedly validated")
	}
	onlySegment := base
	onlySegment.LifetimeSegmentID = "segment-1"
	if err := corpus.ValidateIdentityAuthoritySet(onlySegment); err == nil {
		t.Fatal("LifetimeSegmentID without GenerationID unexpectedly validated")
	}
	both := base
	both.GenerationID = "generation-1"
	both.LifetimeSegmentID = "segment-1"
	if err := corpus.ValidateIdentityAuthoritySet(both); err != nil {
		t.Fatal(err)
	}
}

func TestResolveIdentityAuthoritySetUsesSharedCandidateAndUniverseSemantics(t *testing.T) {
	at := time.Date(2026, 9, 27, 22, 30, 0, 0, time.UTC)
	base := corpus.IdentityAuthoritySet{
		ID: "authority-resolve", PolicyID: "test:v1", ProviderID: "drive",
		IdentityDomain: "drive:user", ScopeID: "root", CurrentObjectID: "object-1",
		SourceRefs: []string{"source"}, CreatedAt: at,
	}

	newSet := base
	newSet.UniverseCoverage = corpus.CandidateUniverseComplete
	newResolution, err := corpus.ResolveIdentityAuthoritySet(newSet)
	if err != nil {
		t.Fatal(err)
	}
	if newResolution.State != corpus.OccurrenceIdentityResolvedNew {
		t.Fatalf("NEW resolution=%#v", newResolution)
	}

	unresolvedSet := base
	unresolvedSet.ID = "authority-unresolved"
	unresolvedSet.UniverseCoverage = corpus.CandidateUniverseUnknown
	unresolved, err := corpus.ResolveIdentityAuthoritySet(unresolvedSet)
	if err != nil {
		t.Fatal(err)
	}
	if unresolved.State != corpus.OccurrenceIdentityUnresolved {
		t.Fatalf("unresolved resolution=%#v", unresolved)
	}

	sameSet := base
	sameSet.ID = "authority-same"
	sameSet.UniverseCoverage = corpus.CandidateUniverseUnknown
	sameSet.Candidates = []corpus.IdentityAuthorityCandidate{{
		ArtifactID: "art-1", Direction: corpus.DirectionSupportsSame, SourceRef: "same",
	}}
	same, err := corpus.ResolveIdentityAuthoritySet(sameSet)
	if err != nil {
		t.Fatal(err)
	}
	if same.State != corpus.OccurrenceIdentityResolvedSame || same.SelectedArtifactID != "art-1" {
		t.Fatalf("SAME resolution=%#v", same)
	}
}
