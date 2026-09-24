package corpus_test

import (
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
)

func TestResolveContinuityNoEvidenceIsUnresolved(t *testing.T) {
	got := corpus.ResolveContinuity(nil)
	if got.State != corpus.ContinuityUnresolved {
		t.Fatalf("state=%q, want %q", got.State, corpus.ContinuityUnresolved)
	}
}

func TestResolveContinuitySupportingEvidenceCannotConfirmSame(t *testing.T) {
	got := corpus.ResolveContinuity([]corpus.DecisionEvidence{{
		Source:    "localfs:os.SameFile",
		Direction: corpus.DirectionSupportsSame,
		Strength:  corpus.EvidenceSupporting,
	}})
	if got.State != corpus.ContinuityAmbiguous {
		t.Fatalf("state=%q, want %q", got.State, corpus.ContinuityAmbiguous)
	}
}

func TestResolveContinuitySupportingMismatchCannotConfirmDistinct(t *testing.T) {
	got := corpus.ResolveContinuity([]corpus.DecisionEvidence{{
		Source:    "localfs:os.SameFile",
		Direction: corpus.DirectionSupportsDistinct,
		Strength:  corpus.EvidenceSupporting,
	}})
	if got.State != corpus.ContinuityAmbiguous {
		t.Fatalf("state=%q, want %q", got.State, corpus.ContinuityAmbiguous)
	}
}

func TestResolveContinuityConclusiveSame(t *testing.T) {
	got := corpus.ResolveContinuity([]corpus.DecisionEvidence{{
		Source:    "test:direct-operation-provenance",
		Direction: corpus.DirectionSupportsSame,
		Strength:  corpus.EvidenceConclusive,
	}})
	if got.State != corpus.ContinuityConfirmedSame {
		t.Fatalf("state=%q, want %q", got.State, corpus.ContinuityConfirmedSame)
	}
}

func TestResolveContinuityConclusiveDistinct(t *testing.T) {
	got := corpus.ResolveContinuity([]corpus.DecisionEvidence{{
		Source:    "test:direct-copy-provenance",
		Direction: corpus.DirectionSupportsDistinct,
		Strength:  corpus.EvidenceConclusive,
	}})
	if got.State != corpus.ContinuityConfirmedDistinct {
		t.Fatalf("state=%q, want %q", got.State, corpus.ContinuityConfirmedDistinct)
	}
}

func TestResolveContinuityConflictingConclusiveEvidenceIsAmbiguous(t *testing.T) {
	got := corpus.ResolveContinuity([]corpus.DecisionEvidence{
		{
			Source:    "provider-a",
			Direction: corpus.DirectionSupportsSame,
			Strength:  corpus.EvidenceConclusive,
		},
		{
			Source:    "provider-b",
			Direction: corpus.DirectionSupportsDistinct,
			Strength:  corpus.EvidenceConclusive,
		},
	})
	if got.State != corpus.ContinuityAmbiguous {
		t.Fatalf("state=%q, want %q", got.State, corpus.ContinuityAmbiguous)
	}
}
