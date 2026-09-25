package corpus_test

import (
	"errors"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
)

func TestGenericRcloneIDIsSupportingOnly(t *testing.T) {
	got, err := corpus.ProviderIdentityEvidence(
		corpus.RcloneGenericIdentityContract(),
		identityComparison("remote:user", "id-1", "id-1", corpus.ProviderHistoryContinuous),
	)
	if err != nil {
		t.Fatal(err)
	}
	if got.Direction != corpus.DirectionSupportsSame || got.Strength != corpus.EvidenceSupporting {
		t.Fatalf("generic rclone ID overstated continuity: %#v", got)
	}
}

func TestDriveEqualIDUnknownGapIsSupportingOnly(t *testing.T) {
	got, err := corpus.ProviderIdentityEvidence(
		corpus.GoogleDriveFileIDContract(),
		identityComparison("drive:user-1", "file-123", "file-123", corpus.ProviderHistoryUnknown),
	)
	if err != nil {
		t.Fatal(err)
	}
	if got.Direction != corpus.DirectionSupportsSame || got.Strength != corpus.EvidenceSupporting {
		t.Fatalf("Drive equal ID across unknown gap became conclusive: %#v", got)
	}
}

func TestDriveEqualIDContinuousHistoryIsConclusiveSame(t *testing.T) {
	got, err := corpus.ProviderIdentityEvidence(
		corpus.GoogleDriveFileIDContract(),
		identityComparison("drive:user-1", "file-123", "file-123", corpus.ProviderHistoryContinuous),
	)
	if err != nil {
		t.Fatal(err)
	}
	if got.Direction != corpus.DirectionSupportsSame || got.Strength != corpus.EvidenceConclusive {
		t.Fatalf("continuous Drive identity not conclusive: %#v", got)
	}
	decision := corpus.ResolveContinuity([]corpus.DecisionEvidence{got})
	if decision.State != corpus.ContinuityConfirmedSame {
		t.Fatalf("decision=%q, want CONFIRMED_SAME", decision.State)
	}
}

func TestDriveDifferentIDsAreConclusiveDistinctWithinDomain(t *testing.T) {
	got, err := corpus.ProviderIdentityEvidence(
		corpus.GoogleDriveFileIDContract(),
		identityComparison("drive:user-1", "file-source", "file-copy", corpus.ProviderHistoryUnknown),
	)
	if err != nil {
		t.Fatal(err)
	}
	if got.Direction != corpus.DirectionSupportsDistinct || got.Strength != corpus.EvidenceConclusive {
		t.Fatalf("distinct Drive IDs not conclusive: %#v", got)
	}
	decision := corpus.ResolveContinuity([]corpus.DecisionEvidence{got})
	if decision.State != corpus.ContinuityConfirmedDistinct {
		t.Fatalf("decision=%q, want CONFIRMED_DISTINCT", decision.State)
	}
}

func TestGloballyNonReusingContractCanConfirmSameAcrossUnknownGap(t *testing.T) {
	contract := corpus.ProviderIdentityContract{
		ID:        "test:globally-non-reusing",
		Provider:  "test",
		Semantics: corpus.ProviderIdentityGloballyNonReusing,
	}
	got, err := corpus.ProviderIdentityEvidence(
		contract,
		identityComparison("test:domain", "object-1", "object-1", corpus.ProviderHistoryUnknown),
	)
	if err != nil {
		t.Fatal(err)
	}
	if got.Strength != corpus.EvidenceConclusive || got.Direction != corpus.DirectionSupportsSame {
		t.Fatalf("globally non-reusing contract=%#v", got)
	}
}

func TestProviderIdentityRejectsCrossDomainComparison(t *testing.T) {
	comparison := corpus.ProviderIdentityComparison{
		Previous: corpus.ProviderIdentityRef{IdentityDomain: "drive:user-a", ObjectID: "same"},
		Current:  corpus.ProviderIdentityRef{IdentityDomain: "drive:user-b", ObjectID: "same"},
		Coverage: corpus.ProviderHistoryContinuous,
	}
	_, err := corpus.ProviderIdentityEvidence(corpus.GoogleDriveFileIDContract(), comparison)
	if !errors.Is(err, corpus.ErrInvalidProviderIdentityComparison) {
		t.Fatalf("error=%v, want ErrInvalidProviderIdentityComparison", err)
	}
}

func TestProviderIdentityRejectsEmptyID(t *testing.T) {
	_, err := corpus.ProviderIdentityEvidence(
		corpus.GoogleDriveFileIDContract(),
		identityComparison("drive:user", "", "file-1", corpus.ProviderHistoryContinuous),
	)
	if !errors.Is(err, corpus.ErrInvalidProviderIdentityComparison) {
		t.Fatalf("error=%v, want ErrInvalidProviderIdentityComparison", err)
	}
}

func TestProviderIdentityRejectsUnknownSemanticsAndCoverage(t *testing.T) {
	contract := corpus.ProviderIdentityContract{
		ID:        "bad",
		Provider:  "bad",
		Semantics: corpus.ProviderIdentitySemantics("MAGIC"),
	}
	_, err := corpus.ProviderIdentityEvidence(
		contract,
		identityComparison("bad:domain", "a", "a", corpus.ProviderHistoryUnknown),
	)
	if !errors.Is(err, corpus.ErrInvalidProviderIdentityComparison) {
		t.Fatalf("semantics error=%v", err)
	}

	contract.Semantics = corpus.ProviderIdentitySupporting
	_, err = corpus.ProviderIdentityEvidence(
		contract,
		identityComparison("bad:domain", "a", "a", corpus.ProviderHistoryCoverage("BROKEN")),
	)
	if !errors.Is(err, corpus.ErrInvalidProviderIdentityComparison) {
		t.Fatalf("coverage error=%v", err)
	}
}

func identityComparison(domain string, previousID, currentID corpus.ProviderObjectID, coverage corpus.ProviderHistoryCoverage) corpus.ProviderIdentityComparison {
	return corpus.ProviderIdentityComparison{
		Previous: corpus.ProviderIdentityRef{
			IdentityDomain: domain,
			ObjectID:       previousID,
		},
		Current: corpus.ProviderIdentityRef{
			IdentityDomain: domain,
			ObjectID:       currentID,
		},
		Coverage: coverage,
	}
}
