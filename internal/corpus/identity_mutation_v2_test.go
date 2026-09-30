package corpus_test

import (
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
)

func TestIdentityMutationFingerprintPreservesV1ForKnownFactsAndUsesV2ForUnknown(t *testing.T) {
	at := time.Date(2026, 9, 30, 0, 0, 0, 0, time.UTC)
	request := corpus.IdentityMutationRequest{
		ScanID: "scan", AuthoritySetID: "authority",
		Observation: corpus.ObservationRecordInput{
			ProviderObject:  corpus.ProviderObject{ProviderID: "p", ID: "o", IdentityState: corpus.ObjectIdentityObserved},
			Locators:        []corpus.Locator{{ProviderID: "p", Root: "r", Path: "x"}},
			AssignmentState: corpus.AssignmentUnresolved, ObservedAt: at, Kind: corpus.EntryOther,
			Size: corpus.KnownSize(0), Mode: corpus.KnownMode(0), ModifiedAt: corpus.KnownModifiedAt(at),
		},
	}
	known, err := corpus.FingerprintIdentityMutation(corpus.IdentityMutationNew, request)
	if err != nil {
		t.Fatal(err)
	}
	if known.Version != corpus.IdentityMutationFingerprintV1 {
		t.Fatalf("known=%s", known.Version)
	}
	request.Observation.Mode = nil
	unknown, err := corpus.FingerprintIdentityMutation(corpus.IdentityMutationNew, request)
	if err != nil {
		t.Fatal(err)
	}
	if unknown.Version != corpus.IdentityMutationFingerprintV2 {
		t.Fatalf("unknown=%s", unknown.Version)
	}
	if known.SHA256 == unknown.SHA256 {
		t.Fatal("availability change did not change fingerprint")
	}
}
