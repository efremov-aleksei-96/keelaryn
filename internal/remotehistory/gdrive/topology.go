package gdrive

import (
	"errors"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
)

type TopologyEvidenceKind string
type TopologyPresence string
type ParentKnowledge string
type ManagedRootMembership string
type MembershipUnknownReason string

const (
	TopologyEvidenceBootstrap TopologyEvidenceKind = "BOOTSTRAP"
	TopologyEvidenceUpsert    TopologyEvidenceKind = "UPSERT"
	TopologyEvidenceRemoved   TopologyEvidenceKind = "REMOVED"

	TopologyPresent     TopologyPresence = "PRESENT"
	TopologyUnavailable TopologyPresence = "UNAVAILABLE"

	ParentKnown       ParentKnowledge = "KNOWN"
	ParentUnknown     ParentKnowledge = "UNKNOWN"
	ParentUnavailable ParentKnowledge = "UNAVAILABLE"

	MembershipIn      ManagedRootMembership = "IN"
	MembershipOut     ManagedRootMembership = "OUT"
	MembershipUnknown ManagedRootMembership = "UNKNOWN"

	UnknownTopologyStale     MembershipUnknownReason = "TOPOLOGY_STALE"
	UnknownMissingParent     MembershipUnknownReason = "MISSING_PARENT"
	UnknownCycle             MembershipUnknownReason = "CYCLE"
	UnknownScopeMismatch     MembershipUnknownReason = "SCOPE_MISMATCH"
	UnknownObjectUnavailable MembershipUnknownReason = "OBJECT_UNAVAILABLE"
)

var ErrInvalidTopologyState = errors.New("invalid Google Drive topology state")

type TopologyEvidence struct {
	GenerationID        remotehistory.HistoryGenerationID
	PublicationSequence remotehistory.HistoryPublicationSequence
	ChangeOrdinal       *int64
	Kind                TopologyEvidenceKind
	ObjectID            corpus.ProviderObjectID
	Presence            TopologyPresence
	ParentKnowledge     ParentKnowledge
	ParentObjectID      corpus.ProviderObjectID
	DriveID             string
}

type TopologyNode struct {
	GenerationID            remotehistory.HistoryGenerationID
	ObjectID                corpus.ProviderObjectID
	Presence                TopologyPresence
	ParentKnowledge         ParentKnowledge
	ParentObjectID          corpus.ProviderObjectID
	DriveID                 string
	LastPublicationSequence remotehistory.HistoryPublicationSequence
	LastChangeOrdinal       *int64
}

type ManagedRootBinding struct {
	GenerationID        remotehistory.HistoryGenerationID
	ManagedRootObjectID corpus.ProviderObjectID
	BoundSequence       remotehistory.HistoryPublicationSequence
	CreatedAt           time.Time
}

type MembershipResult struct {
	State               ManagedRootMembership
	Reason              MembershipUnknownReason
	GenerationID        remotehistory.HistoryGenerationID
	PublicationSequence remotehistory.HistoryPublicationSequence
	ManagedRootObjectID corpus.ProviderObjectID
	ObjectID            corpus.ProviderObjectID
	TerminalObjectID    corpus.ProviderObjectID
}

func ValidateTopologyEvidence(e TopologyEvidence) error {
	if e.GenerationID == "" || e.ObjectID == "" || e.PublicationSequence == 0 {
		return ErrInvalidTopologyState
	}
	switch e.Kind {
	case TopologyEvidenceBootstrap:
		if e.PublicationSequence != 1 || e.ChangeOrdinal != nil {
			return ErrInvalidTopologyState
		}
		return validatePresentTopology(e.ObjectID, e.Presence, e.ParentKnowledge, e.ParentObjectID)
	case TopologyEvidenceUpsert:
		if e.PublicationSequence < 2 || e.ChangeOrdinal == nil || *e.ChangeOrdinal < 0 {
			return ErrInvalidTopologyState
		}
		return validatePresentTopology(e.ObjectID, e.Presence, e.ParentKnowledge, e.ParentObjectID)
	case TopologyEvidenceRemoved:
		if e.PublicationSequence < 2 || e.ChangeOrdinal == nil || *e.ChangeOrdinal < 0 ||
			e.Presence != TopologyUnavailable ||
			e.ParentKnowledge != ParentUnavailable ||
			e.ParentObjectID != "" {
			return ErrInvalidTopologyState
		}
		return nil
	default:
		return ErrInvalidTopologyState
	}
}

func ValidateTopologyNode(n TopologyNode) error {
	if n.GenerationID == "" || n.ObjectID == "" || n.LastPublicationSequence == 0 {
		return ErrInvalidTopologyState
	}
	if n.LastPublicationSequence == 1 {
		if n.LastChangeOrdinal != nil {
			return ErrInvalidTopologyState
		}
	} else if n.LastChangeOrdinal == nil || *n.LastChangeOrdinal < 0 {
		return ErrInvalidTopologyState
	}
	switch n.Presence {
	case TopologyPresent:
		return validatePresentTopology(n.ObjectID, n.Presence, n.ParentKnowledge, n.ParentObjectID)
	case TopologyUnavailable:
		if n.ParentKnowledge != ParentUnavailable || n.ParentObjectID != "" {
			return ErrInvalidTopologyState
		}
		return nil
	default:
		return ErrInvalidTopologyState
	}
}

func ValidateManagedRootBinding(binding ManagedRootBinding) error {
	if binding.GenerationID == "" ||
		binding.ManagedRootObjectID == "" ||
		binding.BoundSequence == 0 ||
		binding.CreatedAt.IsZero() {
		return ErrInvalidTopologyState
	}
	return nil
}

func validatePresentTopology(
	objectID corpus.ProviderObjectID,
	presence TopologyPresence,
	knowledge ParentKnowledge,
	parentID corpus.ProviderObjectID,
) error {
	if presence != TopologyPresent {
		return ErrInvalidTopologyState
	}
	switch knowledge {
	case ParentKnown:
		if parentID == "" || parentID == objectID {
			return ErrInvalidTopologyState
		}
	case ParentUnknown:
		if parentID != "" {
			return ErrInvalidTopologyState
		}
	default:
		return ErrInvalidTopologyState
	}
	return nil
}
