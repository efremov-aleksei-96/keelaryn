package gdrive_test

import (
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory/gdrive"
)

func TestTopologyDomainValidation(t *testing.T) {
	bootstrap := gdrive.TopologyEvidence{
		GenerationID: "g1",
		PublicationSequence: 1,
		Kind: gdrive.TopologyEvidenceBootstrap,
		ObjectID: "file-1",
		Presence: gdrive.TopologyPresent,
		ParentKnowledge: gdrive.ParentKnown,
		ParentObjectID: "root-id",
	}
	if err := gdrive.ValidateTopologyEvidence(bootstrap); err != nil {
		t.Fatal(err)
	}

	selfParent := bootstrap
	selfParent.ParentObjectID = "file-1"
	if err := gdrive.ValidateTopologyEvidence(selfParent); err == nil {
		t.Fatal("self-parent topology evidence unexpectedly validated")
	}

	ordinal := int64(3)
	removed := gdrive.TopologyEvidence{
		GenerationID: "g1",
		PublicationSequence: 2,
		ChangeOrdinal: &ordinal,
		Kind: gdrive.TopologyEvidenceRemoved,
		ObjectID: "file-1",
		Presence: gdrive.TopologyUnavailable,
		ParentKnowledge: gdrive.ParentUnavailable,
	}
	if err := gdrive.ValidateTopologyEvidence(removed); err != nil {
		t.Fatal(err)
	}

	node := gdrive.TopologyNode{
		GenerationID: "g1",
		ObjectID: "file-1",
		Presence: gdrive.TopologyPresent,
		ParentKnowledge: gdrive.ParentKnown,
		ParentObjectID: "root-id",
		LastPublicationSequence: 1,
	}
	if err := gdrive.ValidateTopologyNode(node); err != nil {
		t.Fatal(err)
	}

	binding := gdrive.ManagedRootBinding{
		GenerationID: "g1",
		ManagedRootObjectID: "file-1",
		BoundSequence: remotehistory.HistoryPublicationSequence(1),
		CreatedAt: time.Now(),
	}
	if err := gdrive.ValidateManagedRootBinding(binding); err != nil {
		t.Fatal(err)
	}
}
