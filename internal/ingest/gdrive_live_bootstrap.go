package ingest

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory/gdrive"
)

var (
	ErrGoogleDriveLiveBootstrapPrestateChanged = errors.New("Google Drive live bootstrap provider prestate changed")
	ErrGoogleDriveLiveBootstrapSequence        = errors.New("Google Drive live bootstrap requires publication sequence 1")
)

type GoogleDriveLiveBootstrapStore interface {
	gdrive.TopologyHistoryStore
	RemoteIdentityMaterializationStore
	GoogleDriveManagedRootMembershipStore
	BindGoogleDriveManagedRoot(context.Context, remotehistory.HistoryGenerationID, corpus.ProviderObjectID, time.Time) (gdrive.ManagedRootBinding, error)
}

type GoogleDriveLiveBootstrapResult struct {
	Coordinator   remotehistory.CoordinatorResult
	Generation    remotehistory.HistoryGeneration
	Binding       gdrive.ManagedRootBinding
	Scan          corpus.ScanSession
	ScanReplayed  bool
	MetadataCount int
}

// BootstrapGoogleDriveLiveMetadata composes the already-qualified Drive
// RemoteHistory bootstrap, managed-root projection and generic Observation /
// identity materializer. Provider access is read-only. Metadata is never a
// second durable inventory.
func BootstrapGoogleDriveLiveMetadata(
	ctx context.Context,
	store GoogleDriveLiveBootstrapStore,
	adapter *gdrive.Adapter,
	scope remotehistory.Scope,
	fingerprint remotehistory.ScopePolicyFingerprint,
	managedRootObjectID corpus.ProviderObjectID,
	at time.Time,
) (GoogleDriveLiveBootstrapResult, error) {
	if store == nil || adapter == nil || managedRootObjectID == "" || at.IsZero() {
		return GoogleDriveLiveBootstrapResult{}, ErrInvalidRemoteMetadataSnapshot
	}
	coordinator, err := gdrive.NewTopologyCoordinator(store, adapter, scope, fingerprint)
	if err != nil {
		return GoogleDriveLiveBootstrapResult{}, err
	}
	bootstrap, err := coordinator.BootstrapWithMetadata(ctx, at.UTC())
	if err != nil {
		return GoogleDriveLiveBootstrapResult{Coordinator: bootstrap.Coordinator}, err
	}
	result := GoogleDriveLiveBootstrapResult{Coordinator: bootstrap.Coordinator, Generation: bootstrap.Coordinator.Generation}

	var metadata []gdrive.MetadataRecord
	switch bootstrap.Coordinator.Status {
	case remotehistory.CoordinatorBootstrapCommitted:
		metadata = bootstrap.Bootstrap.Metadata
	case remotehistory.CoordinatorAlreadyActive:
		generation := bootstrap.Coordinator.Generation
		if generation.Status != remotehistory.HistoryGenerationActive || generation.CurrentSequence != 1 {
			return result, fmt.Errorf("%w: generation=%s sequence=%d status=%s",
				ErrGoogleDriveLiveBootstrapSequence, generation.ID, generation.CurrentSequence, generation.Status)
		}
		candidate, err := adapter.BootstrapWithMetadata(ctx, scope)
		if err != nil {
			return result, err
		}
		if err := validateLiveBootstrapReplay(ctx, store, generation, candidate); err != nil {
			return result, err
		}
		metadata = candidate.Metadata
	default:
		return result, fmt.Errorf("%w: coordinator status=%s bootstrap=%s",
			ErrRemoteSourceNotCurrent, bootstrap.Coordinator.Status, bootstrap.Coordinator.BootstrapStatus)
	}

	binding, err := store.BindGoogleDriveManagedRoot(ctx, result.Generation.ID, managedRootObjectID, at.UTC())
	if err != nil {
		return result, err
	}
	result.Binding = binding
	projection, err := NewGoogleDriveManagedRootProjection(store, managedRootObjectID)
	if err != nil {
		return result, err
	}
	scanRoot, err := GoogleDriveManagedRootScanRoot(scope.IdentityDomain, managedRootObjectID)
	if err != nil {
		return result, err
	}
	entries, err := liveMetadataEntriesInScope(ctx, projection, result.Generation, scanRoot, managedRootObjectID, metadata)
	if err != nil {
		return result, err
	}
	result.MetadataCount = len(entries)
	snapshot := RemoteMetadataSnapshot{
		GenerationID:            result.Generation.ID,
		PublicationSequence:     result.Generation.CurrentSequence,
		ScanRoot:                scanRoot,
		SourceScopeID:           string(managedRootObjectID),
		MaterializationPolicyID: LightweightAllMaterializationPolicyIDV2,
		Entries:                 entries,
	}
	scan, replayed, err := MaterializeRemoteMetadataWithIdentity(
		ctx, store, projection, snapshot, RemoteIdentityMaterializationOptions{}, at.UTC(),
	)
	result.Scan, result.ScanReplayed = scan, replayed
	return result, err
}

func validateLiveBootstrapReplay(
	ctx context.Context,
	store GoogleDriveLiveBootstrapStore,
	generation remotehistory.HistoryGeneration,
	candidate gdrive.BootstrapMetadataBundle,
) error {
	if candidate.Bundle.History.Status != remotehistory.BootstrapComplete ||
		candidate.Bundle.History.Cursor != generation.CommittedCursor {
		return fmt.Errorf("%w: durable=%s candidate=%s",
			ErrGoogleDriveLiveBootstrapPrestateChanged, generation.CommittedCursor, candidate.Bundle.History.Cursor)
	}
	memberships, err := store.RemoteHistoryMembership(ctx, generation.ID)
	if err != nil {
		return err
	}
	if len(memberships) != len(candidate.Bundle.History.Objects) {
		return fmt.Errorf("%w: durable objects=%d candidate=%d",
			ErrGoogleDriveLiveBootstrapPrestateChanged, len(memberships), len(candidate.Bundle.History.Objects))
	}
	current := make(map[corpus.ProviderObjectID]remotehistory.RemoteObjectState, len(memberships))
	for _, membership := range memberships {
		if membership.LastPublicationSequence > generation.CurrentSequence {
			return ErrGoogleDriveLiveBootstrapPrestateChanged
		}
		current[membership.Object.ObjectID] = membership.Object
	}
	for _, object := range candidate.Bundle.History.Objects {
		durable, ok := current[object.ObjectID]
		if !ok || !sameRemoteObjectState(durable, object) {
			return fmt.Errorf("%w: object=%s", ErrGoogleDriveLiveBootstrapPrestateChanged, object.ObjectID)
		}
	}
	return nil
}

func sameRemoteObjectState(a, b remotehistory.RemoteObjectState) bool {
	if a.ObjectID != b.ObjectID || len(a.Locators) != len(b.Locators) {
		return false
	}
	left := append([]corpus.Locator(nil), a.Locators...)
	right := append([]corpus.Locator(nil), b.Locators...)
	sort.Slice(left, func(i, j int) bool {
		if left[i].ProviderID != left[j].ProviderID {
			return left[i].ProviderID < left[j].ProviderID
		}
		if left[i].Root != left[j].Root {
			return left[i].Root < left[j].Root
		}
		return left[i].Path < left[j].Path
	})
	sort.Slice(right, func(i, j int) bool {
		if right[i].ProviderID != right[j].ProviderID {
			return right[i].ProviderID < right[j].ProviderID
		}
		if right[i].Root != right[j].Root {
			return right[i].Root < right[j].Root
		}
		return right[i].Path < right[j].Path
	})
	for i := range left {
		if left[i] != right[i] {
			return false
		}
	}
	return true
}

func liveMetadataEntriesInScope(
	ctx context.Context,
	projection RemoteScopeProjection,
	generation remotehistory.HistoryGeneration,
	scanRoot string,
	managedRootObjectID corpus.ProviderObjectID,
	metadata []gdrive.MetadataRecord,
) ([]RemoteMetadataEntry, error) {
	scope := RemoteMaterializationScope{
		Generation: generation, PublicationSequence: generation.CurrentSequence,
		ScanRoot: scanRoot, SourceScopeID: string(managedRootObjectID),
		MaterializationPolicyID: LightweightAllMaterializationPolicyIDV2,
	}
	entries := make([]RemoteMetadataEntry, 0, len(metadata))
	for _, record := range metadata {
		membership, err := projection.Membership(ctx, scope, record.ObjectID)
		if err != nil {
			return nil, err
		}
		switch membership.State {
		case RemoteScopeMembershipIn:
			entries = append(entries, RemoteMetadataEntry{
				ProviderObjectID: record.ObjectID,
				Kind:             record.Kind,
				Size:             cloneInt64(record.Size),
				ModifiedAt:       cloneTimeUTC(record.ModifiedAt),
			})
		case RemoteScopeMembershipOut:
		case RemoteScopeMembershipUnknown:
			return nil, fmt.Errorf("%w: object=%s reason=%s", ErrRemoteMembershipUnknown, record.ObjectID, membership.Reason)
		default:
			return nil, ErrInvalidRemoteScopeProjection
		}
	}
	sort.Slice(entries, func(i, j int) bool { return entries[i].ProviderObjectID < entries[j].ProviderObjectID })
	return entries, nil
}
