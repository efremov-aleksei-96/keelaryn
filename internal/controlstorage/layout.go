package controlstorage

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

var (
	ErrInvalidControlDir  = errors.New("invalid control directory")
	ErrControlDirNotFound = errors.New("control directory does not exist")
	ErrControlDirInsecure = errors.New("control directory is not securely protected")
	ErrControlFileUnsafe  = errors.New("control database path is unsafe")
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

// Resolve computes the physical control-state paths without creating or
// modifying anything on disk. The existing parent is symlink-resolved so a
// lexical path cannot later hide a write through an ancestor alias.
func Resolve(dir string) (Layout, error) {
	if strings.TrimSpace(dir) == "" {
		return Layout{}, ErrInvalidControlDir
	}
	abs, err := filepath.Abs(dir)
	if err != nil {
		return Layout{}, fmt.Errorf("resolve control directory: %w", err)
	}
	abs = filepath.Clean(abs)
	if filepath.Dir(abs) == abs {
		return Layout{}, ErrInvalidControlDir
	}

	if info, statErr := os.Lstat(abs); statErr == nil {
		if info.Mode()&os.ModeSymlink != 0 {
			return Layout{}, ErrInvalidControlDir
		}
	} else if !errors.Is(statErr, os.ErrNotExist) {
		return Layout{}, fmt.Errorf("inspect control directory: %w", statErr)
	}

	parent := filepath.Dir(abs)
	resolvedParent, err := filepath.EvalSymlinks(parent)
	if err != nil {
		return Layout{}, fmt.Errorf("resolve control directory parent: %w", err)
	}
	parentInfo, err := os.Stat(resolvedParent)
	if err != nil {
		return Layout{}, fmt.Errorf("inspect control directory parent: %w", err)
	}
	if !parentInfo.IsDir() {
		return Layout{}, ErrInvalidControlDir
	}

	physical := filepath.Join(resolvedParent, filepath.Base(abs))
	return Layout{
		Dir:      physical,
		StateDB:  filepath.Join(physical, StateDatabaseName),
		SearchDB: filepath.Join(physical, SearchDatabaseName),
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
		if err := verifyExisting(layout); err != nil {
			_ = os.Remove(layout.Dir)
			return Layout{}, err
		}
		return layout, nil
	}

	if err := validateDirectoryInfo(info); err != nil {
		return Layout{}, err
	}
	if err := verifyLayout(layout); err != nil {
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
	if err := verifyLayout(layout); err != nil {
		return Layout{}, err
	}
	return layout, nil
}

// Verify checks an existing control directory without mutation.
func Verify(dir string) error {
	_, err := OpenExisting(dir)
	return err
}

func verifyExisting(layout Layout) error {
	info, err := os.Lstat(layout.Dir)
	if err != nil {
		return fmt.Errorf("inspect created control directory: %w", err)
	}
	if err := validateDirectoryInfo(info); err != nil {
		return err
	}
	return verifyLayout(layout)
}

func verifyLayout(layout Layout) error {
	if err := verifyProtectedDir(layout.Dir); err != nil {
		return err
	}
	for _, path := range []string{layout.StateDB, layout.SearchDB} {
		info, err := os.Lstat(path)
		if errors.Is(err, os.ErrNotExist) {
			continue
		}
		if err != nil {
			return fmt.Errorf("inspect control database path: %w", err)
		}
		if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
			return fmt.Errorf("%w: %s", ErrControlFileUnsafe, path)
		}
		if err := verifyControlFile(path); err != nil {
			return fmt.Errorf("%w: %s: %v", ErrControlFileUnsafe, path, err)
		}
	}
	return nil
}

func validateDirectoryInfo(info os.FileInfo) error {
	if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return ErrInvalidControlDir
	}
	return nil
}
