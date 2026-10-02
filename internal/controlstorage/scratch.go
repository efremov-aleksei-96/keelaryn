package controlstorage

import (
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// CreateProtectedTempDir creates a unique temporary directory using the same
// platform-specific protection primitive as durable control storage. The
// directory is protected at creation time, not hardened after sensitive bytes
// may already have been written.
func CreateProtectedTempDir(prefix string) (string, error) {
	if prefix == "" || strings.ContainsAny(prefix, `/\`) {
		return "", ErrInvalidControlDir
	}
	parent := os.TempDir()
	for attempt := 0; attempt < 100; attempt++ {
		var random [16]byte
		if _, err := rand.Read(random[:]); err != nil {
			return "", fmt.Errorf("generate protected temporary directory name: %w", err)
		}
		path := filepath.Join(parent, prefix+hex.EncodeToString(random[:]))
		if err := createProtectedDir(path); err != nil {
			if errors.Is(err, os.ErrExist) {
				continue
			}
			return "", fmt.Errorf("create protected temporary directory: %w", err)
		}
		if err := verifyProtectedDir(path); err != nil {
			_ = os.Remove(path)
			return "", fmt.Errorf("verify protected temporary directory: %w", err)
		}
		return path, nil
	}
	return "", fmt.Errorf("create protected temporary directory: exhausted collision retries")
}

// VerifyProtectedTempFile verifies that a scratch file created inside a
// protected temporary directory has the same owner/ACL/link safety expected
// from control database files.
func VerifyProtectedTempFile(path string) error {
	info, err := os.Lstat(path)
	if err != nil {
		return fmt.Errorf("inspect protected temporary file: %w", err)
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return fmt.Errorf("%w: %s", ErrControlFileUnsafe, path)
	}
	if err := verifyControlFile(path); err != nil {
		return fmt.Errorf("%w: %s: %v", ErrControlFileUnsafe, path, err)
	}
	return nil
}
