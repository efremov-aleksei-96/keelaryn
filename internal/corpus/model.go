package corpus

import "time"

// Identity types are deliberately distinct. No constructor derives ArtifactID
// or RevisionID from a path, provider object ID, or content hash.
type ArtifactID string
type ProviderID string
type ProviderObjectID string
type ProviderObjectOccurrenceID string
type ObservationID string
type LocatorID string
type ScanSessionID string
type RevisionID string

// Artifact is Keelaryn's stable logical identity for a tracked thing.
type Artifact struct {
	ID ArtifactID `json:"id"`
}

// Revision identifies a distinct content state of one Artifact.
type Revision struct {
	ID         RevisionID `json:"id"`
	ArtifactID ArtifactID `json:"artifact_id"`
}

// ProviderObject is an object in one provider's own identity domain.
// ID may be empty when the provider cannot yet supply trustworthy native
// identity evidence. Empty is preferable to inventing identity from a path.
type ProviderObject struct {
	ProviderID    ProviderID          `json:"provider_id"`
	ID            ProviderObjectID    `json:"id,omitempty"`
	IdentityState ObjectIdentityState `json:"identity_state"`
}

type ObjectIdentityState string

const (
	ObjectIdentityUnresolved ObjectIdentityState = "UNRESOLVED"
	ObjectIdentityObserved   ObjectIdentityState = "OBSERVED"
)

// Locator describes where an observed object is accessible. It is never an
// Artifact identity.
type Locator struct {
	ProviderID ProviderID `json:"provider_id"`
	Root       string     `json:"root"`
	Path       string     `json:"path"`
}

type EntryKind string

const (
	EntryRegularFile EntryKind = "REGULAR_FILE"
	EntrySymlink     EntryKind = "SYMLINK"
	EntryOther       EntryKind = "OTHER"
)

// Observation is immutable evidence produced by discovery. P0-00 does not
// reconcile observations into Artifacts/Revisions yet.
type Observation struct {
	ProviderObject ProviderObject `json:"provider_object"`
	Locator        Locator        `json:"locator"`
	Kind           EntryKind      `json:"kind"`
	Size           int64          `json:"size"`
	Mode           uint32         `json:"mode"`
	ModifiedAt     time.Time      `json:"modified_at"`
}

// Catalog proves the minimum domain model can coexist in memory without
// conflating its identity domains. Reconciliation logic is intentionally
// deferred to a later P0 slice.
type Catalog struct {
	Artifacts       map[ArtifactID]Artifact
	ProviderObjects map[ProviderObjectID]ProviderObject
	Revisions       map[RevisionID]Revision
	Observations    []Observation
}

func NewCatalog() *Catalog {
	return &Catalog{
		Artifacts:       make(map[ArtifactID]Artifact),
		ProviderObjects: make(map[ProviderObjectID]ProviderObject),
		Revisions:       make(map[RevisionID]Revision),
	}
}


// ObservationRecordInput is provider-neutral append-only evidence to persist.
// Empty ArtifactID/RevisionID with AssignmentUnresolved is a valid first-class
// state and must not be "fixed" by guessing identity.
type ObservationRecordInput struct {
	ProviderObject  ProviderObject  `json:"provider_object"`
	Locators        []Locator       `json:"locators"`
	ArtifactID      ArtifactID      `json:"artifact_id,omitempty"`
	RevisionID      RevisionID      `json:"revision_id,omitempty"`
	AssignmentState AssignmentState `json:"assignment_state"`
	ObservedAt      time.Time       `json:"observed_at"`
	Kind            EntryKind       `json:"kind"`
	Size            int64           `json:"size"`
	Mode            uint32          `json:"mode"`
	ModifiedAt      time.Time       `json:"modified_at"`
}

// LocatorRecord gives an observation-time Locator its own record identity.
// LocatorID is provenance bookkeeping, not Artifact or ProviderObject identity.
type LocatorRecord struct {
	ID            LocatorID      `json:"id"`
	ObservationID ObservationID  `json:"observation_id"`
	Locator       Locator        `json:"locator"`
}

// ObservationRecord is the durable append-only form of discovery evidence.
// ProviderObjectOccurrenceID names this observation's physical-object
// occurrence record; it deliberately does not claim continuity with any other
// occurrence.
type ObservationRecord struct {
	ID                       ObservationID              `json:"id"`
	ProviderObjectOccurrenceID ProviderObjectOccurrenceID `json:"provider_object_occurrence_id"`
	ProviderObject           ProviderObject             `json:"provider_object"`
	Locators                 []LocatorRecord            `json:"locators"`
	ArtifactID               ArtifactID                 `json:"artifact_id,omitempty"`
	RevisionID               RevisionID                 `json:"revision_id,omitempty"`
	AssignmentState          AssignmentState            `json:"assignment_state"`
	ObservedAt               time.Time                  `json:"observed_at"`
	Kind                     EntryKind                  `json:"kind"`
	Size                     int64                      `json:"size"`
	Mode                     uint32                     `json:"mode"`
	ModifiedAt               time.Time                  `json:"modified_at"`
}


// ScanStatus marks whether one provider/root enumeration is eligible to define
// current inventory. Only COMPLETE scans are authoritative.
type ScanStatus string

const (
	ScanOpen     ScanStatus = "OPEN"
	ScanComplete ScanStatus = "COMPLETE"
	ScanAborted  ScanStatus = "ABORTED"
)

// ScanSession is a completeness boundary for exactly one provider/root.
type ScanSession struct {
	ID          ScanSessionID `json:"id"`
	ProviderID  ProviderID    `json:"provider_id"`
	Root        string        `json:"root"`
	Status      ScanStatus    `json:"status"`
	StartedAt   time.Time     `json:"started_at"`
	FinishedAt  time.Time     `json:"finished_at,omitempty"`
}

// InventoryEntry is a derived row from the latest COMPLETE scan. It is not
// stored authority: the Observation plus ScanSession remain authoritative.
type InventoryEntry struct {
	ScanID          ScanSessionID  `json:"scan_id"`
	ObservationID   ObservationID  `json:"observation_id"`
	ArtifactID      ArtifactID     `json:"artifact_id,omitempty"`
	RevisionID      RevisionID     `json:"revision_id,omitempty"`
	AssignmentState AssignmentState `json:"assignment_state"`
	Locator         Locator        `json:"locator"`
	Kind            EntryKind      `json:"kind"`
	Size            int64          `json:"size"`
	ModifiedAt      time.Time      `json:"modified_at"`
}


// OccurrenceCandidateSet is a read-only reconciliation view for one currently
// observed provider-object occurrence. It carries every current Locator plus
// the provider-neutral candidate-set resolution.
//
// Inputs are retained so callers can explicitly add stronger evidence and call
// ResolveCandidateSet again without re-running candidate discovery.
type OccurrenceCandidateSet struct {
	Locators    []Locator                `json:"locators"`
	Kind        EntryKind                `json:"kind"`
	Inputs      []ArtifactCandidateInput `json:"inputs"`
	Resolution  CandidateSetResolution   `json:"resolution"`
}
