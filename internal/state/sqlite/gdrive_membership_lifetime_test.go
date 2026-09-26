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

func TestManagedRootBindingFailsClosedAfterSameIDReincarnation(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := googleTopologyTestScope()
	fp := remotehistory.ScopePolicyFingerprint("google-drive-history-universe:v1:test")
	base := time.Date(2026, 9, 27, 1, 0, 0, 0, time.UTC)

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
	if _, err := store.BindGoogleDriveManagedRoot(
		ctx, generation.ID, "managed", base.Add(time.Second),
	); err != nil {
		t.Fatal(err)
	}
	before := lifetimeSegmentForObject(t, store, generation.ID, "managed")

	remove := gdrive.ChangeCycleBundle{
		History: remotehistory.ChangeCycle{
			StreamID:       scope.StreamID,
			Status:         remotehistory.CycleComplete,
			PreviousCursor: "cursor-1",
			NextCursor:     "cursor-2",
			Coverage:       corpus.ProviderHistoryContinuous,
			Changes: []remotehistory.RemoteChange{{
				Kind:     remotehistory.ChangeRemoved,
				ObjectID: "managed",
			}},
		},
		Topology: []gdrive.TopologyState{{
			ObjectID:        "managed",
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

	readd := gdrive.ChangeCycleBundle{
		History: remotehistory.ChangeCycle{
			StreamID:       scope.StreamID,
			Status:         remotehistory.CycleComplete,
			PreviousCursor: "cursor-2",
			NextCursor:     "cursor-3",
			Coverage:       corpus.ProviderHistoryContinuous,
			Changes: []remotehistory.RemoteChange{{
				Kind:     remotehistory.ChangeUpsert,
				ObjectID: "managed",
				State:    googleTopologyObject(scope, "managed"),
			}},
		},
		Topology: []gdrive.TopologyState{
			topologyPresent("managed", corpus.ProviderObjectID(scope.Root)),
		},
	}
	generation, err = store.PublishGoogleDriveRemoteHistoryCycle(
		ctx, generation.ID, scope, fp, 2, "cursor-2", readd, base.Add(3*time.Second),
	)
	if err != nil {
		t.Fatal(err)
	}

	after := lifetimeSegmentForObject(t, store, generation.ID, "managed")
	if after.ID == before.ID {
		t.Fatalf("managed-root reincarnation reused lifetime segment: %s", after.ID)
	}

	got, err := store.GoogleDriveManagedRootMembership(
		ctx, generation.ID, 3, "managed", "child",
	)
	if err != nil {
		t.Fatal(err)
	}
	if got.State != gdrive.MembershipUnknown || got.Reason != gdrive.UnknownLifetimeMismatch {
		t.Fatalf("membership after managed-root reincarnation=%#v", got)
	}

	_, err = store.BindGoogleDriveManagedRoot(
		ctx, generation.ID, "managed", base.Add(4*time.Second),
	)
	if !errors.Is(err, ErrGoogleManagedRootBindingStale) {
		t.Fatalf("rebinding same native ID error=%v want ErrGoogleManagedRootBindingStale", err)
	}
}

func TestParentEdgeFailsClosedAcrossSameIDReincarnationUntilFreshChildEvidence(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := googleTopologyTestScope()
	fp := remotehistory.ScopePolicyFingerprint("google-drive-history-universe:v1:test")
	base := time.Date(2026, 9, 27, 2, 0, 0, 0, time.UTC)

	generation, err := store.StartGoogleDriveRemoteHistoryGeneration(
		ctx,
		scope,
		fp,
		googleMembershipBootstrapBundle(scope, []gdrive.TopologyState{
			topologyPresent("managed", corpus.ProviderObjectID(scope.Root)),
			topologyPresent("parent", "managed"),
			topologyPresent("child", "parent"),
			topologyPresent("outside", corpus.ProviderObjectID(scope.Root)),
		}),
		base,
	)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.BindGoogleDriveManagedRoot(
		ctx, generation.ID, "managed", base.Add(time.Second),
	); err != nil {
		t.Fatal(err)
	}

	childBefore := lifetimeSegmentForObject(t, store, generation.ID, "child")
	parentBefore := lifetimeSegmentForObject(t, store, generation.ID, "parent")

	removeParent := gdrive.ChangeCycleBundle{
		History: remotehistory.ChangeCycle{
			StreamID:       scope.StreamID,
			Status:         remotehistory.CycleComplete,
			PreviousCursor: "cursor-1",
			NextCursor:     "cursor-2",
			Coverage:       corpus.ProviderHistoryContinuous,
			Changes: []remotehistory.RemoteChange{{
				Kind:     remotehistory.ChangeRemoved,
				ObjectID: "parent",
			}},
		},
		Topology: []gdrive.TopologyState{{
			ObjectID:        "parent",
			Presence:        gdrive.TopologyUnavailable,
			ParentKnowledge: gdrive.ParentUnavailable,
		}},
	}
	generation, err = store.PublishGoogleDriveRemoteHistoryCycle(
		ctx, generation.ID, scope, fp, 1, "cursor-1", removeParent, base.Add(2*time.Second),
	)
	if err != nil {
		t.Fatal(err)
	}

	readdParent := gdrive.ChangeCycleBundle{
		History: remotehistory.ChangeCycle{
			StreamID:       scope.StreamID,
			Status:         remotehistory.CycleComplete,
			PreviousCursor: "cursor-2",
			NextCursor:     "cursor-3",
			Coverage:       corpus.ProviderHistoryContinuous,
			Changes: []remotehistory.RemoteChange{{
				Kind:     remotehistory.ChangeUpsert,
				ObjectID: "parent",
				State:    googleTopologyObject(scope, "parent"),
			}},
		},
		Topology: []gdrive.TopologyState{
			topologyPresent("parent", "outside"),
		},
	}
	generation, err = store.PublishGoogleDriveRemoteHistoryCycle(
		ctx, generation.ID, scope, fp, 2, "cursor-2", readdParent, base.Add(3*time.Second),
	)
	if err != nil {
		t.Fatal(err)
	}

	parentAfter := lifetimeSegmentForObject(t, store, generation.ID, "parent")
	if parentAfter.ID == parentBefore.ID {
		t.Fatalf("parent reincarnation reused lifetime segment: %s", parentAfter.ID)
	}

	staleEdge, err := store.GoogleDriveManagedRootMembership(
		ctx, generation.ID, 3, "managed", "child",
	)
	if err != nil {
		t.Fatal(err)
	}
	if staleEdge.State != gdrive.MembershipUnknown || staleEdge.Reason != gdrive.UnknownLifetimeMismatch {
		t.Fatalf("stale parent edge membership=%#v", staleEdge)
	}

	refreshChild := gdrive.ChangeCycleBundle{
		History: remotehistory.ChangeCycle{
			StreamID:       scope.StreamID,
			Status:         remotehistory.CycleComplete,
			PreviousCursor: "cursor-3",
			NextCursor:     "cursor-4",
			Coverage:       corpus.ProviderHistoryContinuous,
			Changes: []remotehistory.RemoteChange{{
				Kind:     remotehistory.ChangeUpsert,
				ObjectID: "child",
				State:    googleTopologyObject(scope, "child"),
			}},
		},
		Topology: []gdrive.TopologyState{
			topologyPresent("child", "parent"),
		},
	}
	generation, err = store.PublishGoogleDriveRemoteHistoryCycle(
		ctx, generation.ID, scope, fp, 3, "cursor-3", refreshChild, base.Add(4*time.Second),
	)
	if err != nil {
		t.Fatal(err)
	}

	refreshed, err := store.GoogleDriveManagedRootMembership(
		ctx, generation.ID, 4, "managed", "child",
	)
	if err != nil {
		t.Fatal(err)
	}
	if refreshed.State != gdrive.MembershipOut {
		t.Fatalf("fresh parent edge membership=%#v want OUT", refreshed)
	}

	childAfter := lifetimeSegmentForObject(t, store, generation.ID, "child")
	if childAfter.ID != childBefore.ID || childAfter.Status != childBefore.Status {
		t.Fatalf("child lifetime changed without removal: before=%#v after=%#v", childBefore, childAfter)
	}
	if err := store.VerifyRemoteHistoryLifetimeSegments(ctx, generation.ID); err != nil {
		t.Fatal(err)
	}
}
