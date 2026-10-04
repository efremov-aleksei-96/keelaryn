package controlstorage

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
)

var (
	ErrSearchStagingNotStandalone = errors.New("staged search database is not a standalone closed SQLite file")
	ErrSearchActiveNotStandalone  = errors.New("active search database has SQLite sidecars and cannot be discarded safely")
)

func DiscardActiveSearchFamily(layout Layout) error {
	if err := validateSearchFamilyPath(layout, layout.SearchDB, SearchDatabaseName); err != nil {
		return err
	}
	mainInfo, mainErr := os.Lstat(layout.SearchDB)
	if mainErr != nil && !errors.Is(mainErr, os.ErrNotExist) {
		return fmt.Errorf("inspect active search database: %w", mainErr)
	}
	if mainErr == nil {
		if mainInfo.Mode()&os.ModeSymlink != 0 || !mainInfo.Mode().IsRegular() {
			return fmt.Errorf("%w: %s", ErrControlFileUnsafe, layout.SearchDB)
		}
		if err := verifyControlFile(layout.SearchDB); err != nil {
			return fmt.Errorf("%w: %s: %v", ErrControlFileUnsafe, layout.SearchDB, err)
		}
		for _, suffix := range []string{"-journal", "-wal", "-shm"} {
			path := layout.SearchDB + suffix
			if _, err := os.Lstat(path); err == nil {
				return fmt.Errorf("%w: sidecar=%s", ErrSearchActiveNotStandalone, filepath.Base(path))
			} else if !errors.Is(err, os.ErrNotExist) {
				return fmt.Errorf("inspect active search sidecar: %w", err)
			}
		}
		return os.Remove(layout.SearchDB)
	}

	// With no active main file, exact orphan sidecars are derived leftovers and
	// cannot participate in SQLite recovery. They may be discarded.
	return discardSearchFamily(layout, layout.SearchDB, SearchDatabaseName)
}

// DiscardActiveSearchFamilyAfterReconcileAttempt discards the exact validated
// active derived SQLite family only after the protected runtime has attempted
// SQLite reconciliation under the search mutation lock. Sidecars are expected
// here; every existing exact family member is validated before the first
// removal so an unsafe alias/reparse point fails with zero deletion.
func PromoteStagedSearchAfterReconcile(layout Layout) error {
	return promoteStagedSearchAfterReconcile(layout, os.Rename)
}

func DiscardStagedSearchFamily(layout Layout) error {
	return discardSearchFamily(layout, layout.SearchStagingDB, SearchStagingDatabaseName)
}

func VerifyStandaloneSearchStaging(layout Layout) error {
	if err := validateSearchFamilyPath(layout, layout.SearchStagingDB, SearchStagingDatabaseName); err != nil {
		return err
	}
	info, err := os.Lstat(layout.SearchStagingDB)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return ErrSearchStagingNotStandalone
		}
		return fmt.Errorf("inspect staged search database: %w", err)
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return fmt.Errorf("%w: %s", ErrControlFileUnsafe, layout.SearchStagingDB)
	}
	if err := verifyControlFile(layout.SearchStagingDB); err != nil {
		return fmt.Errorf("%w: %s: %v", ErrControlFileUnsafe, layout.SearchStagingDB, err)
	}
	for _, suffix := range []string{"-journal", "-wal", "-shm"} {
		path := layout.SearchStagingDB + suffix
		if _, err := os.Lstat(path); err == nil {
			return fmt.Errorf("%w: sidecar=%s", ErrSearchStagingNotStandalone, filepath.Base(path))
		} else if !errors.Is(err, os.ErrNotExist) {
			return fmt.Errorf("inspect staged search sidecar: %w", err)
		}
	}
	return nil
}

func PromoteStagedSearch(layout Layout) error {
	return promoteStagedSearch(layout, os.Rename)
}

func promoteStagedSearch(layout Layout, rename func(string, string) error) error {
	if rename == nil {
		return ErrInvalidControlDir
	}
	if err := VerifyStandaloneSearchStaging(layout); err != nil {
		return err
	}
	if err := DiscardActiveSearchFamily(layout); err != nil {
		return err
	}
	if err := rename(layout.SearchStagingDB, layout.SearchDB); err != nil {
		return fmt.Errorf("promote staged search database: %w", err)
	}
	if err := verifyControlFile(layout.SearchDB); err != nil {
		return fmt.Errorf("%w: %s: %v", ErrControlFileUnsafe, layout.SearchDB, err)
	}
	return nil
}

func promoteStagedSearchAfterReconcile(layout Layout, rename func(string, string) error) error {
	if rename == nil {
		return ErrInvalidControlDir
	}
	if err := VerifyStandaloneSearchStaging(layout); err != nil {
		return err
	}
	// Reconciliation already ran under the search mutation lock. Active search
	// state is derived/disposable here whether SQLite removed all sidecars, left
	// an orphan sidecar, or could not open a corrupt family. Validate every exact
	// family member before the first removal, then complete the staged rename
	// without another cancellation-sensitive return point.
	if err := discardSearchFamily(layout, layout.SearchDB, SearchDatabaseName); err != nil {
		return err
	}
	if err := rename(layout.SearchStagingDB, layout.SearchDB); err != nil {
		return fmt.Errorf("promote staged search database after reconciliation: %w", err)
	}
	if err := verifyControlFile(layout.SearchDB); err != nil {
		return fmt.Errorf("%w: %s: %v", ErrControlFileUnsafe, layout.SearchDB, err)
	}
	return nil
}

func discardSearchFamily(layout Layout, mainPath, expectedBase string) error {
	if err := validateSearchFamilyPath(layout, mainPath, expectedBase); err != nil {
		return err
	}
	paths := []string{mainPath, mainPath + "-journal", mainPath + "-wal", mainPath + "-shm"}
	existing := make([]string, 0, len(paths))

	// Validate the complete exact family before deleting any member. An unsafe
	// later sidecar must not cause a partially-discarded family.
	for _, path := range paths {
		info, err := os.Lstat(path)
		if err != nil {
			if errors.Is(err, os.ErrNotExist) {
				continue
			}
			return fmt.Errorf("inspect derived search file %s: %w", filepath.Base(path), err)
		}
		if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
			return fmt.Errorf("%w: %s", ErrControlFileUnsafe, path)
		}
		if err := verifyControlFile(path); err != nil {
			return fmt.Errorf("%w: %s: %v", ErrControlFileUnsafe, path, err)
		}
		existing = append(existing, path)
	}
	for _, path := range existing {
		if err := os.Remove(path); err != nil {
			return fmt.Errorf("remove derived search file %s: %w", filepath.Base(path), err)
		}
	}
	return nil
}

func validateSearchFamilyPath(layout Layout, path, expectedBase string) error {
	if layout.Dir == "" || path == "" {
		return ErrInvalidControlDir
	}
	want := filepath.Join(filepath.Clean(layout.Dir), expectedBase)
	if filepath.Clean(path) != want {
		return ErrInvalidControlDir
	}
	return nil
}
