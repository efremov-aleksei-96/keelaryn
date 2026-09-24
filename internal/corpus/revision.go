package corpus

import (
	"errors"
	"fmt"
)

var (
	ErrInvalidContentEvidence       = errors.New("invalid content evidence")
	ErrContentEvidenceNotComparable = errors.New("content evidence algorithms are not comparable")
)

const ContentAlgorithmSHA256 = "sha256"

// ContentEvidence describes observed bytes. It is evidence for Revision
// comparison only; Digest is never an ArtifactID or RevisionID.
type ContentEvidence struct {
	Algorithm string `json:"algorithm"`
	Digest    string `json:"digest"`
	Size      int64  `json:"size"`
}

type RevisionRecord struct {
	Revision Revision        `json:"revision"`
	Sequence uint64          `json:"sequence"`
	Evidence ContentEvidence `json:"evidence"`
}

type RevisionObservation struct {
	Current RevisionRecord `json:"current"`
	Created bool           `json:"created"`
}

// RevisionTracker is a process-local P0 semantics probe. It validates Artifact
// existence through the registry but keeps Revision identity separate from
// Artifact identity and content hashes.
type RevisionTracker struct {
	registry *ArtifactRegistry
	next     uint64
	current  map[ArtifactID]RevisionRecord
	history  map[ArtifactID][]RevisionRecord
}

// ValidateContentEvidence applies provider-neutral evidence sanity rules.
func ValidateContentEvidence(evidence ContentEvidence) error {
	if evidence.Algorithm == "" || evidence.Digest == "" || evidence.Size < 0 {
		return ErrInvalidContentEvidence
	}
	return nil
}

func NewRevisionTracker(registry *ArtifactRegistry) *RevisionTracker {
	return &RevisionTracker{
		registry: registry,
		current:  make(map[ArtifactID]RevisionRecord),
		history:  make(map[ArtifactID][]RevisionRecord),
	}
}

func (t *RevisionTracker) Observe(artifactID ArtifactID, evidence ContentEvidence) (RevisionObservation, error) {
	if t.registry == nil {
		return RevisionObservation{}, errors.New("revision tracker has no Artifact registry")
	}
	if _, ok := t.registry.Artifact(artifactID); !ok {
		return RevisionObservation{}, fmt.Errorf("%w: %s", ErrArtifactNotFound, artifactID)
	}
	if err := ValidateContentEvidence(evidence); err != nil {
		return RevisionObservation{}, err
	}

	previous, exists := t.current[artifactID]
	if !exists {
		record := t.allocate(artifactID, 1, evidence)
		return RevisionObservation{Current: record, Created: true}, nil
	}

	if previous.Evidence.Algorithm != evidence.Algorithm {
		return RevisionObservation{}, fmt.Errorf(
			"%w: current=%s observed=%s",
			ErrContentEvidenceNotComparable,
			previous.Evidence.Algorithm,
			evidence.Algorithm,
		)
	}

	if previous.Evidence.Digest == evidence.Digest && previous.Evidence.Size == evidence.Size {
		return RevisionObservation{Current: previous, Created: false}, nil
	}

	record := t.allocate(artifactID, previous.Sequence+1, evidence)
	return RevisionObservation{Current: record, Created: true}, nil
}

func (t *RevisionTracker) Current(artifactID ArtifactID) (RevisionRecord, bool) {
	record, ok := t.current[artifactID]
	return record, ok
}

func (t *RevisionTracker) History(artifactID ArtifactID) []RevisionRecord {
	src := t.history[artifactID]
	out := make([]RevisionRecord, len(src))
	copy(out, src)
	return out
}

func (t *RevisionTracker) allocate(artifactID ArtifactID, sequence uint64, evidence ContentEvidence) RevisionRecord {
	t.next++
	record := RevisionRecord{
		Revision: Revision{
			ID:         RevisionID(fmt.Sprintf("session-revision-%06d", t.next)),
			ArtifactID: artifactID,
		},
		Sequence: sequence,
		Evidence: evidence,
	}
	t.current[artifactID] = record
	t.history[artifactID] = append(t.history[artifactID], record)
	return record
}
