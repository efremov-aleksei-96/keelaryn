package local_test

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/controlstorage"
	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/ingest"
	providerlocalfs "github.com/efremov-aleksei-96/keelaryn/internal/provider/localfs"
	localruntime "github.com/efremov-aleksei-96/keelaryn/internal/runtime/local"
	sqlitestate "github.com/efremov-aleksei-96/keelaryn/internal/state/sqlite"
)

func TestProtectedRuntimeKeepsAcceptedBootstrapAfterLaterUnresolvedCompleteScan(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	controlDir := filepath.Join(t.TempDir(), "control")
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte("needle body"), 0o600); err != nil {
		t.Fatal(err)
	}
	base := time.Date(2026, 10, 4, 12, 20, 0, 0, time.UTC)

	first, err := localruntime.BootstrapProtectedIndex(ctx, localruntime.ProtectedIndexOptions{
		Root: root, ControlDir: controlDir, ObservedAt: base, MaxBytes: 1 << 20,
	})
	if err != nil {
		t.Fatal(err)
	}

	layout, err := controlstorage.OpenExisting(controlDir)
	if err != nil {
		t.Fatal(err)
	}
	state, err := sqlitestate.Open(ctx, layout.StateDB)
	if err != nil {
		t.Fatal(err)
	}
	later, err := ingest.LocalFS(
		ctx, state, providerlocalfs.New(localruntime.ProviderID), root, base.Add(time.Minute),
	)
	if err != nil {
		state.Close()
		t.Fatal(err)
	}
	latest, found, err := state.LatestCompleteScan(ctx, localruntime.ProviderID, root)
	if err != nil {
		state.Close()
		t.Fatal(err)
	}
	if !found || latest.ID != later.ID || later.ID == first.ScanID {
		state.Close()
		t.Fatalf("latest=%#v found=%v later=%s first=%s", latest, found, later.ID, first.ScanID)
	}
	generic, err := state.Inventory(ctx, localruntime.ProviderID, root)
	if err != nil {
		state.Close()
		t.Fatal(err)
	}
	if len(generic) != 1 || generic[0].ScanID != later.ID || generic[0].AssignmentState != corpus.AssignmentUnresolved {
		state.Close()
		t.Fatalf("generic inventory=%#v", generic)
	}
	if err := state.Close(); err != nil {
		t.Fatal(err)
	}

	hits, err := localruntime.QueryProtectedReadOnlyCurrent(ctx, controlDir, "needle", 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(hits) != 1 {
		t.Fatalf("hits=%#v want one accepted bootstrap hit", hits)
	}
	bundle, err := localruntime.BuildProtectedContextReadOnlyBound(ctx, localruntime.ProtectedContextOptions{
		Root: root, ControlDir: controlDir, Query: "needle", Reason: "regression",
		Limit: 10, MaxBytes: 1 << 20, MaxTotalBytes: 1 << 20,
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(bundle.Items) != 1 || bundle.Items[0].ArtifactID != hits[0].ArtifactID ||
		bundle.Items[0].RevisionID != hits[0].RevisionID {
		t.Fatalf("bundle=%#v hits=%#v", bundle, hits)
	}

	rebuilt, err := localruntime.BootstrapProtectedIndex(ctx, localruntime.ProtectedIndexOptions{
		Root: root, ControlDir: controlDir, ObservedAt: base.Add(2 * time.Minute), MaxBytes: 1 << 20,
	})
	if err != nil {
		t.Fatal(err)
	}
	if !rebuilt.ReusedScan || rebuilt.ScanID != first.ScanID {
		t.Fatalf("rebuild=%#v want accepted bootstrap scan=%s", rebuilt, first.ScanID)
	}
}
