//go:build aix || android || darwin || dragonfly || freebsd || illumos || linux || netbsd || openbsd || solaris

package controlstorage_test

import (
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/controlstorage"
)

func TestUnixVerifyRejectsRelaxedModeWithoutRepairingIt(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "control")
	if _, err := controlstorage.Prepare(dir); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(dir, 0o755); err != nil {
		t.Fatal(err)
	}

	_, err := controlstorage.OpenExisting(dir)
	if !errors.Is(err, controlstorage.ErrControlDirInsecure) {
		t.Fatalf("error=%v want ErrControlDirInsecure", err)
	}
	info, statErr := os.Stat(dir)
	if statErr != nil {
		t.Fatal(statErr)
	}
	if info.Mode().Perm() != 0o755 {
		t.Fatalf("existing insecure directory was silently repaired: mode=%#o", info.Mode().Perm())
	}
}
