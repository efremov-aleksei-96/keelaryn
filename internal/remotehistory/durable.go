package remotehistory

import (
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
)

type HistoryGenerationID string
type HistoryPublicationSequence uint64
type ScopePolicyFingerprint string

type HistoryGenerationStatus string

const (
	HistoryGenerationActive HistoryGenerationStatus = "ACTIVE"
	HistoryGenerationClosed HistoryGenerationStatus = "CLOSED"
)

type HistoryClosureReason string

const (
	HistoryClosureGap                 HistoryClosureReason = "GAP"
	HistoryClosureInvalidCursor       HistoryClosureReason = "INVALID_CURSOR"
	HistoryClosureScopeMismatch       HistoryClosureReason = "SCOPE_MISMATCH"
	HistoryClosureInsufficientHistory HistoryClosureReason = "INSUFFICIENT_HISTORY"
)

type HistoryPublicationKind string

const (
	HistoryPublicationBootstrap   HistoryPublicationKind = "BOOTSTRAP"
	HistoryPublicationIncremental HistoryPublicationKind = "INCREMENTAL"
)

type HistoryGeneration struct {
	ID                     HistoryGenerationID         `json:"id"`
	Scope                  Scope                       `json:"scope"`
	ScopePolicyFingerprint ScopePolicyFingerprint     `json:"scope_policy_fingerprint"`
	Status                 HistoryGenerationStatus    `json:"status"`
	CreatedAt              time.Time                  `json:"created_at"`
	ClosedAt               time.Time                  `json:"closed_at,omitempty"`
	ClosureReason          HistoryClosureReason       `json:"closure_reason,omitempty"`
	CurrentSequence        HistoryPublicationSequence `json:"current_sequence"`
	CommittedCursor        HistoryCursor              `json:"committed_cursor"`
}

type HistoryPublication struct {
	GenerationID       HistoryGenerationID         `json:"generation_id"`
	Sequence           HistoryPublicationSequence `json:"sequence"`
	Kind               HistoryPublicationKind     `json:"kind"`
	PreviousCursor     HistoryCursor               `json:"previous_cursor,omitempty"`
	CommittedCursor    HistoryCursor               `json:"committed_cursor"`
	CommittedAt        time.Time                   `json:"committed_at"`
	FingerprintVersion string                      `json:"fingerprint_version"`
	FingerprintSHA256  string                      `json:"fingerprint_sha256"`
}

type HistoryMembership struct {
	GenerationID            HistoryGenerationID         `json:"generation_id"`
	Object                  RemoteObjectState           `json:"object"`
	LastPublicationSequence HistoryPublicationSequence `json:"last_publication_sequence"`
}

var (
	ErrInvalidHistoryGeneration  = errors.New("invalid remote history generation")
	ErrInvalidHistoryPublication = errors.New("invalid remote history publication")
	ErrInvalidHistoryFailure     = errors.New("invalid remote history failure cycle")
)

func ValidateScopePolicyFingerprint(fingerprint ScopePolicyFingerprint) error {
	if strings.TrimSpace(string(fingerprint)) == "" {
		return ErrInvalidHistoryGeneration
	}
	return nil
}

func ValidateCompleteCycle(scope Scope, expectedCursor HistoryCursor, cycle ChangeCycle) error {
	if err := ValidateScope(scope); err != nil {
		return err
	}
	if expectedCursor == "" ||
		cycle.StreamID != scope.StreamID ||
		cycle.Status != CycleComplete ||
		cycle.PreviousCursor != expectedCursor ||
		cycle.NextCursor == "" ||
		cycle.Coverage != corpus.ProviderHistoryContinuous {
		return ErrInvalidHistoryPublication
	}
	for _, change := range cycle.Changes {
		if err := validateChange(scope, change); err != nil {
			return err
		}
	}
	return nil
}

func TrustBreakReason(scope Scope, expectedCursor HistoryCursor, cycle ChangeCycle) (HistoryClosureReason, error) {
	if err := ValidateScope(scope); err != nil {
		return "", err
	}
	if expectedCursor == "" ||
		cycle.StreamID != scope.StreamID ||
		cycle.PreviousCursor != expectedCursor ||
		cycle.NextCursor != expectedCursor ||
		cycle.Coverage != corpus.ProviderHistoryUnknown ||
		len(cycle.Changes) != 0 {
		return "", ErrInvalidHistoryFailure
	}
	switch cycle.Status {
	case CycleGap:
		return HistoryClosureGap, nil
	case CycleInvalidCursor:
		return HistoryClosureInvalidCursor, nil
	case CycleScopeMismatch:
		return HistoryClosureScopeMismatch, nil
	case CycleInsufficientHistory:
		return HistoryClosureInsufficientHistory, nil
	default:
		return "", fmt.Errorf("%w: status=%q", ErrInvalidHistoryFailure, cycle.Status)
	}
}
