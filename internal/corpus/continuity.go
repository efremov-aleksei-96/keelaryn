package corpus

// ContinuityEvidenceKind classifies provider evidence between two observations.
// Evidence is not itself an Artifact continuity decision.
type ContinuityEvidenceKind string

const (
	ContinuityNativeIdentityMatch    ContinuityEvidenceKind = "NATIVE_IDENTITY_MATCH"
	ContinuityNativeIdentityMismatch ContinuityEvidenceKind = "NATIVE_IDENTITY_MISMATCH"
	ContinuityEvidenceUnavailable    ContinuityEvidenceKind = "EVIDENCE_UNAVAILABLE"
)

// ContinuityEvidence records what a provider can say about two observed
// provider objects. Automatic Artifact merging is intentionally forbidden in
// P0-03 because native filesystem identifiers can be reused after deletion or
// otherwise fail to be globally stable over time.
type ContinuityEvidence struct {
	Kind                 ContinuityEvidenceKind `json:"kind"`
	ProviderID           ProviderID             `json:"provider_id"`
	PreviousLocators     []Locator              `json:"previous_locators"`
	CurrentLocators      []Locator              `json:"current_locators"`
	Basis                string                 `json:"basis"`
	AutomaticMergeAllowed bool                  `json:"automatic_merge_allowed"`
}
