package search

import (
	"context"
	"errors"
	"fmt"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/extract"
)

var (
	ErrExtractionNotIndexable       = errors.New("extraction is not indexable")
	ErrExtractionRevisionNotCurrent = errors.New("extraction Revision is not current")
)

type RevisionReader interface {
	RevisionHistory(context.Context, corpus.ArtifactID) ([]corpus.RevisionRecord, error)
}

// DocumentFromCurrentExtraction revalidates Revision authority immediately
// before publishing an extracted result into derived search state.
func DocumentFromCurrentExtraction(
	ctx context.Context,
	revisions RevisionReader,
	result extract.Result,
) (Document, error) {
	if revisions == nil ||
		result.Status != extract.StatusExtracted ||
		result.ArtifactID == "" ||
		result.RevisionID == "" ||
		result.ExtractorID == "" {
		return Document{}, ErrExtractionNotIndexable
	}

	history, err := revisions.RevisionHistory(ctx, result.ArtifactID)
	if err != nil {
		return Document{}, fmt.Errorf("read Revision history for search: %w", err)
	}
	var current corpus.RevisionRecord
	var found bool
	for _, record := range history {
		if !found || record.Sequence > current.Sequence {
			current = record
			found = true
		}
	}
	if !found ||
		current.Revision.ArtifactID != result.ArtifactID ||
		current.Revision.ID != result.RevisionID ||
		current.Evidence.Algorithm != result.Evidence.Algorithm ||
		current.Evidence.Digest != result.Evidence.Digest ||
		current.Evidence.Size != result.Evidence.Size {
		return Document{}, fmt.Errorf(
			"%w: artifact=%s revision=%s",
			ErrExtractionRevisionNotCurrent,
			result.ArtifactID,
			result.RevisionID,
		)
	}

	document := Document{
		ArtifactID:  result.ArtifactID,
		RevisionID:  result.RevisionID,
		ExtractorID: result.ExtractorID,
		MediaType:   result.MediaType,
		Evidence:    result.Evidence,
		Text:        result.Text,
	}
	if err := ValidateDocument(document); err != nil {
		return Document{}, err
	}
	return document, nil
}
