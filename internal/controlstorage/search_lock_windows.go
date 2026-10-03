//go:build windows

package controlstorage

import (
	"errors"
	"fmt"
	"os"

	"golang.org/x/sys/windows"
)

func lockSearchMutationFile(file *os.File) error {
	var overlapped windows.Overlapped
	err := windows.LockFileEx(
		windows.Handle(file.Fd()),
		windows.LOCKFILE_EXCLUSIVE_LOCK|windows.LOCKFILE_FAIL_IMMEDIATELY,
		0,
		1,
		0,
		&overlapped,
	)
	if err == nil {
		return nil
	}
	if errors.Is(err, windows.ERROR_LOCK_VIOLATION) {
		return ErrSearchMutationLocked
	}
	return fmt.Errorf("lock search mutation file: %w", err)
}

func unlockSearchMutationFile(file *os.File) error {
	var overlapped windows.Overlapped
	if err := windows.UnlockFileEx(windows.Handle(file.Fd()), 0, 1, 0, &overlapped); err != nil {
		return fmt.Errorf("unlock search mutation file: %w", err)
	}
	return nil
}
