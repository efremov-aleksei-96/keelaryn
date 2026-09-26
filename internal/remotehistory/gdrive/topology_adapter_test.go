package gdrive_test

import (
	"context"
	"errors"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory/gdrive"
)

func TestBootstrapWithTopologyPublishesFinalParentState(t *testing.T) {
	client := &fakeClient{
		startToken: "fence",
		filePages: []gdrive.FilePage{{Files: []gdrive.FileRecord{
			{ID: "a", Parents: []string{"my-drive-root-id"}},
			{ID: "child", Parents: []string{"a"}},
		}}},
		changePages: map[string]changeResult{
			"fence": {page: gdrive.ChangePage{
				Changes: []gdrive.ChangeRecord{{
					FileID: "a",
					File: &gdrive.FileRecord{ID: "a", Parents: []string{"folder-new"}},
				}},
				NewStartPageToken: "terminal",
			}},
		},
	}
	adapter := mustAdapter(t, client, myDriveConfig())
	bundle, err := adapter.BootstrapWithTopology(context.Background(), myDriveConfig().Scope())
	if err != nil {
		t.Fatal(err)
	}
	if bundle.History.Status != remotehistory.BootstrapComplete || len(bundle.Topology) != 2 {
		t.Fatalf("bundle=%#v", bundle)
	}
	if bundle.Topology[0].ObjectID != "a" ||
		bundle.Topology[0].ParentKnowledge != gdrive.ParentKnown ||
		bundle.Topology[0].ParentObjectID != "folder-new" {
		t.Fatalf("a topology=%#v", bundle.Topology[0])
	}
	if bundle.Topology[1].ObjectID != "child" ||
		bundle.Topology[1].ParentObjectID != "a" {
		t.Fatalf("child topology=%#v", bundle.Topology[1])
	}
}

func TestReadChangesWithTopologyAlignsHistoryAndTopology(t *testing.T) {
	client := &fakeClient{changePages: map[string]changeResult{
		"cursor-1": {page: gdrive.ChangePage{
			Changes: []gdrive.ChangeRecord{
				{FileID: "gone", Removed: true},
				{FileID: "live", File: &gdrive.FileRecord{ID: "live", Parents: []string{"folder-1"}}},
			},
			NewStartPageToken: "cursor-2",
		}},
	}}
	adapter := mustAdapter(t, client, myDriveConfig())
	bundle, err := adapter.ReadChangesWithTopology(context.Background(), myDriveConfig().Scope(), "cursor-1", "")
	if err != nil {
		t.Fatal(err)
	}
	if len(bundle.History.Changes) != 2 || len(bundle.Topology) != 2 {
		t.Fatalf("bundle=%#v", bundle)
	}
	if bundle.History.Changes[0].Kind != remotehistory.ChangeRemoved ||
		bundle.Topology[0].Presence != gdrive.TopologyUnavailable ||
		bundle.Topology[0].ObjectID != "gone" {
		t.Fatalf("removed pair=%#v %#v", bundle.History.Changes[0], bundle.Topology[0])
	}
	if bundle.History.Changes[1].Kind != remotehistory.ChangeUpsert ||
		bundle.Topology[1].Presence != gdrive.TopologyPresent ||
		bundle.Topology[1].ParentObjectID != "folder-1" {
		t.Fatalf("upsert pair=%#v %#v", bundle.History.Changes[1], bundle.Topology[1])
	}
}

func TestConsumeChangesWithTopologyPreservesRepeatedObjectOrder(t *testing.T) {
	client := &fakeClient{changePages: map[string]changeResult{
		"cursor-1": {page: gdrive.ChangePage{
			Changes: []gdrive.ChangeRecord{{
				FileID: "same",
				File: &gdrive.FileRecord{ID: "same", Parents: []string{"parent-1"}},
			}},
			NextPageToken: "page-2",
		}},
		"page-2": {page: gdrive.ChangePage{
			Changes: []gdrive.ChangeRecord{{
				FileID: "same",
				File: &gdrive.FileRecord{ID: "same", Parents: []string{"parent-2"}},
			}},
			NewStartPageToken: "cursor-2",
		}},
	}}
	adapter := mustAdapter(t, client, myDriveConfig())
	bundle, err := gdrive.ConsumeChangesWithTopology(
		context.Background(), adapter, myDriveConfig().Scope(), "cursor-1",
	)
	if err != nil {
		t.Fatal(err)
	}
	if bundle.History.Status != remotehistory.CycleComplete ||
		bundle.History.NextCursor != "cursor-2" ||
		len(bundle.History.Changes) != 2 ||
		len(bundle.Topology) != 2 {
		t.Fatalf("bundle=%#v", bundle)
	}
	if bundle.Topology[0].ParentObjectID != "parent-1" ||
		bundle.Topology[1].ParentObjectID != "parent-2" {
		t.Fatalf("topology order=%#v", bundle.Topology)
	}
}

func TestTopologyAwareAdapterRejectsMultipleParents(t *testing.T) {
	client := &fakeClient{changePages: map[string]changeResult{
		"cursor-1": {page: gdrive.ChangePage{
			Changes: []gdrive.ChangeRecord{{
				FileID: "ambiguous",
				File: &gdrive.FileRecord{ID: "ambiguous", Parents: []string{"p1", "p2"}},
			}},
			NewStartPageToken: "cursor-2",
		}},
	}}
	adapter := mustAdapter(t, client, myDriveConfig())
	_, err := adapter.ReadChangesWithTopology(context.Background(), myDriveConfig().Scope(), "cursor-1", "")
	if !errors.Is(err, gdrive.ErrInvalidTopologyState) {
		t.Fatalf("error=%v", err)
	}
}
