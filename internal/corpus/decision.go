package corpus

// EvidenceStrength distinguishes a useful signal from evidence that a provider
// or operation contract declares sufficient for a continuity decision.
type EvidenceStrength string

const (
	EvidenceSupporting EvidenceStrength = "SUPPORTING"
	EvidenceConclusive EvidenceStrength = "CONCLUSIVE"
)

type ContinuityDirection string

const (
	DirectionSupportsSame     ContinuityDirection = "SUPPORTS_SAME"
	DirectionSupportsDistinct ContinuityDirection = "SUPPORTS_DISTINCT"
	DirectionUnknown          ContinuityDirection = "UNKNOWN"
)

type ContinuityDecisionState string

const (
	ContinuityUnresolved       ContinuityDecisionState = "UNRESOLVED"
	ContinuityAmbiguous        ContinuityDecisionState = "AMBIGUOUS"
	ContinuityConfirmedSame    ContinuityDecisionState = "CONFIRMED_SAME"
	ContinuityConfirmedDistinct ContinuityDecisionState = "CONFIRMED_DISTINCT"
)

// DecisionEvidence is normalized input to continuity resolution.
// Supporting evidence can inform a decision but cannot authorize identity
// mutation on its own.
type DecisionEvidence struct {
	Source    string              `json:"source"`
	Direction ContinuityDirection `json:"direction"`
	Strength  EvidenceStrength    `json:"strength"`
}

// ContinuityDecision is the fail-closed result of evidence resolution.
type ContinuityDecision struct {
	State    ContinuityDecisionState `json:"state"`
	Evidence []DecisionEvidence       `json:"evidence"`
}

// ResolveContinuity deliberately defaults to ambiguity.
// Only non-conflicting conclusive evidence can confirm continuity or
// distinctness. Supporting evidence alone never changes Artifact identity.
func ResolveContinuity(evidence []DecisionEvidence) ContinuityDecision {
	out := ContinuityDecision{
		State:    ContinuityUnresolved,
		Evidence: append([]DecisionEvidence(nil), evidence...),
	}
	if len(evidence) == 0 {
		return out
	}

	var same, distinct bool
	for _, item := range evidence {
		if item.Strength != EvidenceConclusive {
			continue
		}
		switch item.Direction {
		case DirectionSupportsSame:
			same = true
		case DirectionSupportsDistinct:
			distinct = true
		}
	}

	switch {
	case same && distinct:
		out.State = ContinuityAmbiguous
	case same:
		out.State = ContinuityConfirmedSame
	case distinct:
		out.State = ContinuityConfirmedDistinct
	default:
		out.State = ContinuityAmbiguous
	}
	return out
}
