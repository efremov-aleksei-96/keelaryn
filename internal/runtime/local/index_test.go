package local_test

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"

	localruntime "github.com/efremov-aleksei-96/keelaryn/internal/runtime/local"
)

func TestBootstrapIndexRecoversCommittedEmptyCorpus(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	control := t.TempDir()
	options := localruntime.IndexOptions{
		Root: root,
		StateDB: filepath.Join(control, "state.db"),
		SearchDB: filepath.Join(control, "search.db"),
		ObservedAt: time.Date(2026, 9, 29, 19, 20, 0, 0, time.UTC),
		MaxBytes: 1024,
	}

	first, err := localruntime.BootstrapIndex(ctx, options)
	if err != nil {
		t.Fatal(err)
	}
	if first.ReusedScan || first.Indexed != 0 {
		t.Fatalf("first=%#v", first)
	}

	options.ObservedAt = options.ObservedAt.Add(time.Hour)
	second, err := localruntime.BootstrapIndex(ctx, options)
	if err != nil {
		t.Fatal(err)
	}
	if !second.ReusedScan || second.ScanID != first.ScanID {
		t.Fatalf("second=%#v first=%#v", second, first)
	}
}

func TestBootstrapIndexRejectsRuntimeDatabaseInsideCorpusBeforeMutation(t *testing.T) {
	root := t.TempDir()
	control := t.TempDir()
	statePath := filepath.Join(root, "state.db")
	_, err := localruntime.BootstrapIndex(context.Background(), localruntime.IndexOptions{
		Root: root,
		StateDB: statePath,
		SearchDB: filepath.Join(control, "search.db"),
		ObservedAt: time.Date(2026, 9, 29, 19, 20, 0, 0, time.UTC),
		MaxBytes: 1024,
	})
	if !errors.Is(err, localruntime.ErrRuntimeStateInCorpus) {
		t.Fatalf("error=%v want ErrRuntimeStateInCorpus", err)
	}
	if _, statErr := os.Stat(statePath); !errors.Is(statErr, os.ErrNotExist) {
		t.Fatalf("state database was created inside corpus: %v", statErr)
	}
}
