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
