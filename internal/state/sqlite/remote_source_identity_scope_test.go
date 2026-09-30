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
			Kind: entry.Kind, Size: corpus.KnownSize(entry.Size), Mode: corpus.KnownMode(entry.Mode), ModifiedAt: corpus.KnownModifiedAt(modifiedAt),
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

func TestRemoteSourceBoundIdentityMutationRejectsObservationTimeOutsideScanBoundary(t *testing.T) {
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
	entry := entries[1]
	modifiedAt, err := time.Parse(time.RFC3339Nano, entry.ModifiedAt)
	if err != nil {
		t.Fatal(err)
	}
	beforeArtifacts := internalTableCount(t, fixture.store.Path(), "artifacts")
	beforeRequests := internalTableCount(t, fixture.store.Path(), "identity_mutation_requests")
	_, err = fixture.store.AcceptNewObservationInScan(ctx, corpus.IdentityMutationRequest{
		ID: "req-remote-source-bad-observed-at",
		ScanID: scan.ID,
		Observation: corpus.ObservationRecordInput{
			ProviderObject: corpus.ProviderObject{
				ProviderID: gdrive.ProviderID, ID: entry.ProviderObjectID, IdentityState: corpus.ObjectIdentityObserved,
			},
			Locators: append([]corpus.Locator(nil), entry.Locators...),
			AssignmentState: corpus.AssignmentUnresolved,
			ObservedAt: scan.StartedAt.Add(time.Nanosecond),
			Kind: entry.Kind, Size: corpus.KnownSize(entry.Size), Mode: corpus.KnownMode(entry.Mode), ModifiedAt: corpus.KnownModifiedAt(modifiedAt),
		},
		AuthoritySetID: authority.ID,
		DecidedAt: scan.StartedAt.Add(time.Nanosecond),
	})
	if !errors.Is(err, ErrScanScopeMismatch) {
		t.Fatalf("error=%v want ErrScanScopeMismatch", err)
	}
	if internalTableCount(t, fixture.store.Path(), "artifacts") != beforeArtifacts ||
		internalTableCount(t, fixture.store.Path(), "identity_mutation_requests") != beforeRequests {
		t.Fatal("out-of-bound observation time mutated identity state")
	}
	if err := fixture.store.AbortScan(ctx, scan.ID, scan.StartedAt.Add(time.Second)); err != nil {
		t.Fatal(err)
	}
}

func TestRemoteSourceBoundIdentityMutationRejectsNoncanonicalGoogleLocator(t *testing.T) {
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
	entry := entries[1]
	modifiedAt, err := time.Parse(time.RFC3339Nano, entry.ModifiedAt)
	if err != nil {
		t.Fatal(err)
	}
	beforeArtifacts := internalTableCount(t, fixture.store.Path(), "artifacts")
	beforeRequests := internalTableCount(t, fixture.store.Path(), "identity_mutation_requests")
	_, err = fixture.store.AcceptNewObservationInScan(ctx, corpus.IdentityMutationRequest{
		ID: "req-remote-source-bad-locator",
		ScanID: scan.ID,
		Observation: corpus.ObservationRecordInput{
			ProviderObject: corpus.ProviderObject{
				ProviderID: gdrive.ProviderID, ID: entry.ProviderObjectID, IdentityState: corpus.ObjectIdentityObserved,
			},
			Locators: []corpus.Locator{{
				ProviderID: gdrive.ProviderID,
				Root: fixture.scanRoot,
				Path: "file-id/not-child",
			}},
			AssignmentState: corpus.AssignmentUnresolved,
			ObservedAt: scan.StartedAt,
			Kind: entry.Kind, Size: corpus.KnownSize(entry.Size), Mode: corpus.KnownMode(entry.Mode), ModifiedAt: corpus.KnownModifiedAt(modifiedAt),
		},
		AuthoritySetID: authority.ID,
		DecidedAt: scan.StartedAt,
	})
	if !errors.Is(err, ErrScanScopeMismatch) {
		t.Fatalf("error=%v want ErrScanScopeMismatch", err)
	}
	if internalTableCount(t, fixture.store.Path(), "artifacts") != beforeArtifacts ||
		internalTableCount(t, fixture.store.Path(), "identity_mutation_requests") != beforeRequests {
		t.Fatal("noncanonical locator mutated identity state")
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
			Kind: entry.Kind, Size: corpus.KnownSize(entry.Size), Mode: corpus.KnownMode(entry.Mode), ModifiedAt: corpus.KnownModifiedAt(modifiedAt),
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

func TestRemoteSourceBoundSameAcceptanceAndReplaySurviveHistoryAdvance(t *testing.T) {
	ctx := context.Background()
	fixture := newGoogleRemoteCompletionFixture(t)
	entries := []remotehistory.RemoteMetadataFingerprintEntry{
		fixture.entry("managed", corpus.EntryOther, 0, fixture.base),
		fixture.entry("child", corpus.EntryRegularFile, 7, fixture.base.Add(time.Second)),
	}
	segments, err := fixture.store.RemoteHistoryLifetimeSegments(ctx, fixture.generation.ID)
	if err != nil {
		t.Fatal(err)
	}
	segment := findLatestLifetimeSegment(segments, "child")
	seedAuthority, err := fixture.store.CreateRemoteHistoryIdentityAuthority(
		ctx, fixture.generation.ID, segment.ID, fixture.base.Add(30*time.Second),
	)
	if err != nil {
		t.Fatal(err)
	}
	seedScan, err := fixture.store.StartScan(
		ctx, gdrive.ProviderID, fixture.generation.Scope.Root, fixture.base.Add(40*time.Second),
	)
	if err != nil {
		t.Fatal(err)
	}
	seedEntry := entries[1]
	seedModified, err := time.Parse(time.RFC3339Nano, seedEntry.ModifiedAt)
	if err != nil {
		t.Fatal(err)
	}
	seed, err := fixture.store.AcceptNewObservationInScan(ctx, corpus.IdentityMutationRequest{
		ID: "req-remote-source-same-seed",
		ScanID: seedScan.ID,
		Observation: corpus.ObservationRecordInput{
			ProviderObject: corpus.ProviderObject{
				ProviderID: gdrive.ProviderID, ID: seedEntry.ProviderObjectID, IdentityState: corpus.ObjectIdentityObserved,
			},
			Locators: []corpus.Locator{{
				ProviderID: gdrive.ProviderID,
				Root: fixture.generation.Scope.Root,
				Path: gdrive.FileIDLocatorPath(seedEntry.ProviderObjectID),
			}},
			AssignmentState: corpus.AssignmentUnresolved,
			ObservedAt: fixture.base.Add(40*time.Second),
			Kind: seedEntry.Kind, Size: corpus.KnownSize(seedEntry.Size), Mode: corpus.KnownMode(seedEntry.Mode), ModifiedAt: corpus.KnownModifiedAt(seedModified),
		},
		ContentEvidence: &corpus.ContentEvidence{
			Algorithm: corpus.ContentAlgorithmSHA256, Digest: "seed-seven", Size: 7,
		},
		AuthoritySetID: seedAuthority.ID,
		DecidedAt: fixture.base.Add(40*time.Second),
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := fixture.store.CompleteScan(ctx, seedScan.ID, fixture.base.Add(50*time.Second)); err != nil {
		t.Fatal(err)
	}

	scan, err := fixture.startScan(entries, fixture.scanRoot)
	if err != nil {
		t.Fatal(err)
	}
	sameAuthority, err := fixture.store.CreateRemoteHistoryIdentityAuthority(
		ctx, fixture.generation.ID, segment.ID, scan.StartedAt,
	)
	if err != nil {
		t.Fatal(err)
	}
	modifiedAt, err := time.Parse(time.RFC3339Nano, entries[1].ModifiedAt)
	if err != nil {
		t.Fatal(err)
	}
	request := corpus.IdentityMutationRequest{
		ID: "req-remote-source-same",
		ScanID: scan.ID,
		Observation: corpus.ObservationRecordInput{
			ProviderObject: corpus.ProviderObject{
				ProviderID: gdrive.ProviderID, ID: "child", IdentityState: corpus.ObjectIdentityObserved,
			},
			Locators: append([]corpus.Locator(nil), entries[1].Locators...),
			AssignmentState: corpus.AssignmentUnresolved,
			ObservedAt: scan.StartedAt,
			Kind: entries[1].Kind, Size: corpus.KnownSize(entries[1].Size), Mode: corpus.KnownMode(entries[1].Mode), ModifiedAt: corpus.KnownModifiedAt(modifiedAt),
		},
		ContentEvidence: &corpus.ContentEvidence{
			Algorithm: corpus.ContentAlgorithmSHA256, Digest: "seed-seven", Size: 7,
		},
		AuthoritySetID: sameAuthority.ID,
		DecidedAt: scan.StartedAt,
	}
	first, err := fixture.store.AcceptSameObservationInScan(ctx, request)
	if err != nil {
		t.Fatal(err)
	}
	if first.Observation.ArtifactID != seed.Observation.ArtifactID ||
		first.Revision == nil || first.Revision.Created {
		t.Fatalf("source-bound SAME=%#v seed=%#v", first, seed)
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
	beforeObs := internalTableCount(t, fixture.store.Path(), "observations")
	beforeRevisions := internalTableCount(t, fixture.store.Path(), "revisions")
	replay, err := fixture.store.AcceptSameObservationInScan(ctx, request)
	if err != nil {
		t.Fatal(err)
	}
	if !replay.Replayed || replay.Observation.ID != first.Observation.ID ||
		replay.Decision.ID != first.Decision.ID {
		t.Fatalf("historical SAME replay first=%#v replay=%#v", first, replay)
	}
	if internalTableCount(t, fixture.store.Path(), "observations") != beforeObs ||
		internalTableCount(t, fixture.store.Path(), "revisions") != beforeRevisions {
		t.Fatal("historical SAME replay mutated durable state")
	}
	if err := fixture.store.AbortScan(ctx, scan.ID, fixture.base.Add(3*time.Minute)); err != nil {
		t.Fatal(err)
	}
}

func TestRemoteSourceBoundSameRejectsFreshAuthorityAfterHistoryAdvance(t *testing.T) {
	ctx := context.Background()
	fixture := newGoogleRemoteCompletionFixture(t)
	entries := []remotehistory.RemoteMetadataFingerprintEntry{
		fixture.entry("managed", corpus.EntryOther, 0, fixture.base),
		fixture.entry("child", corpus.EntryRegularFile, 7, fixture.base.Add(time.Second)),
	}
	segments, err := fixture.store.RemoteHistoryLifetimeSegments(ctx, fixture.generation.ID)
	if err != nil {
		t.Fatal(err)
	}
	segment := findLatestLifetimeSegment(segments, "child")
	seedAuthority, err := fixture.store.CreateRemoteHistoryIdentityAuthority(
		ctx, fixture.generation.ID, segment.ID, fixture.base.Add(30*time.Second),
	)
	if err != nil {
		t.Fatal(err)
	}
	seedScan, err := fixture.store.StartScan(
		ctx, gdrive.ProviderID, fixture.generation.Scope.Root, fixture.base.Add(40*time.Second),
	)
	if err != nil {
		t.Fatal(err)
	}
	modifiedAt, err := time.Parse(time.RFC3339Nano, entries[1].ModifiedAt)
	if err != nil {
		t.Fatal(err)
	}
	seed, err := fixture.store.AcceptNewObservationInScan(ctx, corpus.IdentityMutationRequest{
		ID: "req-remote-source-same-advance-seed",
		ScanID: seedScan.ID,
		Observation: corpus.ObservationRecordInput{
			ProviderObject: corpus.ProviderObject{
				ProviderID: gdrive.ProviderID, ID: "child", IdentityState: corpus.ObjectIdentityObserved,
			},
			Locators: []corpus.Locator{{
				ProviderID: gdrive.ProviderID,
				Root: fixture.generation.Scope.Root,
				Path: gdrive.FileIDLocatorPath("child"),
			}},
			AssignmentState: corpus.AssignmentUnresolved,
			ObservedAt: fixture.base.Add(40*time.Second),
			Kind: entries[1].Kind, Size: corpus.KnownSize(entries[1].Size), Mode: corpus.KnownMode(entries[1].Mode), ModifiedAt: corpus.KnownModifiedAt(modifiedAt),
		},
		ContentEvidence: &corpus.ContentEvidence{
			Algorithm: corpus.ContentAlgorithmSHA256, Digest: "seed-advance", Size: 7,
		},
		AuthoritySetID: seedAuthority.ID,
		DecidedAt: fixture.base.Add(40*time.Second),
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := fixture.store.CompleteScan(ctx, seedScan.ID, fixture.base.Add(50*time.Second)); err != nil {
		t.Fatal(err)
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
	freshAuthority, err := fixture.store.CreateRemoteHistoryIdentityAuthority(
		ctx, fixture.generation.ID, segment.ID, fixture.base.Add(3*time.Minute),
	)
	if err != nil {
		t.Fatal(err)
	}
	beforeObs := internalTableCount(t, fixture.store.Path(), "observations")
	beforeRevisions := internalTableCount(t, fixture.store.Path(), "revisions")
	beforeDecisions := internalTableCount(t, fixture.store.Path(), "accepted_continuity_decisions")
	_, err = fixture.store.AcceptSameObservationInScan(ctx, corpus.IdentityMutationRequest{
		ID: "req-remote-source-same-advanced",
		ScanID: scan.ID,
		Observation: corpus.ObservationRecordInput{
			ProviderObject: corpus.ProviderObject{
				ProviderID: gdrive.ProviderID, ID: "child", IdentityState: corpus.ObjectIdentityObserved,
			},
			Locators: append([]corpus.Locator(nil), entries[1].Locators...),
			AssignmentState: corpus.AssignmentUnresolved,
			ObservedAt: scan.StartedAt,
			Kind: entries[1].Kind, Size: corpus.KnownSize(entries[1].Size), Mode: corpus.KnownMode(entries[1].Mode), ModifiedAt: corpus.KnownModifiedAt(modifiedAt),
		},
		ContentEvidence: &corpus.ContentEvidence{
			Algorithm: corpus.ContentAlgorithmSHA256, Digest: "seed-advance", Size: 7,
		},
		AuthoritySetID: freshAuthority.ID,
		DecidedAt: fixture.base.Add(3*time.Minute),
	})
	if !errors.Is(err, ErrRemoteHistoryScanSourceAdvanced) {
		t.Fatalf("error=%v want ErrRemoteHistoryScanSourceAdvanced", err)
	}
	if internalTableCount(t, fixture.store.Path(), "observations") != beforeObs ||
		internalTableCount(t, fixture.store.Path(), "revisions") != beforeRevisions ||
		internalTableCount(t, fixture.store.Path(), "accepted_continuity_decisions") != beforeDecisions {
		t.Fatal("advanced source SAME mutated identity state")
	}
	if seed.Observation.ArtifactID == "" {
		t.Fatal("seed binding missing")
	}
	if err := fixture.store.AbortScan(ctx, scan.ID, fixture.base.Add(3*time.Minute)); err != nil {
		t.Fatal(err)
	}
}

func TestRemoteSourceBoundIdentityMutationRejectsUnsupportedProvider(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")
	base := time.Date(2026, 9, 27, 23, 30, 0, 0, time.UTC)
	generation, err := store.StartRemoteHistoryGeneration(
		ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), base,
	)
	if err != nil {
		t.Fatal(err)
	}
	segments, err := store.RemoteHistoryLifetimeSegments(ctx, generation.ID)
	if err != nil {
		t.Fatal(err)
	}
	segment := findLatestLifetimeSegment(segments, "id-1")
	authority, err := store.CreateRemoteHistoryIdentityAuthority(
		ctx, generation.ID, segment.ID, base.Add(time.Minute),
	)
	if err != nil {
		t.Fatal(err)
	}
	fingerprint, err := remotehistory.FingerprintRemoteMetadataSnapshot(remotehistory.RemoteMetadataFingerprintInput{
		GenerationID: generation.ID,
		PublicationSequence: 1,
		ProviderID: scope.ProviderID,
		ScanRoot: scope.Root,
		SourceScopeID: "scope",
		MaterializationPolicyID: remotehistory.LightweightAllMaterializationPolicyID,
		Entries: []remotehistory.RemoteMetadataFingerprintEntry{{
			ProviderObjectID: "id-1",
			Locators: []corpus.Locator{{ProviderID: scope.ProviderID, Root: scope.Root, Path: "id-1"}},
			Kind: corpus.EntryOther,
			Size: 0,
			Mode: 0,
			ModifiedAt: base.UTC().Format(time.RFC3339Nano),
		}},
	})
	if err != nil {
		t.Fatal(err)
	}
	scan, _, err := store.StartRemoteHistoryScan(ctx, scope.Root, remotehistory.RemoteScanSourceInput{
		GenerationID: generation.ID,
		PublicationSequence: 1,
		SourceScopeID: "scope",
		MaterializationPolicyID: remotehistory.LightweightAllMaterializationPolicyID,
		SnapshotFingerprintVersion: remotehistory.RemoteMetadataSnapshotFingerprintVersion,
		SnapshotFingerprintSHA256: fingerprint,
	}, base.Add(time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	beforeArtifacts := internalTableCount(t, store.Path(), "artifacts")
	_, err = store.AcceptNewObservationInScan(ctx, corpus.IdentityMutationRequest{
		ID: "req-remote-source-unsupported-provider",
		ScanID: scan.ID,
		Observation: corpus.ObservationRecordInput{
			ProviderObject: corpus.ProviderObject{
				ProviderID: scope.ProviderID, ID: "id-1", IdentityState: corpus.ObjectIdentityObserved,
			},
			Locators: []corpus.Locator{{ProviderID: scope.ProviderID, Root: scope.Root, Path: "id-1"}},
			AssignmentState: corpus.AssignmentUnresolved,
			ObservedAt: scan.StartedAt,
			Kind: corpus.EntryOther,
			Size: corpus.KnownSize(0),
			Mode: corpus.KnownMode(0),
			ModifiedAt: corpus.KnownModifiedAt(base),
		},
		AuthoritySetID: authority.ID,
		DecidedAt: scan.StartedAt,
	})
	if !errors.Is(err, ErrScanScopeMismatch) {
		t.Fatalf("error=%v want ErrScanScopeMismatch", err)
	}
	if internalTableCount(t, store.Path(), "artifacts") != beforeArtifacts {
		t.Fatal("unsupported provider identity mutation minted Artifact")
	}
	if err := store.AbortScan(ctx, scan.ID, base.Add(2*time.Minute)); err != nil {
		t.Fatal(err)
	}
}
