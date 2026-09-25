package localfs_test

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/extract"
	extractlocalfs "github.com/efremov-aleksei-96/keelaryn/internal/extract/localfs"
	"github.com/efremov-aleksei-96/keelaryn/internal/ingest"
	providerlocalfs "github.com/efremov-aleksei-96/keelaryn/internal/provider/localfs"
	sqlitestate "github.com/efremov-aleksei-96/keelaryn/internal/state/sqlite"
)

func TestExtractAssignedTextWithExactRevisionProvenance(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	content := []byte("hello Keelaryn\n")
	mustWriteExtract(t, filepath.Join(root, "note.txt"), content)
	store, provider, entry := bootstrapOne(t, root, "note.txt")

	got, err := extractlocalfs.Extract(ctx, store, provider, entry, 1024)
	if err != nil {
		t.Fatal(err)
	}
	if got.Status != extract.StatusExtracted || got.Text != string(content) {
		t.Fatalf("result=%#v", got)
	}
	if got.ArtifactID != entry.ArtifactID || got.RevisionID != entry.RevisionID || got.Locator != entry.Locator {
		t.Fatalf("provenance changed: %#v", got)
	}
	if got.ExtractorID != extractlocalfs.ExtractorID || got.MediaType != "text/plain" {
		t.Fatalf("extractor metadata=%#v", got)
	}
	history, err := store.RevisionHistory(ctx, entry.ArtifactID)
	if err != nil {
		t.Fatal(err)
	}
	if len(history) != 1 {
		t.Fatalf("extraction mutated Revision history: %#v", history)
	}
}

func TestExtractMarkdown(t *testing.T) {
	root := t.TempDir()
	content := []byte("# Title\n\nBody")
	mustWriteExtract(t, filepath.Join(root, "README.md"), content)
	store, provider, entry := bootstrapOne(t, root, "README.md")

	got, err := extractlocalfs.Extract(context.Background(), store, provider, entry, 1024)
	if err != nil {
		t.Fatal(err)
	}
	if got.Status != extract.StatusExtracted || got.MediaType != "text/markdown" || got.Text != string(content) {
		t.Fatalf("result=%#v", got)
	}
}

func TestUnsupportedExtensionDoesNotReadFile(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "file.pdf")
	mustWriteExtract(t, path, []byte("not actually a PDF"))
	store, provider, entry := bootstrapOne(t, root, "file.pdf")
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}

	got, err := extractlocalfs.Extract(context.Background(), store, provider, entry, 1024)
	if err != nil {
		t.Fatalf("unsupported extraction attempted file read: %v", err)
	}
	if got.Status != extract.StatusUnsupported || got.Text != "" || got.Evidence.Digest != "" {
		t.Fatalf("unsupported result=%#v", got)
	}
}

func TestNonUTF8IsOpaque(t *testing.T) {
	root := t.TempDir()
	mustWriteExtract(t, filepath.Join(root, "binary.txt"), []byte{0xff, 0xfe, 0xfd})
	store, provider, entry := bootstrapOne(t, root, "binary.txt")

	got, err := extractlocalfs.Extract(context.Background(), store, provider, entry, 1024)
	if err != nil {
		t.Fatal(err)
	}
	if got.Status != extract.StatusOpaque || got.Text != "" {
		t.Fatalf("opaque result=%#v", got)
	}
}

func TestChangedBytesReturnStaleRevision(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "note.txt")
	mustWriteExtract(t, path, []byte("old"))
	store, provider, entry := bootstrapOne(t, root, "note.txt")
	mustWriteExtract(t, path, []byte("new"))

	got, err := extractlocalfs.Extract(context.Background(), store, provider, entry, 1024)
	if err != nil {
		t.Fatal(err)
	}
	if got.Status != extract.StatusStaleRevision || got.Text != "" {
		t.Fatalf("stale result=%#v", got)
	}
}

func TestExtractionLimitExceeded(t *testing.T) {
	root := t.TempDir()
	mustWriteExtract(t, filepath.Join(root, "large.txt"), []byte("1234567890"))
	store, provider, entry := bootstrapOne(t, root, "large.txt")

	got, err := extractlocalfs.Extract(context.Background(), store, provider, entry, 4)
	if err != nil {
		t.Fatal(err)
	}
	if got.Status != extract.StatusLimitExceeded || got.Text != "" {
		t.Fatalf("limit result=%#v", got)
	}
}

func TestUnassignedInventoryCannotBeExtracted(t *testing.T) {
	root := t.TempDir()
	mustWriteExtract(t, filepath.Join(root, "note.txt"), []byte("text"))
	provider := providerlocalfs.New("localfs")
	snapshot, err := provider.Snapshot(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}
	obs := snapshot.Observations()[0]
	entry := corpus.InventoryEntry{
		AssignmentState: corpus.AssignmentUnresolved,
		Locator: obs.Locator,
		Kind: obs.Kind,
		Size: obs.Size,
		ModifiedAt: obs.ModifiedAt,
	}
	_, err = extractlocalfs.Extract(context.Background(), emptyRevisionReader{}, provider, entry, 1024)
	if !errors.Is(err, extractlocalfs.ErrInvalidExtractionRequest) {
		t.Fatalf("error=%v, want ErrInvalidExtractionRequest", err)
	}
}

func TestMissingReferencedRevisionFailsClosed(t *testing.T) {
	root := t.TempDir()
	mustWriteExtract(t, filepath.Join(root, "note.txt"), []byte("text"))
	store, provider, entry := bootstrapOne(t, root, "note.txt")
	entry.RevisionID = "rev_missing"

	_, err := extractlocalfs.Extract(context.Background(), store, provider, entry, 1024)
	if !errors.Is(err, extractlocalfs.ErrReferencedRevisionMissing) {
		t.Fatalf("error=%v, want ErrReferencedRevisionMissing", err)
	}
}

type emptyRevisionReader struct{}

func (emptyRevisionReader) RevisionHistory(context.Context, corpus.ArtifactID) ([]corpus.RevisionRecord, error) {
	return nil, nil
}

func bootstrapOne(t *testing.T, root, path string) (*sqlitestate.Store, *providerlocalfs.Provider, corpus.InventoryEntry) {
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
	at := time.Date(2026, 9, 25, 18, 0, 0, 0, time.UTC)
	scan, err := ingest.BootstrapLocalFS(ctx, store, provider, root, at)
	if err != nil {
		t.Fatal(err)
	}
	inventory, err := store.Inventory(ctx, "localfs", scan.Root)
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range inventory {
		if entry.Locator.Path == path {
			return store, provider, entry
		}
	}
	t.Fatalf("inventory path %q not found: %#v", path, inventory)
	return nil, nil, corpus.InventoryEntry{}
}

func mustWriteExtract(t *testing.T, path string, content []byte) {
	t.Helper()
	if err := os.WriteFile(path, content, 0o600); err != nil {
		t.Fatal(err)
	}
}
