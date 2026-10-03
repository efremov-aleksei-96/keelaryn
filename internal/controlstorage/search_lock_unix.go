//go:build aix || android || darwin || dragonfly || freebsd || illumos || linux || netbsd || openbsd || solaris

package controlstorage

import (
	"errors"
	"fmt"
	"os"

	"golang.org/x/sys/unix"
)

func lockSearchMutationFile(file *os.File) error {
	err := unix.Flock(int(file.Fd()), unix.LOCK_EX|unix.LOCK_NB)
	if err == nil {
		return nil
	}
	if errors.Is(err, unix.EWOULDBLOCK) || errors.Is(err, unix.EAGAIN) {
		return ErrSearchMutationLocked
	}
	return fmt.Errorf("lock search mutation file: %w", err)
}

func unlockSearchMutationFile(file *os.File) error {
	if err := unix.Flock(int(file.Fd()), unix.LOCK_UN); err != nil {
		return fmt.Errorf("unlock search mutation file: %w", err)
	}
	return nil
}
