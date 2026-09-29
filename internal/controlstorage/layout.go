package controlstorage

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

var (
	ErrInvalidControlDir   = errors.New("invalid control directory")
	ErrControlDirNotFound  = errors.New("control directory does not exist")
	ErrControlDirInsecure  = errors.New("control directory is not securely protected")
)

const (
	StateDatabaseName  = "state.db"
	SearchDatabaseName = "search.db"
)

// Layout is the runtime-local control-state layout. The directory is the
// security boundary so SQLite journal/WAL/SHM side files remain inside the
// same protected namespace as the main databases.
type Layout struct {
	Dir      string
	StateDB  string
	SearchDB string
}

// Resolve computes the control-state paths without creating or modifying
// anything on disk.
func Resolve(dir string) (Layout, error) {
	if strings.TrimSpace(dir) == "" {
		return Layout{}, ErrInvalidControlDir
	}
	abs, err := filepath.Abs(dir)
	if err != nil {
		return Layout{}, fmt.Errorf("resolve control directory: %w", err)
	}
	abs = filepath.Clean(abs)
	return Layout{
		Dir:      abs,
		StateDB:  filepath.Join(abs, StateDatabaseName),
		SearchDB: filepath.Join(abs, SearchDatabaseName),
	}, nil
}

// Prepare creates a new protected control directory or verifies an existing
// one. Existing directories are never silently chmod/ACL-rewritten: an
// insecure existing path fails closed so Keelaryn cannot accidentally change
// permissions on an arbitrary user directory.
func Prepare(dir string) (Layout, error) {
	layout, err := Resolve(dir)
	if err != nil {
		return Layout{}, err
	}

	info, err := os.Lstat(layout.Dir)
	if err != nil {
		if !errors.Is(err, os.ErrNotExist) {
			return Layout{}, fmt.Errorf("inspect control directory: %w", err)
		}
		if err := createProtectedDir(layout.Dir); err != nil {
			return Layout{}, fmt.Errorf("create protected control directory: %w", err)
		}
		if err := verifyExisting(layout.Dir); err != nil {
			_ = os.Remove(layout.Dir)
			return Layout{}, err
		}
		return layout, nil
	}

	if err := validateDirectoryInfo(info); err != nil {
		return Layout{}, err
	}
	if err := verifyProtectedDir(layout.Dir); err != nil {
		return Layout{}, err
	}
	return layout, nil
}

// OpenExisting resolves and verifies a control directory without creating or
// mutating it.
func OpenExisting(dir string) (Layout, error) {
	layout, err := Resolve(dir)
	if err != nil {
		return Layout{}, err
	}
	info, err := os.Lstat(layout.Dir)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return Layout{}, ErrControlDirNotFound
		}
		return Layout{}, fmt.Errorf("inspect control directory: %w", err)
	}
	if err := validateDirectoryInfo(info); err != nil {
		return Layout{}, err
	}
	if err := verifyProtectedDir(layout.Dir); err != nil {
		return Layout{}, err
	}
	return layout, nil
}

// Verify checks an existing control directory without mutation.
func Verify(dir string) error {
	_, err := OpenExisting(dir)
	return err
}

func verifyExisting(dir string) error {
	info, err := os.Lstat(dir)
	if err != nil {
		return fmt.Errorf("inspect created control directory: %w", err)
	}
	if err := validateDirectoryInfo(info); err != nil {
		return err
	}
	return verifyProtectedDir(dir)
}

func validateDirectoryInfo(info os.FileInfo) error {
	if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return ErrInvalidControlDir
	}
	return nil
}
