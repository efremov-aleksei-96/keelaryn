package corpus

import "time"

// Identity types are deliberately distinct. No constructor derives ArtifactID
// or RevisionID from a path, provider object ID, or content hash.
type ArtifactID string
type ProviderID string
type ProviderObjectID string
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
