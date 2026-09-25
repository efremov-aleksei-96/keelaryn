package localfs_test

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/contextbundle"
	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/extract"
	contextlocalfs "github.com/efremov-aleksei-96/keelaryn/internal/contextbundle/localfs"
	"github.com/efremov-aleksei-96/keelaryn/internal/ingest"
	providerlocalfs "github.com/efremov-aleksei-96/keelaryn/internal/provider/localfs"
	sqlitestate "github.com/efremov-aleksei-96/keelaryn/internal/state/sqlite"
)

func TestBuildPreservesExplicitSelectionOrderAndProvenance(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	mustWriteContext(t, filepath.Join(root, "b.md"), []byte("# B"))
	mustWriteContext(t, filepath.Join(root, "a.txt"), []byte("A"))
	store, provider, entries := bootstrapContext(t, root)

	byPath := inventoryByPath(entries)
	selections := []contextbundle.Selection{
		{Entry: byPath["b.md"], Reason: "answer architecture question", MaxBytes: 1024},
		{Entry: byPath["a.txt"], Reason: "supply exact note", MaxBytes: 1024},
	}
	got, err := contextlocalfs.Build(ctx, store, provider, selections)
	if err != nil {
		t.Fatal(err)
	}
	if len(got.Items) != 2 {
		t.Fatalf("items=%#v", got.Items)
	}
	if got.Items[0].Locator.Path != "b.md" || got.Items[1].Locator.Path != "a.txt" {
		t.Fatalf("selection order changed: %#v", got.Items)
	}
	for i := range got.Items {
		item := got.Items[i]
		entry := selections[i].Entry
		if item.Status != extract.StatusExtracted {
			t.Fatalf("item %d status=%q", i, item.Status)
		}
		if item.Reason != selections[i].Reason ||
			item.ArtifactID != entry.ArtifactID ||
			item.RevisionID != entry.RevisionID ||
			item.Locator != entry.Locator ||
			item.ExtractorID == "" ||
			item.Evidence.Digest == "" {
			t.Fatalf("item %d provenance=%#v", i, item)
		}
	}
	if got.Items[0].Text != "# B" || got.Items[1].Text != "A" {
		t.Fatalf("texts=%#v", got.Items)
	}
}

func TestBuildPreservesUnsupportedOutcomeWithoutText(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	path := filepath.Join(root, "file.pdf")
	mustWriteContext(t, path, []byte("not pdf"))
	store, provider, entries := bootstrapContext(t, root)
	entry := inventoryByPath(entries)["file.pdf"]
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}

	got, err := contextlocalfs.Build(ctx, store, provider, []contextbundle.Selection{{
		Entry: entry, Reason: "explicitly selected attachment", MaxBytes: 1024,
	}})
	if err != nil {
		t.Fatalf("unsupported bundle item attempted read: %v", err)
	}
	if len(got.Items) != 1 || got.Items[0].Status != extract.StatusUnsupported || got.Items[0].Text != "" || got.Items[0].Evidence.Digest != "" {
		t.Fatalf("unsupported item=%#v", got.Items)
	}
}

func TestBuildPreservesStaleRevisionOutcome(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	path := filepath.Join(root, "note.txt")
	mustWriteContext(t, path, []byte("old"))
	store, provider, entries := bootstrapContext(t, root)
	entry := inventoryByPath(entries)["note.txt"]
	mustWriteContext(t, path, []byte("new"))

	got, err := contextlocalfs.Build(ctx, store, provider, []contextbundle.Selection{{
		Entry: entry, Reason: "selected before file changed", MaxBytes: 1024,
	}})
	if err != nil {
		t.Fatal(err)
	}
	if got.Items[0].Status != extract.StatusStaleRevision || got.Items[0].Text != "" {
		t.Fatalf("stale item=%#v", got.Items[0])
	}
	if got.Items[0].ArtifactID != entry.ArtifactID || got.Items[0].RevisionID != entry.RevisionID {
		t.Fatalf("stale provenance lost: %#v", got.Items[0])
	}
}

func TestBuildRejectsEmptyReasonBeforeExtraction(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	path := filepath.Join(root, "note.txt")
	mustWriteContext(t, path, []byte("text"))
	store, provider, entries := bootstrapContext(t, root)
	entry := inventoryByPath(entries)["note.txt"]
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}

	_, err := contextlocalfs.Build(ctx, store, provider, []contextbundle.Selection{{
		Entry: entry, Reason: "   ", MaxBytes: 1024,
	}})
	if !errors.Is(err, contextlocalfs.ErrInvalidSelection) {
		t.Fatalf("error=%v, want ErrInvalidSelection", err)
	}
}

func TestBuildRejectsNegativeLimit(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	mustWriteContext(t, filepath.Join(root, "note.txt"), []byte("text"))
	store, provider, entries := bootstrapContext(t, root)
	entry := inventoryByPath(entries)["note.txt"]

	_, err := contextlocalfs.Build(ctx, store, provider, []contextbundle.Selection{{
		Entry: entry, Reason: "selected", MaxBytes: -1,
	}})
	if !errors.Is(err, contextlocalfs.ErrInvalidSelection) {
		t.Fatalf("error=%v, want ErrInvalidSelection", err)
	}
}

func TestBuildEmptySelectionIsEmptyBundle(t *testing.T) {
	root := t.TempDir()
	store, provider, _ := bootstrapContext(t, root)

	got, err := contextlocalfs.Build(context.Background(), store, provider, nil)
	if err != nil {
		t.Fatal(err)
	}
	if got.Items == nil || len(got.Items) != 0 {
		t.Fatalf("empty bundle=%#v", got)
	}
}

func TestBuildLimitOutcomeCarriesNoText(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	mustWriteContext(t, filepath.Join(root, "large.txt"), []byte("123456789"))
	store, provider, entries := bootstrapContext(t, root)
	entry := inventoryByPath(entries)["large.txt"]

	got, err := contextlocalfs.Build(ctx, store, provider, []contextbundle.Selection{{
		Entry: entry, Reason: "bounded context", MaxBytes: 4,
	}})
	if err != nil {
		t.Fatal(err)
	}
	if got.Items[0].Status != extract.StatusLimitExceeded || got.Items[0].Text != "" {
		t.Fatalf("limit item=%#v", got.Items[0])
	}
}

func bootstrapContext(t *testing.T, root string) (*sqlitestate.Store, *providerlocalfs.Provider, []corpus.InventoryEntry) {
	t.Helper()
	ctx := context.Background()
	store, err := sqlitestate.Open(ctx, filepath.Join(t.TempDir(), "state.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := store.Close(); err != nil {
			t.Error(err)
		}
	})
	provider := providerlocalfs.New("localfs")
	at := time.Date(2026, 9, 25, 20, 0, 0, 0, time.UTC)
	scan, err := ingest.BootstrapLocalFS(ctx, store, provider, root, at)
	if err != nil {
		t.Fatal(err)
	}
	inventory, err := store.Inventory(ctx, "localfs", scan.Root)
	if err != nil {
		t.Fatal(err)
	}
	return store, provider, inventory
}

func inventoryByPath(entries []corpus.InventoryEntry) map[string]corpus.InventoryEntry {
	out := make(map[string]corpus.InventoryEntry, len(entries))
	for _, entry := range entries {
		out[entry.Locator.Path] = entry
	}
	return out
}

func mustWriteContext(t *testing.T, path string, content []byte) {
	t.Helper()
	if err := os.WriteFile(path, content, 0o600); err != nil {
		t.Fatal(err)
	}
}
