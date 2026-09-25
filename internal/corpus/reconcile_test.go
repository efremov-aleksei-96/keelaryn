package corpus_test

import (
	"errors"
	"reflect"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
)

func TestResolveCandidateSetNoCandidatesIsUnresolved(t *testing.T) {
	got, err := corpus.ResolveCandidateSet(nil)
	if err != nil {
		t.Fatal(err)
	}
	if got.State != corpus.CandidateSetUnresolved || got.SelectedArtifactID != "" || len(got.Candidates) != 0 {
		t.Fatalf("unexpected result: %#v", got)
	}
}

func TestSupportingLocatorOverlapIsAmbiguous(t *testing.T) {
	got, err := corpus.ResolveCandidateSet([]corpus.ArtifactCandidateInput{{
		ArtifactID: "art_a",
		Evidence: []corpus.DecisionEvidence{
			(corpus.ReconciliationSignal{
				Kind:   corpus.SignalLocatorOverlap,
				Source: "test:locator-overlap",
			}).DecisionEvidence(),
		},
	}})
	if err != nil {
		t.Fatal(err)
	}
	if got.State != corpus.CandidateSetAmbiguous || got.SelectedArtifactID != "" {
		t.Fatalf("supporting locator evidence resolved identity: %#v", got)
	}
	if got.Candidates[0].Decision.State != corpus.ContinuityAmbiguous {
		t.Fatalf("candidate decision=%q, want AMBIGUOUS", got.Candidates[0].Decision.State)
	}
}

func TestEqualContentAcrossTwoArtifactsPreservesBothCandidates(t *testing.T) {
	signal := (corpus.ReconciliationSignal{
		Kind:   corpus.SignalContentEqual,
		Source: "test:sha256-equal",
	}).DecisionEvidence()

	got, err := corpus.ResolveCandidateSet([]corpus.ArtifactCandidateInput{
		{ArtifactID: "art_b", Evidence: []corpus.DecisionEvidence{signal}},
		{ArtifactID: "art_a", Evidence: []corpus.DecisionEvidence{signal}},
	})
	if err != nil {
		t.Fatal(err)
	}
	if got.State != corpus.CandidateSetAmbiguous || got.SelectedArtifactID != "" {
		t.Fatalf("equal content selected a winner: %#v", got)
	}
	ids := []corpus.ArtifactID{got.Candidates[0].ArtifactID, got.Candidates[1].ArtifactID}
	if !reflect.DeepEqual(ids, []corpus.ArtifactID{"art_a", "art_b"}) {
		t.Fatalf("candidate IDs=%#v", ids)
	}
}

func TestSupportingProviderMatchCannotResolveCandidate(t *testing.T) {
	got, err := corpus.ResolveCandidateSet([]corpus.ArtifactCandidateInput{{
		ArtifactID: "art_a",
		Evidence: []corpus.DecisionEvidence{
			(corpus.ReconciliationSignal{
				Kind:   corpus.SignalProviderContinuityMatch,
				Source: "localfs:os.SameFile",
			}).DecisionEvidence(),
		},
	}})
	if err != nil {
		t.Fatal(err)
	}
	if got.State != corpus.CandidateSetAmbiguous {
		t.Fatalf("supporting native match resolved identity: %#v", got)
	}
}

func TestSupportingProviderMismatchCannotEliminateCandidate(t *testing.T) {
	got, err := corpus.ResolveCandidateSet([]corpus.ArtifactCandidateInput{{
		ArtifactID: "art_a",
		Evidence: []corpus.DecisionEvidence{
			(corpus.ReconciliationSignal{
				Kind:   corpus.SignalProviderContinuityMismatch,
				Source: "localfs:os.SameFile",
			}).DecisionEvidence(),
		},
	}})
	if err != nil {
		t.Fatal(err)
	}
	if got.State != corpus.CandidateSetAmbiguous {
		t.Fatalf("supporting mismatch eliminated candidate: %#v", got)
	}
	if got.Candidates[0].Decision.State != corpus.ContinuityAmbiguous {
		t.Fatalf("pairwise decision=%q, want AMBIGUOUS", got.Candidates[0].Decision.State)
	}
}

func TestDuplicateCandidateEvidenceIsMerged(t *testing.T) {
	got, err := corpus.ResolveCandidateSet([]corpus.ArtifactCandidateInput{
		{
			ArtifactID: "art_a",
			Evidence: []corpus.DecisionEvidence{{
				Source:    "one",
				Direction: corpus.DirectionSupportsSame,
				Strength:  corpus.EvidenceSupporting,
			}},
		},
		{
			ArtifactID: "art_a",
			Evidence: []corpus.DecisionEvidence{{
				Source:    "two",
				Direction: corpus.DirectionSupportsSame,
				Strength:  corpus.EvidenceSupporting,
			}},
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(got.Candidates) != 1 || len(got.Candidates[0].Decision.Evidence) != 2 {
		t.Fatalf("duplicate Artifact candidate was not merged: %#v", got)
	}
	if got.State != corpus.CandidateSetAmbiguous {
		t.Fatalf("merged supporting evidence resolved identity: %#v", got)
	}
}

func TestUniqueConclusiveSameResolvesCandidate(t *testing.T) {
	got, err := corpus.ResolveCandidateSet([]corpus.ArtifactCandidateInput{{
		ArtifactID: "art_a",
		Evidence: []corpus.DecisionEvidence{{
			Source:    "test:direct-operation-provenance",
			Direction: corpus.DirectionSupportsSame,
			Strength:  corpus.EvidenceConclusive,
		}},
	}})
	if err != nil {
		t.Fatal(err)
	}
	if got.State != corpus.CandidateSetResolvedSame || got.SelectedArtifactID != "art_a" {
		t.Fatalf("conclusive same did not resolve: %#v", got)
	}
}

func TestConclusiveSamePlusConclusiveDistinctCompetitorResolvesUniqueSame(t *testing.T) {
	got, err := corpus.ResolveCandidateSet([]corpus.ArtifactCandidateInput{
		{
			ArtifactID: "art_a",
			Evidence: []corpus.DecisionEvidence{{
				Source:    "same",
				Direction: corpus.DirectionSupportsSame,
				Strength:  corpus.EvidenceConclusive,
			}},
		},
		{
			ArtifactID: "art_b",
			Evidence: []corpus.DecisionEvidence{{
				Source:    "distinct",
				Direction: corpus.DirectionSupportsDistinct,
				Strength:  corpus.EvidenceConclusive,
			}},
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	if got.State != corpus.CandidateSetResolvedSame || got.SelectedArtifactID != "art_a" {
		t.Fatalf("unique plausible conclusive candidate did not resolve: %#v", got)
	}
}

func TestConclusiveSamePlusSupportingCompetitorRemainsAmbiguous(t *testing.T) {
	got, err := corpus.ResolveCandidateSet([]corpus.ArtifactCandidateInput{
		{
			ArtifactID: "art_a",
			Evidence: []corpus.DecisionEvidence{{
				Source:    "same",
				Direction: corpus.DirectionSupportsSame,
				Strength:  corpus.EvidenceConclusive,
			}},
		},
		{
			ArtifactID: "art_b",
			Evidence: []corpus.DecisionEvidence{{
				Source:    "maybe",
				Direction: corpus.DirectionSupportsSame,
				Strength:  corpus.EvidenceSupporting,
			}},
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	if got.State != corpus.CandidateSetAmbiguous || got.SelectedArtifactID != "" {
		t.Fatalf("competing plausible Artifact was ignored: %#v", got)
	}
}

func TestTwoConclusiveSameCandidatesRemainAmbiguous(t *testing.T) {
	got, err := corpus.ResolveCandidateSet([]corpus.ArtifactCandidateInput{
		{
			ArtifactID: "art_a",
			Evidence: []corpus.DecisionEvidence{{
				Source:    "same-a",
				Direction: corpus.DirectionSupportsSame,
				Strength:  corpus.EvidenceConclusive,
			}},
		},
		{
			ArtifactID: "art_b",
			Evidence: []corpus.DecisionEvidence{{
				Source:    "same-b",
				Direction: corpus.DirectionSupportsSame,
				Strength:  corpus.EvidenceConclusive,
			}},
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	if got.State != corpus.CandidateSetAmbiguous || got.SelectedArtifactID != "" {
		t.Fatalf("two conclusive candidates selected a winner: %#v", got)
	}
}

func TestAllCandidatesConfirmedDistinctLeavesIdentityUnresolved(t *testing.T) {
	got, err := corpus.ResolveCandidateSet([]corpus.ArtifactCandidateInput{{
		ArtifactID: "art_a",
		Evidence: []corpus.DecisionEvidence{{
			Source:    "distinct",
			Direction: corpus.DirectionSupportsDistinct,
			Strength:  corpus.EvidenceConclusive,
		}},
	}})
	if err != nil {
		t.Fatal(err)
	}
	if got.State != corpus.CandidateSetUnresolved || got.SelectedArtifactID != "" {
		t.Fatalf("distinct from known candidate was mistaken for current identity: %#v", got)
	}
	if got.Candidates[0].Decision.State != corpus.ContinuityConfirmedDistinct {
		t.Fatalf("pairwise distinct evidence was lost: %#v", got)
	}
}

func TestResolveCandidateSetRejectsEmptyArtifactID(t *testing.T) {
	_, err := corpus.ResolveCandidateSet([]corpus.ArtifactCandidateInput{{}})
	if !errors.Is(err, corpus.ErrInvalidArtifactCandidate) {
		t.Fatalf("error=%v, want ErrInvalidArtifactCandidate", err)
	}
}

func TestReconciliationSignalsAreAlwaysSupporting(t *testing.T) {
	for _, kind := range []corpus.ReconciliationSignalKind{
		corpus.SignalLocatorOverlap,
		corpus.SignalContentEqual,
		corpus.SignalProviderContinuityMatch,
		corpus.SignalProviderContinuityMismatch,
	} {
		got := (corpus.ReconciliationSignal{Kind: kind, Source: "test"}).DecisionEvidence()
		if got.Strength != corpus.EvidenceSupporting {
			t.Fatalf("kind=%q strength=%q, want SUPPORTING", kind, got.Strength)
		}
	}
}
