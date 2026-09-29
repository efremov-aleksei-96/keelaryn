//go:build !windows && !aix && !android && !darwin && !dragonfly && !freebsd && !illumos && !linux && !netbsd && !openbsd && !solaris

package controlstorage

import "fmt"

func createProtectedDir(path string) error {
	return fmt.Errorf("%w: platform has no control-storage adapter", ErrInvalidControlDir)
}

func verifyProtectedDir(path string) error {
	return fmt.Errorf("%w: platform has no control-storage adapter", ErrInvalidControlDir)
}

func verifyControlFile(path string) error {
	return fmt.Errorf("%w: platform has no control-storage adapter", ErrInvalidControlDir)
}
