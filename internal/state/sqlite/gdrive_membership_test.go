package sqlitestate

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory/gdrive"
	"zombiezen.com/go/sqlite"
)

func TestGoogleManagedRootMembershipClassifiesReachability(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := googleTopologyTestScope()
	fp := remotehistory.ScopePolicyFingerprint("google-drive-history-universe:v1:test")
	base := time.Date(2026, 9, 26, 22, 0, 0, 0, time.UTC)

	bundle := googleMembershipBootstrapBundle(scope, []gdrive.TopologyState{
		topologyPresent("managed", corpus.ProviderObjectID(scope.Root)),
		topologyPresent("direct", "managed"),
		topologyPresent("folder-a", "managed"),
		topologyPresent("deep", "folder-a"),
		topologyPresent("outside-folder", corpus.ProviderObjectID(scope.Root)),
		topologyPresent("outside", "outside-folder"),
		{ObjectID: "unknown-parent", Presence: gdrive.TopologyPresent, ParentKnowledge: gdrive.ParentUnknown},
		topologyPresent("missing-parent", "not-visible"),
	})
	generation, err := store.StartGoogleDriveRemoteHistoryGeneration(ctx, scope, fp, bundle, base)
	if err != nil {
		t.Fatal(err)
	}

	binding, err := store.BindGoogleDriveManagedRoot(ctx, generation.ID, "managed", base.Add(time.Second))
	if err != nil {
		t.Fatal(err)
	}
	if binding.BoundSequence != 1 || binding.ManagedRootObjectID != "managed" {
		t.Fatalf("binding=%#v", binding)
	}
	replayed, err := store.BindGoogleDriveManagedRoot(ctx, generation.ID, "managed", base.Add(2*time.Second))
	if err != nil {
		t.Fatal(err)
	}
	if replayed != binding {
		t.Fatalf("binding replay changed durable result: first=%#v replay=%#v", binding, replayed)
	}

	cases := []struct {
		name   string
		object corpus.ProviderObjectID
		state  gdrive.ManagedRootMembership
		reason gdrive.MembershipUnknownReason
	}{
		{name: "managed root", object: "managed", state: gdrive.MembershipIn},
		{name: "direct child", object: "direct", state: gdrive.MembershipIn},
		{name: "deep descendant", object: "deep", state: gdrive.MembershipIn},
		{name: "outside subtree", object: "outside", state: gdrive.MembershipOut},
		{name: "unknown parent", object: "unknown-parent", state: gdrive.MembershipUnknown, reason: gdrive.UnknownMissingParent},
		{name: "missing ancestor row", object: "missing-parent", state: gdrive.MembershipUnknown, reason: gdrive.UnknownMissingParent},
		{name: "missing object", object: "absent-object", state: gdrive.MembershipUnknown, reason: gdrive.UnknownObjectUnavailable},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got, err := store.GoogleDriveManagedRootMembership(ctx, generation.ID, 1, "managed", tc.object)
			if err != nil {
				t.Fatal(err)
			}
			if got.State != tc.state || got.Reason != tc.reason {
				t.Fatalf("membership=%#v want state=%s reason=%s", got, tc.state, tc.reason)
			}
		})
	}

	rootBinding, err := store.BindGoogleDriveManagedRoot(ctx, generation.ID, corpus.ProviderObjectID(scope.Root), base.Add(3*time.Second))
	if err != nil {
		t.Fatal(err)
	}
	if rootBinding.ManagedRootObjectID != corpus.ProviderObjectID(scope.Root) {
		t.Fatalf("root binding=%#v", rootBinding)
	}
	got, err := store.GoogleDriveManagedRootMembership(ctx, generation.ID, 1, corpus.ProviderObjectID(scope.Root), "outside")
	if err != nil {
		t.Fatal(err)
	}
	if got.State != gdrive.MembershipIn {
		t.Fatalf("provider-root membership=%#v", got)
	}
}

func TestGoogleManagedRootMembershipRequiresDurableBinding(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := googleTopologyTestScope()
	fp := remotehistory.ScopePolicyFingerprint("google-drive-history-universe:v1:test")
	generation, err := store.StartGoogleDriveRemoteHistoryGeneration(
		ctx,
		scope,
		fp,
		googleMembershipBootstrapBundle(scope, []gdrive.TopologyState{
			topologyPresent("managed", corpus.ProviderObjectID(scope.Root)),
			topologyPresent("child", "managed"),
		}),
		time.Now().UTC(),
	)
	if err != nil {
		t.Fatal(err)
	}
	_, err = store.GoogleDriveManagedRootMembership(ctx, generation.ID, 1, "managed", "child")
	if !errors.Is(err, ErrGoogleManagedRootBindingNotFound) {
		t.Fatalf("error=%v want ErrGoogleManagedRootBindingNotFound", err)
	}
}

func TestGoogleManagedRootMembershipDetectsCycle(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := googleTopologyTestScope()
	fp := remotehistory.ScopePolicyFingerprint("google-drive-history-universe:v1:test")
	generation, err := store.StartGoogleDriveRemoteHistoryGeneration(
		ctx,
		scope,
		fp,
		googleMembershipBootstrapBundle(scope, []gdrive.TopologyState{
			topologyPresent("managed", corpus.ProviderObjectID(scope.Root)),
			topologyPresent("cycle-a", "cycle-b"),
			topologyPresent("cycle-b", "cycle-a"),
		}),
		time.Now().UTC(),
	)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.BindGoogleDriveManagedRoot(ctx, generation.ID, "managed", time.Now().UTC()); err != nil {
		t.Fatal(err)
	}
	got, err := store.GoogleDriveManagedRootMembership(ctx, generation.ID, 1, "managed", "cycle-a")
	if err != nil {
		t.Fatal(err)
	}
	if got.State != gdrive.MembershipUnknown || got.Reason != gdrive.UnknownCycle {
		t.Fatalf("cycle membership=%#v", got)
	}
}

func TestGoogleManagedRootMembershipFailsClosedOnStaleWatermark(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := googleTopologyTestScope()
	fp := remotehistory.ScopePolicyFingerprint("google-drive-history-universe:v1:test")
	base := time.Date(2026, 9, 26, 22, 30, 0, 0, time.UTC)
	generation, err := store.StartGoogleDriveRemoteHistoryGeneration(
		ctx,
		scope,
		fp,
		googleMembershipBootstrapBundle(scope, []gdrive.TopologyState{
			topologyPresent("managed", corpus.ProviderObjectID(scope.Root)),
			topologyPresent("child", "managed"),
		}),
		base,
	)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.BindGoogleDriveManagedRoot(ctx, generation.ID, "managed", base.Add(time.Second)); err != nil {
		t.Fatal(err)
	}

	cycle := remotehistory.ChangeCycle{
		StreamID:       scope.StreamID,
		Status:         remotehistory.CycleComplete,
		PreviousCursor: "cursor-1",
		NextCursor:     "cursor-2",
		Coverage:       corpus.ProviderHistoryContinuous,
		Changes: []remotehistory.RemoteChange{{
			Kind:     remotehistory.ChangeUpsert,
			ObjectID: "child",
			State:    googleTopologyObject(scope, "child"),
		}},
	}
	_, err = store.publishRemoteHistoryCycleWithSidecar(
		ctx,
		generation.ID,
		scope,
		fp,
		1,
		"cursor-1",
		cycle,
		base.Add(2*time.Second),
		func(*sqlite.Conn, remotehistory.HistoryGeneration, remotehistory.HistoryPublicationSequence, []remotehistory.RemoteChange) error {
			return nil
		},
	)
	if err != nil {
		t.Fatal(err)
	}

	got, err := store.GoogleDriveManagedRootMembership(ctx, generation.ID, 2, "managed", "child")
	if err != nil {
		t.Fatal(err)
	}
	if got.State != gdrive.MembershipUnknown || got.Reason != gdrive.UnknownTopologyStale {
		t.Fatalf("stale topology membership=%#v", got)
	}
}

func TestAncestorMoveChangesMembershipWithoutChangingDescendantLifetime(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := googleTopologyTestScope()
	fp := remotehistory.ScopePolicyFingerprint("google-drive-history-universe:v1:test")
	base := time.Date(2026, 9, 26, 23, 0, 0, 0, time.UTC)

	generation, err := store.StartGoogleDriveRemoteHistoryGeneration(
		ctx,
		scope,
		fp,
		googleMembershipBootstrapBundle(scope, []gdrive.TopologyState{
			topologyPresent("managed", corpus.ProviderObjectID(scope.Root)),
			topologyPresent("ancestor", "managed"),
			topologyPresent("descendant", "ancestor"),
			topologyPresent("outside", corpus.ProviderObjectID(scope.Root)),
		}),
		base,
	)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.BindGoogleDriveManagedRoot(ctx, generation.ID, "managed", base.Add(time.Second)); err != nil {
		t.Fatal(err)
	}

	before := lifetimeSegmentForObject(t, store, generation.ID, "descendant")
	initial, err := store.GoogleDriveManagedRootMembership(ctx, generation.ID, 1, "managed", "descendant")
	if err != nil {
		t.Fatal(err)
	}
	if initial.State != gdrive.MembershipIn {
		t.Fatalf("initial membership=%#v", initial)
	}

	moveOut := gdrive.ChangeCycleBundle{
		History: remotehistory.ChangeCycle{
			StreamID:       scope.StreamID,
			Status:         remotehistory.CycleComplete,
			PreviousCursor: "cursor-1",
			NextCursor:     "cursor-2",
			Coverage:       corpus.ProviderHistoryContinuous,
			Changes: []remotehistory.RemoteChange{{
				Kind:     remotehistory.ChangeUpsert,
				ObjectID: "ancestor",
				State:    googleTopologyObject(scope, "ancestor"),
			}},
		},
		Topology: []gdrive.TopologyState{topologyPresent("ancestor", "outside")},
	}
	generation, err = store.PublishGoogleDriveRemoteHistoryCycle(
		ctx, generation.ID, scope, fp, 1, "cursor-1", moveOut, base.Add(2*time.Second),
	)
	if err != nil {
		t.Fatal(err)
	}
	outside, err := store.GoogleDriveManagedRootMembership(ctx, generation.ID, 2, "managed", "descendant")
	if err != nil {
		t.Fatal(err)
	}
	if outside.State != gdrive.MembershipOut {
		t.Fatalf("after ancestor move out=%#v", outside)
	}
	afterOut := lifetimeSegmentForObject(t, store, generation.ID, "descendant")
	if afterOut.ID != before.ID || afterOut.Status != before.Status {
		t.Fatalf("descendant lifetime changed on ancestor move: before=%#v after=%#v", before, afterOut)
	}

	moveBack := gdrive.ChangeCycleBundle{
		History: remotehistory.ChangeCycle{
			StreamID:       scope.StreamID,
			Status:         remotehistory.CycleComplete,
			PreviousCursor: "cursor-2",
			NextCursor:     "cursor-3",
			Coverage:       corpus.ProviderHistoryContinuous,
			Changes: []remotehistory.RemoteChange{{
				Kind:     remotehistory.ChangeUpsert,
				ObjectID: "ancestor",
				State:    googleTopologyObject(scope, "ancestor"),
			}},
		},
		Topology: []gdrive.TopologyState{topologyPresent("ancestor", "managed")},
	}
	generation, err = store.PublishGoogleDriveRemoteHistoryCycle(
		ctx, generation.ID, scope, fp, 2, "cursor-2", moveBack, base.Add(3*time.Second),
	)
	if err != nil {
		t.Fatal(err)
	}
	back, err := store.GoogleDriveManagedRootMembership(ctx, generation.ID, 3, "managed", "descendant")
	if err != nil {
		t.Fatal(err)
	}
	if back.State != gdrive.MembershipIn {
		t.Fatalf("after ancestor move back=%#v", back)
	}
	afterBack := lifetimeSegmentForObject(t, store, generation.ID, "descendant")
	if afterBack.ID != before.ID || afterBack.Status != before.Status {
		t.Fatalf("descendant lifetime changed after move back: before=%#v after=%#v", before, afterBack)
	}
	if err := store.VerifyRemoteHistoryLifetimeSegments(ctx, generation.ID); err != nil {
		t.Fatal(err)
	}
}

func TestRemovedObjectMembershipIsUnknownNotDeletionOrOut(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := googleTopologyTestScope()
	fp := remotehistory.ScopePolicyFingerprint("google-drive-history-universe:v1:test")
	base := time.Date(2026, 9, 26, 23, 30, 0, 0, time.UTC)

	generation, err := store.StartGoogleDriveRemoteHistoryGeneration(
		ctx,
		scope,
		fp,
		googleMembershipBootstrapBundle(scope, []gdrive.TopologyState{
			topologyPresent("managed", corpus.ProviderObjectID(scope.Root)),
			topologyPresent("child", "managed"),
		}),
		base,
	)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.BindGoogleDriveManagedRoot(ctx, generation.ID, "managed", base.Add(time.Second)); err != nil {
		t.Fatal(err)
	}

	remove := gdrive.ChangeCycleBundle{
		History: remotehistory.ChangeCycle{
			StreamID:       scope.StreamID,
			Status:         remotehistory.CycleComplete,
			PreviousCursor: "cursor-1",
			NextCursor:     "cursor-2",
			Coverage:       corpus.ProviderHistoryContinuous,
			Changes: []remotehistory.RemoteChange{{
				Kind:     remotehistory.ChangeRemoved,
				ObjectID: "child",
			}},
		},
		Topology: []gdrive.TopologyState{{
			ObjectID:        "child",
			Presence:        gdrive.TopologyUnavailable,
			ParentKnowledge: gdrive.ParentUnavailable,
		}},
	}
	generation, err = store.PublishGoogleDriveRemoteHistoryCycle(
		ctx, generation.ID, scope, fp, 1, "cursor-1", remove, base.Add(2*time.Second),
	)
	if err != nil {
		t.Fatal(err)
	}
	got, err := store.GoogleDriveManagedRootMembership(ctx, generation.ID, 2, "managed", "child")
	if err != nil {
		t.Fatal(err)
	}
	if got.State != gdrive.MembershipUnknown || got.Reason != gdrive.UnknownObjectUnavailable {
		t.Fatalf("removed membership=%#v", got)
	}
}

func googleMembershipBootstrapBundle(
	scope remotehistory.Scope,
	topology []gdrive.TopologyState,
) gdrive.BootstrapBundle {
	objects := make([]remotehistory.RemoteObjectState, 0, len(topology))
	for _, state := range topology {
		objects = append(objects, *googleTopologyObject(scope, state.ObjectID))
	}
	return gdrive.BootstrapBundle{
		History: remotehistory.BootstrapResult{
			StreamID: scope.StreamID,
			Status:   remotehistory.BootstrapComplete,
			Cursor:   "cursor-1",
			Coverage: corpus.ProviderHistoryContinuous,
			Objects:  objects,
		},
		Topology: topology,
	}
}

func topologyPresent(
	objectID corpus.ProviderObjectID,
	parentID corpus.ProviderObjectID,
) gdrive.TopologyState {
	return gdrive.TopologyState{
		ObjectID:        objectID,
		Presence:        gdrive.TopologyPresent,
		ParentKnowledge: gdrive.ParentKnown,
		ParentObjectID:  parentID,
	}
}

func lifetimeSegmentForObject(
	t *testing.T,
	store *Store,
	generationID remotehistory.HistoryGenerationID,
	objectID corpus.ProviderObjectID,
) remotehistory.ProviderObjectLifetimeSegment {
	t.Helper()
	segments, err := store.RemoteHistoryLifetimeSegments(context.Background(), generationID)
	if err != nil {
		t.Fatal(err)
	}
	for _, segment := range segments {
		if segment.ProviderObjectID == objectID && segment.Status == remotehistory.LifetimeSegmentActive {
			return segment
		}
	}
	t.Fatalf("active lifetime segment not found for %s", objectID)
	return remotehistory.ProviderObjectLifetimeSegment{}
}
