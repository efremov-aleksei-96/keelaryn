package corpus

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"
)

var (
	ErrInvalidIdentityAuthoritySet    = errors.New("invalid identity authority set")
	ErrInvalidIdentityMutationRequest = errors.New("invalid identity mutation request")
)

type IdentityMutationRequestID string
type IdentityAuthoritySetID string

type IdentityMutationKind string

const (
	IdentityMutationSame IdentityMutationKind = "SAME"
	IdentityMutationNew  IdentityMutationKind = "NEW"
)

const IdentityMutationFingerprintV1 = "identity-mutation-fingerprint:v1"

// IdentityAuthorityCandidate is one authority-bearing predecessor fact.
// Strength is deliberately absent: persistence by a qualified producer is what
// makes this fact authoritative.
type IdentityAuthorityCandidate struct {
	ArtifactID ArtifactID
	Direction  ContinuityDirection
	SourceRef  string
}

// IdentityAuthoritySet is immutable producer output consumed by identity
// mutation transactions. Production callers pass only its durable ID.
type IdentityAuthoritySet struct {
	ID                IdentityAuthoritySetID
	PolicyID          string
	ProviderID        ProviderID
	IdentityDomain    string
	ScopeID           string
	CurrentObjectID   ProviderObjectID
	UniverseCoverage  CandidateUniverseCoverage
	GenerationID      string
	LifetimeSegmentID string
	SourceRefs        []string
	Candidates        []IdentityAuthorityCandidate
	CreatedAt         time.Time
}

func ValidateIdentityAuthoritySet(set IdentityAuthoritySet) error {
	if set.ID == "" ||
		strings.TrimSpace(set.PolicyID) == "" ||
		set.ProviderID == "" ||
		strings.TrimSpace(set.IdentityDomain) == "" ||
		strings.TrimSpace(set.ScopeID) == "" ||
		set.CurrentObjectID == "" ||
		set.CreatedAt.IsZero() {
		return ErrInvalidIdentityAuthoritySet
	}
	switch set.UniverseCoverage {
	case CandidateUniverseUnknown, CandidateUniverseComplete:
	default:
		return fmt.Errorf("%w: coverage=%q", ErrInvalidIdentityAuthoritySet, set.UniverseCoverage)
	}
	if (set.GenerationID == "") != (set.LifetimeSegmentID == "") {
		return fmt.Errorf("%w: generation/lifetime segment references must be paired", ErrInvalidIdentityAuthoritySet)
	}
	if len(set.SourceRefs) == 0 {
		return fmt.Errorf("%w: no source references", ErrInvalidIdentityAuthoritySet)
	}
	seenRefs := make(map[string]struct{}, len(set.SourceRefs))
	for _, ref := range set.SourceRefs {
		ref = strings.TrimSpace(ref)
		if ref == "" {
			return fmt.Errorf("%w: empty source reference", ErrInvalidIdentityAuthoritySet)
		}
		if _, ok := seenRefs[ref]; ok {
			return fmt.Errorf("%w: duplicate source reference %q", ErrInvalidIdentityAuthoritySet, ref)
		}
		seenRefs[ref] = struct{}{}
	}

	seenCandidates := make(map[string]struct{}, len(set.Candidates))
	for _, candidate := range set.Candidates {
		if candidate.ArtifactID == "" || strings.TrimSpace(candidate.SourceRef) == "" {
			return fmt.Errorf("%w: invalid candidate", ErrInvalidIdentityAuthoritySet)
		}
		switch candidate.Direction {
		case DirectionSupportsSame, DirectionSupportsDistinct:
		default:
			return fmt.Errorf("%w: candidate direction=%q", ErrInvalidIdentityAuthoritySet, candidate.Direction)
		}
		key := string(candidate.ArtifactID) + "\x00" + string(candidate.Direction) + "\x00" + candidate.SourceRef
		if _, ok := seenCandidates[key]; ok {
			return fmt.Errorf("%w: duplicate candidate authority", ErrInvalidIdentityAuthoritySet)
		}
		seenCandidates[key] = struct{}{}
	}
	return nil
}

// IdentityMutationRequest is intent, not authority.
type IdentityMutationRequest struct {
	ID              IdentityMutationRequestID
	ScanID          ScanSessionID
	Observation     ObservationRecordInput
	ContentEvidence *ContentEvidence
	AuthoritySetID  IdentityAuthoritySetID
	DecidedAt       time.Time
}

type IdentityMutationFingerprint struct {
	Version string
	SHA256  string
}

type identityMutationFingerprintPayload struct {
	Version         string
	Kind            IdentityMutationKind
	ScanID          ScanSessionID
	ProviderObject  ProviderObject
	Locators        []Locator
	ArtifactID      ArtifactID
	RevisionID      RevisionID
	AssignmentState AssignmentState
	ObservedAt      string
	EntryKind       EntryKind
	Size            int64
	Mode            uint32
	ModifiedAt      string
	ContentEvidence *ContentEvidence
	AuthoritySetID  IdentityAuthoritySetID
}

// FingerprintIdentityMutation binds an idempotency key to request meaning.
// DecidedAt and request ID are intentionally excluded: exact replay returns the
// original durable timestamp and result.
func FingerprintIdentityMutation(kind IdentityMutationKind, request IdentityMutationRequest) (IdentityMutationFingerprint, error) {
	switch kind {
	case IdentityMutationSame, IdentityMutationNew:
	default:
		return IdentityMutationFingerprint{}, ErrInvalidIdentityMutationRequest
	}
	if request.ScanID == "" || request.AuthoritySetID == "" {
		return IdentityMutationFingerprint{}, ErrInvalidIdentityMutationRequest
	}

	locators := append([]Locator(nil), request.Observation.Locators...)
	sort.Slice(locators, func(i, j int) bool {
		if locators[i].ProviderID != locators[j].ProviderID {
			return locators[i].ProviderID < locators[j].ProviderID
		}
		if locators[i].Root != locators[j].Root {
			return locators[i].Root < locators[j].Root
		}
		return locators[i].Path < locators[j].Path
	})

	var evidence *ContentEvidence
	if request.ContentEvidence != nil {
		value := *request.ContentEvidence
		evidence = &value
	}

	payload := identityMutationFingerprintPayload{
		Version:         IdentityMutationFingerprintV1,
		Kind:            kind,
		ScanID:          request.ScanID,
		ProviderObject:  request.Observation.ProviderObject,
		Locators:        locators,
		ArtifactID:      request.Observation.ArtifactID,
		RevisionID:      request.Observation.RevisionID,
		AssignmentState: request.Observation.AssignmentState,
		ObservedAt:      request.Observation.ObservedAt.UTC().Format(time.RFC3339Nano),
		EntryKind:       request.Observation.Kind,
		Size:            request.Observation.Size,
		Mode:            request.Observation.Mode,
		ModifiedAt:      request.Observation.ModifiedAt.UTC().Format(time.RFC3339Nano),
		ContentEvidence: evidence,
		AuthoritySetID:  request.AuthoritySetID,
	}
	data, err := json.Marshal(payload)
	if err != nil {
		return IdentityMutationFingerprint{}, fmt.Errorf("marshal identity mutation fingerprint: %w", err)
	}
	sum := sha256.Sum256(data)
	return IdentityMutationFingerprint{
		Version: IdentityMutationFingerprintV1,
		SHA256:  hex.EncodeToString(sum[:]),
	}, nil
}
