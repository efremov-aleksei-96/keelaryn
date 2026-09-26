package corpus

import (
	"errors"
	"fmt"
	"strings"
	"time"
)

var (
	ErrInvalidCandidateUniverseProof       = errors.New("invalid candidate-universe proof")
	ErrInvalidOccurrenceIdentityResolution = errors.New("invalid occurrence identity resolution")
)

type AdmissionRequestID = IdentityMutationRequestID

type CandidateUniverseCoverage string

const (
	CandidateUniverseUnknown  CandidateUniverseCoverage = "UNKNOWN"
	CandidateUniverseComplete CandidateUniverseCoverage = "COMPLETE"
)

// CandidateUniverseProof states whether the predecessor universe considered by
// one admission policy is complete for the exact provider/root/identity domain.
//
// COMPLETE is authority-bearing evidence. It must come from a qualified source;
// absence of path/hash/candidates is never sufficient by itself.
type CandidateUniverseProof struct {
	PolicyID        string                    `json:"policy_id"`
	ProviderID      ProviderID                `json:"provider_id"`
	IdentityDomain  string                    `json:"identity_domain"`
	ScopeID         string                    `json:"scope_id"`
	CurrentObjectID ProviderObjectID          `json:"current_object_id"`
	Coverage        CandidateUniverseCoverage `json:"coverage"`
	EvidenceRefs    []string                  `json:"evidence_refs,omitempty"`
}

func ValidateCandidateUniverseProof(proof CandidateUniverseProof) error {
	if strings.TrimSpace(proof.PolicyID) == "" ||
		proof.ProviderID == "" ||
		strings.TrimSpace(proof.IdentityDomain) == "" ||
		strings.TrimSpace(proof.ScopeID) == "" ||
		proof.CurrentObjectID == "" {
		return ErrInvalidCandidateUniverseProof
	}
	switch proof.Coverage {
	case CandidateUniverseUnknown:
		return nil
	case CandidateUniverseComplete:
		if len(proof.EvidenceRefs) == 0 {
			return fmt.Errorf("%w: COMPLETE requires evidence references", ErrInvalidCandidateUniverseProof)
		}
		seen := make(map[string]struct{}, len(proof.EvidenceRefs))
		for _, ref := range proof.EvidenceRefs {
			ref = strings.TrimSpace(ref)
			if ref == "" {
				return fmt.Errorf("%w: empty evidence reference", ErrInvalidCandidateUniverseProof)
			}
			if _, exists := seen[ref]; exists {
				return fmt.Errorf("%w: duplicate evidence reference %q", ErrInvalidCandidateUniverseProof, ref)
			}
			seen[ref] = struct{}{}
		}
		return nil
	default:
		return fmt.Errorf("%w: coverage=%q", ErrInvalidCandidateUniverseProof, proof.Coverage)
	}
}

type OccurrenceIdentityState string

const (
	OccurrenceIdentityUnresolved   OccurrenceIdentityState = "UNRESOLVED"
	OccurrenceIdentityAmbiguous    OccurrenceIdentityState = "AMBIGUOUS"
	OccurrenceIdentityResolvedSame OccurrenceIdentityState = "RESOLVED_SAME"
	OccurrenceIdentityResolvedNew  OccurrenceIdentityState = "RESOLVED_NEW"
)

// OccurrenceIdentityResolution composes the existing continuity candidate set
// with an optional proof that its predecessor universe is complete. NEW is an
// admission outcome, not continuity "with nothing".
type OccurrenceIdentityResolution struct {
	State              OccurrenceIdentityState `json:"state"`
	SelectedArtifactID ArtifactID              `json:"selected_artifact_id,omitempty"`
	Candidates         CandidateSetResolution  `json:"candidates"`
	Universe           *CandidateUniverseProof `json:"universe,omitempty"`
}

func ResolveOccurrenceIdentity(candidates CandidateSetResolution, proof *CandidateUniverseProof) (OccurrenceIdentityResolution, error) {
	if err := ValidateCandidateSetResolution(candidates); err != nil {
		return OccurrenceIdentityResolution{}, err
	}

	var copiedProof *CandidateUniverseProof
	if proof != nil {
		if err := ValidateCandidateUniverseProof(*proof); err != nil {
			return OccurrenceIdentityResolution{}, err
		}
		value := *proof
		value.EvidenceRefs = append([]string(nil), proof.EvidenceRefs...)
		copiedProof = &value
	}

	out := OccurrenceIdentityResolution{
		State:      OccurrenceIdentityUnresolved,
		Candidates: candidates,
		Universe:   copiedProof,
	}
	switch candidates.State {
	case CandidateSetResolvedSame:
		out.State = OccurrenceIdentityResolvedSame
		out.SelectedArtifactID = candidates.SelectedArtifactID
		return out, nil
	case CandidateSetAmbiguous:
		out.State = OccurrenceIdentityAmbiguous
		return out, nil
	case CandidateSetUnresolved:
	default:
		return OccurrenceIdentityResolution{}, fmt.Errorf(
			"%w: candidate state=%q",
			ErrInvalidOccurrenceIdentityResolution,
			candidates.State,
		)
	}

	if copiedProof == nil || copiedProof.Coverage != CandidateUniverseComplete {
		return out, nil
	}
	for _, candidate := range candidates.Candidates {
		if candidate.Decision.State != ContinuityConfirmedDistinct {
			out.State = OccurrenceIdentityAmbiguous
			return out, nil
		}
	}
	out.State = OccurrenceIdentityResolvedNew
	return out, nil
}

func ValidateOccurrenceIdentityResolution(resolution OccurrenceIdentityResolution) error {
	recomputed, err := ResolveOccurrenceIdentity(resolution.Candidates, resolution.Universe)
	if err != nil {
		return err
	}
	if resolution.State != recomputed.State ||
		resolution.SelectedArtifactID != recomputed.SelectedArtifactID {
		return ErrInvalidOccurrenceIdentityResolution
	}
	return nil
}

// ProviderArtifactBinding is the legacy/native-object binding shape used by
// pre-lifetime policies. RemoteHistory lifetime authority is segment-scoped;
// callers must not treat this naked object-ID mapping as cross-segment proof.
type ProviderArtifactBinding struct {
	IdentityDomain   string           `json:"identity_domain"`
	ProviderID       ProviderID       `json:"provider_id"`
	ProviderObjectID ProviderObjectID `json:"provider_object_id"`
	ArtifactID       ArtifactID       `json:"artifact_id"`
	PolicyID         string           `json:"policy_id"`
	AcceptedAt       time.Time        `json:"accepted_at"`
}

type AcceptedAdmissionRecord struct {
	RequestID        IdentityMutationRequestID    `json:"request_id"`
	AuthoritySetID   IdentityAuthoritySetID       `json:"authority_set_id,omitempty"`
	ObservationID    ObservationID                `json:"observation_id"`
	ArtifactID        ArtifactID                  `json:"artifact_id"`
	State             OccurrenceIdentityState      `json:"state"`
	PolicyID          string                       `json:"policy_id"`
	IdentityDomain    string                       `json:"identity_domain"`
	ProviderID        ProviderID                   `json:"provider_id"`
	ProviderObjectID  ProviderObjectID             `json:"provider_object_id"`
	LifetimeSegmentID string                       `json:"lifetime_segment_id,omitempty"`
	Resolution        OccurrenceIdentityResolution `json:"resolution"`
	DecidedAt         time.Time                    `json:"decided_at"`
}

type ArtifactAdmissionAcceptance struct {
	Observation ObservationRecord       `json:"observation"`
	Revision    *RevisionObservation     `json:"revision,omitempty"`
	Decision    AcceptedAdmissionRecord `json:"decision"`
	Binding     ProviderArtifactBinding  `json:"binding"`
	Replayed    bool                     `json:"replayed"`
}
