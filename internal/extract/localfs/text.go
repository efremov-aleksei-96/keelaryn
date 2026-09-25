package localfs

import (
	"context"
	"errors"
	"fmt"
	"path/filepath"
	"strings"
	"unicode/utf8"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/extract"
	providerlocalfs "github.com/efremov-aleksei-96/keelaryn/internal/provider/localfs"
)

var (
	ErrInvalidExtractionRequest = errors.New("invalid extraction request")
	ErrReferencedRevisionMissing = errors.New("referenced Revision is missing")
)

const ExtractorID = "builtin:text-utf8:v1"

type RevisionReader interface {
	RevisionHistory(context.Context, corpus.ArtifactID) ([]corpus.RevisionRecord, error)
}

// Extract performs bounded, on-demand extraction for one currently assigned
// inventory row. It never writes durable state.
func Extract(
	ctx context.Context,
	revisions RevisionReader,
	provider *providerlocalfs.Provider,
	entry corpus.InventoryEntry,
	maxBytes int64,
) (extract.Result, error) {
	if revisions == nil || provider == nil || maxBytes < 0 {
		return extract.Result{}, ErrInvalidExtractionRequest
	}
	if entry.AssignmentState != corpus.AssignmentAssigned ||
		entry.ArtifactID == "" ||
		entry.RevisionID == "" ||
		entry.Kind != corpus.EntryRegularFile ||
		entry.Locator.ProviderID == "" ||
		entry.Locator.Root == "" ||
		entry.Locator.Path == "" {
		return extract.Result{}, ErrInvalidExtractionRequest
	}

	result := extract.Result{
		Status:      extract.StatusUnsupported,
		ArtifactID:  entry.ArtifactID,
		RevisionID:  entry.RevisionID,
		Locator:     entry.Locator,
		ExtractorID: ExtractorID,
	}

	mediaType, supported := supportedTextType(entry.Locator.Path)
	if !supported {
		return result, nil
	}
	result.MediaType = mediaType

	expected, err := exactRevision(ctx, revisions, entry.ArtifactID, entry.RevisionID)
	if err != nil {
		return extract.Result{}, err
	}

	sample, err := provider.ReadBoundedRegularFile(ctx, entry.Locator.Root, entry.Locator.Path, maxBytes)
	if err != nil {
		if errors.Is(err, providerlocalfs.ErrContentLimitExceeded) {
			result.Status = extract.StatusLimitExceeded
			return result, nil
		}
		return extract.Result{}, err
	}
	result.Evidence = sample.Evidence

	if sample.Evidence.Algorithm != expected.Evidence.Algorithm ||
		sample.Evidence.Digest != expected.Evidence.Digest ||
		sample.Evidence.Size != expected.Evidence.Size {
		result.Status = extract.StatusStaleRevision
		return result, nil
	}
	if !utf8.Valid(sample.Bytes) {
		result.Status = extract.StatusOpaque
		return result, nil
	}

	result.Status = extract.StatusExtracted
	result.Text = string(sample.Bytes)
	return result, nil
}

func exactRevision(ctx context.Context, reader RevisionReader, artifactID corpus.ArtifactID, revisionID corpus.RevisionID) (corpus.RevisionRecord, error) {
	history, err := reader.RevisionHistory(ctx, artifactID)
	if err != nil {
		return corpus.RevisionRecord{}, fmt.Errorf("read Revision history: %w", err)
	}
	for _, record := range history {
		if record.Revision.ID == revisionID {
			return record, nil
		}
	}
	return corpus.RevisionRecord{}, fmt.Errorf("%w: artifact=%s revision=%s", ErrReferencedRevisionMissing, artifactID, revisionID)
}

func supportedTextType(path string) (string, bool) {
	switch strings.ToLower(filepath.Ext(path)) {
	case ".txt":
		return "text/plain", true
	case ".md", ".markdown":
		return "text/markdown", true
	default:
		return "", false
	}
}
