package ingest_test

import (
	"context"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/ingest"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory/gdrive"
)

func TestRemoteIdentityMaterializationNewCreatesArtifactWithoutForcedRevision(t *testing.T) {
	ctx := context.Background()
	fixture := newGoogleRemoteFixture(t, "account-A", false)
	snapshot := fixture.snapshot(
		remoteMetadataEntry("managed", corpus.EntryOther, 0, 0, fixture.base),
		remoteMetadataEntry("child", corpus.EntryRegularFile, 7, 0, fixture.base.Add(time.Second)),
	)

	scan, replayed, err := ingest.MaterializeRemoteMetadataWithIdentity(
		ctx, fixture.store, fixture.projection, snapshot,
		ingest.RemoteIdentityMaterializationOptions{}, fixture.base.Add(time.Minute),
	)
	if err != nil {
		t.Fatal(err)
	}
	if replayed || scan.Status != corpus.ScanComplete {
		t.Fatalf("replayed=%v scan=%#v", replayed, scan)
	}
	child := remoteInventoryObservation(t, fixture, "child")
	if child.AssignmentState != corpus.AssignmentAssigned || child.ArtifactID == "" {
		t.Fatalf("NEW child was not assigned: %#v", child)
	}
	if child.RevisionID != "" {
		t.Fatalf("NEW without content evidence invented Revision: %#v", child)
	}
}

func TestRemoteIdentityMaterializationRegularSameWithoutEvidenceRemainsUnresolved(t *testing.T) {
	ctx := context.Background()
	fixture := newGoogleRemoteFixture(t, "account-A", false)
	firstSnapshot := fixture.snapshot(
		remoteMetadataEntry("managed", corpus.EntryOther, 0, 0, fixture.base),
		remoteMetadataEntry("child", corpus.EntryRegularFile, 7, 0, fixture.base.Add(time.Second)),
	)
	if _, _, err := ingest.MaterializeRemoteMetadataWithIdentity(
		ctx, fixture.store, fixture.projection, firstSnapshot,
		ingest.RemoteIdentityMaterializationOptions{}, fixture.base.Add(time.Minute),
	); err != nil {
		t.Fatal(err)
	}
	firstChild := remoteInventoryObservation(t, fixture, "child")
	firstManaged := remoteInventoryObservation(t, fixture, "managed")

	advanceGoogleRemoteFixture(t, fixture, "cursor-1", "cursor-2", fixture.base.Add(90*time.Second))
	secondSnapshot := fixture.snapshot(
		remoteMetadataEntry("managed", corpus.EntryOther, 0, 0, fixture.base),
		remoteMetadataEntry("child", corpus.EntryRegularFile, 7, 0, fixture.base.Add(time.Second)),
	)
	secondSnapshot.PublicationSequence = 2
	if _, _, err := ingest.MaterializeRemoteMetadataWithIdentity(
		ctx, fixture.store, fixture.projection, secondSnapshot,
		ingest.RemoteIdentityMaterializationOptions{}, fixture.base.Add(2*time.Minute),
	); err != nil {
		t.Fatal(err)
	}

	secondChild := remoteInventoryObservation(t, fixture, "child")
	if secondChild.AssignmentState != corpus.AssignmentUnresolved ||
		secondChild.ArtifactID != "" || secondChild.RevisionID != "" {
		t.Fatalf("regular SAME without evidence bypassed defer boundary: %#v", secondChild)
	}
	secondManaged := remoteInventoryObservation(t, fixture, "managed")
	if secondManaged.AssignmentState != corpus.AssignmentAssigned ||
		secondManaged.ArtifactID == "" ||
		secondManaged.ArtifactID != firstManaged.ArtifactID {
		t.Fatalf("non-regular SAME did not preserve Artifact: first=%#v second=%#v", firstManaged, secondManaged)
	}
	if firstChild.ArtifactID == "" {
		t.Fatal("first child NEW artifact missing")
	}
}

func TestRemoteIdentityMaterializationRegularSameWithExactSourceEvidenceCreatesRevision(t *testing.T) {
	ctx := context.Background()
	fixture := newGoogleRemoteFixture(t, "account-A", false)
	firstSnapshot := fixture.snapshot(
		remoteMetadataEntry("managed", corpus.EntryOther, 0, 0, fixture.base),
		remoteMetadataEntry("child", corpus.EntryRegularFile, 7, 0, fixture.base.Add(time.Second)),
	)
	if _, _, err := ingest.MaterializeRemoteMetadataWithIdentity(
		ctx, fixture.store, fixture.projection, firstSnapshot,
		ingest.RemoteIdentityMaterializationOptions{}, fixture.base.Add(time.Minute),
	); err != nil {
		t.Fatal(err)
	}
	firstChild := remoteInventoryObservation(t, fixture, "child")

	advanceGoogleRemoteFixture(t, fixture, "cursor-1", "cursor-2", fixture.base.Add(90*time.Second))
	secondSnapshot := fixture.snapshot(
		remoteMetadataEntry("managed", corpus.EntryOther, 0, 0, fixture.base),
		remoteMetadataEntry("child", corpus.EntryRegularFile, 7, 0, fixture.base.Add(time.Second)),
	)
	secondSnapshot.PublicationSequence = 2
	options := ingest.RemoteIdentityMaterializationOptions{
		ContentEvidence: []ingest.RemoteSourceContentEvidence{{
			GenerationID:        fixture.generation.ID,
			PublicationSequence: 2,
			ProviderObjectID:    "child",
			SourceRef:           "deterministic-test:child:publication-2",
			Evidence: corpus.ContentEvidence{
				Algorithm: corpus.ContentAlgorithmSHA256,
				Digest:    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
				Size:      7,
			},
		}},
	}
	if _, _, err := ingest.MaterializeRemoteMetadataWithIdentity(
		ctx, fixture.store, fixture.projection, secondSnapshot,
		options, fixture.base.Add(2*time.Minute),
	); err != nil {
		t.Fatal(err)
	}

	secondChild := remoteInventoryObservation(t, fixture, "child")
	if secondChild.AssignmentState != corpus.AssignmentAssigned ||
		secondChild.ArtifactID != firstChild.ArtifactID ||
		secondChild.RevisionID == "" {
		t.Fatalf("regular SAME with evidence failed identity/revision integration: first=%#v second=%#v", firstChild, secondChild)
	}
}

func TestRemoteIdentityMaterializationRejectsContentEvidenceFromDifferentSourceBoundary(t *testing.T) {
	fixture := newGoogleRemoteFixture(t, "account-A", false)
	snapshot := fixture.snapshot(
		remoteMetadataEntry("managed", corpus.EntryOther, 0, 0, fixture.base),
		remoteMetadataEntry("child", corpus.EntryRegularFile, 7, 0, fixture.base.Add(time.Second)),
	)
	_, _, err := ingest.MaterializeRemoteMetadataWithIdentity(
		context.Background(), fixture.store, fixture.projection, snapshot,
		ingest.RemoteIdentityMaterializationOptions{
			ContentEvidence: []ingest.RemoteSourceContentEvidence{{
				GenerationID:        fixture.generation.ID,
				PublicationSequence: 2,
				ProviderObjectID:    "child",
				SourceRef:           "wrong-boundary",
				Evidence: corpus.ContentEvidence{
					Algorithm: corpus.ContentAlgorithmSHA256,
					Digest:    "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
					Size:      7,
				},
			}},
		},
		fixture.base.Add(time.Minute),
	)
	if err == nil {
		t.Fatal("mismatched source-bound content evidence was accepted")
	}
	inventory, invErr := fixture.store.Inventory(context.Background(), gdrive.ProviderID, fixture.scanRoot)
	if invErr != nil {
		t.Fatal(invErr)
	}
	if len(inventory) != 0 {
		t.Fatalf("invalid content evidence started/published inventory: %#v", inventory)
	}
}

func remoteInventoryObservation(t *testing.T, fixture googleRemoteFixture, objectID corpus.ProviderObjectID) corpus.ObservationRecord {
	t.Helper()
	inventory, err := fixture.store.Inventory(context.Background(), gdrive.ProviderID, fixture.scanRoot)
	if err != nil {
		t.Fatal(err)
	}
	for _, item := range inventory {
		observation, err := fixture.store.Observation(context.Background(), item.ObservationID)
		if err != nil {
			t.Fatal(err)
		}
		if observation.ProviderObject.ID == objectID {
			return observation
		}
	}
	t.Fatalf("object %s not found in current inventory", objectID)
	return corpus.ObservationRecord{}
}

func advanceGoogleRemoteFixture(
	t *testing.T,
	fixture googleRemoteFixture,
	previousCursor remotehistory.HistoryCursor,
	nextCursor remotehistory.HistoryCursor,
	committedAt time.Time,
) {
	t.Helper()
	cycle := gdrive.ChangeCycleBundle{
		History: remotehistory.ChangeCycle{
			StreamID:       fixture.scope.StreamID,
			Status:         remotehistory.CycleComplete,
			PreviousCursor: previousCursor,
			NextCursor:     nextCursor,
			Coverage:       corpus.ProviderHistoryContinuous,
		},
	}
	if _, err := fixture.store.PublishGoogleDriveRemoteHistoryCycle(
		context.Background(),
		fixture.generation.ID,
		fixture.scope,
		fixture.scopeFingerprint,
		fixture.generation.CurrentSequence,
		previousCursor,
		cycle,
		committedAt,
	); err != nil {
		t.Fatal(err)
	}
}
