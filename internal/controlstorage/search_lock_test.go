package controlstorage_test

import (
	"errors"
	"path/filepath"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/controlstorage"
)

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
