package local

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"reflect"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/controlstorage"
	searchsqlite "github.com/efremov-aleksei-96/keelaryn/internal/search/sqlite"
	sqlitestate "github.com/efremov-aleksei-96/keelaryn/internal/state/sqlite"
)

func TestProtectedRecoveryDiscardsValidPriorStagingInsteadOfTrustingIt(t *testing.T) {
	ctx := context.Background()
	root, control, options, layout := newProtectedRecoveryFixture(t, "valid staging must be rebuilt", 10)
	authorityBefore := protectedRecoveryAuthority(t, ctx, layout.StateDB, root)
	corpusBefore := protectedRecoveryCorpus(t, root)

	activeBytes, err := os.ReadFile(layout.SearchDB)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(layout.SearchStagingDB, activeBytes, 0o600); err != nil {
		t.Fatal(err)
	}
	discardCalls := 0
	ops := defaultProtectedSearchRecoveryOps()
	baseDiscard := ops.discardStaging
	ops.discardStaging = func(got controlstorage.Layout) error {
		discardCalls++
		if _, err := os.Stat(got.SearchStagingDB); err != nil {
			t.Fatalf("preexisting valid staging missing before discard: %v", err)
		}
		return baseDiscard(got)
	}

	if _, err := bootstrapProtectedIndex(ctx, options, ops); err != nil {
		t.Fatal(err)
	}
	if discardCalls != 1 {
		t.Fatalf("discard calls=%d want=1", discardCalls)
	}
	assertProtectedRecoveryInvariant(t, ctx, root, control, layout, authorityBefore, corpusBefore, "valid staging must be rebuilt")
}

func TestProtectedRecoveryDiscardsValidMismatchedStaging(t *testing.T) {
	ctx := context.Background()
	root, control, options, layout := newProtectedRecoveryFixture(t, "primary recovery corpus", 20)
	authorityBefore := protectedRecoveryAuthority(t, ctx, layout.StateDB, root)
	corpusBefore := protectedRecoveryCorpus(t, root)

	otherRoot := t.TempDir()
	otherControl := filepath.Join(t.TempDir(), "other-control")
	if err := os.WriteFile(filepath.Join(otherRoot, "other.txt"), []byte("mismatched staging source"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := BootstrapProtectedIndex(ctx, ProtectedIndexOptions{
		Root: otherRoot, ControlDir: otherControl,
		ObservedAt: time.Date(2026, 10, 3, 13, 21, 0, 0, time.UTC),
		MaxBytes: 1024,
	}); err != nil {
		t.Fatal(err)
	}
	otherLayout, err := controlstorage.OpenExisting(otherControl)
	if err != nil {
		t.Fatal(err)
	}
	mismatched, err := os.ReadFile(otherLayout.SearchDB)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(layout.SearchStagingDB, mismatched, 0o600); err != nil {
		t.Fatal(err)
	}

	if _, err := BootstrapProtectedIndex(ctx, options); err != nil {
		t.Fatalf("valid but mismatched prior staging was not discarded: %v", err)
	}
	assertProtectedRecoveryInvariant(t, ctx, root, control, layout, authorityBefore, corpusBefore, "primary recovery corpus")
}

func TestProtectedRecoveryFailureWindowsAreRetryableAndPreserveAuthority(t *testing.T) {
	ctx := context.Background()
	errInjected := errors.New("injected recovery boundary failure")
	cases := []struct {
		name                 string
		configure            func(*protectedSearchRecoveryOps, controlstorage.Layout)
		wantActiveUnchanged  bool
		wantStagingAfterFail bool
	}{
		{
			name: "before staged verification",
			configure: func(ops *protectedSearchRecoveryOps, layout controlstorage.Layout) {
				base := ops.verifyCandidate
				ops.verifyCandidate = func(ctx context.Context, path string, expected searchsqlite.SourceBoundary) error {
					if filepath.Clean(path) == filepath.Clean(layout.SearchStagingDB) {
						return errInjected
					}
					return base(ctx, path, expected)
				}
			},
			wantActiveUnchanged: true, wantStagingAfterFail: true,
		},
		{
			name: "after staged verification before promotion",
			configure: func(ops *protectedSearchRecoveryOps, _ controlstorage.Layout) {
				ops.reconcileActive = func(context.Context, controlstorage.Layout) error { return errInjected }
			},
			wantActiveUnchanged: true, wantStagingAfterFail: true,
		},
		{
			name: "promotion destination unavailable",
			configure: func(ops *protectedSearchRecoveryOps, _ controlstorage.Layout) {
				ops.promote = func(controlstorage.Layout) error { return errInjected }
			},
			wantActiveUnchanged: true, wantStagingAfterFail: true,
		},
		{
			name: "post promotion verification",
			configure: func(ops *protectedSearchRecoveryOps, layout controlstorage.Layout) {
				base := ops.verifyCandidate
				ops.verifyCandidate = func(ctx context.Context, path string, expected searchsqlite.SourceBoundary) error {
					if filepath.Clean(path) == filepath.Clean(layout.SearchDB) {
						return errInjected
					}
					return base(ctx, path, expected)
				}
			},
			wantActiveUnchanged: false, wantStagingAfterFail: false,
		},
	}

	for i, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			root, control, options, layout := newProtectedRecoveryFixture(t, "fault window searchable", 30+i)
			authorityBefore := protectedRecoveryAuthority(t, ctx, layout.StateDB, root)
			corpusBefore := protectedRecoveryCorpus(t, root)
			activeBefore, err := os.ReadFile(layout.SearchDB)
			if err != nil {
				t.Fatal(err)
			}

			ops := defaultProtectedSearchRecoveryOps()
			tc.configure(&ops, layout)
			_, err = bootstrapProtectedIndex(ctx, options, ops)
			if !errors.Is(err, errInjected) {
				t.Fatalf("error=%v want injected failure", err)
			}
			if got := protectedRecoveryAuthority(t, ctx, layout.StateDB, root); string(got) != string(authorityBefore) {
				t.Fatal("authoritative state changed across injected recovery failure")
			}
			if got := protectedRecoveryCorpus(t, root); !reflect.DeepEqual(got, corpusBefore) {
				t.Fatal("corpus bytes/topology changed across injected recovery failure")
			}
			if tc.wantActiveUnchanged {
				got, readErr := os.ReadFile(layout.SearchDB)
				if readErr != nil {
					t.Fatal(readErr)
				}
				if string(got) != string(activeBefore) {
					t.Fatal("active search cache changed before successful promotion")
				}
			}
			_, stageErr := os.Stat(layout.SearchStagingDB)
			if tc.wantStagingAfterFail && stageErr != nil {
				t.Fatalf("verified/retryable staging missing after failure: %v", stageErr)
			}
			if !tc.wantStagingAfterFail && !errors.Is(stageErr, os.ErrNotExist) {
				t.Fatalf("staging unexpectedly remains after completed promotion: %v", stageErr)
			}

			if _, err := BootstrapProtectedIndex(ctx, options); err != nil {
				t.Fatalf("deterministic retry failed: %v", err)
			}
			assertProtectedRecoveryInvariant(t, ctx, root, control, layout, authorityBefore, corpusBefore, "fault window searchable")
		})
	}
}

func newProtectedRecoveryFixture(t *testing.T, text string, minute int) (string, string, ProtectedIndexOptions, controlstorage.Layout) {
	t.Helper()
	root := t.TempDir()
	control := filepath.Join(t.TempDir(), "control")
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte(text), 0o600); err != nil {
		t.Fatal(err)
	}
	options := ProtectedIndexOptions{
		Root: root, ControlDir: control,
		ObservedAt: time.Date(2026, 10, 3, 13, minute, 0, 0, time.UTC),
		MaxBytes: 1024,
	}
	if _, err := BootstrapProtectedIndex(context.Background(), options); err != nil {
		t.Fatal(err)
	}
	layout, err := controlstorage.OpenExisting(control)
	if err != nil {
		t.Fatal(err)
	}
	return root, control, options, layout
}

func assertProtectedRecoveryInvariant(
	t *testing.T,
	ctx context.Context,
	root, control string,
	layout controlstorage.Layout,
	authorityBefore []byte,
	corpusBefore map[string][sha256.Size]byte,
	query string,
) {
	t.Helper()
	if got := protectedRecoveryAuthority(t, ctx, layout.StateDB, root); string(got) != string(authorityBefore) {
		t.Fatal("authoritative state changed across derived recovery")
	}
	if got := protectedRecoveryCorpus(t, root); !reflect.DeepEqual(got, corpusBefore) {
		t.Fatal("corpus bytes/topology changed across derived recovery")
	}
	if _, err := os.Lstat(layout.SearchStagingDB); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("staging survived successful recovery: %v", err)
	}
	hits, err := QueryProtectedReadOnlyCurrent(ctx, control, query, 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(hits) != 1 {
		t.Fatalf("hits=%#v", hits)
	}
}

func protectedRecoveryAuthority(t *testing.T, ctx context.Context, statePath, root string) []byte {
	t.Helper()
	state, err := sqlitestate.OpenReadOnly(ctx, statePath)
	if err != nil {
		t.Fatal(err)
	}
	defer state.Close()
	scan, found, err := state.LatestCompleteScan(ctx, ProviderID, root)
	if err != nil {
		t.Fatal(err)
	}
	if !found {
		t.Fatal("authoritative scan missing")
	}
	inventory, err := state.Inventory(ctx, ProviderID, root)
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
		histories = append(histories, map[string]any{"artifact_id": entry.ArtifactID, "history": history})
	}
	payload, err := json.Marshal(map[string]any{"scan": scan, "inventory": inventory, "histories": histories})
	if err != nil {
		t.Fatal(err)
	}
	return payload
}

func protectedRecoveryCorpus(t *testing.T, root string) map[string][sha256.Size]byte {
	t.Helper()
	out := map[string][sha256.Size]byte{}
	err := filepath.WalkDir(root, func(path string, entry fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if entry.IsDir() {
			return nil
		}
		if !entry.Type().IsRegular() {
			return errors.New("unexpected non-regular corpus entry in recovery fixture")
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(root, path)
		if err != nil {
			return err
		}
		out[filepath.ToSlash(rel)] = sha256.Sum256(data)
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return out
}

func TestProtectedRecoveryRepairsCorruptActiveFamilyWithSidecar(t *testing.T) {
	ctx := context.Background()
	root, control, options, layout := newProtectedRecoveryFixture(t, "corrupt family with sidecar", 41)
	authorityBefore := protectedRecoveryAuthority(t, ctx, layout.StateDB, root)
	corpusBefore := protectedRecoveryCorpus(t, root)

	if err := os.WriteFile(layout.SearchDB, []byte("not sqlite"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(layout.SearchDB+"-journal", []byte("unrecoverable derived journal"), 0o600); err != nil {
		t.Fatal(err)
	}

	if _, err := BootstrapProtectedIndex(ctx, options); err != nil {
		t.Fatalf("corrupt active SQLite family with sidecar was not recoverable: %v", err)
	}
	if _, err := os.Lstat(layout.SearchDB + "-journal"); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("unrecoverable active sidecar survived recovery: %v", err)
	}
	assertProtectedRecoveryInvariant(t, ctx, root, control, layout, authorityBefore, corpusBefore, "corrupt family with sidecar")
}

func TestProtectedRecoveryPromotesPastOrphanActiveSHM(t *testing.T) {
	ctx := context.Background()
	root, control, options, layout := newProtectedRecoveryFixture(t, "orphan shm recovery", 43)
	authorityBefore := protectedRecoveryAuthority(t, ctx, layout.StateDB, root)
	corpusBefore := protectedRecoveryCorpus(t, root)

	// Model a crash residue that is not a usable WAL family. SQLite may open
	// the valid main database successfully and leave this orphan SHM behind.
	if err := os.WriteFile(layout.SearchDB+"-shm", make([]byte, 32*1024), 0o600); err != nil {
		t.Fatal(err)
	}

	if _, err := BootstrapProtectedIndex(ctx, options); err != nil {
		t.Fatalf("orphan active SHM blocked deterministic promotion: %v", err)
	}
	if _, err := os.Lstat(layout.SearchDB + "-shm"); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("orphan active SHM survived recovery: %v", err)
	}
	assertProtectedRecoveryInvariant(t, ctx, root, control, layout, authorityBefore, corpusBefore, "orphan shm recovery")
}

func TestReconcileActiveSearchFamilyCancellationPreservesActiveFamily(t *testing.T) {
	_, _, _, layout := newProtectedRecoveryFixture(t, "canceled reconcile preserves active", 44)
	activeBefore, err := os.ReadFile(layout.SearchDB)
	if err != nil {
		t.Fatal(err)
	}
	shmBefore := make([]byte, 32*1024)
	if err := os.WriteFile(layout.SearchDB+"-shm", shmBefore, 0o600); err != nil {
		t.Fatal(err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	err = reconcileActiveSearchSQLiteFamily(ctx, layout)
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("error=%v want context.Canceled", err)
	}
	if got, readErr := os.ReadFile(layout.SearchDB); readErr != nil || string(got) != string(activeBefore) {
		t.Fatalf("active cache changed after canceled reconciliation: err=%v", readErr)
	}
	if got, readErr := os.ReadFile(layout.SearchDB+"-shm"); readErr != nil || string(got) != string(shmBefore) {
		t.Fatalf("active sidecar changed after canceled reconciliation: err=%v", readErr)
	}
}

func TestProtectedRecoveryCancellationAfterRealReconcileBeforePromotionPreservesActiveAndStaging(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	root, _, options, layout := newProtectedRecoveryFixture(t, "cancel before promotion", 45)
	authorityBefore := protectedRecoveryAuthority(t, context.Background(), layout.StateDB, root)
	corpusBefore := protectedRecoveryCorpus(t, root)
	if err := os.WriteFile(layout.SearchDB+"-shm", make([]byte, 32*1024), 0o600); err != nil {
		t.Fatal(err)
	}

	ops := defaultProtectedSearchRecoveryOps()
	baseReconcile := ops.reconcileActive
	ops.reconcileActive = func(callCtx context.Context, got controlstorage.Layout) error {
		if err := baseReconcile(callCtx, got); err != nil {
			return err
		}
		cancel()
		return nil
	}
	_, err := bootstrapProtectedIndex(ctx, options, ops)
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("error=%v want context.Canceled", err)
	}
	if _, statErr := os.Stat(layout.SearchDB); statErr != nil {
		t.Fatalf("active cache disappeared after cancellation before promotion: %v", statErr)
	}
	expected, expectedErr := expectedSearchBoundaryReadOnly(context.Background(), layout.StateDB, root)
	if expectedErr != nil {
		t.Fatal(expectedErr)
	}
	if verifyErr := verifyProtectedSearchCandidate(context.Background(), layout.SearchDB, expected); verifyErr != nil {
		t.Fatalf("active cache is not valid/current after canceled reconciliation: %v", verifyErr)
	}
	if _, statErr := os.Stat(layout.SearchStagingDB); statErr != nil {
		t.Fatalf("verified staging was not retained after cancellation: %v", statErr)
	}
	if got := protectedRecoveryAuthority(t, context.Background(), layout.StateDB, root); string(got) != string(authorityBefore) {
		t.Fatal("authoritative state changed after cancellation before promotion")
	}
	if got := protectedRecoveryCorpus(t, root); !reflect.DeepEqual(got, corpusBefore) {
		t.Fatal("corpus bytes/topology changed after cancellation before promotion")
	}
}


func TestProtectedRecoveryCancellationDuringPromotionDoesNotOverrideCommittedResult(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	root, control, options, layout := newProtectedRecoveryFixture(t, "cancel during committed promotion", 46)
	authorityBefore := protectedRecoveryAuthority(t, context.Background(), layout.StateDB, root)
	corpusBefore := protectedRecoveryCorpus(t, root)

	ops := defaultProtectedSearchRecoveryOps()
	basePromote := ops.promote
	ops.promote = func(got controlstorage.Layout) error {
		if err := basePromote(got); err != nil {
			return err
		}
		// Cancellation after the commit boundary must not make the caller observe
		// a cancellation after active replacement and staging consumption.
		cancel()
		return nil
	}

	if _, err := bootstrapProtectedIndex(ctx, options, ops); err != nil {
		t.Fatalf("committed promotion was incorrectly overridden by cancellation: %v", err)
	}
	if ctx.Err() != context.Canceled {
		t.Fatalf("test did not cancel caller context: %v", ctx.Err())
	}
	if _, err := os.Lstat(layout.SearchStagingDB); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("staging survived committed promotion: %v", err)
	}
	if got := protectedRecoveryAuthority(t, context.Background(), layout.StateDB, root); string(got) != string(authorityBefore) {
		t.Fatal("authoritative state changed during committed derived promotion")
	}
	if got := protectedRecoveryCorpus(t, root); !reflect.DeepEqual(got, corpusBefore) {
		t.Fatal("corpus bytes/topology changed during committed derived promotion")
	}
	hits, err := QueryProtectedReadOnlyCurrent(context.Background(), control, "cancel during committed promotion", 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(hits) != 1 {
		t.Fatalf("committed active search is not queryable: %#v", hits)
	}
}
