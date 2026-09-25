package contextbundle

import (
	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/extract"
)

// Selection is one caller-explicit request to place an already identified
// corpus item into task context. Reason records why the caller selected it;
// Keelaryn does not infer or rank that reason in P0.
type Selection struct {
	Entry    corpus.InventoryEntry `json:"entry"`
	Reason   string                `json:"reason"`
	MaxBytes int64                 `json:"max_bytes"`
}

// Item preserves the exact extraction outcome and provenance for one explicit
// selection. Text is populated only when Status is EXTRACTED.
type Item struct {
	Reason      string                 `json:"reason"`
	Status      extract.Status         `json:"status"`
	ArtifactID  corpus.ArtifactID      `json:"artifact_id"`
	RevisionID  corpus.RevisionID      `json:"revision_id"`
	Locator     corpus.Locator         `json:"locator"`
	ExtractorID string                 `json:"extractor_id"`
	MediaType   string                 `json:"media_type,omitempty"`
	Evidence    corpus.ContentEvidence `json:"evidence,omitempty"`
	Text        string                 `json:"text,omitempty"`
}

// Bundle is derived, rebuildable task context. It is not durable identity
// state and carries no authority beyond the source Artifact/Revision
// provenance recorded in each Item.
type Bundle struct {
	Items []Item `json:"items"`
}
