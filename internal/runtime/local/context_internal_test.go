package local

import (
	"errors"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	extractlocalfs "github.com/efremov-aleksei-96/keelaryn/internal/extract/localfs"
	"github.com/efremov-aleksei-96/keelaryn/internal/search"
)

func TestSelectionsForHitsUsesFirstDeterministicCurrentLocator(t *testing.T) {
	hit := search.Hit{
		ArtifactID: "art-1", RevisionID: "rev-1", ExtractorID: extractlocalfs.ExtractorID,
	}
	inventory := []corpus.InventoryEntry{
		{
			ArtifactID: "art-1", RevisionID: "rev-1", AssignmentState: corpus.AssignmentAssigned,
			Kind: corpus.EntryRegularFile, Locator: corpus.Locator{Path: "a.txt"},
		},
		{
			ArtifactID: "art-1", RevisionID: "rev-1", AssignmentState: corpus.AssignmentAssigned,
			Kind: corpus.EntryRegularFile, Locator: corpus.Locator{Path: "b.txt"},
		},
	}
	selections, err := selectionsForHits([]search.Hit{hit}, inventory, "task", 1024)
	if err != nil {
		t.Fatal(err)
	}
	if len(selections) != 1 || selections[0].Entry.Locator.Path != "a.txt" {
		t.Fatalf("selections=%#v", selections)
	}
}

func TestSelectionsForHitsRejectsNonCurrentExactRevision(t *testing.T) {
	hit := search.Hit{
		ArtifactID: "art-1", RevisionID: "rev-old", ExtractorID: extractlocalfs.ExtractorID,
	}
	inventory := []corpus.InventoryEntry{{
		ArtifactID: "art-1", RevisionID: "rev-current", AssignmentState: corpus.AssignmentAssigned,
		Kind: corpus.EntryRegularFile, Locator: corpus.Locator{Path: "note.txt"},
	}}
	_, err := selectionsForHits([]search.Hit{hit}, inventory, "task", 1024)
	if !errors.Is(err, ErrSearchHitNotCurrent) {
		t.Fatalf("error=%v want ErrSearchHitNotCurrent", err)
	}
}
