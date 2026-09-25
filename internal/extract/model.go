package extract

import (
	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
)

type Status string

const (
	StatusExtracted     Status = "EXTRACTED"
	StatusUnsupported   Status = "UNSUPPORTED"
	StatusOpaque        Status = "OPAQUE"
	StatusStaleRevision Status = "STALE_REVISION"
	StatusLimitExceeded Status = "LIMIT_EXCEEDED"
)

// Result is derived, rebuildable extraction output. It is never identity
// authority and is not persisted by the P0 built-in extractor.
type Result struct {
	Status      Status                 `json:"status"`
	ArtifactID  corpus.ArtifactID      `json:"artifact_id"`
	RevisionID  corpus.RevisionID      `json:"revision_id"`
	Locator     corpus.Locator         `json:"locator"`
	ExtractorID string                 `json:"extractor_id"`
	MediaType   string                 `json:"media_type,omitempty"`
	Evidence    corpus.ContentEvidence `json:"evidence,omitempty"`
	Text        string                 `json:"text,omitempty"`
}
