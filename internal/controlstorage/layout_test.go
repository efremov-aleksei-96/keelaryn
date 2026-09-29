package controlstorage_test

import (
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/controlstorage"
)

func TestPrepareCreatesAndReopensProtectedLayout(t *testing.T) {
	parent := t.TempDir()
	dir := filepath.Join(parent, "control")

	layout, err := controlstorage.Prepare(dir)
	if err != nil {
		t.Fatal(err)
	}
	if layout.Dir == "" ||
		layout.StateDB != filepath.Join(layout.Dir, controlstorage.StateDatabaseName) ||
		layout.SearchDB != filepath.Join(layout.Dir, controlstorage.SearchDatabaseName) {
		t.Fatalf("layout=%#v", layout)
	}
	if _, err := os.Stat(layout.Dir); err != nil {
		t.Fatal(err)
	}

	reopened, err := controlstorage.OpenExisting(dir)
	if err != nil {
		t.Fatal(err)
	}
	if reopened != layout {
		t.Fatalf("reopened=%#v layout=%#v", reopened, layout)
	}
	if err := controlstorage.Verify(dir); err != nil {
		t.Fatal(err)
	}
}

func TestOpenExistingMissingDoesNotCreate(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "missing")
	_, err := controlstorage.OpenExisting(dir)
	if !errors.Is(err, controlstorage.ErrControlDirNotFound) {
		t.Fatalf("error=%v want ErrControlDirNotFound", err)
	}
	if _, statErr := os.Stat(dir); !errors.Is(statErr, os.ErrNotExist) {
		t.Fatalf("missing control directory was created: %v", statErr)
	}
}

func TestPrepareRejectsNonDirectory(t *testing.T) {
	path := filepath.Join(t.TempDir(), "control")
	if err := os.WriteFile(path, []byte("not a directory"), 0o600); err != nil {
		t.Fatal(err)
	}
	_, err := controlstorage.Prepare(path)
	if !errors.Is(err, controlstorage.ErrInvalidControlDir) {
		t.Fatalf("error=%v want ErrInvalidControlDir", err)
	}
}

func TestPrepareDoesNotCreateMissingParents(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "missing-parent", "control")
	_, err := controlstorage.Prepare(dir)
	if err == nil {
		t.Fatal("Prepare unexpectedly created missing parent hierarchy")
	}
	if _, statErr := os.Stat(filepath.Dir(dir)); !errors.Is(statErr, os.ErrNotExist) {
		t.Fatalf("missing parent was created: %v", statErr)
	}
}
