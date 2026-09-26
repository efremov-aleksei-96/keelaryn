package remotehistory_test

import (
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
)

func TestProviderLifetimeSegmentIDIsDeterministicAndIncarnationScoped(t *testing.T) {
	first, err := remotehistory.ProviderLifetimeSegmentID(
		"generation-1", "object-1", remotehistory.LifetimeSegmentStartBootstrap, 1, nil,
	)
	if err != nil {
		t.Fatal(err)
	}
	again, err := remotehistory.ProviderLifetimeSegmentID(
		"generation-1", "object-1", remotehistory.LifetimeSegmentStartBootstrap, 1, nil,
	)
	if err != nil {
		t.Fatal(err)
	}
	if first != again {
		t.Fatalf("deterministic ID changed: %q != %q", first, again)
	}
	otherGeneration, err := remotehistory.ProviderLifetimeSegmentID(
		"generation-2", "object-1", remotehistory.LifetimeSegmentStartBootstrap, 1, nil,
	)
	if err != nil {
		t.Fatal(err)
	}
	if first == otherGeneration {
		t.Fatal("same native object across generations reused lifetime segment identity")
	}
	ordinal := int64(4)
	reappeared, err := remotehistory.ProviderLifetimeSegmentID(
		"generation-1", "object-1", remotehistory.LifetimeSegmentStartUpsert, 7, &ordinal,
	)
	if err != nil {
		t.Fatal(err)
	}
	if first == reappeared {
		t.Fatal("same native object reappearance reused bootstrap lifetime segment identity")
	}
}

func TestValidateProviderObjectLifetimeSegmentRejectsTamperedID(t *testing.T) {
	id, err := remotehistory.ProviderLifetimeSegmentID(
		"generation-1", "object-1", remotehistory.LifetimeSegmentStartBootstrap, 1, nil,
	)
	if err != nil {
		t.Fatal(err)
	}
	segment := remotehistory.ProviderObjectLifetimeSegment{
		ID: id,
		GenerationID: "generation-1",
		ProviderObjectID: "object-1",
		StartKind: remotehistory.LifetimeSegmentStartBootstrap,
		StartPublicationSequence: 1,
		LastPresentPublicationSequence: 1,
		Status: remotehistory.LifetimeSegmentActive,
	}
	if err := remotehistory.ValidateProviderObjectLifetimeSegment(segment); err != nil {
		t.Fatal(err)
	}
	segment.ID = "hseg_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	if err := remotehistory.ValidateProviderObjectLifetimeSegment(segment); err == nil {
		t.Fatal("tampered lifetime segment ID unexpectedly validated")
	}
}
