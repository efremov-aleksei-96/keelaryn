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

var (
	ErrRootNotDirectory      = errors.New("localfs corpus root is not a directory")
	ErrLocatorNotObserved    = errors.New("locator is not present in snapshot")
	ErrIdentityEvidenceAbsent = errors.New("provider object identity evidence is unavailable")
)

// Provider is the read-only local filesystem discovery adapter.
//
// P0-01 can compare regular-file identity in memory using Go's os.SameFile.
// It still does not serialize a native file ID or turn a path into identity.
type Provider struct {
	id corpus.ProviderID
}

func New(id corpus.ProviderID) *Provider {
	return &Provider{id: id}
}

func (p *Provider) Discover(ctx context.Context, root string) ([]corpus.Observation, error) {
	snapshot, err := p.Snapshot(ctx, root)
	if err != nil {
		return nil, err
	}
	return snapshot.Observations(), nil
}

// Snapshot contains read-only observations plus ephemeral, provider-specific
// identity evidence. The evidence is deliberately not serialized or promoted
// to a durable ProviderObjectID in this spike.
type Snapshot struct {
	observations []corpus.Observation
	identityInfo map[string]os.FileInfo
}

func (s *Snapshot) Observations() []corpus.Observation {
	out := make([]corpus.Observation, len(s.observations))
	copy(out, s.observations)
	return out
}


// ObjectGroup is one ephemeral provider-object equivalence class inside a
// Snapshot. Multiple Locators can describe the same physical provider object
// (for example, filesystem hard links). Groups intentionally have no durable
// ID yet.
type ObjectGroup struct {
	Locators []corpus.Locator `json:"locators"`
}

// ObjectGroups deterministically groups regular-file locators using the same
// already-qualified platform identity semantics as SameProviderObject.
// Entries without identity evidence (such as symlinks) are deliberately not
// assigned to a group.
func (s *Snapshot) ObjectGroups() []ObjectGroup {
	type workingGroup struct {
		representative os.FileInfo
		locators       []corpus.Locator
	}

	working := make([]workingGroup, 0)
	for _, observation := range s.observations {
		info, ok := s.identityInfo[observation.Locator.Path]
		if !ok {
			continue
		}

		match := -1
		for i := range working {
			if os.SameFile(working[i].representative, info) {
				match = i
				break
			}
		}

		if match < 0 {
			working = append(working, workingGroup{
				representative: info,
				locators:       []corpus.Locator{observation.Locator},
			})
			continue
		}
		working[match].locators = append(working[match].locators, observation.Locator)
	}

	out := make([]ObjectGroup, len(working))
	for i := range working {
		locators := make([]corpus.Locator, len(working[i].locators))
		copy(locators, working[i].locators)
		out[i] = ObjectGroup{Locators: locators}
	}
	return out
}

// SameProviderObject reports whether two regular-file locators are backed by
// the same physical filesystem object according to Go's platform-specific
// os.SameFile implementation.
//
// The comparison is pairwise evidence only. It does not allocate an Artifact
// ID, Revision ID, or durable ProviderObject ID.
func (s *Snapshot) SameProviderObject(path string, other *Snapshot, otherPath string) (bool, error) {
	left, ok := s.identityInfo[path]
	if !ok {
		if !s.hasLocator(path) {
			return false, fmt.Errorf("%w: %s", ErrLocatorNotObserved, path)
		}
		return false, fmt.Errorf("%w: %s", ErrIdentityEvidenceAbsent, path)
	}
	right, ok := other.identityInfo[otherPath]
	if !ok {
		if !other.hasLocator(otherPath) {
			return false, fmt.Errorf("%w: %s", ErrLocatorNotObserved, otherPath)
		}
		return false, fmt.Errorf("%w: %s", ErrIdentityEvidenceAbsent, otherPath)
	}
	return os.SameFile(left, right), nil
}

func (s *Snapshot) hasLocator(path string) bool {
	for i := range s.observations {
		if s.observations[i].Locator.Path == path {
			return true
		}
	}
	return false
}

func (p *Provider) Snapshot(ctx context.Context, root string) (*Snapshot, error) {
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

	snapshot := &Snapshot{
		observations: make([]corpus.Observation, 0),
		identityInfo: make(map[string]os.FileInfo),
	}

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
		locatorPath := filepath.ToSlash(rel)
		kind := classify(info.Mode())

		snapshot.observations = append(snapshot.observations, corpus.Observation{
			ProviderObject: corpus.ProviderObject{
				ProviderID:    p.id,
				IdentityState: corpus.ObjectIdentityUnresolved,
			},
			Locator: corpus.Locator{
				ProviderID: p.id,
				Root:       absRoot,
				Path:       locatorPath,
			},
			Kind:       kind,
			Size:       info.Size(),
			Mode:       uint32(info.Mode()),
			ModifiedAt: info.ModTime().UTC(),
		})

		if kind == corpus.EntryRegularFile {
			sameFileInfo, err := os.Stat(path)
			if err != nil {
				return fmt.Errorf("stat identity evidence %q: %w", path, err)
			}
			// On Windows os.SameFile may lazily load volume/file-index data
			// from the path. Comparing the FileInfo to itself while the path
			// is known materializes that evidence before a later rename.
			if !os.SameFile(sameFileInfo, sameFileInfo) {
				return fmt.Errorf("materialize identity evidence %q", path)
			}
			snapshot.identityInfo[locatorPath] = sameFileInfo
		}
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("discover local corpus: %w", err)
	}

	sort.Slice(snapshot.observations, func(i, j int) bool {
		return snapshot.observations[i].Locator.Path < snapshot.observations[j].Locator.Path
	})

	return snapshot, nil
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
