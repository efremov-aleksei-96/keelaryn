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
	if revisions == nil || provider == nil {
		return contextbundle.Bundle{}, ErrInvalidSelection
	}
	if err := ctx.Err(); err != nil {
		return contextbundle.Bundle{}, err
	}

	items := make([]contextbundle.Item, 0, len(selections))
	for i, selection := range selections {
		if strings.TrimSpace(selection.Reason) == "" || selection.MaxBytes < 0 {
			return contextbundle.Bundle{}, fmt.Errorf("%w: selection %d", ErrInvalidSelection, i)
		}

		result, err := extractlocalfs.Extract(
			ctx,
			revisions,
			provider,
			selection.Entry,
			selection.MaxBytes,
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
		}
		items = append(items, item)
	}
	return contextbundle.Bundle{Items: items}, nil
}
