//go:build aix || android || darwin || dragonfly || freebsd || illumos || linux || netbsd || openbsd || solaris

package controlstorage

import (
	"fmt"
	"os"

	"golang.org/x/sys/unix"
)

const privateDirectoryMode = 0o700

func createProtectedDir(path string) error {
	if err := os.Mkdir(path, privateDirectoryMode); err != nil {
		return err
	}
	// A restrictive umask can remove owner bits. Normalize only the directory
	// Keelaryn just created; existing directories are never rewritten.
	if err := os.Chmod(path, privateDirectoryMode); err != nil {
		_ = os.Remove(path)
		return err
	}
	return nil
}

func verifyProtectedDir(path string) error {
	info, err := os.Lstat(path)
	if err != nil {
		return fmt.Errorf("inspect protected control directory: %w", err)
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return ErrInvalidControlDir
	}
	if info.Mode().Perm() != privateDirectoryMode {
		return fmt.Errorf("%w: mode=%#o want=%#o", ErrControlDirInsecure, info.Mode().Perm(), privateDirectoryMode)
	}

	var stat unix.Stat_t
	if err := unix.Lstat(path, &stat); err != nil {
		return fmt.Errorf("read control directory owner: %w", err)
	}
	if int(stat.Uid) != unix.Geteuid() {
		return fmt.Errorf("%w: owner uid=%d current euid=%d", ErrControlDirInsecure, stat.Uid, unix.Geteuid())
	}
	return nil
}
