package controlstorage_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/controlstorage"
)

func TestProtectedTempDirectoryAndFile(t *testing.T) {
	dir, err := controlstorage.CreateProtectedTempDir("keelaryn-control-test-")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(dir)

	path := filepath.Join(dir, "scratch.db")
	if err := os.WriteFile(path, []byte("protected"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := controlstorage.VerifyProtectedTempFile(path); err != nil {
		t.Fatal(err)
	}
}
