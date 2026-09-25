package corpus

import (
	"errors"
	"fmt"
	"sort"
)

var (
	ErrInvalidArtifactCandidate = errors.New("invalid Artifact candidate")
	ErrInvalidCandidateSetResolution = errors.New("invalid candidate-set resolution")
)

// ReconciliationSignalKind is a normalized, provider-neutral hint used during
// candidate reconciliation. These signals are deliberately SUPPORTING only.
type ReconciliationSignalKind string

const (
	SignalLocatorOverlap           ReconciliationSignalKind = "LOCATOR_OVERLAP"
	SignalContentEqual             ReconciliationSignalKind = "CONTENT_EQUAL"
	SignalProviderContinuityMatch  ReconciliationSignalKind = "PROVIDER_CONTINUITY_MATCH"
	SignalProviderContinuityMismatch ReconciliationSignalKind = "PROVIDER_CONTINUITY_MISMATCH"
)

// ReconciliationSignal converts common candidate-generation signals into the
// already-qualified continuity decision model. None of these signals is
// sufficient to mutate Artifact identity.
type ReconciliationSignal struct {
	Kind   ReconciliationSignalKind `json:"kind"`
	Source string                   `json:"source"`
}

func (s ReconciliationSignal) DecisionEvidence() DecisionEvidence {
	direction := DirectionUnknown
	switch s.Kind {
	case SignalLocatorOverlap, SignalContentEqual, SignalProviderContinuityMatch:
		direction = DirectionSupportsSame
	case SignalProviderContinuityMismatch:
		direction = DirectionSupportsDistinct
	}
	return DecisionEvidence{
		Source:    s.Source,
		Direction: direction,
		Strength:  EvidenceSupporting,
	}
}

// ArtifactCandidateInput accumulates evidence about one prior Artifact. The
// same Artifact may appear more than once in the input; ResolveCandidateSet
// merges all evidence before resolving it.
type ArtifactCandidateInput struct {
	ArtifactID ArtifactID        `json:"artifact_id"`
	Evidence   []DecisionEvidence `json:"evidence"`
}

// ArtifactCandidateResolution is the pairwise continuity decision for one
// prior Artifact candidate.
type ArtifactCandidateResolution struct {
	ArtifactID ArtifactID         `json:"artifact_id"`
	Decision   ContinuityDecision `json:"decision"`
}

// CandidateSetState answers whether the candidate set identifies the current
// occurrence. Pairwise CONFIRMED_DISTINCT results can eliminate candidates,
// but "distinct from all known candidates" is still UNRESOLVED identity.
type CandidateSetState string

const (
	CandidateSetUnresolved   CandidateSetState = "UNRESOLVED"
	CandidateSetAmbiguous    CandidateSetState = "AMBIGUOUS"
	CandidateSetResolvedSame CandidateSetState = "RESOLVED_SAME"
)

// CandidateSetResolution never chooses a best-effort winner.
//
// SelectedArtifactID is populated only for RESOLVED_SAME, which requires one
// uniquely plausible candidate whose pairwise decision is CONFIRMED_SAME.
type CandidateSetResolution struct {
	State              CandidateSetState             `json:"state"`
	SelectedArtifactID ArtifactID                    `json:"selected_artifact_id,omitempty"`
	Candidates         []ArtifactCandidateResolution `json:"candidates"`
}

func ResolveCandidateSet(inputs []ArtifactCandidateInput) (CandidateSetResolution, error) {
	if len(inputs) == 0 {
		return CandidateSetResolution{
			State:      CandidateSetUnresolved,
			Candidates: []ArtifactCandidateResolution{},
		}, nil
	}

	merged := make(map[ArtifactID][]DecisionEvidence)
	for _, input := range inputs {
		if input.ArtifactID == "" {
			return CandidateSetResolution{}, fmt.Errorf("%w: empty ArtifactID", ErrInvalidArtifactCandidate)
		}
		merged[input.ArtifactID] = append(merged[input.ArtifactID], input.Evidence...)
	}

	ids := make([]ArtifactID, 0, len(merged))
	for id := range merged {
		ids = append(ids, id)
	}
	sort.Slice(ids, func(i, j int) bool { return ids[i] < ids[j] })

	out := CandidateSetResolution{
		State:      CandidateSetUnresolved,
		Candidates: make([]ArtifactCandidateResolution, 0, len(ids)),
	}
	plausible := make([]ArtifactCandidateResolution, 0, len(ids))

	for _, id := range ids {
		resolution := ArtifactCandidateResolution{
			ArtifactID: id,
			Decision:   ResolveContinuity(merged[id]),
		}
		out.Candidates = append(out.Candidates, resolution)
		if resolution.Decision.State != ContinuityConfirmedDistinct {
			plausible = append(plausible, resolution)
		}
	}

	switch {
	case len(plausible) == 0:
		out.State = CandidateSetUnresolved
	case len(plausible) == 1 && plausible[0].Decision.State == ContinuityConfirmedSame:
		out.State = CandidateSetResolvedSame
		out.SelectedArtifactID = plausible[0].ArtifactID
	default:
		out.State = CandidateSetAmbiguous
	}
	return out, nil
}


// ValidateCandidateSetResolution proves that a serialized/provided resolution
// is exactly reproducible from the evidence it carries. This prevents callers
// from fabricating RESOLVED_SAME by changing only the selected Artifact/state.
func ValidateCandidateSetResolution(resolution CandidateSetResolution) error {
	inputs := make([]ArtifactCandidateInput, len(resolution.Candidates))
	for i, candidate := range resolution.Candidates {
		if candidate.ArtifactID == "" {
			return fmt.Errorf("%w: candidate %d has empty ArtifactID", ErrInvalidCandidateSetResolution, i)
		}
		inputs[i] = ArtifactCandidateInput{
			ArtifactID: candidate.ArtifactID,
			Evidence:   append([]DecisionEvidence(nil), candidate.Decision.Evidence...),
		}
	}

	recomputed, err := ResolveCandidateSet(inputs)
	if err != nil {
		return fmt.Errorf("%w: %v", ErrInvalidCandidateSetResolution, err)
	}
	if resolution.State != recomputed.State ||
		resolution.SelectedArtifactID != recomputed.SelectedArtifactID ||
		len(resolution.Candidates) != len(recomputed.Candidates) {
		return ErrInvalidCandidateSetResolution
	}
	for i := range resolution.Candidates {
		got := resolution.Candidates[i]
		want := recomputed.Candidates[i]
		if got.ArtifactID != want.ArtifactID ||
			got.Decision.State != want.Decision.State ||
			!sameDecisionEvidence(got.Decision.Evidence, want.Decision.Evidence) {
			return fmt.Errorf("%w: candidate %d does not reproduce", ErrInvalidCandidateSetResolution, i)
		}
	}
	return nil
}

func sameDecisionEvidence(a, b []DecisionEvidence) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
