//go:build !windows && !aix && !android && !darwin && !dragonfly && !freebsd && !illumos && !linux && !netbsd && !openbsd && !solaris

package controlstorage

import (
	"fmt"
	"os"
)

func lockSearchMutationFile(file *os.File) error {
	return fmt.Errorf("%w: platform has no search-lock adapter", ErrInvalidControlDir)
}

func unlockSearchMutationFile(file *os.File) error {
	return nil
}
