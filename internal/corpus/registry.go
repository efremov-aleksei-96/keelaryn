package corpus

import (
	"errors"
	"fmt"
)

var (
	ErrArtifactNotFound          = errors.New("artifact not found")
	ErrUnknownContinuityDecision = errors.New("unknown continuity decision")
)

type AssignmentState string

const (
	AssignmentAssigned   AssignmentState = "ASSIGNED"
	AssignmentUnresolved AssignmentState = "UNRESOLVED"
)

// ArtifactAssignment is the result of applying one continuity decision.
//
// Ambiguous and unresolved decisions deliberately return no ArtifactID.
// CandidateArtifactIDs tell the caller which existing identity was considered
// without mutating the registry or guessing.
type ArtifactAssignment struct {
	State                AssignmentState         `json:"state"`
	ArtifactID           ArtifactID              `json:"artifact_id,omitempty"`
	CandidateArtifactIDs []ArtifactID            `json:"candidate_artifact_ids,omitempty"`
	Decision             ContinuityDecisionState `json:"decision"`
}

// ArtifactRegistry is the minimal in-memory identity authority for the P0
// technology spike. IDs are process-local and intentionally non-durable.
//
// The registry is provider-neutral: it never sees paths, hashes, native file
// IDs, or provider object IDs. Those belong to evidence/reconciliation layers.
type ArtifactRegistry struct {
	next      uint64
	artifacts map[ArtifactID]Artifact
}

func NewArtifactRegistry() *ArtifactRegistry {
	return &ArtifactRegistry{
		artifacts: make(map[ArtifactID]Artifact),
	}
}

// AdoptNew creates a new Artifact for an observation that has no prior
// continuity candidate. This is the only unconditional creation path.
func (r *ArtifactRegistry) AdoptNew() ArtifactAssignment {
	artifact := r.allocate()
	return ArtifactAssignment{
		State:      AssignmentAssigned,
		ArtifactID: artifact.ID,
		Decision:   ContinuityConfirmedDistinct,
	}
}

// Reconcile applies a continuity decision against one existing candidate.
//
// CONFIRMED_SAME preserves the candidate Artifact.
// CONFIRMED_DISTINCT creates a new Artifact.
// AMBIGUOUS/UNRESOLVED perform no identity mutation and return the candidate
// explicitly so a later evidence source or user decision can resolve it.
func (r *ArtifactRegistry) Reconcile(candidate ArtifactID, decision ContinuityDecision) (ArtifactAssignment, error) {
	if _, ok := r.artifacts[candidate]; !ok {
		return ArtifactAssignment{}, fmt.Errorf("%w: %s", ErrArtifactNotFound, candidate)
	}

	switch decision.State {
	case ContinuityConfirmedSame:
		return ArtifactAssignment{
			State:      AssignmentAssigned,
			ArtifactID: candidate,
			Decision:   decision.State,
		}, nil

	case ContinuityConfirmedDistinct:
		artifact := r.allocate()
		return ArtifactAssignment{
			State:                AssignmentAssigned,
			ArtifactID:           artifact.ID,
			CandidateArtifactIDs: []ArtifactID{candidate},
			Decision:             decision.State,
		}, nil

	case ContinuityAmbiguous, ContinuityUnresolved:
		return ArtifactAssignment{
			State:                AssignmentUnresolved,
			CandidateArtifactIDs: []ArtifactID{candidate},
			Decision:             decision.State,
		}, nil

	default:
		return ArtifactAssignment{}, fmt.Errorf("%w: %s", ErrUnknownContinuityDecision, decision.State)
	}
}

func (r *ArtifactRegistry) Artifact(id ArtifactID) (Artifact, bool) {
	artifact, ok := r.artifacts[id]
	return artifact, ok
}

func (r *ArtifactRegistry) Count() int {
	return len(r.artifacts)
}

func (r *ArtifactRegistry) allocate() Artifact {
	r.next++
	id := ArtifactID(fmt.Sprintf("session-artifact-%06d", r.next))
	artifact := Artifact{ID: id}
	r.artifacts[id] = artifact
	return artifact
}
