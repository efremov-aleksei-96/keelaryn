package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	localruntime "github.com/efremov-aleksei-96/keelaryn/internal/runtime/local"
	"github.com/efremov-aleksei-96/keelaryn/internal/search"
)

func TestScanOutputsObservationsWithoutInventingIdentity(t *testing.T) {
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte("hello"), 0o600); err != nil {
		t.Fatal(err)
	}

	var stdout, stderr bytes.Buffer
	if err := run([]string{"scan", "--root", root}, &stdout, &stderr); err != nil {
		t.Fatalf("run: %v; stderr=%s", err, stderr.String())
	}

	var observations []corpus.Observation
	if err := json.Unmarshal(stdout.Bytes(), &observations); err != nil {
		t.Fatalf("decode output: %v\n%s", err, stdout.String())
	}
	if len(observations) != 1 {
		t.Fatalf("observations=%d, want 1", len(observations))
	}
	if observations[0].Locator.Path != "note.txt" {
		t.Fatalf("path=%q", observations[0].Locator.Path)
	}
	if observations[0].ProviderObject.ID != "" {
		t.Fatalf("provider identity was invented: %#v", observations[0].ProviderObject)
	}
}

func TestBootstrapIndexAndSearchThroughExecutableSurface(t *testing.T) {
	root := t.TempDir()
	control := t.TempDir()
	content := []byte("Keelaryn runtime composition searchable")
	if err := os.WriteFile(filepath.Join(root, "note.md"), content, 0o600); err != nil {
		t.Fatal(err)
	}
	stateDB := filepath.Join(control, "state.db")
	searchDB := filepath.Join(control, "search.db")

	var stdout, stderr bytes.Buffer
	err := run([]string{
		"bootstrap-index",
		"--root", root,
		"--state-db", stateDB,
		"--search-db", searchDB,
		"--max-bytes", "4096",
	}, &stdout, &stderr)
	if err != nil {
		t.Fatalf("bootstrap-index: %v; stderr=%s", err, stderr.String())
	}
	var first localruntime.IndexResult
	if err := json.Unmarshal(stdout.Bytes(), &first); err != nil {
		t.Fatal(err)
	}
	if first.ReusedScan || first.Indexed != 1 {
		t.Fatalf("first=%#v", first)
	}

	stdout.Reset()
	stderr.Reset()
	if err := run([]string{
		"search",
		"--search-db", searchDB,
		"--query", "runtime searchable",
	}, &stdout, &stderr); err != nil {
		t.Fatalf("search: %v; stderr=%s", err, stderr.String())
	}
	var hits []search.Hit
	if err := json.Unmarshal(stdout.Bytes(), &hits); err != nil {
		t.Fatal(err)
	}
	if len(hits) != 1 || hits[0].ArtifactID == "" || hits[0].RevisionID == "" {
		t.Fatalf("hits=%#v", hits)
	}

	stdout.Reset()
	stderr.Reset()
	if err := run([]string{
		"bootstrap-index",
		"--root", root,
		"--state-db", stateDB,
		"--search-db", searchDB,
		"--max-bytes", "4096",
	}, &stdout, &stderr); err != nil {
		t.Fatalf("replay bootstrap-index: %v; stderr=%s", err, stderr.String())
	}
	var replay localruntime.IndexResult
	if err := json.Unmarshal(stdout.Bytes(), &replay); err != nil {
		t.Fatal(err)
	}
	if !replay.ReusedScan || replay.ScanID != first.ScanID || replay.Indexed != 1 {
		t.Fatalf("replay=%#v first=%#v", replay, first)
	}

	entries, err := os.ReadDir(root)
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 1 || entries[0].Name() != "note.md" {
		t.Fatalf("corpus mutated by runtime composition: %#v", entries)
	}
}

func TestBootstrapIndexRejectsDatabaseInsideCorpus(t *testing.T) {
	root := t.TempDir()
	control := t.TempDir()
	stateDB := filepath.Join(root, "state.db")
	var stdout, stderr bytes.Buffer
	err := run([]string{
		"bootstrap-index",
		"--root", root,
		"--state-db", stateDB,
		"--search-db", filepath.Join(control, "search.db"),
	}, &stdout, &stderr)
	if !errors.Is(err, localruntime.ErrRuntimeStateInCorpus) {
		t.Fatalf("error=%v want ErrRuntimeStateInCorpus", err)
	}
	if _, statErr := os.Stat(stateDB); !errors.Is(statErr, os.ErrNotExist) {
		t.Fatalf("state database created inside corpus: %v", statErr)
	}
}
