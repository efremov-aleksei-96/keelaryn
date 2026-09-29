package sqlite_test

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/extract"
	extractlocalfs "github.com/efremov-aleksei-96/keelaryn/internal/extract/localfs"
	"github.com/efremov-aleksei-96/keelaryn/internal/ingest"
	providerlocalfs "github.com/efremov-aleksei-96/keelaryn/internal/provider/localfs"
	searchsqlite "github.com/efremov-aleksei-96/keelaryn/internal/search/sqlite"
	sqlitestate "github.com/efremov-aleksei-96/keelaryn/internal/state/sqlite"
)

func TestLocalRevisionExtractionToFTSExactProvenance(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	content := []byte("Keelaryn exact revision searchable text")
	if err := os.WriteFile(filepath.Join(root, "note.txt"), content, 0o600); err != nil {
		t.Fatal(err)
	}

	state, err := sqlitestate.Open(ctx, filepath.Join(t.TempDir(), "state.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer state.Close()

	provider := providerlocalfs.New("localfs")
	at := time.Date(2026, 9, 29, 18, 30, 0, 0, time.UTC)
	scan, err := ingest.BootstrapLocalFS(ctx, state, provider, root, at)
	if err != nil {
		t.Fatal(err)
	}
	inventory, err := state.Inventory(ctx, corpus.ProviderID("localfs"), scan.Root)
	if err != nil {
		t.Fatal(err)
	}
	var entry corpus.InventoryEntry
	var found bool
	for _, candidate := range inventory {
		if candidate.Locator.Path == "note.txt" {
			entry = candidate
			found = true
			break
		}
	}
	if !found || entry.ArtifactID == "" || entry.RevisionID == "" {
		t.Fatalf("assigned note.txt inventory not found: %#v", inventory)
	}

	result, err := extractlocalfs.Extract(ctx, state, provider, entry, 4096)
	if err != nil {
		t.Fatal(err)
	}
	if result.Status != extract.StatusExtracted {
		t.Fatalf("extraction=%#v", result)
	}

	index, err := searchsqlite.Open(ctx, filepath.Join(t.TempDir(), "search.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer index.Close()
	if err := index.ReplaceAll(ctx, state, []extract.Result{result}); err != nil {
		t.Fatal(err)
	}
	hits, err := index.Search(ctx, "exact searchable", 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(hits) != 1 {
		t.Fatalf("hits=%#v", hits)
	}
	hit := hits[0]
	if hit.ArtifactID != entry.ArtifactID ||
		hit.RevisionID != entry.RevisionID ||
		hit.ExtractorID != extractlocalfs.ExtractorID ||
		hit.Evidence != result.Evidence {
		t.Fatalf("hit provenance=%#v entry=%#v extraction=%#v", hit, entry, result)
	}

	history, err := state.RevisionHistory(ctx, entry.ArtifactID)
	if err != nil {
		t.Fatal(err)
	}
	if len(history) != 1 || history[0].Revision.ID != entry.RevisionID {
		t.Fatalf("search pipeline mutated Revision authority: %#v", history)
	}
}
