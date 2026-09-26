package sqlitestate

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory/gdrive"
)

func TestRemoteSourceBoundNewAcceptanceUsesHistoryUniverseAuthorityAndManagedScanScope(t *testing.T) {
	ctx := context.Background()
	fixture := newGoogleRemoteCompletionFixture(t)
	entries := []remotehistory.RemoteMetadataFingerprintEntry{
		fixture.entry("managed", corpus.EntryOther, 0, fixture.base),
		fixture.entry("child", corpus.EntryRegularFile, 7, fixture.base.Add(time.Second)),
	}
	scan, err := fixture.startScan(entries, fixture.scanRoot)
	if err != nil {
		t.Fatal(err)
	}
	segments, err := fixture.store.RemoteHistoryLifetimeSegments(ctx, fixture.generation.ID)
	if err != nil {
		t.Fatal(err)
	}
	segment := findLatestLifetimeSegment(segments, "child")
	authority, err := fixture.store.CreateRemoteHistoryIdentityAuthority(
		ctx, fixture.generation.ID, segment.ID, scan.StartedAt,
	)
	if err != nil {
		t.Fatal(err)
	}
	if authority.ScopeID == scan.Root {
		t.Fatalf("test does not exercise history-universe != managed-root scope: authority=%q scan=%q", authority.ScopeID, scan.Root)
	}
	entry := entries[1]
	modifiedAt, err := time.Parse(time.RFC3339Nano, entry.ModifiedAt)
	if err != nil {
		t.Fatal(err)
	}
	accepted, err := fixture.store.AcceptNewObservationInScan(ctx, corpus.IdentityMutationRequest{
		ID: "req-remote-source-new",
		ScanID: scan.ID,
		Observation: corpus.ObservationRecordInput{
			ProviderObject: corpus.ProviderObject{
				ProviderID: gdrive.ProviderID, ID: entry.ProviderObjectID, IdentityState: corpus.ObjectIdentityObserved,
			},
			Locators: append([]corpus.Locator(nil), entry.Locators...),
			AssignmentState: corpus.AssignmentUnresolved,
			ObservedAt: scan.StartedAt,
			Kind: entry.Kind, Size: entry.Size, Mode: entry.Mode, ModifiedAt: modifiedAt,
		},
		AuthoritySetID: authority.ID,
		DecidedAt: scan.StartedAt,
	})
	if err != nil {
		t.Fatal(err)
	}
	if accepted.Observation.ArtifactID == "" || accepted.Decision.LifetimeSegmentID != string(segment.ID) {
		t.Fatalf("acceptance=%#v", accepted)
	}
	if err := fixture.store.AbortScan(ctx, scan.ID, scan.StartedAt.Add(time.Second)); err != nil {
		t.Fatal(err)
	}
}

func TestRemoteSourceBoundIdentityMutationRejectsFreshAuthorityAfterHistoryAdvance(t *testing.T) {
	ctx := context.Background()
	fixture := newGoogleRemoteCompletionFixture(t)
	entries := []remotehistory.RemoteMetadataFingerprintEntry{
		fixture.entry("managed", corpus.EntryOther, 0, fixture.base),
		fixture.entry("child", corpus.EntryRegularFile, 7, fixture.base.Add(time.Second)),
	}
	scan, err := fixture.startScan(entries, fixture.scanRoot)
	if err != nil {
		t.Fatal(err)
	}

	cycle := gdrive.ChangeCycleBundle{
		History: remotehistory.ChangeCycle{
			StreamID: fixture.generation.Scope.StreamID,
			Status: remotehistory.CycleComplete,
			PreviousCursor: "cursor-1",
			NextCursor: "cursor-2",
			Coverage: corpus.ProviderHistoryContinuous,
		},
	}
	if _, err := fixture.store.PublishGoogleDriveRemoteHistoryCycle(
		ctx,
		fixture.generation.ID,
		fixture.generation.Scope,
		remotehistory.ScopePolicyFingerprint("google-drive-history-universe:v1:test"),
		1,
		"cursor-1",
		cycle,
		fixture.base.Add(2*time.Minute),
	); err != nil {
		t.Fatal(err)
	}
	segments, err := fixture.store.RemoteHistoryLifetimeSegments(ctx, fixture.generation.ID)
	if err != nil {
		t.Fatal(err)
	}
	segment := findLatestLifetimeSegment(segments, "child")
	freshAuthority, err := fixture.store.CreateRemoteHistoryIdentityAuthority(
		ctx, fixture.generation.ID, segment.ID, fixture.base.Add(3*time.Minute),
	)
	if err != nil {
		t.Fatal(err)
	}

	entry := entries[1]
	modifiedAt, err := time.Parse(time.RFC3339Nano, entry.ModifiedAt)
	if err != nil {
		t.Fatal(err)
	}
	beforeArtifacts := internalTableCount(t, fixture.store.Path(), "artifacts")
	beforeRequests := internalTableCount(t, fixture.store.Path(), "identity_mutation_requests")
	_, err = fixture.store.AcceptNewObservationInScan(ctx, corpus.IdentityMutationRequest{
		ID: "req-remote-source-advanced",
		ScanID: scan.ID,
		Observation: corpus.ObservationRecordInput{
			ProviderObject: corpus.ProviderObject{
				ProviderID: gdrive.ProviderID, ID: entry.ProviderObjectID, IdentityState: corpus.ObjectIdentityObserved,
			},
			Locators: append([]corpus.Locator(nil), entry.Locators...),
			AssignmentState: corpus.AssignmentUnresolved,
			ObservedAt: scan.StartedAt,
			Kind: entry.Kind, Size: entry.Size, Mode: entry.Mode, ModifiedAt: modifiedAt,
		},
		AuthoritySetID: freshAuthority.ID,
		DecidedAt: fixture.base.Add(3*time.Minute),
	})
	if !errors.Is(err, ErrRemoteHistoryScanSourceAdvanced) {
		t.Fatalf("error=%v want ErrRemoteHistoryScanSourceAdvanced", err)
	}
	if internalTableCount(t, fixture.store.Path(), "artifacts") != beforeArtifacts ||
		internalTableCount(t, fixture.store.Path(), "identity_mutation_requests") != beforeRequests {
		t.Fatal("advanced source mutated identity state")
	}
	if err := fixture.store.AbortScan(ctx, scan.ID, fixture.base.Add(3*time.Minute)); err != nil {
		t.Fatal(err)
	}
}
