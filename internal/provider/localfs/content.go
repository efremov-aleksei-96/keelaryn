package localfs

import (
	"bytes"
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
	ErrContentLimitExceeded   = errors.New("content read limit exceeded")
	ErrInvalidContentLimit    = errors.New("invalid content read limit")
)

// ContentSample is one fresh read-only observation of the object currently
// present at a locator plus byte evidence read from the same open handle.
//
// It does not assert continuity with any previous Snapshot or Artifact.
type ContentSample struct {
	Observation corpus.Observation     `json:"observation"`
	Evidence    corpus.ContentEvidence `json:"evidence"`
}

// BoundedFileSample additionally retains the bytes read from the same handle.
// It is intended for derived on-demand extraction, not durable storage.
type BoundedFileSample struct {
	ContentSample
	Bytes []byte `json:"-"`
}

// ReadContentEvidence samples the current regular file at locatorPath without
// retaining file bytes.
func (p *Provider) ReadContentEvidence(ctx context.Context, root, locatorPath string) (ContentSample, error) {
	sample, err := p.readRegularFile(ctx, root, locatorPath, -1, false)
	if err != nil {
		return ContentSample{}, err
	}
	return sample.ContentSample, nil
}

// ReadBoundedRegularFile samples one current regular file and retains at most
// maxBytes bytes. The content evidence and bytes come from the same open file
// handle and share the same race/replacement validation.
func (p *Provider) ReadBoundedRegularFile(ctx context.Context, root, locatorPath string, maxBytes int64) (BoundedFileSample, error) {
	if maxBytes < 0 {
		return BoundedFileSample{}, ErrInvalidContentLimit
	}
	return p.readRegularFile(ctx, root, locatorPath, maxBytes, true)
}

func (p *Provider) readRegularFile(ctx context.Context, root, locatorPath string, maxBytes int64, retainBytes bool) (BoundedFileSample, error) {
	if err := ctx.Err(); err != nil {
		return BoundedFileSample{}, err
	}

	absRoot, err := filepath.Abs(root)
	if err != nil {
		return BoundedFileSample{}, fmt.Errorf("resolve corpus root: %w", err)
	}
	absRoot = filepath.Clean(absRoot)

	rootInfo, err := os.Lstat(absRoot)
	if err != nil {
		return BoundedFileSample{}, fmt.Errorf("inspect corpus root: %w", err)
	}
	if !rootInfo.IsDir() {
		return BoundedFileSample{}, ErrRootNotDirectory
	}

	relNative := filepath.Clean(filepath.FromSlash(locatorPath))
	if relNative == "." || filepath.IsAbs(relNative) || relNative == ".." ||
		strings.HasPrefix(relNative, ".."+string(os.PathSeparator)) {
		return BoundedFileSample{}, fmt.Errorf("%w: %s", ErrInvalidContentLocator, locatorPath)
	}

	fullPath := filepath.Join(absRoot, relNative)
	relCheck, err := filepath.Rel(absRoot, fullPath)
	if err != nil || relCheck == ".." || strings.HasPrefix(relCheck, ".."+string(os.PathSeparator)) {
		return BoundedFileSample{}, fmt.Errorf("%w: %s", ErrInvalidContentLocator, locatorPath)
	}

	preInfo, err := os.Lstat(fullPath)
	if err != nil {
		return BoundedFileSample{}, fmt.Errorf("lstat content %q: %w", fullPath, err)
	}
	if !preInfo.Mode().IsRegular() {
		return BoundedFileSample{}, fmt.Errorf("%w: %s", ErrContentNotRegular, locatorPath)
	}

	file, err := os.Open(fullPath)
	if err != nil {
		return BoundedFileSample{}, fmt.Errorf("open content %q: %w", fullPath, err)
	}
	defer file.Close()

	openedInfo, err := file.Stat()
	if err != nil {
		return BoundedFileSample{}, fmt.Errorf("stat opened content %q: %w", fullPath, err)
	}
	if !openedInfo.Mode().IsRegular() || !os.SameFile(preInfo, openedInfo) {
		return BoundedFileSample{}, fmt.Errorf("%w: %s", ErrObservedObjectChanged, locatorPath)
	}
	if maxBytes >= 0 && openedInfo.Size() > maxBytes {
		return BoundedFileSample{}, fmt.Errorf("%w: size=%d limit=%d", ErrContentLimitExceeded, openedInfo.Size(), maxBytes)
	}

	hash := sha256.New()
	var retained bytes.Buffer
	buf := make([]byte, 128*1024)
	var size int64
	for {
		if err := ctx.Err(); err != nil {
			return BoundedFileSample{}, err
		}
		n, readErr := file.Read(buf)
		if n > 0 {
			size += int64(n)
			if maxBytes >= 0 && size > maxBytes {
				return BoundedFileSample{}, fmt.Errorf("%w: read=%d limit=%d", ErrContentLimitExceeded, size, maxBytes)
			}
			if _, err := hash.Write(buf[:n]); err != nil {
				return BoundedFileSample{}, fmt.Errorf("hash content %q: %w", fullPath, err)
			}
			if retainBytes {
				if _, err := retained.Write(buf[:n]); err != nil {
					return BoundedFileSample{}, fmt.Errorf("retain content %q: %w", fullPath, err)
				}
			}
		}
		if errors.Is(readErr, io.EOF) {
			break
		}
		if readErr != nil {
			return BoundedFileSample{}, fmt.Errorf("read content %q: %w", fullPath, readErr)
		}
	}

	afterInfo, err := file.Stat()
	if err != nil {
		return BoundedFileSample{}, fmt.Errorf("restat opened content %q: %w", fullPath, err)
	}
	if afterInfo.Size() != openedInfo.Size() ||
		!afterInfo.ModTime().Equal(openedInfo.ModTime()) ||
		size != afterInfo.Size() {
		return BoundedFileSample{}, fmt.Errorf("%w: %s", ErrContentUnstable, locatorPath)
	}

	postInfo, err := os.Lstat(fullPath)
	if err != nil {
		return BoundedFileSample{}, fmt.Errorf("%w: %s", ErrObservedObjectChanged, locatorPath)
	}
	if !postInfo.Mode().IsRegular() || !os.SameFile(openedInfo, postInfo) {
		return BoundedFileSample{}, fmt.Errorf("%w: %s", ErrObservedObjectChanged, locatorPath)
	}

	normalizedPath := filepath.ToSlash(relCheck)
	sample := BoundedFileSample{
		ContentSample: ContentSample{
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
		},
	}
	if retainBytes {
		sample.Bytes = retained.Bytes()
	}
	return sample, nil
}
