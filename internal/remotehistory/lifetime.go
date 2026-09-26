package remotehistory

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
)

const ProviderLifetimeSegmentIdentityVersion = "provider-lifetime-segment:v1"

type ProviderObjectLifetimeSegmentID string
type LifetimeSegmentStatus string
type LifetimeSegmentStartKind string
type LifetimeSegmentClosureReason string

const (
	LifetimeSegmentActive LifetimeSegmentStatus = "ACTIVE"
	LifetimeSegmentClosed LifetimeSegmentStatus = "CLOSED"

	LifetimeSegmentStartBootstrap LifetimeSegmentStartKind = "BOOTSTRAP"
	LifetimeSegmentStartUpsert    LifetimeSegmentStartKind = "UPSERT"

	LifetimeSegmentClosedRemovedFromScope      LifetimeSegmentClosureReason = "REMOVED_FROM_SCOPE"
	LifetimeSegmentClosedHistoryGeneration     LifetimeSegmentClosureReason = "HISTORY_GENERATION_CLOSED"
)

var ErrInvalidProviderObjectLifetimeSegment = errors.New("invalid provider object lifetime segment")

type ProviderObjectLifetimeSegment struct {
	ID                     ProviderObjectLifetimeSegmentID `json:"id"`
	GenerationID           HistoryGenerationID              `json:"generation_id"`
	ProviderObjectID       corpus.ProviderObjectID          `json:"provider_object_id"`
	StartKind              LifetimeSegmentStartKind         `json:"start_kind"`
	StartPublicationSequence HistoryPublicationSequence     `json:"start_publication_sequence"`
	StartChangeOrdinal     *int64                           `json:"start_change_ordinal,omitempty"`
	LastPresentPublicationSequence HistoryPublicationSequence `json:"last_present_publication_sequence"`
	LastPresentChangeOrdinal *int64                         `json:"last_present_change_ordinal,omitempty"`
	Status                 LifetimeSegmentStatus            `json:"status"`
	EndPublicationSequence *HistoryPublicationSequence      `json:"end_publication_sequence,omitempty"`
	EndChangeOrdinal       *int64                           `json:"end_change_ordinal,omitempty"`
	ClosureReason          LifetimeSegmentClosureReason     `json:"closure_reason,omitempty"`
}

type providerLifetimeSegmentIdentity struct {
	Version                  string                     `json:"version"`
	GenerationID             HistoryGenerationID        `json:"generation_id"`
	ProviderObjectID         corpus.ProviderObjectID    `json:"provider_object_id"`
	StartKind                LifetimeSegmentStartKind   `json:"start_kind"`
	StartPublicationSequence HistoryPublicationSequence `json:"start_publication_sequence"`
	StartChangeOrdinal       *int64                     `json:"start_change_ordinal"`
}

func ProviderLifetimeSegmentID(
	generationID HistoryGenerationID,
	objectID corpus.ProviderObjectID,
	startKind LifetimeSegmentStartKind,
	startSequence HistoryPublicationSequence,
	startOrdinal *int64,
) (ProviderObjectLifetimeSegmentID, error) {
	if generationID == "" || objectID == "" || startSequence == 0 {
		return "", ErrInvalidProviderObjectLifetimeSegment
	}
	switch startKind {
	case LifetimeSegmentStartBootstrap:
		if startSequence != 1 || startOrdinal != nil {
			return "", ErrInvalidProviderObjectLifetimeSegment
		}
	case LifetimeSegmentStartUpsert:
		if startSequence < 2 || startOrdinal == nil || *startOrdinal < 0 {
			return "", ErrInvalidProviderObjectLifetimeSegment
		}
	default:
		return "", ErrInvalidProviderObjectLifetimeSegment
	}
	encoded, err := json.Marshal(providerLifetimeSegmentIdentity{
		Version:                  ProviderLifetimeSegmentIdentityVersion,
		GenerationID:             generationID,
		ProviderObjectID:         objectID,
		StartKind:                startKind,
		StartPublicationSequence: startSequence,
		StartChangeOrdinal:       startOrdinal,
	})
	if err != nil {
		return "", fmt.Errorf("encode lifetime segment identity: %w", err)
	}
	sum := sha256.Sum256(encoded)
	return ProviderObjectLifetimeSegmentID("hseg_" + hex.EncodeToString(sum[:])), nil
}

func ValidateProviderObjectLifetimeSegment(segment ProviderObjectLifetimeSegment) error {
	expected, err := ProviderLifetimeSegmentID(
		segment.GenerationID,
		segment.ProviderObjectID,
		segment.StartKind,
		segment.StartPublicationSequence,
		segment.StartChangeOrdinal,
	)
	if err != nil {
		return err
	}
	if segment.ID != expected || segment.LastPresentPublicationSequence < segment.StartPublicationSequence {
		return ErrInvalidProviderObjectLifetimeSegment
	}
	if segment.LastPresentPublicationSequence == 1 {
		if segment.LastPresentChangeOrdinal != nil {
			return ErrInvalidProviderObjectLifetimeSegment
		}
	} else if segment.LastPresentChangeOrdinal == nil || *segment.LastPresentChangeOrdinal < 0 {
		return ErrInvalidProviderObjectLifetimeSegment
	}
	switch segment.Status {
	case LifetimeSegmentActive:
		if segment.EndPublicationSequence != nil || segment.EndChangeOrdinal != nil || segment.ClosureReason != "" {
			return ErrInvalidProviderObjectLifetimeSegment
		}
	case LifetimeSegmentClosed:
		if segment.EndPublicationSequence == nil || *segment.EndPublicationSequence < segment.StartPublicationSequence {
			return ErrInvalidProviderObjectLifetimeSegment
		}
		switch segment.ClosureReason {
		case LifetimeSegmentClosedRemovedFromScope:
			if segment.EndChangeOrdinal == nil || *segment.EndChangeOrdinal < 0 {
				return ErrInvalidProviderObjectLifetimeSegment
			}
		case LifetimeSegmentClosedHistoryGeneration:
			if segment.EndChangeOrdinal != nil {
				return ErrInvalidProviderObjectLifetimeSegment
			}
		default:
			return ErrInvalidProviderObjectLifetimeSegment
		}
	default:
		return ErrInvalidProviderObjectLifetimeSegment
	}
	return nil
}
