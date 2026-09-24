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
	"strings"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
)

var (
	ErrObservedObjectChanged = errors.New("observed provider object changed during content read")
	ErrContentNotRegular      = errors.New("content locator is not a regular file")
	ErrInvalidContentLocator  = errors.New("invalid content locator")
	ErrContentUnstable        = errors.New("content changed during read")
)

// ContentSample is one fresh read-only observation of the object currently
// present at a locator plus byte evidence read from the same open handle.
//
// It does not assert continuity with any previous Snapshot or Artifact.
type ContentSample struct {
	Observation corpus.Observation     `json:"observation"`
	Evidence    corpus.ContentEvidence `json:"evidence"`
}

// ReadContentEvidence samples the current regular file at locatorPath.
//
// The file handle itself is the identity anchor during the read. The locator is
// checked before open and again before close; while the handle remains open the
// underlying object cannot be deleted and have that same live object identity
// reused. This avoids the unsafe "old Snapshot FileInfo vs later path" pattern.
//
// The result is still a fresh observation only. Assigning it to an existing
// Artifact requires an independent continuity decision.
func (p *Provider) ReadContentEvidence(ctx context.Context, root, locatorPath string) (ContentSample, error) {
	if err := ctx.Err(); err != nil {
		return ContentSample{}, err
	}

	absRoot, err := filepath.Abs(root)
	if err != nil {
		return ContentSample{}, fmt.Errorf("resolve corpus root: %w", err)
	}
	absRoot = filepath.Clean(absRoot)

	rootInfo, err := os.Lstat(absRoot)
	if err != nil {
		return ContentSample{}, fmt.Errorf("inspect corpus root: %w", err)
	}
	if !rootInfo.IsDir() {
		return ContentSample{}, ErrRootNotDirectory
	}

	relNative := filepath.Clean(filepath.FromSlash(locatorPath))
	if relNative == "." || filepath.IsAbs(relNative) || relNative == ".." ||
		strings.HasPrefix(relNative, ".."+string(os.PathSeparator)) {
		return ContentSample{}, fmt.Errorf("%w: %s", ErrInvalidContentLocator, locatorPath)
	}

	fullPath := filepath.Join(absRoot, relNative)
	relCheck, err := filepath.Rel(absRoot, fullPath)
	if err != nil || relCheck == ".." || strings.HasPrefix(relCheck, ".."+string(os.PathSeparator)) {
		return ContentSample{}, fmt.Errorf("%w: %s", ErrInvalidContentLocator, locatorPath)
	}

	preInfo, err := os.Lstat(fullPath)
	if err != nil {
		return ContentSample{}, fmt.Errorf("lstat content %q: %w", fullPath, err)
	}
	if !preInfo.Mode().IsRegular() {
		return ContentSample{}, fmt.Errorf("%w: %s", ErrContentNotRegular, locatorPath)
	}

	file, err := os.Open(fullPath)
	if err != nil {
		return ContentSample{}, fmt.Errorf("open content %q: %w", fullPath, err)
	}
	defer file.Close()

	openedInfo, err := file.Stat()
	if err != nil {
		return ContentSample{}, fmt.Errorf("stat opened content %q: %w", fullPath, err)
	}
	if !openedInfo.Mode().IsRegular() || !os.SameFile(preInfo, openedInfo) {
		return ContentSample{}, fmt.Errorf("%w: %s", ErrObservedObjectChanged, locatorPath)
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
				return ContentSample{}, fmt.Errorf("hash content %q: %w", fullPath, err)
			}
			size += int64(n)
		}
		if errors.Is(readErr, io.EOF) {
			break
		}
		if readErr != nil {
			return ContentSample{}, fmt.Errorf("read content %q: %w", fullPath, readErr)
		}
	}

	afterInfo, err := file.Stat()
	if err != nil {
		return ContentSample{}, fmt.Errorf("restat opened content %q: %w", fullPath, err)
	}
	if afterInfo.Size() != openedInfo.Size() ||
		!afterInfo.ModTime().Equal(openedInfo.ModTime()) ||
		size != afterInfo.Size() {
		return ContentSample{}, fmt.Errorf("%w: %s", ErrContentUnstable, locatorPath)
	}

	postInfo, err := os.Lstat(fullPath)
	if err != nil {
		return ContentSample{}, fmt.Errorf("%w: %s", ErrObservedObjectChanged, locatorPath)
	}
	if !postInfo.Mode().IsRegular() || !os.SameFile(openedInfo, postInfo) {
		return ContentSample{}, fmt.Errorf("%w: %s", ErrObservedObjectChanged, locatorPath)
	}

	normalizedPath := filepath.ToSlash(relCheck)
	return ContentSample{
		Observation: corpus.Observation{
			ProviderObject: corpus.ProviderObject{
				ProviderID:    p.id,
				IdentityState: corpus.ObjectIdentityUnresolved,
			},
			Locator: corpus.Locator{
				ProviderID: p.id,
				Root:       absRoot,
				Path:       normalizedPath,
			},
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
