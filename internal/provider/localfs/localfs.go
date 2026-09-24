package localfs

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
)

var ErrRootNotDirectory = errors.New("localfs corpus root is not a directory")

// Provider is the read-only local filesystem discovery adapter.
//
// P0-00 intentionally does not claim a cross-platform native file identity.
// Until that layer is implemented, ProviderObject identity remains UNRESOLVED
// rather than using the path as a fake identity.
type Provider struct {
	id corpus.ProviderID
}

func New(id corpus.ProviderID) *Provider {
	return &Provider{id: id}
}

func (p *Provider) Discover(ctx context.Context, root string) ([]corpus.Observation, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}

	absRoot, err := filepath.Abs(root)
	if err != nil {
		return nil, fmt.Errorf("resolve corpus root: %w", err)
	}
	absRoot = filepath.Clean(absRoot)

	rootInfo, err := os.Lstat(absRoot)
	if err != nil {
		return nil, fmt.Errorf("inspect corpus root: %w", err)
	}
	if !rootInfo.IsDir() {
		return nil, ErrRootNotDirectory
	}

	observations := make([]corpus.Observation, 0)
	err = filepath.WalkDir(absRoot, func(path string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if err := ctx.Err(); err != nil {
			return err
		}
		if path == absRoot || entry.IsDir() {
			return nil
		}

		info, err := os.Lstat(path)
		if err != nil {
			return fmt.Errorf("lstat %q: %w", path, err)
		}

		rel, err := filepath.Rel(absRoot, path)
		if err != nil {
			return fmt.Errorf("relative locator for %q: %w", path, err)
		}

		kind := classify(info.Mode())
		observations = append(observations, corpus.Observation{
			ProviderObject: corpus.ProviderObject{
				ProviderID:    p.id,
				IdentityState: corpus.ObjectIdentityUnresolved,
			},
			Locator: corpus.Locator{
				ProviderID: p.id,
				Root:       absRoot,
				Path:       filepath.ToSlash(rel),
			},
			Kind:       kind,
			Size:       info.Size(),
			Mode:       uint32(info.Mode()),
			ModifiedAt: info.ModTime().UTC(),
		})
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("discover local corpus: %w", err)
	}

	// filepath.WalkDir is lexical already; sort explicitly so the provider
	// contract remains deterministic even if traversal implementation changes.
	sort.Slice(observations, func(i, j int) bool {
		return observations[i].Locator.Path < observations[j].Locator.Path
	})

	return observations, nil
}

func classify(mode os.FileMode) corpus.EntryKind {
	switch {
	case mode.IsRegular():
		return corpus.EntryRegularFile
	case mode&os.ModeSymlink != 0:
		return corpus.EntrySymlink
	default:
		return corpus.EntryOther
	}
}
