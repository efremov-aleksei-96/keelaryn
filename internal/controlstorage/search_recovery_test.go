package controlstorage_test

import (
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/controlstorage"
)

func TestDiscardStagedSearchFamilyIsExact(t *testing.T) {
	layout, err := controlstorage.Prepare(filepath.Join(t.TempDir(), "control"))
	if err != nil {
		t.Fatal(err)
	}
	stateBytes := []byte("state-authority")
	activeBytes := []byte("active-cache")
	if err := os.WriteFile(layout.StateDB, stateBytes, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(layout.SearchDB, activeBytes, 0o600); err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{
		layout.SearchStagingDB,
		layout.SearchStagingDB + "-journal",
		layout.SearchStagingDB + "-wal",
		layout.SearchStagingDB + "-shm",
	} {
		if err := os.WriteFile(path, []byte(filepath.Base(path)), 0o600); err != nil {
			t.Fatal(err)
		}
	}

	if err := controlstorage.DiscardStagedSearchFamily(layout); err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{
		layout.SearchStagingDB,
		layout.SearchStagingDB + "-journal",
		layout.SearchStagingDB + "-wal",
		layout.SearchStagingDB + "-shm",
	} {
		if _, err := os.Lstat(path); !errors.Is(err, os.ErrNotExist) {
			t.Fatalf("%s still exists: %v", path, err)
		}
	}
	assertFileBytes(t, layout.StateDB, stateBytes)
	assertFileBytes(t, layout.SearchDB, activeBytes)
}

func TestDiscardStagedSearchFamilyRejectsSymlink(t *testing.T) {
	layout, err := controlstorage.Prepare(filepath.Join(t.TempDir(), "control"))
	if err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(t.TempDir(), "outside.db")
	if err := os.WriteFile(target, []byte("outside"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, layout.SearchStagingDB); err != nil {
		t.Skipf("symlink unavailable: %v", err)
	}

	err = controlstorage.DiscardStagedSearchFamily(layout)
	if !errors.Is(err, controlstorage.ErrControlFileUnsafe) {
		t.Fatalf("error=%v want ErrControlFileUnsafe", err)
	}
	assertFileBytes(t, target, []byte("outside"))
}

func TestVerifyStandaloneSearchStagingRejectsSidecar(t *testing.T) {
	layout, err := controlstorage.Prepare(filepath.Join(t.TempDir(), "control"))
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(layout.SearchStagingDB, []byte("staged"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(layout.SearchStagingDB+"-wal", []byte("wal"), 0o600); err != nil {
		t.Fatal(err)
	}

	err = controlstorage.VerifyStandaloneSearchStaging(layout)
	if !errors.Is(err, controlstorage.ErrSearchStagingNotStandalone) {
		t.Fatalf("error=%v want ErrSearchStagingNotStandalone", err)
	}
}

func TestPromoteStagedSearchReplacesOnlyDerivedActiveFamily(t *testing.T) {
	layout, err := controlstorage.Prepare(filepath.Join(t.TempDir(), "control"))
	if err != nil {
		t.Fatal(err)
	}
	stateBytes := []byte("state-authority")
	stagedBytes := []byte("new-cache")
	if err := os.WriteFile(layout.StateDB, stateBytes, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(layout.SearchDB, []byte("old-cache"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(layout.SearchStagingDB, stagedBytes, 0o600); err != nil {
		t.Fatal(err)
	}

	if err := controlstorage.PromoteStagedSearch(layout); err != nil {
		t.Fatal(err)
	}
	assertFileBytes(t, layout.StateDB, stateBytes)
	assertFileBytes(t, layout.SearchDB, stagedBytes)
	if _, err := os.Lstat(layout.SearchStagingDB); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("staging still exists: %v", err)
	}
}

func TestPromoteStagedSearchRefusesActiveSQLiteSidecarWithoutMutation(t *testing.T) {
	layout, err := controlstorage.Prepare(filepath.Join(t.TempDir(), "control"))
	if err != nil {
		t.Fatal(err)
	}
	activeBytes := []byte("active-cache")
	stagedBytes := []byte("staged-cache")
	if err := os.WriteFile(layout.SearchDB, activeBytes, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(layout.SearchDB+"-journal", []byte("hot-journal"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(layout.SearchStagingDB, stagedBytes, 0o600); err != nil {
		t.Fatal(err)
	}

	err = controlstorage.PromoteStagedSearch(layout)
	if !errors.Is(err, controlstorage.ErrSearchActiveNotStandalone) {
		t.Fatalf("error=%v want ErrSearchActiveNotStandalone", err)
	}
	assertFileBytes(t, layout.SearchDB, activeBytes)
	assertFileBytes(t, layout.SearchDB+"-journal", []byte("hot-journal"))
	assertFileBytes(t, layout.SearchStagingDB, stagedBytes)
}

func assertFileBytes(t *testing.T, path string, want []byte) {
	t.Helper()
	got, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != string(want) {
		t.Fatalf("%s=%q want=%q", path, got, want)
	}
}
