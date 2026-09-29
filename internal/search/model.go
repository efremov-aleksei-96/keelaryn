package search

import (
	"errors"
	"strings"
	"unicode/utf8"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
)

var ErrInvalidDocument = errors.New("invalid search document")

// Document is rebuildable search input for one exact Artifact Revision and
// extractor identity. It is never Artifact, Revision or Locator authority.
type Document struct {
	ArtifactID  corpus.ArtifactID      `json:"artifact_id"`
	RevisionID  corpus.RevisionID      `json:"revision_id"`
	ExtractorID string                 `json:"extractor_id"`
	MediaType   string                 `json:"media_type,omitempty"`
	Evidence    corpus.ContentEvidence `json:"evidence"`
	Text        string                 `json:"text"`
}

// Hit identifies the exact derived Revision document that matched. It does not
// claim that the Revision or any Locator is current inventory authority.
type Hit struct {
	ArtifactID  corpus.ArtifactID      `json:"artifact_id"`
	RevisionID  corpus.RevisionID      `json:"revision_id"`
	ExtractorID string                 `json:"extractor_id"`
	MediaType   string                 `json:"media_type,omitempty"`
	Evidence    corpus.ContentEvidence `json:"evidence"`
}

func ValidateDocument(document Document) error {
	if document.ArtifactID == "" ||
		document.RevisionID == "" ||
		strings.TrimSpace(document.ExtractorID) == "" ||
		!utf8.ValidString(document.Text) {
		return ErrInvalidDocument
	}
	if err := corpus.ValidateContentEvidence(document.Evidence); err != nil {
		return ErrInvalidDocument
	}
	return nil
}
