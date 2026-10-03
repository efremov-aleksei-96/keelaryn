package controlstorage

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func TestPromoteStagedSearchRenameFailureLeavesDeterministicRetryState(t *testing.T) {
	layout, err := Prepare(filepath.Join(t.TempDir(), "control"))
	if err != nil {
		t.Fatal(err)
	}
	stateBytes := []byte("state-authority")
	activeBytes := []byte("old-derived-cache")
	stagedBytes := []byte("verified-staged-cache")
	if err := os.WriteFile(layout.StateDB, stateBytes, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(layout.SearchDB, activeBytes, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(layout.SearchStagingDB, stagedBytes, 0o600); err != nil {
		t.Fatal(err)
	}

	errInjected := errors.New("injected rename failure")
	err = promoteStagedSearch(layout, func(oldPath, newPath string) error {
		if oldPath != layout.SearchStagingDB || newPath != layout.SearchDB {
			t.Fatalf("rename paths old=%q new=%q", oldPath, newPath)
		}
		return errInjected
	})
	if !errors.Is(err, errInjected) {
		t.Fatalf("error=%v want injected rename failure", err)
	}
	if got, err := os.ReadFile(layout.StateDB); err != nil || string(got) != string(stateBytes) {
		t.Fatalf("state authority changed: bytes=%q err=%v", got, err)
	}
	if _, err := os.Lstat(layout.SearchDB); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("active cache should be absent after remove-before-rename failure: %v", err)
	}
	if got, err := os.ReadFile(layout.SearchStagingDB); err != nil || string(got) != string(stagedBytes) {
		t.Fatalf("retryable staging changed: bytes=%q err=%v", got, err)
	}

	if err := PromoteStagedSearch(layout); err != nil {
		t.Fatalf("deterministic promotion retry failed: %v", err)
	}
	if got, err := os.ReadFile(layout.SearchDB); err != nil || string(got) != string(stagedBytes) {
		t.Fatalf("promoted cache bytes=%q err=%v", got, err)
	}
	if _, err := os.Lstat(layout.SearchStagingDB); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("staging survived successful retry: %v", err)
	}
}


func TestDiscardActiveSearchFamilyAfterReconcileFailureDeletesExactDerivedFamily(t *testing.T) {
	layout, err := Prepare(filepath.Join(t.TempDir(), "control"))
	if err != nil {
		t.Fatal(err)
	}
	stateBytes := []byte("state-authority-unchanged")
	stagingBytes := []byte("verified-staging-unchanged")
	if err := os.WriteFile(layout.StateDB, stateBytes, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(layout.SearchStagingDB, stagingBytes, 0o600); err != nil {
		t.Fatal(err)
	}
	for path, data := range map[string][]byte{
		layout.SearchDB:            []byte("corrupt-derived-main"),
		layout.SearchDB + "-journal": []byte("derived-journal"),
		layout.SearchDB + "-wal":     []byte("derived-wal"),
		layout.SearchDB + "-shm":     []byte("derived-shm"),
	} {
		if err := os.WriteFile(path, data, 0o600); err != nil {
			t.Fatal(err)
		}
	}

	if err := DiscardActiveSearchFamilyAfterReconcileFailure(layout); err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{layout.SearchDB, layout.SearchDB + "-journal", layout.SearchDB + "-wal", layout.SearchDB + "-shm"} {
		if _, err := os.Lstat(path); !errors.Is(err, os.ErrNotExist) {
			t.Fatalf("active derived family member survived discard: %s err=%v", path, err)
		}
	}
	if got, err := os.ReadFile(layout.StateDB); err != nil || string(got) != string(stateBytes) {
		t.Fatalf("state authority changed: bytes=%q err=%v", got, err)
	}
	if got, err := os.ReadFile(layout.SearchStagingDB); err != nil || string(got) != string(stagingBytes) {
		t.Fatalf("verified staging changed: bytes=%q err=%v", got, err)
	}
}

func TestDiscardActiveSearchFamilyAfterReconcileFailureUnsafeSidecarIsZeroMutation(t *testing.T) {
	layout, err := Prepare(filepath.Join(t.TempDir(), "control"))
	if err != nil {
		t.Fatal(err)
	}
	mainBytes := []byte("derived-main-must-survive")
	if err := os.WriteFile(layout.SearchDB, mainBytes, 0o600); err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(t.TempDir(), "outside-target")
	targetBytes := []byte("outside-must-not-change")
	if err := os.WriteFile(target, targetBytes, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, layout.SearchDB+"-wal"); err != nil {
		t.Skipf("symlink unavailable: %v", err)
	}

	err = DiscardActiveSearchFamilyAfterReconcileFailure(layout)
	if !errors.Is(err, ErrControlFileUnsafe) {
		t.Fatalf("error=%v want ErrControlFileUnsafe", err)
	}
	if got, err := os.ReadFile(layout.SearchDB); err != nil || string(got) != string(mainBytes) {
		t.Fatalf("active main changed despite unsafe sidecar: bytes=%q err=%v", got, err)
	}
	if got, err := os.ReadFile(target); err != nil || string(got) != string(targetBytes) {
		t.Fatalf("external target changed: bytes=%q err=%v", got, err)
	}
}
