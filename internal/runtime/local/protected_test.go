package local_test

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/controlstorage"
	localruntime "github.com/efremov-aleksei-96/keelaryn/internal/runtime/local"
	sqlitestate "github.com/efremov-aleksei-96/keelaryn/internal/state/sqlite"
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




func TestProtectedRuntimeSearchLockOnlyStillAllowsFreshBootstrap(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte("fresh after lock-only crash"), 0o600); err != nil {
		t.Fatal(err)
	}
	control := filepath.Join(t.TempDir(), "control")
	layout, err := controlstorage.Prepare(control)
	if err != nil {
		t.Fatal(err)
	}
	lock, err := controlstorage.AcquireSearchMutationLock(layout)
	if err != nil {
		t.Fatal(err)
	}
	if err := lock.Close(); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Lstat(layout.StateDB); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("state.db unexpectedly exists before fresh bootstrap: %v", err)
	}

	result, err := localruntime.BootstrapProtectedIndex(ctx, localruntime.ProtectedIndexOptions{
		Root: root, ControlDir: control,
		ObservedAt: time.Date(2026, 10, 3, 11, 45, 0, 0, time.UTC),
		MaxBytes: 1024,
	})
	if err != nil {
		t.Fatal(err)
	}
	if result.ReusedScan || result.Indexed != 1 {
		t.Fatalf("result=%#v", result)
	}
	if _, err := os.Stat(layout.StateDB); err != nil {
		t.Fatalf("fresh bootstrap did not create state.db: %v", err)
	}
	if _, err := localruntime.QueryProtectedReadOnlyCurrent(ctx, control, "fresh after lock-only", 10); err != nil {
		t.Fatal(err)
	}
}

func TestProtectedRuntimeMissingStateWithDerivedFootprintFailsClosed(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	control := filepath.Join(t.TempDir(), "control")
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte("lost authority must not remint"), 0o600); err != nil {
		t.Fatal(err)
	}
	options := localruntime.ProtectedIndexOptions{
		Root: root, ControlDir: control,
		ObservedAt: time.Date(2026, 10, 3, 11, 50, 0, 0, time.UTC),
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
	stagingBefore := []byte("prior-derived-staging")
	if err := os.WriteFile(layout.SearchStagingDB, stagingBefore, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(layout.StateDB); err != nil {
		t.Fatal(err)
	}

	_, err = localruntime.BootstrapProtectedIndex(ctx, options)
	if !errors.Is(err, localruntime.ErrStateDatabaseNotFound) {
		t.Fatalf("error=%v want ErrStateDatabaseNotFound", err)
	}
	if _, err := os.Lstat(layout.StateDB); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("missing authoritative state was recreated: %v", err)
	}
	if got := mustReadFile(t, layout.SearchDB); string(got) != string(searchBefore) {
		t.Fatal("active derived cache changed after authoritative state loss")
	}
	if got := mustReadFile(t, layout.SearchStagingDB); string(got) != string(stagingBefore) {
		t.Fatal("staging changed after authoritative state loss")
	}
}

func TestProtectedRuntimeOrphanStateSidecarWithoutMainFailsClosed(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte("orphan state sidecar"), 0o600); err != nil {
		t.Fatal(err)
	}
	control := filepath.Join(t.TempDir(), "control")
	layout, err := controlstorage.Prepare(control)
	if err != nil {
		t.Fatal(err)
	}
	sidecar := layout.StateDB + "-wal"
	sidecarBytes := []byte("possible-authority-recovery-state")
	if err := os.WriteFile(sidecar, sidecarBytes, 0o600); err != nil {
		t.Fatal(err)
	}

	_, err = localruntime.BootstrapProtectedIndex(ctx, localruntime.ProtectedIndexOptions{
		Root: root, ControlDir: control,
		ObservedAt: time.Date(2026, 10, 3, 11, 55, 0, 0, time.UTC),
		MaxBytes: 1024,
	})
	if !errors.Is(err, localruntime.ErrStateDatabaseNotFound) {
		t.Fatalf("error=%v want ErrStateDatabaseNotFound", err)
	}
	if _, err := os.Lstat(layout.StateDB); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("state.db unexpectedly created: %v", err)
	}
	if got := mustReadFile(t, sidecar); string(got) != string(sidecarBytes) {
		t.Fatal("orphan state sidecar was mutated")
	}
	for _, path := range []string{layout.SearchDB, layout.SearchStagingDB} {
		if _, err := os.Lstat(path); !errors.Is(err, os.ErrNotExist) {
			t.Fatalf("derived search mutation started before missing state failed closed: %s err=%v", path, err)
		}
	}
	lockInfo, err := os.Lstat(layout.SearchLock)
	if err != nil {
		t.Fatalf("coordination-only search lock was not created before post-lock authority preflight: %v", err)
	}
	if !lockInfo.Mode().IsRegular() || lockInfo.Mode()&os.ModeSymlink != 0 {
		t.Fatalf("search lock is not a safe regular coordination file: mode=%v", lockInfo.Mode())
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
	authorityBefore := captureLocalAuthority(t, ctx, layout.StateDB, root)
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
	if got := captureLocalAuthority(t, ctx, layout.StateDB, root); string(got) != string(authorityBefore) {
		t.Fatal("authoritative state changed while recovering derived search cache")
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
	authorityBefore := captureLocalAuthority(t, ctx, layout.StateDB, root)
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
	if got := captureLocalAuthority(t, ctx, layout.StateDB, root); string(got) != string(authorityBefore) {
		t.Fatal("authoritative state changed while rebuilding missing derived cache")
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
	authorityBefore := captureLocalAuthority(t, ctx, layout.StateDB, root)
	if err := os.WriteFile(layout.SearchStagingDB, []byte("interrupted-staging"), 0o600); err != nil {
		t.Fatal(err)
	}

	if _, err := localruntime.BootstrapProtectedIndex(ctx, options); err != nil {
		t.Fatal(err)
	}
	if got := captureLocalAuthority(t, ctx, layout.StateDB, root); string(got) != string(authorityBefore) {
		t.Fatal("authoritative state changed during staging retry")
	}
	if _, err := os.Lstat(layout.SearchStagingDB); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("staging survived retry: %v", err)
	}
	if _, err := localruntime.QueryProtectedReadOnly(ctx, control, "staging retry", 10); err != nil {
		t.Fatal(err)
	}
}


func TestProtectedReadOnlyQueryNeverUsesStagingCache(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	control := filepath.Join(t.TempDir(), "control")
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte("active cache authority"), 0o600); err != nil {
		t.Fatal(err)
	}
	options := localruntime.ProtectedIndexOptions{
		Root: root, ControlDir: control,
		ObservedAt: time.Date(2026, 10, 3, 12, 25, 0, 0, time.UTC),
		MaxBytes: 1024,
	}
	if _, err := localruntime.BootstrapProtectedIndex(ctx, options); err != nil {
		t.Fatal(err)
	}
	layout, err := controlstorage.OpenExisting(control)
	if err != nil {
		t.Fatal(err)
	}
	staging := []byte("not-a-query-authority")
	if err := os.WriteFile(layout.SearchStagingDB, staging, 0o600); err != nil {
		t.Fatal(err)
	}

	hits, err := localruntime.QueryProtectedReadOnly(ctx, control, "active cache authority", 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(hits) != 1 {
		t.Fatalf("hits=%#v", hits)
	}
	if got := mustReadFile(t, layout.SearchStagingDB); string(got) != string(staging) {
		t.Fatal("read-only query touched staging")
	}
}

func TestProtectedRuntimeRecoversNoActiveWithInterruptedStaging(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	control := filepath.Join(t.TempDir(), "control")
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte("rename interruption retry"), 0o600); err != nil {
		t.Fatal(err)
	}
	options := localruntime.ProtectedIndexOptions{
		Root: root, ControlDir: control,
		ObservedAt: time.Date(2026, 10, 3, 12, 27, 0, 0, time.UTC),
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
	authorityBefore := captureLocalAuthority(t, ctx, layout.StateDB, root)
	if err := os.Remove(layout.SearchDB); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(layout.SearchStagingDB, []byte("staged-after-active-removal"), 0o600); err != nil {
		t.Fatal(err)
	}

	recovered, err := localruntime.BootstrapProtectedIndex(ctx, options)
	if err != nil {
		t.Fatal(err)
	}
	if !recovered.ReusedScan || recovered.ScanID != first.ScanID {
		t.Fatalf("recovered=%#v first=%#v", recovered, first)
	}
	if got := captureLocalAuthority(t, ctx, layout.StateDB, root); string(got) != string(authorityBefore) {
		t.Fatal("authoritative state changed while recovering no-active+staging state")
	}
	if _, err := os.Lstat(layout.SearchStagingDB); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("staging survived deterministic retry: %v", err)
	}
	hits, err := localruntime.QueryProtectedReadOnly(ctx, control, "rename interruption retry", 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(hits) != 1 {
		t.Fatalf("hits=%#v", hits)
	}
}

func TestProtectedRuntimeRecoversOrphanStagingSidecar(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	control := filepath.Join(t.TempDir(), "control")
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte("orphan sidecar recovery"), 0o600); err != nil {
		t.Fatal(err)
	}
	options := localruntime.ProtectedIndexOptions{
		Root: root, ControlDir: control,
		ObservedAt: time.Date(2026, 10, 3, 12, 29, 0, 0, time.UTC),
		MaxBytes: 1024,
	}
	if _, err := localruntime.BootstrapProtectedIndex(ctx, options); err != nil {
		t.Fatal(err)
	}
	layout, err := controlstorage.OpenExisting(control)
	if err != nil {
		t.Fatal(err)
	}
	authorityBefore := captureLocalAuthority(t, ctx, layout.StateDB, root)
	orphan := layout.SearchStagingDB + "-wal"
	if err := os.WriteFile(orphan, []byte("orphan-wal"), 0o600); err != nil {
		t.Fatal(err)
	}

	if _, err := localruntime.BootstrapProtectedIndex(ctx, options); err != nil {
		t.Fatal(err)
	}
	if got := captureLocalAuthority(t, ctx, layout.StateDB, root); string(got) != string(authorityBefore) {
		t.Fatal("authoritative state changed while cleaning orphan staging sidecar")
	}
	if _, err := os.Lstat(orphan); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("orphan staging sidecar survived retry: %v", err)
	}
	hits, err := localruntime.QueryProtectedReadOnly(ctx, control, "orphan sidecar recovery", 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(hits) != 1 {
		t.Fatalf("hits=%#v", hits)
	}
}

func TestProtectedCurrentSearchFailsClosedWithoutAuthoritativeState(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	control := filepath.Join(t.TempDir(), "control")
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte("bound current search"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := localruntime.BootstrapProtectedIndex(ctx, localruntime.ProtectedIndexOptions{
		Root: root, ControlDir: control,
		ObservedAt: time.Date(2026, 10, 3, 12, 31, 0, 0, time.UTC),
		MaxBytes: 1024,
	}); err != nil {
		t.Fatal(err)
	}
	layout, err := controlstorage.OpenExisting(control)
	if err != nil {
		t.Fatal(err)
	}
	hits, err := localruntime.QueryProtectedReadOnlyCurrent(ctx, control, "bound current search", 10)
	if err != nil || len(hits) != 1 {
		t.Fatalf("initial current search hits=%#v err=%v", hits, err)
	}
	if err := os.Remove(layout.StateDB); err != nil {
		t.Fatal(err)
	}
	if _, err := localruntime.QueryProtectedReadOnlyCurrent(ctx, control, "bound current search", 10); !errors.Is(err, localruntime.ErrStateDatabaseNotFound) {
		t.Fatalf("error=%v want ErrStateDatabaseNotFound", err)
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
	authorityBefore := captureLocalAuthority(t, ctx, layout.StateDB, root)
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
	if got := captureLocalAuthority(t, ctx, layout.StateDB, root); string(got) != string(authorityBefore) {
		t.Fatal("authoritative state changed under lock contention")
	}
	if got := mustReadFile(t, layout.SearchDB); string(got) != string(searchBefore) {
		t.Fatal("search.db changed under lock contention")
	}
}

func TestProtectedSearchWriterLockBlocksRWPathsButNotReadOnlyQuery(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	control := filepath.Join(t.TempDir(), "control")
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte("writer lock boundary"), 0o600); err != nil {
		t.Fatal(err)
	}
	options := localruntime.ProtectedIndexOptions{
		Root: root, ControlDir: control,
		ObservedAt: time.Date(2026, 10, 3, 12, 32, 0, 0, time.UTC),
		MaxBytes: 1024,
	}
	if _, err := localruntime.BootstrapProtectedIndex(ctx, options); err != nil {
		t.Fatal(err)
	}
	layout, err := controlstorage.OpenExisting(control)
	if err != nil {
		t.Fatal(err)
	}
	lock, err := controlstorage.AcquireSearchMutationLock(layout)
	if err != nil {
		t.Fatal(err)
	}
	defer lock.Close()

	if _, err := localruntime.QueryProtected(ctx, control, "writer lock", 10); !errors.Is(err, controlstorage.ErrSearchMutationLocked) {
		t.Fatalf("RW query error=%v want ErrSearchMutationLocked", err)
	}
	if _, err := localruntime.BuildProtectedContext(ctx, localruntime.ProtectedContextOptions{
		Root: root, ControlDir: control,
		Query: "writer lock", Reason: "test writer lock", Limit: 10, MaxBytes: 1024,
	}); !errors.Is(err, controlstorage.ErrSearchMutationLocked) {
		t.Fatalf("RW context error=%v want ErrSearchMutationLocked", err)
	}
	hits, err := localruntime.QueryProtectedReadOnly(ctx, control, "writer lock", 10)
	if err != nil {
		t.Fatalf("read-only query under writer lock: %v", err)
	}
	if len(hits) != 1 {
		t.Fatalf("read-only hits=%#v", hits)
	}
}

func TestProtectedRuntimeReconcilesActiveSidecarBeforePromotion(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	control := filepath.Join(t.TempDir(), "control")
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte("promotion reconciles sidecar"), 0o600); err != nil {
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
	authorityBefore := captureLocalAuthority(t, ctx, layout.StateDB, root)
	if err := os.WriteFile(layout.SearchDB+"-journal", []byte("simulate-hot-family"), 0o600); err != nil {
		t.Fatal(err)
	}

	if _, err := localruntime.BootstrapProtectedIndex(ctx, options); err != nil {
		t.Fatalf("active SQLite family was not reconciled before promotion: %v", err)
	}
	if got := captureLocalAuthority(t, ctx, layout.StateDB, root); string(got) != string(authorityBefore) {
		t.Fatal("authoritative state changed while reconciling derived active SQLite family")
	}
	if _, err := os.Lstat(layout.SearchStagingDB); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("staging survived successful promotion: %v", err)
	}
	if _, err := os.Lstat(layout.SearchDB + "-journal"); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("active journal survived reconciliation/promotion: %v", err)
	}
	hits, err := localruntime.QueryProtectedReadOnly(ctx, control, "promotion reconciles sidecar", 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(hits) != 1 {
		t.Fatalf("hits=%#v", hits)
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
	stagingBefore := []byte("preexisting-staging-must-survive-invalid-state")
	if err := os.WriteFile(layout.SearchStagingDB, stagingBefore, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(layout.StateDB, []byte("corrupt state authority"), 0o600); err != nil {
		t.Fatal(err)
	}

	if _, err := localruntime.BootstrapProtectedIndex(ctx, options); err == nil {
		t.Fatal("corrupt state.db unexpectedly allowed derived recovery")
	}
	if got := mustReadFile(t, layout.SearchDB); string(got) != string(searchBefore) {
		t.Fatal("active search cache changed after state.db corruption")
	}
	if got := mustReadFile(t, layout.SearchStagingDB); string(got) != string(stagingBefore) {
		t.Fatal("staging changed before corrupt state.db failed closed")
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
	authorityBefore := captureLocalAuthority(t, ctx, layout.StateDB, root)
	searchBefore := mustReadFile(t, layout.SearchDB)
	stagingBefore := []byte("preexisting-staging-must-survive-corpus-drift")
	if err := os.WriteFile(layout.SearchStagingDB, stagingBefore, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("changed corpus"), 0o600); err != nil {
		t.Fatal(err)
	}

	if _, err := localruntime.BootstrapProtectedIndex(ctx, options); err == nil {
		t.Fatal("corpus drift unexpectedly allowed derived recovery")
	}
	if got := captureLocalAuthority(t, ctx, layout.StateDB, root); string(got) != string(authorityBefore) {
		t.Fatal("authoritative state changed after corpus drift")
	}
	if got := mustReadFile(t, layout.SearchDB); string(got) != string(searchBefore) {
		t.Fatal("active search cache changed after corpus drift")
	}
	if got := mustReadFile(t, layout.SearchStagingDB); string(got) != string(stagingBefore) {
		t.Fatal("staging changed before corpus drift failed closed")
	}
}

func captureLocalAuthority(t *testing.T, ctx context.Context, statePath, root string) []byte {
	t.Helper()
	state, err := sqlitestate.OpenReadOnly(ctx, statePath)
	if err != nil {
		t.Fatal(err)
	}
	defer state.Close()

	scan, found, err := state.LatestCompleteScan(ctx, localruntime.ProviderID, root)
	if err != nil {
		t.Fatal(err)
	}
	if !found {
		t.Fatal("authoritative scan missing")
	}
	inventory, err := state.Inventory(ctx, localruntime.ProviderID, root)
	if err != nil {
		t.Fatal(err)
	}
	histories := make([]map[string]any, 0)
	seen := map[string]bool{}
	for _, entry := range inventory {
		if entry.ArtifactID == "" || seen[string(entry.ArtifactID)] {
			continue
		}
		seen[string(entry.ArtifactID)] = true
		history, err := state.RevisionHistory(ctx, entry.ArtifactID)
		if err != nil {
			t.Fatal(err)
		}
		histories = append(histories, map[string]any{
			"artifact_id": entry.ArtifactID,
			"history":     history,
		})
	}
	payload, err := json.Marshal(map[string]any{
		"scan":      scan,
		"inventory": inventory,
		"histories": histories,
	})
	if err != nil {
		t.Fatal(err)
	}
	return payload
}

func mustReadFile(t *testing.T, path string) []byte {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return data
}
