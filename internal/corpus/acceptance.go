package corpus

import "time"

type AcceptedContinuityID string

const ContinuityPolicyCandidateSetV1 = "candidate-set:v1"

// AcceptedContinuityRecord is non-rebuildable provenance for an identity
// continuity decision that was actually committed to an Observation.
type AcceptedContinuityRecord struct {
	ID             AcceptedContinuityID      `json:"id"`
	RequestID      IdentityMutationRequestID `json:"request_id,omitempty"`
	AuthoritySetID IdentityAuthoritySetID    `json:"authority_set_id,omitempty"`
	ObservationID  ObservationID             `json:"observation_id"`
	ArtifactID    ArtifactID             `json:"artifact_id"`
	State         CandidateSetState      `json:"state"`
	PolicyID      string                 `json:"policy_id"`
	Resolution    CandidateSetResolution `json:"resolution"`
	DecidedAt     time.Time              `json:"decided_at"`
}

// ContinuityAcceptance is the atomic result of accepting RESOLVED_SAME.
type ContinuityAcceptance struct {
	Observation ObservationRecord       `json:"observation"`
	Revision    *RevisionObservation     `json:"revision,omitempty"`
	Decision    AcceptedContinuityRecord `json:"decision"`
	Replayed    bool                     `json:"replayed"`
}
