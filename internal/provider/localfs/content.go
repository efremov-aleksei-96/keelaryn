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

var ErrObservedObjectChanged = errors.New("observed provider object changed before content read")

// ContentEvidence hashes the bytes of a regular file already represented by
// this Snapshot. The method revalidates provider-object identity after opening
// the locator. If the path was replaced by another object after the snapshot,
// the digest is discarded and the call fails closed.
func (s *Snapshot) ContentEvidence(ctx context.Context, locatorPath string) (corpus.ContentEvidence, error) {
	expected, ok := s.identityInfo[locatorPath]
	if !ok {
		if !s.hasLocator(locatorPath) {
			return corpus.ContentEvidence{}, fmt.Errorf("%w: %s", ErrLocatorNotObserved, locatorPath)
		}
		return corpus.ContentEvidence{}, fmt.Errorf("%w: %s", ErrIdentityEvidenceAbsent, locatorPath)
	}

	locator, ok := s.locator(locatorPath)
	if !ok {
		return corpus.ContentEvidence{}, fmt.Errorf("%w: %s", ErrLocatorNotObserved, locatorPath)
	}

	fullPath := filepath.Join(locator.Root, filepath.FromSlash(locator.Path))
	file, err := os.Open(fullPath)
	if err != nil {
		return corpus.ContentEvidence{}, fmt.Errorf("open content %q: %w", fullPath, err)
	}
	defer file.Close()

	openedInfo, err := file.Stat()
	if err != nil {
		return corpus.ContentEvidence{}, fmt.Errorf("stat opened content %q: %w", fullPath, err)
	}
	if !openedInfo.Mode().IsRegular() || !os.SameFile(expected, openedInfo) {
		return corpus.ContentEvidence{}, fmt.Errorf("%w: %s", ErrObservedObjectChanged, locatorPath)
	}

	hash := sha256.New()
	buf := make([]byte, 128*1024)
	var size int64
	for {
		if err := ctx.Err(); err != nil {
			return corpus.ContentEvidence{}, err
		}
		n, readErr := file.Read(buf)
		if n > 0 {
			if _, err := hash.Write(buf[:n]); err != nil {
				return corpus.ContentEvidence{}, fmt.Errorf("hash content %q: %w", fullPath, err)
			}
			size += int64(n)
		}
		switch {
		case errors.Is(readErr, io.EOF):
			return corpus.ContentEvidence{
				Algorithm: corpus.ContentAlgorithmSHA256,
				Digest:    hex.EncodeToString(hash.Sum(nil)),
				Size:      size,
			}, nil
		case readErr != nil:
			return corpus.ContentEvidence{}, fmt.Errorf("read content %q: %w", fullPath, readErr)
		}
	}
}

func (s *Snapshot) locator(path string) (corpus.Locator, bool) {
	for i := range s.observations {
		if s.observations[i].Locator.Path == path {
			return s.observations[i].Locator, true
		}
	}
	return corpus.Locator{}, false
}
