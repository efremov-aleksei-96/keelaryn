package search

import (
	"context"
	"errors"
	"fmt"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/extract"
)

var (
	ErrExtractionNotIndexable      = errors.New("extraction is not indexable")
	ErrExtractionRevisionMismatch  = errors.New("extraction Revision provenance mismatch")
)

type RevisionReader interface {
	RevisionHistory(context.Context, corpus.ArtifactID) ([]corpus.RevisionRecord, error)
}

// DocumentFromExtraction revalidates exact Revision authority before an
// extraction result can enter derived search state. It deliberately does not
// claim that the Revision is current inventory authority.
func DocumentFromExtraction(
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
	var exact corpus.RevisionRecord
	var found bool
	for _, record := range history {
		if record.Revision.ID == result.RevisionID {
			exact = record
			found = true
			break
		}
	}
	if !found ||
		exact.Revision.ArtifactID != result.ArtifactID ||
		exact.Evidence.Algorithm != result.Evidence.Algorithm ||
		exact.Evidence.Digest != result.Evidence.Digest ||
		exact.Evidence.Size != result.Evidence.Size {
		return Document{}, fmt.Errorf(
			"%w: artifact=%s revision=%s",
			ErrExtractionRevisionMismatch,
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
