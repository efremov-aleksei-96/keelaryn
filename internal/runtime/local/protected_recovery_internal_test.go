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
	"strings"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/controlstorage"
	searchsqlite "github.com/efremov-aleksei-96/keelaryn/internal/search/sqlite"
	sqlitestate "github.com/efremov-aleksei-96/keelaryn/internal/state/sqlite"
	zsqlite "zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
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

func TestProtectedRecoveryFullStateVerificationFailsBeforeDerivedMutation(t *testing.T) {
	ctx := context.Background()
	root, _, options, layout := newProtectedRecoveryFixture(t, "hidden state corruption guard", 42)
	authorityBefore := protectedRecoveryAuthority(t, ctx, layout.StateDB, root)
	corpusBefore := protectedRecoveryCorpus(t, root)
	activeBefore, err := os.ReadFile(layout.SearchDB)
	if err != nil {
		t.Fatal(err)
	}
	stagingBefore := []byte("prior-staging-must-survive-invalid-state")
	if err := os.WriteFile(layout.SearchStagingDB, stagingBefore, 0o600); err != nil {
		t.Fatal(err)
	}

	injectOrphanLocatorForeignKeyViolation(t, layout.StateDB, root)

	// The selected authority reads used by the old preflight still succeed and
	// return the same local authority, proving this corruption is outside that
	// narrow read set.
	state, err := sqlitestate.OpenReadOnly(ctx, layout.StateDB)
	if err != nil {
		t.Fatalf("narrow read-only state open unexpectedly caught the FK violation: %v", err)
	}
	if err := state.Close(); err != nil {
		t.Fatal(err)
	}
	if got := protectedRecoveryAuthority(t, ctx, layout.StateDB, root); string(got) != string(authorityBefore) {
		t.Fatal("injected unrelated FK violation changed selected local authority")
	}
	if err := sqlitestate.VerifyReadOnly(ctx, layout.StateDB); err == nil {
		t.Fatal("full read-only verifier accepted an injected foreign-key violation")
	}

	if _, err := BootstrapProtectedIndex(ctx, options); err == nil {
		t.Fatal("recovery unexpectedly mutated derived state with invalid authoritative state.db")
	}
	if got, err := os.ReadFile(layout.SearchDB); err != nil || string(got) != string(activeBefore) {
		t.Fatalf("active search cache changed before invalid state failed closed: err=%v", err)
	}
	if got, err := os.ReadFile(layout.SearchStagingDB); err != nil || string(got) != string(stagingBefore) {
		t.Fatalf("staging changed before invalid state failed closed: err=%v", err)
	}
	if got := protectedRecoveryCorpus(t, root); !reflect.DeepEqual(got, corpusBefore) {
		t.Fatal("corpus bytes/topology changed while invalid state failed closed")
	}
}

func injectOrphanLocatorForeignKeyViolation(t *testing.T, statePath, root string) {
	t.Helper()
	conn, err := zsqlite.OpenConn(statePath, zsqlite.OpenReadWrite)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	if err := sqlitex.ExecuteTransient(conn, "PRAGMA foreign_keys = OFF;", nil); err != nil {
		t.Fatal(err)
	}

	var triggers []string
	if err := sqlitex.Execute(conn,
		"SELECT name FROM sqlite_schema WHERE type='trigger' AND tbl_name='locators' ORDER BY name",
		&sqlitex.ExecOptions{ResultFunc: func(stmt *zsqlite.Stmt) error {
			triggers = append(triggers, stmt.ColumnText(0))
			return nil
		}}); err != nil {
		t.Fatal(err)
	}
	for _, name := range triggers {
		quoted := `"` + strings.ReplaceAll(name, `"`, `""`) + `"`
		if err := sqlitex.ExecuteTransient(conn, "DROP TRIGGER "+quoted+";", nil); err != nil {
			t.Fatalf("drop locator trigger %q: %v", name, err)
		}
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO locators (locator_id, observation_id, provider_id, root, path) VALUES (?1, ?2, ?3, ?4, ?5)",
		&sqlitex.ExecOptions{Args: []any{
			"loc_orphan_recovery_fk",
			"obs_missing_recovery_fk",
			string(ProviderID),
			root,
			"orphan-recovery-fk.txt",
		}}); err != nil {
		t.Fatal(err)
	}
}
