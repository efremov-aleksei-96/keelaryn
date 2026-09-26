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
