package localfs

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
)

var ErrObservedGroupChanged = errors.New("observed provider-object group changed during content sampling")

// SampleObjectGroupContent samples one regular-file ObjectGroup while an open
// representative handle anchors the physical object identity.
//
// Every locator in the group is revalidated before and after hashing while the
// representative handle remains open. This prevents a deleted object's native
// ID from being reused underneath a cross-time SameFile comparison.
func (s *Snapshot) SampleObjectGroupContent(ctx context.Context, group ObjectGroup) (ContentSample, error) {
	if err := ctx.Err(); err != nil {
		return ContentSample{}, err
	}
	if len(group.Locators) == 0 {
		return ContentSample{}, fmt.Errorf("%w: empty group", ErrObservedGroupChanged)
	}
	for _, locator := range group.Locators {
		if locator.ProviderID != s.providerID || locator.Root != s.root || locator.Path == "" {
			return ContentSample{}, fmt.Errorf("%w: locator scope mismatch %#v", ErrObservedGroupChanged, locator)
		}
	}

	representative := group.Locators[0]
	fullPath := filepath.Join(s.root, filepath.FromSlash(representative.Path))
	preInfo, err := os.Lstat(fullPath)
	if err != nil {
		return ContentSample{}, fmt.Errorf("%w: representative lstat: %v", ErrObservedGroupChanged, err)
	}
	if !preInfo.Mode().IsRegular() {
		return ContentSample{}, fmt.Errorf("%w: representative is not regular", ErrObservedGroupChanged)
	}

	file, err := os.Open(fullPath)
	if err != nil {
		return ContentSample{}, fmt.Errorf("open group representative %q: %w", fullPath, err)
	}
	defer file.Close()

	openedInfo, err := file.Stat()
	if err != nil {
		return ContentSample{}, fmt.Errorf("stat group representative %q: %w", fullPath, err)
	}
	if !openedInfo.Mode().IsRegular() || !os.SameFile(preInfo, openedInfo) {
		return ContentSample{}, fmt.Errorf("%w: representative changed before open", ErrObservedGroupChanged)
	}
	if err := s.validateGroupLocators(group, openedInfo); err != nil {
		return ContentSample{}, err
	}

	hash := sha256.New()
	buf := make([]byte, 128*1024)
	var size int64
	for {
		if err := ctx.Err(); err != nil {
			return ContentSample{}, err
		}
		n, readErr := file.Read(buf)
		if n > 0 {
			if _, err := hash.Write(buf[:n]); err != nil {
				return ContentSample{}, fmt.Errorf("hash group representative %q: %w", fullPath, err)
			}
			size += int64(n)
		}
		if errors.Is(readErr, io.EOF) {
			break
		}
		if readErr != nil {
			return ContentSample{}, fmt.Errorf("read group representative %q: %w", fullPath, readErr)
		}
	}

	afterInfo, err := file.Stat()
	if err != nil {
		return ContentSample{}, fmt.Errorf("restat group representative %q: %w", fullPath, err)
	}
	if afterInfo.Size() != openedInfo.Size() ||
		!afterInfo.ModTime().Equal(openedInfo.ModTime()) ||
		size != afterInfo.Size() {
		return ContentSample{}, fmt.Errorf("%w: representative content unstable", ErrObservedGroupChanged)
	}
	if err := s.validateGroupLocators(group, openedInfo); err != nil {
		return ContentSample{}, err
	}

	return ContentSample{
		Observation: corpus.Observation{
			ProviderObject: corpus.ProviderObject{
				ProviderID:    s.providerID,
				IdentityState: corpus.ObjectIdentityUnresolved,
			},
			Locator: representative,
			Kind:       corpus.EntryRegularFile,
			Size:       afterInfo.Size(),
			Mode:       uint32(afterInfo.Mode()),
			ModifiedAt: afterInfo.ModTime().UTC(),
		},
		Evidence: corpus.ContentEvidence{
			Algorithm: corpus.ContentAlgorithmSHA256,
			Digest:    hex.EncodeToString(hash.Sum(nil)),
			Size:      size,
		},
	}, nil
}

func (s *Snapshot) validateGroupLocators(group ObjectGroup, anchor os.FileInfo) error {
	for _, locator := range group.Locators {
		fullPath := filepath.Join(s.root, filepath.FromSlash(locator.Path))
		lstat, err := os.Lstat(fullPath)
		if err != nil {
			return fmt.Errorf("%w: locator %q unavailable: %v", ErrObservedGroupChanged, locator.Path, err)
		}
		if !lstat.Mode().IsRegular() {
			return fmt.Errorf("%w: locator %q is not regular", ErrObservedGroupChanged, locator.Path)
		}
		info, err := os.Stat(fullPath)
		if err != nil {
			return fmt.Errorf("%w: stat locator %q: %v", ErrObservedGroupChanged, locator.Path, err)
		}
		if !os.SameFile(anchor, info) {
			return fmt.Errorf("%w: locator %q no longer names the sampled object", ErrObservedGroupChanged, locator.Path)
		}
	}
	return nil
}
