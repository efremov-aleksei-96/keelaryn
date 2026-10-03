package controlstorage_test

import (
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/controlstorage"
)

func TestSearchMutationLockRejectsSymlinkBeforeOpen(t *testing.T) {
	layout, err := controlstorage.Prepare(filepath.Join(t.TempDir(), "control"))
	if err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(t.TempDir(), "outside-lock-target")
	targetBytes := []byte("outside-must-not-be-opened-as-control-lock")
	if err := os.WriteFile(target, targetBytes, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, layout.SearchLock); err != nil {
		t.Skipf("symlink unavailable: %v", err)
	}

	lock, err := controlstorage.AcquireSearchMutationLock(layout)
	if lock != nil {
		_ = lock.Close()
	}
	if !errors.Is(err, controlstorage.ErrControlFileUnsafe) {
		t.Fatalf("error=%v want ErrControlFileUnsafe", err)
	}
	got, err := os.ReadFile(target)
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != string(targetBytes) {
		t.Fatal("external lock target changed")
	}
}

func TestSearchMutationLockSerializesWriters(t *testing.T) {
	layout, err := controlstorage.Prepare(filepath.Join(t.TempDir(), "control"))
	if err != nil {
		t.Fatal(err)
	}

	first, err := controlstorage.AcquireSearchMutationLock(layout)
	if err != nil {
		t.Fatal(err)
	}
	defer first.Close()

	if err := controlstorage.Verify(layout.Dir); err != nil {
		t.Fatal(err)
	}

	second, err := controlstorage.AcquireSearchMutationLock(layout)
	if !errors.Is(err, controlstorage.ErrSearchMutationLocked) {
		if second != nil {
			_ = second.Close()
		}
		t.Fatalf("second lock error=%v want ErrSearchMutationLocked", err)
	}

	if err := first.Close(); err != nil {
		t.Fatal(err)
	}

	third, err := controlstorage.AcquireSearchMutationLock(layout)
	if err != nil {
		t.Fatalf("reacquire after release: %v", err)
	}
	if err := third.Close(); err != nil {
		t.Fatal(err)
	}
}
