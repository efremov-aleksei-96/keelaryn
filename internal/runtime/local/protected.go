package local

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/contextbundle"
	"github.com/efremov-aleksei-96/keelaryn/internal/controlstorage"
	"github.com/efremov-aleksei-96/keelaryn/internal/search"
)

type ProtectedIndexOptions struct {
	Root       string
	ControlDir string
	ObservedAt time.Time
	MaxBytes   int64
}

type ProtectedContextOptions struct {
	Root       string
	ControlDir string
	Query      string
	Reason     string
	Limit      int
	MaxBytes   int64
}

// BootstrapProtectedIndex is the executable control-storage boundary. It
// resolves the physical control parent and proves the control directory is
// outside the corpus before any directory or SQLite file can be created.
func BootstrapProtectedIndex(ctx context.Context, options ProtectedIndexOptions) (IndexResult, error) {
	if options.ObservedAt.IsZero() || options.MaxBytes < 0 {
		return IndexResult{}, ErrInvalidOptions
	}
	root, layout, err := resolveProtectedLayout(options.Root, options.ControlDir)
	if err != nil {
		return IndexResult{}, err
	}
	layout, err = controlstorage.Prepare(layout.Dir)
	if err != nil {
		return IndexResult{}, err
	}

	result, operationErr := BootstrapIndex(ctx, IndexOptions{
		Root: root, StateDB: layout.StateDB, SearchDB: layout.SearchDB,
		ObservedAt: options.ObservedAt, MaxBytes: options.MaxBytes,
	})
	verifyErr := controlstorage.Verify(layout.Dir)
	if operationErr != nil {
		if verifyErr != nil {
			return IndexResult{}, errors.Join(operationErr, verifyErr)
		}
		return IndexResult{}, operationErr
	}
	if verifyErr != nil {
		return IndexResult{}, verifyErr
	}
	return result, nil
}

func QueryProtected(ctx context.Context, controlDir, query string, limit int) ([]search.Hit, error) {
	if strings.TrimSpace(controlDir) == "" {
		return nil, ErrInvalidOptions
	}
	layout, err := controlstorage.OpenExisting(controlDir)
	if err != nil {
		return nil, err
	}
	hits, operationErr := Query(ctx, layout.SearchDB, query, limit)
	verifyErr := controlstorage.Verify(layout.Dir)
	if operationErr != nil {
		if verifyErr != nil {
			return nil, errors.Join(operationErr, verifyErr)
		}
		return nil, operationErr
	}
	if verifyErr != nil {
		return nil, verifyErr
	}
	return hits, nil
}

func QueryProtectedReadOnly(ctx context.Context, controlDir, query string, limit int) ([]search.Hit, error) {
	if strings.TrimSpace(controlDir) == "" {
		return nil, ErrInvalidOptions
	}
	layout, err := controlstorage.OpenExisting(controlDir)
	if err != nil {
		return nil, err
	}
	hits, operationErr := QueryReadOnly(ctx, layout.SearchDB, query, limit)
	verifyErr := controlstorage.Verify(layout.Dir)
	if operationErr != nil {
		if verifyErr != nil {
			return nil, errors.Join(operationErr, verifyErr)
		}
		return nil, operationErr
	}
	if verifyErr != nil {
		return nil, verifyErr
	}
	return hits, nil
}

func BuildProtectedContext(ctx context.Context, options ProtectedContextOptions) (contextbundle.Bundle, error) {
	if strings.TrimSpace(options.Query) == "" ||
		strings.TrimSpace(options.Reason) == "" ||
		options.Limit < 1 ||
		options.MaxBytes < 0 {
		return contextbundle.Bundle{}, ErrInvalidOptions
	}
	root, layout, err := resolveProtectedLayout(options.Root, options.ControlDir)
	if err != nil {
		return contextbundle.Bundle{}, err
	}
	layout, err = controlstorage.OpenExisting(layout.Dir)
	if err != nil {
		return contextbundle.Bundle{}, err
	}

	bundle, operationErr := BuildContext(ctx, ContextOptions{
		Root: root, StateDB: layout.StateDB, SearchDB: layout.SearchDB,
		Query: options.Query, Reason: options.Reason, Limit: options.Limit, MaxBytes: options.MaxBytes,
	})
	verifyErr := controlstorage.Verify(layout.Dir)
	if operationErr != nil {
		if verifyErr != nil {
			return contextbundle.Bundle{}, errors.Join(operationErr, verifyErr)
		}
		return contextbundle.Bundle{}, operationErr
	}
	if verifyErr != nil {
		return contextbundle.Bundle{}, verifyErr
	}
	return bundle, nil
}

func BuildProtectedContextReadOnly(ctx context.Context, options ProtectedContextOptions) (contextbundle.Bundle, error) {
	if strings.TrimSpace(options.Query) == "" ||
		strings.TrimSpace(options.Reason) == "" ||
		options.Limit < 1 ||
		options.MaxBytes < 0 {
		return contextbundle.Bundle{}, ErrInvalidOptions
	}
	root, layout, err := resolveProtectedLayout(options.Root, options.ControlDir)
	if err != nil {
		return contextbundle.Bundle{}, err
	}
	layout, err = controlstorage.OpenExisting(layout.Dir)
	if err != nil {
		return contextbundle.Bundle{}, err
	}

	bundle, operationErr := BuildContextReadOnly(ctx, ContextOptions{
		Root: root, StateDB: layout.StateDB, SearchDB: layout.SearchDB,
		Query: options.Query, Reason: options.Reason, Limit: options.Limit, MaxBytes: options.MaxBytes,
	})
	verifyErr := controlstorage.Verify(layout.Dir)
	if operationErr != nil {
		if verifyErr != nil {
			return contextbundle.Bundle{}, errors.Join(operationErr, verifyErr)
		}
		return contextbundle.Bundle{}, operationErr
	}
	if verifyErr != nil {
		return contextbundle.Bundle{}, verifyErr
	}
	return bundle, nil
}

func resolveProtectedLayout(root, controlDir string) (string, controlstorage.Layout, error) {
	if strings.TrimSpace(root) == "" || strings.TrimSpace(controlDir) == "" {
		return "", controlstorage.Layout{}, ErrInvalidOptions
	}
	rootAbs, err := filepath.Abs(root)
	if err != nil {
		return "", controlstorage.Layout{}, fmt.Errorf("resolve corpus root: %w", err)
	}
	rootAbs = filepath.Clean(rootAbs)
	info, err := os.Stat(rootAbs)
	if err != nil {
		return "", controlstorage.Layout{}, fmt.Errorf("inspect corpus root: %w", err)
	}
	if !info.IsDir() {
		return "", controlstorage.Layout{}, ErrInvalidOptions
	}
	rootPhysical, err := filepath.EvalSymlinks(rootAbs)
	if err != nil {
		return "", controlstorage.Layout{}, fmt.Errorf("resolve physical corpus root: %w", err)
	}
	rootPhysical = filepath.Clean(rootPhysical)

	layout, err := controlstorage.Resolve(controlDir)
	if err != nil {
		return "", controlstorage.Layout{}, err
	}
	if insidePath(rootAbs, layout.Dir) || insidePath(rootPhysical, layout.Dir) {
		return "", controlstorage.Layout{}, ErrRuntimeStateInCorpus
	}
	return rootAbs, layout, nil
}
