package corpus

import (
	"errors"
	"fmt"
	"strings"
)

var ErrInvalidProviderIdentityComparison = errors.New("invalid provider identity comparison")

// ProviderIdentitySemantics describes what a provider contract actually
// guarantees about its object IDs. It is deliberately stricter than merely
// exposing an ID() method.
type ProviderIdentitySemantics string

const (
	// ProviderIdentitySupporting means IDs are useful hints only.
	ProviderIdentitySupporting ProviderIdentitySemantics = "SUPPORTING"

	// ProviderIdentityStableForResourceLifetime means the provider documents
	// IDs as unique per resource and stable while that resource exists. Equal
	// IDs across an unverified disappearance gap are still not conclusive,
	// because non-reuse after permanent deletion is not part of this contract.
	ProviderIdentityStableForResourceLifetime ProviderIdentitySemantics = "STABLE_FOR_RESOURCE_LIFETIME"

	// ProviderIdentityGloballyNonReusing is reserved for a provider contract
	// that explicitly guarantees an object ID is never reused in the identity
	// domain. No current P0 adapter assumes this merely from rclone IDer.
	ProviderIdentityGloballyNonReusing ProviderIdentitySemantics = "GLOBALLY_NON_REUSING"
)

// ProviderHistoryCoverage states whether the interval between two
// observations is itself covered by provider evidence.
type ProviderHistoryCoverage string

const (
	ProviderHistoryUnknown ProviderHistoryCoverage = "UNKNOWN"
	// ProviderHistoryContinuous means the adapter proves a complete continuity
	// window for this identity domain and has no disappearance/replacement gap
	// between the two observations being compared.
	ProviderHistoryContinuous ProviderHistoryCoverage = "CONTINUOUS"
)

// ProviderIdentityContract is provider-specific policy about the meaning of
// native object IDs. ProviderKind is descriptive; IdentityDomain is supplied
// by each comparison because one account/drive/remote must never be silently
// compared with another.
type ProviderIdentityContract struct {
	ID        string                    `json:"id"`
	Provider  string                    `json:"provider"`
	Semantics ProviderIdentitySemantics `json:"semantics"`
}

// ProviderIdentityRef is one provider-native identity observation.
type ProviderIdentityRef struct {
	IdentityDomain string           `json:"identity_domain"`
	ObjectID       ProviderObjectID `json:"object_id"`
}

// ProviderIdentityComparison is normalized input to provider-ID evidence.
type ProviderIdentityComparison struct {
	Previous ProviderIdentityRef      `json:"previous"`
	Current  ProviderIdentityRef      `json:"current"`
	Coverage ProviderHistoryCoverage  `json:"coverage"`
}

// RcloneGenericIdentityContract is the safe default for fs.IDer: rclone
// exposes an ID, but generic IDer does not specify lifetime/non-reuse semantics
// across all backends.
func RcloneGenericIdentityContract() ProviderIdentityContract {
	return ProviderIdentityContract{
		ID:        "rclone:fs.IDer:generic:v1",
		Provider:  "rclone",
		Semantics: ProviderIdentitySupporting,
	}
}

// GoogleDriveFileIDContract captures only the documented Drive fileId
// guarantee: unique per file and stable for the life of that file.
//
// It intentionally does NOT claim global non-reuse after permanent deletion.
// rclone Drive shortcut composite IDs must be normalized by the future adapter
// into the intended shortcut-object or target-object identity before applying
// this contract.
func GoogleDriveFileIDContract() ProviderIdentityContract {
	return ProviderIdentityContract{
		ID:        "google-drive:fileId:v1",
		Provider:  "google-drive",
		Semantics: ProviderIdentityStableForResourceLifetime,
	}
}

// ProviderIdentityEvidence converts a native-ID comparison into normalized
// continuity evidence without overstating the provider contract.
func ProviderIdentityEvidence(contract ProviderIdentityContract, comparison ProviderIdentityComparison) (DecisionEvidence, error) {
	if strings.TrimSpace(contract.ID) == "" ||
		strings.TrimSpace(contract.Provider) == "" ||
		strings.TrimSpace(comparison.Previous.IdentityDomain) == "" ||
		comparison.Previous.IdentityDomain != comparison.Current.IdentityDomain ||
		comparison.Previous.ObjectID == "" ||
		comparison.Current.ObjectID == "" {
		return DecisionEvidence{}, ErrInvalidProviderIdentityComparison
	}

	if comparison.Coverage != ProviderHistoryUnknown &&
		comparison.Coverage != ProviderHistoryContinuous {
		return DecisionEvidence{}, fmt.Errorf("%w: coverage=%q", ErrInvalidProviderIdentityComparison, comparison.Coverage)
	}

	sameID := comparison.Previous.ObjectID == comparison.Current.ObjectID
	evidence := DecisionEvidence{
		Source:   contract.ID,
		Strength: EvidenceSupporting,
	}
	if sameID {
		evidence.Direction = DirectionSupportsSame
	} else {
		evidence.Direction = DirectionSupportsDistinct
	}

	switch contract.Semantics {
	case ProviderIdentitySupporting:
		return evidence, nil

	case ProviderIdentityStableForResourceLifetime:
		if sameID {
			if comparison.Coverage == ProviderHistoryContinuous {
				evidence.Strength = EvidenceConclusive
			}
			return evidence, nil
		}
		// Unique IDs that are stable during each resource lifetime prove two
		// simultaneously/comparably observed provider resources are distinct.
		// This is scoped to one exact identity domain.
		evidence.Strength = EvidenceConclusive
		return evidence, nil

	case ProviderIdentityGloballyNonReusing:
		evidence.Strength = EvidenceConclusive
		return evidence, nil

	default:
		return DecisionEvidence{}, fmt.Errorf(
			"%w: semantics=%q",
			ErrInvalidProviderIdentityComparison,
			contract.Semantics,
		)
	}
}
