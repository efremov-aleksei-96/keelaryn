package main

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
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
