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

func TestManagedRootMembershipDoesNotCrossHistoryUniverses(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	fp := remotehistory.ScopePolicyFingerprint("google-drive-history-universe:v1:test")
	base := time.Date(2026, 9, 27, 0, 0, 0, 0, time.UTC)

	myScope := googleTopologyTestScope()
	myGeneration, err := store.StartGoogleDriveRemoteHistoryGeneration(
		ctx,
		myScope,
		fp,
		googleMembershipBootstrapBundle(myScope, []gdrive.TopologyState{
			topologyPresent("my-managed", corpus.ProviderObjectID(myScope.Root)),
			topologyPresent("same-id", "my-managed"),
		}),
		base,
	)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.BindGoogleDriveManagedRoot(ctx, myGeneration.ID, "my-managed", base.Add(time.Second)); err != nil {
		t.Fatal(err)
	}

	sharedScope := remotehistory.Scope{
		ProviderID:     gdrive.ProviderID,
		IdentityDomain: "google-drive:shared:drive-1",
		StreamID:       "google-drive:shared:drive-1:changes",
		Root:           "drive-1",
	}
	sharedBundle := googleMembershipBootstrapBundle(sharedScope, []gdrive.TopologyState{
		{
			ObjectID:        "shared-managed",
			Presence:        gdrive.TopologyPresent,
			ParentKnowledge: gdrive.ParentKnown,
			ParentObjectID:  corpus.ProviderObjectID(sharedScope.Root),
			DriveID:         "drive-1",
		},
		{
			ObjectID:        "same-id",
			Presence:        gdrive.TopologyPresent,
			ParentKnowledge: gdrive.ParentKnown,
			ParentObjectID:  "shared-managed",
			DriveID:         "drive-1",
		},
	})
	sharedGeneration, err := store.StartGoogleDriveRemoteHistoryGeneration(
		ctx, sharedScope, fp, sharedBundle, base.Add(2*time.Second),
	)
	if err != nil {
		t.Fatal(err)
	}

	_, err = store.GoogleDriveManagedRootMembership(
		ctx, sharedGeneration.ID, 1, "my-managed", "same-id",
	)
	if !errors.Is(err, ErrGoogleManagedRootBindingNotFound) {
		t.Fatalf("cross-universe root binding unexpectedly resolved: %v", err)
	}

	if _, err := store.BindGoogleDriveManagedRoot(
		ctx, sharedGeneration.ID, "shared-managed", base.Add(3*time.Second),
	); err != nil {
		t.Fatal(err)
	}
	got, err := store.GoogleDriveManagedRootMembership(
		ctx, sharedGeneration.ID, 1, "shared-managed", "same-id",
	)
	if err != nil {
		t.Fatal(err)
	}
	if got.State != gdrive.MembershipIn {
		t.Fatalf("shared-drive membership=%#v", got)
	}

	mySegment := lifetimeSegmentForObject(t, store, myGeneration.ID, "same-id")
	sharedSegment := lifetimeSegmentForObject(t, store, sharedGeneration.ID, "same-id")
	if mySegment.ID == sharedSegment.ID {
		t.Fatalf("same native object ID crossed history-universe lifetime boundary: %s", mySegment.ID)
	}
}
