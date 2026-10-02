package localfs

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"github.com/efremov-aleksei-96/keelaryn/internal/contextbundle"
	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/extract"
	extractlocalfs "github.com/efremov-aleksei-96/keelaryn/internal/extract/localfs"
	providerlocalfs "github.com/efremov-aleksei-96/keelaryn/internal/provider/localfs"
)

var ErrInvalidSelection = errors.New("invalid ContextBundle selection")

type RevisionReader interface {
	RevisionHistory(context.Context, corpus.ArtifactID) ([]corpus.RevisionRecord, error)
}

// Build constructs an ephemeral ContextBundle from explicit caller selections.
//
// It does not search, rank, chunk, persist, or mutate corpus state. Selection
// order is preserved exactly.
func Build(
	ctx context.Context,
	revisions RevisionReader,
	provider *providerlocalfs.Provider,
	selections []contextbundle.Selection,
) (contextbundle.Bundle, error) {
	return build(ctx, revisions, provider, selections, nil)
}

// BuildWithTotalMaxBytes enforces a byte ceiling across all extracted text in
// the bundle. The remaining budget is applied before each corpus read, so the
// builder never accumulates more extracted text than maxTotalBytes.
func BuildWithTotalMaxBytes(
	ctx context.Context,
	revisions RevisionReader,
	provider *providerlocalfs.Provider,
	selections []contextbundle.Selection,
	maxTotalBytes int64,
) (contextbundle.Bundle, error) {
	if maxTotalBytes < 0 {
		return contextbundle.Bundle{}, ErrInvalidSelection
	}
	return build(ctx, revisions, provider, selections, &maxTotalBytes)
}

func build(
	ctx context.Context,
	revisions RevisionReader,
	provider *providerlocalfs.Provider,
	selections []contextbundle.Selection,
	totalMaxBytes *int64,
) (contextbundle.Bundle, error) {
	if revisions == nil || provider == nil {
		return contextbundle.Bundle{}, ErrInvalidSelection
	}
	if err := ctx.Err(); err != nil {
		return contextbundle.Bundle{}, err
	}

	items := make([]contextbundle.Item, 0, len(selections))
	remaining := int64(0)
	if totalMaxBytes != nil {
		remaining = *totalMaxBytes
	}
	for i, selection := range selections {
		if strings.TrimSpace(selection.Reason) == "" || selection.MaxBytes < 0 {
			return contextbundle.Bundle{}, fmt.Errorf("%w: selection %d", ErrInvalidSelection, i)
		}

		maxBytes := selection.MaxBytes
		if totalMaxBytes != nil && maxBytes > remaining {
			maxBytes = remaining
		}
		result, err := extractlocalfs.Extract(
			ctx,
			revisions,
			provider,
			selection.Entry,
			maxBytes,
		)
		if err != nil {
			return contextbundle.Bundle{}, fmt.Errorf("selection %d extraction: %w", i, err)
		}

		item := contextbundle.Item{
			Reason:      selection.Reason,
			Status:      result.Status,
			ArtifactID:  result.ArtifactID,
			RevisionID:  result.RevisionID,
			Locator:     result.Locator,
			ExtractorID: result.ExtractorID,
			MediaType:   result.MediaType,
			Evidence:    result.Evidence,
		}
		if result.Status == extract.StatusExtracted {
			item.Text = result.Text
			if totalMaxBytes != nil {
				remaining -= int64(len(result.Text))
			}
		}
		items = append(items, item)
	}
	return contextbundle.Bundle{Items: items}, nil
}
