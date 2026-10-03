package local_test

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/controlstorage"
	localruntime "github.com/efremov-aleksei-96/keelaryn/internal/runtime/local"
)

func TestProtectedRuntimeCreatesAndReopensVerifiedControlStorage(t *testing.T) {
	root := t.TempDir()
	control := filepath.Join(t.TempDir(), "control")
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte("protected runtime searchable"), 0o600); err != nil {
		t.Fatal(err)
	}
	result, err := localruntime.BootstrapProtectedIndex(context.Background(), localruntime.ProtectedIndexOptions{
		Root: root, ControlDir: control,
		ObservedAt: time.Date(2026, 9, 30, 8, 30, 0, 0, time.UTC),
		MaxBytes: 1024,
	})
	if err != nil {
		t.Fatal(err)
	}
	if result.Indexed != 1 {
		t.Fatalf("result=%#v", result)
	}
	if _, err := controlstorage.OpenExisting(control); err != nil {
		t.Fatalf("control storage failed post-bootstrap verification: %v", err)
	}
	hits, err := localruntime.QueryProtected(context.Background(), control, "runtime searchable", 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(hits) != 1 {
		t.Fatalf("hits=%#v", hits)
	}
}

func TestProtectedQueryMissingControlDoesNotCreateDirectory(t *testing.T) {
	control := filepath.Join(t.TempDir(), "missing")
	_, err := localruntime.QueryProtected(context.Background(), control, "anything", 10)
	if !errors.Is(err, controlstorage.ErrControlDirNotFound) {
		t.Fatalf("error=%v want ErrControlDirNotFound", err)
	}
	if _, statErr := os.Stat(control); !errors.Is(statErr, os.ErrNotExist) {
		t.Fatalf("query created missing control directory: %v", statErr)
	}
}

func TestProtectedRuntimeRejectsPhysicalAliasIntoCorpusBeforeMutation(t *testing.T) {
	root := t.TempDir()
	parent := t.TempDir()
	alias := filepath.Join(parent, "corpus-alias")
	if err := os.Symlink(root, alias); err != nil {
		t.Skipf("symlink unavailable: %v", err)
	}
	control := filepath.Join(alias, "control")
	_, err := localruntime.BootstrapProtectedIndex(context.Background(), localruntime.ProtectedIndexOptions{
		Root: root, ControlDir: control,
		ObservedAt: time.Date(2026, 9, 30, 8, 30, 0, 0, time.UTC),
		MaxBytes: 1024,
	})
	if !errors.Is(err, localruntime.ErrRuntimeStateInCorpus) {
		t.Fatalf("error=%v want ErrRuntimeStateInCorpus", err)
	}
	if _, statErr := os.Stat(filepath.Join(root, "control")); !errors.Is(statErr, os.ErrNotExist) {
		t.Fatalf("control directory was created through corpus alias: %v", statErr)
	}
}


func TestProtectedRuntimeRecoversCorruptDerivedSearchWithoutChangingState(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	control := filepath.Join(t.TempDir(), "control")
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte("recoverable derived cache"), 0o600); err != nil {
		t.Fatal(err)
	}
	options := localruntime.ProtectedIndexOptions{
		Root: root, ControlDir: control,
		ObservedAt: time.Date(2026, 10, 3, 12, 0, 0, 0, time.UTC),
		MaxBytes: 1024,
	}
	first, err := localruntime.BootstrapProtectedIndex(ctx, options)
	if err != nil {
		t.Fatal(err)
	}
	layout, err := controlstorage.OpenExisting(control)
	if err != nil {
		t.Fatal(err)
	}
	stateBefore := mustReadFile(t, layout.StateDB)
	if err := os.WriteFile(layout.SearchDB, []byte("not sqlite"), 0o600); err != nil {
		t.Fatal(err)
	}

	recovered, err := localruntime.BootstrapProtectedIndex(ctx, options)
	if err != nil {
		t.Fatal(err)
	}
	if !recovered.ReusedScan || recovered.ScanID != first.ScanID {
		t.Fatalf("recovered=%#v first=%#v", recovered, first)
	}
	if got := mustReadFile(t, layout.StateDB); string(got) != string(stateBefore) {
		t.Fatal("state.db bytes changed while recovering derived search cache")
	}
	hits, err := localruntime.QueryProtectedReadOnly(ctx, control, "recoverable derived", 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(hits) != 1 {
		t.Fatalf("hits=%#v", hits)
	}
	if _, err := os.Lstat(layout.SearchStagingDB); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("staging survived successful promotion: %v", err)
	}
}

func TestProtectedRuntimeRecoversMissingDerivedSearch(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	control := filepath.Join(t.TempDir(), "control")
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte("missing cache recovery"), 0o600); err != nil {
		t.Fatal(err)
	}
	options := localruntime.ProtectedIndexOptions{
		Root: root, ControlDir: control,
		ObservedAt: time.Date(2026, 10, 3, 12, 10, 0, 0, time.UTC),
		MaxBytes: 1024,
	}
	first, err := localruntime.BootstrapProtectedIndex(ctx, options)
	if err != nil {
		t.Fatal(err)
	}
	layout, err := controlstorage.OpenExisting(control)
	if err != nil {
		t.Fatal(err)
	}
	stateBefore := mustReadFile(t, layout.StateDB)
	if err := os.Remove(layout.SearchDB); err != nil {
		t.Fatal(err)
	}

	recovered, err := localruntime.BootstrapProtectedIndex(ctx, options)
	if err != nil {
		t.Fatal(err)
	}
	if !recovered.ReusedScan || recovered.ScanID != first.ScanID {
		t.Fatalf("recovered=%#v first=%#v", recovered, first)
	}
	if got := mustReadFile(t, layout.StateDB); string(got) != string(stateBefore) {
		t.Fatal("state.db bytes changed while rebuilding missing derived cache")
	}
	if _, err := localruntime.QueryProtectedReadOnly(ctx, control, "missing cache", 10); err != nil {
		t.Fatal(err)
	}
}

func TestProtectedRuntimeDiscardsInterruptedStagingAndRebuilds(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	control := filepath.Join(t.TempDir(), "control")
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte("staging retry"), 0o600); err != nil {
		t.Fatal(err)
	}
	options := localruntime.ProtectedIndexOptions{
		Root: root, ControlDir: control,
		ObservedAt: time.Date(2026, 10, 3, 12, 20, 0, 0, time.UTC),
		MaxBytes: 1024,
	}
	if _, err := localruntime.BootstrapProtectedIndex(ctx, options); err != nil {
		t.Fatal(err)
	}
	layout, err := controlstorage.OpenExisting(control)
	if err != nil {
		t.Fatal(err)
	}
	stateBefore := mustReadFile(t, layout.StateDB)
	if err := os.WriteFile(layout.SearchStagingDB, []byte("interrupted-staging"), 0o600); err != nil {
		t.Fatal(err)
	}

	if _, err := localruntime.BootstrapProtectedIndex(ctx, options); err != nil {
		t.Fatal(err)
	}
	if got := mustReadFile(t, layout.StateDB); string(got) != string(stateBefore) {
		t.Fatal("state.db bytes changed during staging retry")
	}
	if _, err := os.Lstat(layout.SearchStagingDB); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("staging survived retry: %v", err)
	}
	if _, err := localruntime.QueryProtectedReadOnly(ctx, control, "staging retry", 10); err != nil {
		t.Fatal(err)
	}
}

func TestProtectedRuntimeLockContentionDoesNotMutateStateOrActiveSearch(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	control := filepath.Join(t.TempDir(), "control")
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte("lock protected"), 0o600); err != nil {
		t.Fatal(err)
	}
	options := localruntime.ProtectedIndexOptions{
		Root: root, ControlDir: control,
		ObservedAt: time.Date(2026, 10, 3, 12, 30, 0, 0, time.UTC),
		MaxBytes: 1024,
	}
	if _, err := localruntime.BootstrapProtectedIndex(ctx, options); err != nil {
		t.Fatal(err)
	}
	layout, err := controlstorage.OpenExisting(control)
	if err != nil {
		t.Fatal(err)
	}
	stateBefore := mustReadFile(t, layout.StateDB)
	searchBefore := mustReadFile(t, layout.SearchDB)
	lock, err := controlstorage.AcquireSearchMutationLock(layout)
	if err != nil {
		t.Fatal(err)
	}
	defer lock.Close()

	_, err = localruntime.BootstrapProtectedIndex(ctx, options)
	if !errors.Is(err, controlstorage.ErrSearchMutationLocked) {
		t.Fatalf("error=%v want ErrSearchMutationLocked", err)
	}
	if got := mustReadFile(t, layout.StateDB); string(got) != string(stateBefore) {
		t.Fatal("state.db changed under lock contention")
	}
	if got := mustReadFile(t, layout.SearchDB); string(got) != string(searchBefore) {
		t.Fatal("search.db changed under lock contention")
	}
}

func TestProtectedRuntimePromotionRefusesActiveSidecarAndKeepsStaging(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	control := filepath.Join(t.TempDir(), "control")
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte("promotion fail closed"), 0o600); err != nil {
		t.Fatal(err)
	}
	options := localruntime.ProtectedIndexOptions{
		Root: root, ControlDir: control,
		ObservedAt: time.Date(2026, 10, 3, 12, 35, 0, 0, time.UTC),
		MaxBytes: 1024,
	}
	if _, err := localruntime.BootstrapProtectedIndex(ctx, options); err != nil {
		t.Fatal(err)
	}
	layout, err := controlstorage.OpenExisting(control)
	if err != nil {
		t.Fatal(err)
	}
	stateBefore := mustReadFile(t, layout.StateDB)
	activeBefore := mustReadFile(t, layout.SearchDB)
	if err := os.WriteFile(layout.SearchDB+"-journal", []byte("simulate-hot-family"), 0o600); err != nil {
		t.Fatal(err)
	}

	_, err = localruntime.BootstrapProtectedIndex(ctx, options)
	if !errors.Is(err, controlstorage.ErrSearchActiveNotStandalone) {
		t.Fatalf("error=%v want ErrSearchActiveNotStandalone", err)
	}
	if got := mustReadFile(t, layout.StateDB); string(got) != string(stateBefore) {
		t.Fatal("state.db changed on failed promotion")
	}
	if got := mustReadFile(t, layout.SearchDB); string(got) != string(activeBefore) {
		t.Fatal("active search.db changed on failed promotion")
	}
	if _, err := os.Stat(layout.SearchStagingDB); err != nil {
		t.Fatalf("verified staging was not retained: %v", err)
	}
}

func TestProtectedRuntimeStateCorruptionDoesNotReplaceActiveSearch(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	control := filepath.Join(t.TempDir(), "control")
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte("state authority"), 0o600); err != nil {
		t.Fatal(err)
	}
	options := localruntime.ProtectedIndexOptions{
		Root: root, ControlDir: control,
		ObservedAt: time.Date(2026, 10, 3, 12, 40, 0, 0, time.UTC),
		MaxBytes: 1024,
	}
	if _, err := localruntime.BootstrapProtectedIndex(ctx, options); err != nil {
		t.Fatal(err)
	}
	layout, err := controlstorage.OpenExisting(control)
	if err != nil {
		t.Fatal(err)
	}
	searchBefore := mustReadFile(t, layout.SearchDB)
	if err := os.WriteFile(layout.StateDB, []byte("corrupt state authority"), 0o600); err != nil {
		t.Fatal(err)
	}

	if _, err := localruntime.BootstrapProtectedIndex(ctx, options); err == nil {
		t.Fatal("corrupt state.db unexpectedly allowed derived recovery")
	}
	if got := mustReadFile(t, layout.SearchDB); string(got) != string(searchBefore) {
		t.Fatal("active search cache changed after state.db corruption")
	}
}

func TestProtectedRuntimeCorpusDriftDoesNotReplaceActiveSearch(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	control := filepath.Join(t.TempDir(), "control")
	path := filepath.Join(root, "note.txt")
	if err := os.WriteFile(path, []byte("original corpus"), 0o600); err != nil {
		t.Fatal(err)
	}
	options := localruntime.ProtectedIndexOptions{
		Root: root, ControlDir: control,
		ObservedAt: time.Date(2026, 10, 3, 12, 50, 0, 0, time.UTC),
		MaxBytes: 1024,
	}
	if _, err := localruntime.BootstrapProtectedIndex(ctx, options); err != nil {
		t.Fatal(err)
	}
	layout, err := controlstorage.OpenExisting(control)
	if err != nil {
		t.Fatal(err)
	}
	stateBefore := mustReadFile(t, layout.StateDB)
	searchBefore := mustReadFile(t, layout.SearchDB)
	if err := os.WriteFile(path, []byte("changed corpus"), 0o600); err != nil {
		t.Fatal(err)
	}

	if _, err := localruntime.BootstrapProtectedIndex(ctx, options); err == nil {
		t.Fatal("corpus drift unexpectedly allowed derived recovery")
	}
	if got := mustReadFile(t, layout.StateDB); string(got) != string(stateBefore) {
		t.Fatal("state.db changed after corpus drift")
	}
	if got := mustReadFile(t, layout.SearchDB); string(got) != string(searchBefore) {
		t.Fatal("active search cache changed after corpus drift")
	}
}

func mustReadFile(t *testing.T, path string) []byte {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return data
}
