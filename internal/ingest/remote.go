package ingest

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory/gdrive"
)

const (
	RemoteMetadataSnapshotFingerprintVersion = "keelaryn.remote-metadata-snapshot:v1"
	LightweightAllMaterializationPolicyID    = "LIGHTWEIGHT_ALL:v1"
	googleManagedRootScanRootVersion         = "google-drive:managed-root:v1"
)

var (
	ErrInvalidRemoteMetadataSnapshot = errors.New("invalid remote metadata snapshot")
	ErrRemoteMetadataSetMismatch     = errors.New("remote metadata snapshot does not equal proven IN set")
	ErrRemoteMembershipUnknown       = errors.New("remote managed-scope membership is unknown")
	ErrRemoteSourceNotCurrent        = errors.New("remote metadata source is not current")
	ErrRemoteMaterializationOpen     = errors.New("matching remote metadata materialization is already open")
	ErrRemoteSnapshotConflict        = errors.New("remote metadata snapshot fingerprint changed during materialization")
	ErrInvalidRemoteScopeProjection  = errors.New("invalid remote managed-scope projection")
	ErrRemoteLocatorCollision       = errors.New("remote metadata snapshot maps different provider objects to the same locator")
)

// RemoteMetadataEntry contains provider metadata facts only. Pointer fields
// distinguish an explicit zero value from a fact the provider did not supply.
// P0-30B fails closed when a required fact is absent.
type RemoteMetadataEntry struct {
	ProviderObjectID corpus.ProviderObjectID
	Kind             corpus.EntryKind
	Size             *int64
	Mode             *uint32
	ModifiedAt       *time.Time
}

// RemoteMetadataSnapshot is a deterministic metadata snapshot for one exact
// RemoteHistory publication and one managed corpus root. Locators are not
// accepted from Core callers: the provider-specific projection owns conversion
// to scan-scoped locators.
type RemoteMetadataSnapshot struct {
	GenerationID            remotehistory.HistoryGenerationID
	PublicationSequence     remotehistory.HistoryPublicationSequence
	ScanRoot                string
	SourceScopeID           string
	MaterializationPolicyID string
	Entries                 []RemoteMetadataEntry
}

type RemoteScopeMembershipState string

const (
	RemoteScopeMembershipIn      RemoteScopeMembershipState = "IN"
	RemoteScopeMembershipOut     RemoteScopeMembershipState = "OUT"
	RemoteScopeMembershipUnknown RemoteScopeMembershipState = "UNKNOWN"
)

type RemoteScopeMembership struct {
	State  RemoteScopeMembershipState
	Reason string
}

// RemoteMaterializationScope is the exact source boundary supplied to a
// provider-specific membership/locator projection. ProjectLocators must be a
// deterministic projection of this boundary and object ID; it must not perform
// live provider discovery.
type RemoteMaterializationScope struct {
	Generation              remotehistory.HistoryGeneration
	PublicationSequence     remotehistory.HistoryPublicationSequence
	ScanRoot                string
	SourceScopeID           string
	MaterializationPolicyID string
}

// RemoteScopeProjection owns provider-specific managed-root membership and
// scan-scoped locator projection without redefining Artifact identity.
type RemoteScopeProjection interface {
	Membership(context.Context, RemoteMaterializationScope, corpus.ProviderObjectID) (RemoteScopeMembership, error)
	ProjectLocators(context.Context, RemoteMaterializationScope, corpus.ProviderObjectID) ([]corpus.Locator, error)
}

// RemoteMaterializationStore is the existing durable-state surface reused by
// P0-30B. There is deliberately no remote-specific inventory write API.
type RemoteMaterializationStore interface {
	RemoteHistoryGeneration(context.Context, remotehistory.HistoryGenerationID) (remotehistory.HistoryGeneration, error)
	RemoteHistoryMembership(context.Context, remotehistory.HistoryGenerationID) ([]remotehistory.HistoryMembership, error)
	StartRemoteHistoryScan(context.Context, string, remotehistory.RemoteScanSourceInput, time.Time) (corpus.ScanSession, bool, error)
	ReconcileRemoteHistoryScan(context.Context, corpus.ScanSessionID) (remotehistory.RemoteScanSourceState, error)
	RecordObservationInScan(context.Context, corpus.ScanSessionID, corpus.ObservationRecordInput) (corpus.ObservationRecord, error)
	CompleteRemoteHistoryScan(context.Context, corpus.ScanSessionID, time.Time) (corpus.ScanSession, bool, error)
	AbortScan(context.Context, corpus.ScanSessionID, time.Time) error
}

type canonicalRemoteMetadataEntry struct {
	ProviderObjectID corpus.ProviderObjectID `json:"provider_object_id"`
	Locators         []corpus.Locator        `json:"locators"`
	Kind             corpus.EntryKind        `json:"kind"`
	Size             int64                   `json:"size"`
	Mode             uint32                  `json:"mode"`
	ModifiedAt       string                  `json:"modified_at"`
}

type preparedRemoteMetadataSnapshot struct {
	generation  remotehistory.HistoryGeneration
	snapshot    RemoteMetadataSnapshot
	entries     []canonicalRemoteMetadataEntry
	fingerprint string
}

// MaterializeRemoteMetadata persists one deterministic LIGHTWEIGHT_ALL remote
// snapshot through the existing ScanSession -> Observation -> Inventory path.
// It does not assign Artifact or Revision identity.
//
// A matching COMPLETE source is replayed, including after RemoteHistory has
// advanced. A matching OPEN source is reconciled but never auto-aborted: P0-30B
// has no durable worker lease/ownership proof, so recovery must explicitly
// decide when an OPEN attempt is abandoned.
func MaterializeRemoteMetadata(
	ctx context.Context,
	store RemoteMaterializationStore,
	projection RemoteScopeProjection,
	snapshot RemoteMetadataSnapshot,
	observedAt time.Time,
) (scan corpus.ScanSession, replayed bool, err error) {
	if store == nil || projection == nil || observedAt.IsZero() {
		return corpus.ScanSession{}, false, ErrInvalidRemoteMetadataSnapshot
	}
	observedAt = observedAt.UTC()

	prepared, err := prepareRemoteMetadataSnapshot(ctx, store, projection, snapshot)
	if err != nil {
		return corpus.ScanSession{}, false, err
	}
	source := prepared.source()

	current := prepared.generation.Status == remotehistory.HistoryGenerationActive &&
		prepared.generation.CurrentSequence == snapshot.PublicationSequence
	if current {
		if err := validateRemoteExactInSet(ctx, store, projection, prepared); err != nil {
			return corpus.ScanSession{}, false, err
		}
	}

	scan, replayed, err = store.StartRemoteHistoryScan(ctx, snapshot.ScanRoot, source, observedAt)
	if err != nil {
		return corpus.ScanSession{}, false, err
	}
	if replayed && scan.Status == corpus.ScanComplete {
		return scan, true, nil
	}
	if replayed {
		if scan.Status != corpus.ScanOpen {
			return scan, false, fmt.Errorf("%w: replayed scan %s has status %s", ErrInvalidRemoteMetadataSnapshot, scan.ID, scan.Status)
		}
		state, reconcileErr := store.ReconcileRemoteHistoryScan(ctx, scan.ID)
		if reconcileErr != nil {
			return scan, true, fmt.Errorf("reconcile existing OPEN remote scan: %w", reconcileErr)
		}
		if state != remotehistory.RemoteScanSourceCurrent {
			return scan, true, fmt.Errorf("%w: existing OPEN scan=%s source state=%s", ErrRemoteSourceNotCurrent, scan.ID, state)
		}
		return scan, true, fmt.Errorf("%w: scan=%s", ErrRemoteMaterializationOpen, scan.ID)
	}

	finalized := false
	defer func() {
		if err == nil || finalized || scan.ID == "" {
			return
		}
		finishAt := scanFinishTime(scan, observedAt)
		if abortErr := store.AbortScan(context.Background(), scan.ID, finishAt); abortErr != nil {
			err = errors.Join(err, fmt.Errorf("abort failed remote materialization scan %s: %w", scan.ID, abortErr))
			return
		}
		scan.Status = corpus.ScanAborted
		scan.FinishedAt = finishAt
	}()

	// Revalidate immediately after the durable OPEN boundary. StartRemoteHistoryScan
	// already checks generation sequence atomically; this also rechecks provider
	// topology/membership and the exact snapshot object set before the first row.
	if err = validateRemoteExactInSet(ctx, store, projection, prepared); err != nil {
		return scan, false, err
	}

	for _, entry := range prepared.entries {
		modifiedAt, parseErr := time.Parse(time.RFC3339Nano, entry.ModifiedAt)
		if parseErr != nil {
			return scan, false, fmt.Errorf("%w: canonical modified time: %v", ErrInvalidRemoteMetadataSnapshot, parseErr)
		}
		input := corpus.ObservationRecordInput{
			ProviderObject: corpus.ProviderObject{
				ProviderID:    prepared.generation.Scope.ProviderID,
				ID:            entry.ProviderObjectID,
				IdentityState: corpus.ObjectIdentityObserved,
			},
			Locators:        append([]corpus.Locator(nil), entry.Locators...),
			AssignmentState: corpus.AssignmentUnresolved,
			ObservedAt:      observedAt,
			Kind:            entry.Kind,
			Size:            entry.Size,
			Mode:            entry.Mode,
			ModifiedAt:      modifiedAt,
		}
		if _, err = store.RecordObservationInScan(ctx, scan.ID, input); err != nil {
			return scan, false, fmt.Errorf("persist remote snapshot observation %s: %w", entry.ProviderObjectID, err)
		}
	}

	// The provider projection and exact IN set are checked again before COMPLETE.
	// If deterministic projection changed, fail closed instead of publishing a
	// competing inventory under the original source fingerprint.
	finalPrepared, prepErr := prepareRemoteMetadataSnapshot(ctx, store, projection, snapshot)
	if prepErr != nil {
		return scan, false, prepErr
	}
	if finalPrepared.fingerprint != prepared.fingerprint {
		return scan, false, ErrRemoteSnapshotConflict
	}
	if err = validateRemoteExactInSet(ctx, store, projection, finalPrepared); err != nil {
		return scan, false, err
	}

	completed, completionReplayed, err := store.CompleteRemoteHistoryScan(ctx, scan.ID, observedAt)
	if err != nil {
		return scan, false, fmt.Errorf("complete remote materialization scan: %w", err)
	}
	finalized = true
	return completed, completionReplayed, nil
}

func (p preparedRemoteMetadataSnapshot) source() remotehistory.RemoteScanSourceInput {
	return remotehistory.RemoteScanSourceInput{
		GenerationID:               p.snapshot.GenerationID,
		PublicationSequence:        p.snapshot.PublicationSequence,
		SourceScopeID:              p.snapshot.SourceScopeID,
		MaterializationPolicyID:    p.snapshot.MaterializationPolicyID,
		SnapshotFingerprintVersion: RemoteMetadataSnapshotFingerprintVersion,
		SnapshotFingerprintSHA256:  p.fingerprint,
	}
}

func prepareRemoteMetadataSnapshot(
	ctx context.Context,
	store RemoteMaterializationStore,
	projection RemoteScopeProjection,
	snapshot RemoteMetadataSnapshot,
) (preparedRemoteMetadataSnapshot, error) {
	if snapshot.GenerationID == "" || snapshot.PublicationSequence == 0 ||
		!isCanonicalNonEmpty(snapshot.ScanRoot) ||
		!isCanonicalNonEmpty(snapshot.SourceScopeID) ||
		snapshot.MaterializationPolicyID != LightweightAllMaterializationPolicyID {
		return preparedRemoteMetadataSnapshot{}, ErrInvalidRemoteMetadataSnapshot
	}
	generation, err := store.RemoteHistoryGeneration(ctx, snapshot.GenerationID)
	if err != nil {
		return preparedRemoteMetadataSnapshot{}, err
	}

	scope := RemoteMaterializationScope{
		Generation:              generation,
		PublicationSequence:     snapshot.PublicationSequence,
		ScanRoot:                snapshot.ScanRoot,
		SourceScopeID:           snapshot.SourceScopeID,
		MaterializationPolicyID: snapshot.MaterializationPolicyID,
	}

	entries := make([]canonicalRemoteMetadataEntry, 0, len(snapshot.Entries))
	seenObjects := make(map[corpus.ProviderObjectID]struct{}, len(snapshot.Entries))
	locatorOwners := make(map[corpus.Locator]corpus.ProviderObjectID, len(snapshot.Entries))
	for _, entry := range snapshot.Entries {
		if entry.ProviderObjectID == "" {
			return preparedRemoteMetadataSnapshot{}, ErrInvalidRemoteMetadataSnapshot
		}
		if _, duplicate := seenObjects[entry.ProviderObjectID]; duplicate {
			return preparedRemoteMetadataSnapshot{}, fmt.Errorf("%w: duplicate object %s", ErrInvalidRemoteMetadataSnapshot, entry.ProviderObjectID)
		}
		seenObjects[entry.ProviderObjectID] = struct{}{}
		if err := validateRemoteMetadataEntry(entry); err != nil {
			return preparedRemoteMetadataSnapshot{}, err
		}

		locators, err := projection.ProjectLocators(ctx, scope, entry.ProviderObjectID)
		if err != nil {
			return preparedRemoteMetadataSnapshot{}, fmt.Errorf("project locators for %s: %w", entry.ProviderObjectID, err)
		}
		locators, err = canonicalScanLocators(generation.Scope.ProviderID, snapshot.ScanRoot, locators)
		if err != nil {
			return preparedRemoteMetadataSnapshot{}, fmt.Errorf("object %s: %w", entry.ProviderObjectID, err)
		}
		for _, locator := range locators {
			if owner, exists := locatorOwners[locator]; exists && owner != entry.ProviderObjectID {
				return preparedRemoteMetadataSnapshot{}, fmt.Errorf(
					"%w: locator=%#v objects=%s,%s",
					ErrRemoteLocatorCollision,
					locator,
					owner,
					entry.ProviderObjectID,
				)
			}
			locatorOwners[locator] = entry.ProviderObjectID
		}
		entries = append(entries, canonicalRemoteMetadataEntry{
			ProviderObjectID: entry.ProviderObjectID,
			Locators:         locators,
			Kind:             entry.Kind,
			Size:             *entry.Size,
			Mode:             *entry.Mode,
			ModifiedAt:       entry.ModifiedAt.UTC().Format(time.RFC3339Nano),
		})
	}
	sort.Slice(entries, func(i, j int) bool {
		return entries[i].ProviderObjectID < entries[j].ProviderObjectID
	})

	fingerprint, err := remoteMetadataFingerprint(generation, snapshot, entries)
	if err != nil {
		return preparedRemoteMetadataSnapshot{}, err
	}
	return preparedRemoteMetadataSnapshot{
		generation:  generation,
		snapshot:    snapshot,
		entries:     entries,
		fingerprint: fingerprint,
	}, nil
}

func validateRemoteMetadataEntry(entry RemoteMetadataEntry) error {
	switch entry.Kind {
	case corpus.EntryRegularFile, corpus.EntrySymlink, corpus.EntryOther:
	default:
		return fmt.Errorf("%w: object %s has invalid kind %q", ErrInvalidRemoteMetadataSnapshot, entry.ProviderObjectID, entry.Kind)
	}
	if entry.Size == nil || *entry.Size < 0 || entry.Mode == nil || entry.ModifiedAt == nil || entry.ModifiedAt.IsZero() {
		return fmt.Errorf("%w: object %s lacks required metadata facts", ErrInvalidRemoteMetadataSnapshot, entry.ProviderObjectID)
	}
	return nil
}

func canonicalScanLocators(providerID corpus.ProviderID, root string, locators []corpus.Locator) ([]corpus.Locator, error) {
	if len(locators) == 0 {
		return nil, ErrInvalidRemoteScopeProjection
	}
	out := append([]corpus.Locator(nil), locators...)
	for _, locator := range out {
		if locator.ProviderID != providerID || locator.Root != root || !isCanonicalNonEmpty(locator.Path) {
			return nil, fmt.Errorf("%w: locator=%#v provider=%s root=%s", ErrInvalidRemoteScopeProjection, locator, providerID, root)
		}
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].ProviderID != out[j].ProviderID {
			return out[i].ProviderID < out[j].ProviderID
		}
		if out[i].Root != out[j].Root {
			return out[i].Root < out[j].Root
		}
		return out[i].Path < out[j].Path
	})
	for i := 1; i < len(out); i++ {
		if out[i] == out[i-1] {
			return nil, fmt.Errorf("%w: duplicate locator %#v", ErrInvalidRemoteScopeProjection, out[i])
		}
	}
	return out, nil
}

func validateRemoteExactInSet(
	ctx context.Context,
	store RemoteMaterializationStore,
	projection RemoteScopeProjection,
	prepared preparedRemoteMetadataSnapshot,
) error {
	generation, err := store.RemoteHistoryGeneration(ctx, prepared.snapshot.GenerationID)
	if err != nil {
		return err
	}
	if generation.Status != remotehistory.HistoryGenerationActive ||
		generation.CurrentSequence != prepared.snapshot.PublicationSequence {
		return fmt.Errorf(
			"%w: generation=%s status=%s current=%d source=%d",
			ErrRemoteSourceNotCurrent,
			generation.ID,
			generation.Status,
			generation.CurrentSequence,
			prepared.snapshot.PublicationSequence,
		)
	}
	scope := RemoteMaterializationScope{
		Generation:              generation,
		PublicationSequence:     prepared.snapshot.PublicationSequence,
		ScanRoot:                prepared.snapshot.ScanRoot,
		SourceScopeID:           prepared.snapshot.SourceScopeID,
		MaterializationPolicyID: prepared.snapshot.MaterializationPolicyID,
	}
	memberships, err := store.RemoteHistoryMembership(ctx, generation.ID)
	if err != nil {
		return err
	}
	in := make(map[corpus.ProviderObjectID]struct{}, len(memberships))
	for _, membership := range memberships {
		if membership.GenerationID != generation.ID || membership.Object.ObjectID == "" ||
			membership.LastPublicationSequence > prepared.snapshot.PublicationSequence {
			return fmt.Errorf("%w: invalid RemoteHistory membership row %#v", ErrInvalidRemoteMetadataSnapshot, membership)
		}
		decision, err := projection.Membership(ctx, scope, membership.Object.ObjectID)
		if err != nil {
			return fmt.Errorf("evaluate membership for %s: %w", membership.Object.ObjectID, err)
		}
		switch decision.State {
		case RemoteScopeMembershipIn:
			in[membership.Object.ObjectID] = struct{}{}
		case RemoteScopeMembershipOut:
		case RemoteScopeMembershipUnknown:
			return fmt.Errorf("%w: object=%s reason=%s", ErrRemoteMembershipUnknown, membership.Object.ObjectID, decision.Reason)
		default:
			return fmt.Errorf("%w: object=%s state=%q", ErrInvalidRemoteScopeProjection, membership.Object.ObjectID, decision.State)
		}
	}
	if len(in) != len(prepared.entries) {
		return fmt.Errorf("%w: snapshot=%d in=%d", ErrRemoteMetadataSetMismatch, len(prepared.entries), len(in))
	}
	for _, entry := range prepared.entries {
		if _, ok := in[entry.ProviderObjectID]; !ok {
			return fmt.Errorf("%w: unexpected object %s", ErrRemoteMetadataSetMismatch, entry.ProviderObjectID)
		}
	}
	return nil
}

func remoteMetadataFingerprint(
	generation remotehistory.HistoryGeneration,
	snapshot RemoteMetadataSnapshot,
	entries []canonicalRemoteMetadataEntry,
) (string, error) {
	value := struct {
		Version                 string                                   `json:"version"`
		GenerationID            remotehistory.HistoryGenerationID        `json:"generation_id"`
		PublicationSequence     remotehistory.HistoryPublicationSequence `json:"publication_sequence"`
		ProviderID              corpus.ProviderID                        `json:"provider_id"`
		ScanRoot                string                                   `json:"scan_root"`
		SourceScopeID           string                                   `json:"source_scope_id"`
		MaterializationPolicyID string                                   `json:"materialization_policy_id"`
		Entries                 []canonicalRemoteMetadataEntry           `json:"entries"`
	}{
		Version:                 RemoteMetadataSnapshotFingerprintVersion,
		GenerationID:            snapshot.GenerationID,
		PublicationSequence:     snapshot.PublicationSequence,
		ProviderID:              generation.Scope.ProviderID,
		ScanRoot:                snapshot.ScanRoot,
		SourceScopeID:           snapshot.SourceScopeID,
		MaterializationPolicyID: snapshot.MaterializationPolicyID,
		Entries:                 entries,
	}
	encoded, err := json.Marshal(value)
	if err != nil {
		return "", fmt.Errorf("encode remote metadata snapshot fingerprint: %w", err)
	}
	sum := sha256.Sum256(encoded)
	return hex.EncodeToString(sum[:]), nil
}

func isCanonicalNonEmpty(value string) bool {
	return value != "" && value == strings.TrimSpace(value)
}

func scanFinishTime(scan corpus.ScanSession, requested time.Time) time.Time {
	requested = requested.UTC()
	if requested.Before(scan.StartedAt) {
		return scan.StartedAt.UTC()
	}
	return requested
}

// GoogleDriveManagedRootScanRoot creates a provider-specific, identity-domain-
// disambiguated corpus-root locator key. The identity domain is hashed because
// it may itself contain account-identifying text; the key is locator scope,
// never Artifact identity.
func GoogleDriveManagedRootScanRoot(identityDomain string, managedRootObjectID corpus.ProviderObjectID) (string, error) {
	if strings.TrimSpace(identityDomain) == "" || managedRootObjectID == "" {
		return "", ErrInvalidRemoteScopeProjection
	}
	domainDigest := sha256.Sum256([]byte(identityDomain))
	objectSegment := base64.RawURLEncoding.EncodeToString([]byte(managedRootObjectID))
	return googleManagedRootScanRootVersion + ":" + hex.EncodeToString(domainDigest[:]) + ":" + objectSegment, nil
}

type GoogleDriveManagedRootMembershipStore interface {
	GoogleDriveManagedRootMembership(
		context.Context,
		remotehistory.HistoryGenerationID,
		remotehistory.HistoryPublicationSequence,
		corpus.ProviderObjectID,
		corpus.ProviderObjectID,
	) (gdrive.MembershipResult, error)
}

// GoogleDriveManagedRootProjection is the minimal Google-specific P0-30B
// adapter. It reuses the qualified durable membership authority and projects a
// scan-scoped file-id locator without performing live Drive reads.
type GoogleDriveManagedRootProjection struct {
	store               GoogleDriveManagedRootMembershipStore
	managedRootObjectID corpus.ProviderObjectID
}

func NewGoogleDriveManagedRootProjection(
	store GoogleDriveManagedRootMembershipStore,
	managedRootObjectID corpus.ProviderObjectID,
) (*GoogleDriveManagedRootProjection, error) {
	if store == nil || managedRootObjectID == "" {
		return nil, ErrInvalidRemoteScopeProjection
	}
	return &GoogleDriveManagedRootProjection{store: store, managedRootObjectID: managedRootObjectID}, nil
}

func (p *GoogleDriveManagedRootProjection) Membership(
	ctx context.Context,
	scope RemoteMaterializationScope,
	objectID corpus.ProviderObjectID,
) (RemoteScopeMembership, error) {
	if err := p.validateScope(scope); err != nil {
		return RemoteScopeMembership{}, err
	}
	if objectID == "" {
		return RemoteScopeMembership{}, ErrInvalidRemoteScopeProjection
	}
	result, err := p.store.GoogleDriveManagedRootMembership(
		ctx,
		scope.Generation.ID,
		scope.PublicationSequence,
		p.managedRootObjectID,
		objectID,
	)
	if err != nil {
		return RemoteScopeMembership{}, err
	}
	switch result.State {
	case gdrive.MembershipIn:
		return RemoteScopeMembership{State: RemoteScopeMembershipIn}, nil
	case gdrive.MembershipOut:
		return RemoteScopeMembership{State: RemoteScopeMembershipOut}, nil
	case gdrive.MembershipUnknown:
		return RemoteScopeMembership{State: RemoteScopeMembershipUnknown, Reason: string(result.Reason)}, nil
	default:
		return RemoteScopeMembership{}, ErrInvalidRemoteScopeProjection
	}
}

func (p *GoogleDriveManagedRootProjection) ProjectLocators(
	_ context.Context,
	scope RemoteMaterializationScope,
	objectID corpus.ProviderObjectID,
) ([]corpus.Locator, error) {
	if err := p.validateScope(scope); err != nil {
		return nil, err
	}
	if objectID == "" {
		return nil, ErrInvalidRemoteScopeProjection
	}
	return []corpus.Locator{{
		ProviderID: gdrive.ProviderID,
		Root:       scope.ScanRoot,
		Path:       "file-id/" + string(objectID),
	}}, nil
}

func (p *GoogleDriveManagedRootProjection) validateScope(scope RemoteMaterializationScope) error {
	if scope.Generation.Scope.ProviderID != gdrive.ProviderID ||
		scope.SourceScopeID != string(p.managedRootObjectID) ||
		scope.MaterializationPolicyID != LightweightAllMaterializationPolicyID {
		return ErrInvalidRemoteScopeProjection
	}
	expectedRoot, err := GoogleDriveManagedRootScanRoot(scope.Generation.Scope.IdentityDomain, p.managedRootObjectID)
	if err != nil {
		return err
	}
	if scope.ScanRoot != expectedRoot {
		return fmt.Errorf("%w: scan root %q != canonical %q", ErrInvalidRemoteScopeProjection, scope.ScanRoot, expectedRoot)
	}
	return nil
}
