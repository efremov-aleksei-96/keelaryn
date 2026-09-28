package ingest

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
)

const remoteIdentityMutationRequestIDVersion = "remote-identity-mutation-request:v1"

var (
	ErrInvalidRemoteContentEvidence      = errors.New("invalid remote source-bound content evidence")
	ErrRemoteIdentitySegmentUnavailable  = errors.New("remote identity lifetime segment unavailable")
	ErrRemoteIdentitySegmentAmbiguous    = errors.New("multiple active remote identity lifetime segments")
)

type RemoteSourceContentEvidence struct {
	GenerationID        remotehistory.HistoryGenerationID
	PublicationSequence remotehistory.HistoryPublicationSequence
	ProviderObjectID    corpus.ProviderObjectID
	SourceRef           string
	Evidence            corpus.ContentEvidence
}

type RemoteIdentityMaterializationOptions struct {
	ContentEvidence []RemoteSourceContentEvidence
}

// RemoteIdentityMaterializationStore extends the already-qualified P0-30B
// materialization surface only with existing identity/revision primitives.
// It intentionally adds no second inventory, Artifact model or identity resolver.
type RemoteIdentityMaterializationStore interface {
	RemoteMaterializationStore
	RemoteHistoryLifetimeSegments(context.Context, remotehistory.HistoryGenerationID) ([]remotehistory.ProviderObjectLifetimeSegment, error)
	CreateRemoteHistoryIdentityAuthority(context.Context, remotehistory.HistoryGenerationID, remotehistory.ProviderObjectLifetimeSegmentID, time.Time) (corpus.IdentityAuthoritySet, error)
	AcceptNewObservationInScan(context.Context, corpus.IdentityMutationRequest) (corpus.ArtifactAdmissionAcceptance, error)
	AcceptSameObservationInScan(context.Context, corpus.IdentityMutationRequest) (corpus.ContinuityAcceptance, error)
}

// MaterializeRemoteMetadataWithIdentity integrates the deterministic P0-30B
// metadata materializer with the existing Artifact/Revision acceptance boundary.
//
// Exactly one Observation is persisted per object in a scan attempt:
//   - RESOLVED_NEW -> existing NEW acceptance transaction;
//   - RESOLVED_SAME -> existing SAME acceptance when content rules permit;
//   - regular SAME without exact source-bound ContentEvidence -> unresolved;
//   - AMBIGUOUS / UNRESOLVED -> unresolved.
//
// Identity decisions remain guarded by the source-bound SQLite transaction,
// including generation/publication, managed-root scope and locator validation.
func MaterializeRemoteMetadataWithIdentity(
	ctx context.Context,
	store RemoteIdentityMaterializationStore,
	projection RemoteScopeProjection,
	snapshot RemoteMetadataSnapshot,
	options RemoteIdentityMaterializationOptions,
	observedAt time.Time,
) (corpus.ScanSession, bool, error) {
	if store == nil {
		return corpus.ScanSession{}, false, ErrInvalidRemoteMetadataSnapshot
	}
	evidence, err := validateRemoteSourceContentEvidence(snapshot, options)
	if err != nil {
		return corpus.ScanSession{}, false, err
	}
	writer := &remoteIdentityObservationWriter{
		store:    store,
		evidence: evidence,
	}
	return materializeRemoteMetadata(ctx, store, projection, snapshot, observedAt, writer.write)
}

type remoteIdentityObservationWriter struct {
	store    RemoteIdentityMaterializationStore
	evidence map[corpus.ProviderObjectID]corpus.ContentEvidence
	segments map[corpus.ProviderObjectID]remotehistory.ProviderObjectLifetimeSegment
}

func (w *remoteIdentityObservationWriter) write(
	ctx context.Context,
	scan corpus.ScanSession,
	prepared preparedRemoteMetadataSnapshot,
	entry canonicalRemoteMetadataEntry,
) error {
	input, err := remoteObservationInput(scan, prepared, entry)
	if err != nil {
		return err
	}
	if w.segments == nil {
		w.segments, err = activeRemoteIdentitySegments(ctx, w.store, prepared.snapshot.GenerationID)
		if err != nil {
			return err
		}
	}
	segment, ok := w.segments[entry.ProviderObjectID]
	if !ok {
		return fmt.Errorf("%w: object=%s generation=%s",
			ErrRemoteIdentitySegmentUnavailable, entry.ProviderObjectID, prepared.snapshot.GenerationID)
	}

	authority, err := w.store.CreateRemoteHistoryIdentityAuthority(
		ctx,
		prepared.snapshot.GenerationID,
		segment.ID,
		scan.StartedAt.UTC(),
	)
	if err != nil {
		return fmt.Errorf("create remote identity authority for %s: %w", entry.ProviderObjectID, err)
	}
	resolution, err := corpus.ResolveIdentityAuthoritySet(authority)
	if err != nil {
		return fmt.Errorf("resolve remote identity authority for %s: %w", entry.ProviderObjectID, err)
	}

	content, hasContent := w.evidence[entry.ProviderObjectID]
	request := corpus.IdentityMutationRequest{
		ScanID:         scan.ID,
		Observation:    input,
		AuthoritySetID: authority.ID,
		DecidedAt:      scan.StartedAt.UTC(),
	}
	switch resolution.State {
	case corpus.OccurrenceIdentityResolvedNew:
		request.ID = remoteIdentityMutationRequestID(scan, prepared, entry.ProviderObjectID, corpus.IdentityMutationNew)
		if hasContent {
			value := content
			request.ContentEvidence = &value
		}
		if _, err := w.store.AcceptNewObservationInScan(ctx, request); err != nil {
			return fmt.Errorf("accept remote NEW observation %s: %w", entry.ProviderObjectID, err)
		}
		return nil

	case corpus.OccurrenceIdentityResolvedSame:
		if entry.Kind == corpus.EntryRegularFile && !hasContent {
			if _, err := w.store.RecordObservationInScan(ctx, scan.ID, input); err != nil {
				return fmt.Errorf("persist deferred remote SAME observation %s: %w", entry.ProviderObjectID, err)
			}
			return nil
		}
		request.ID = remoteIdentityMutationRequestID(scan, prepared, entry.ProviderObjectID, corpus.IdentityMutationSame)
		if hasContent {
			value := content
			request.ContentEvidence = &value
		}
		if _, err := w.store.AcceptSameObservationInScan(ctx, request); err != nil {
			return fmt.Errorf("accept remote SAME observation %s: %w", entry.ProviderObjectID, err)
		}
		return nil

	case corpus.OccurrenceIdentityAmbiguous, corpus.OccurrenceIdentityUnresolved:
		if _, err := w.store.RecordObservationInScan(ctx, scan.ID, input); err != nil {
			return fmt.Errorf("persist unresolved remote identity observation %s: %w", entry.ProviderObjectID, err)
		}
		return nil

	default:
		return fmt.Errorf("%w: object=%s resolution=%s",
			corpus.ErrInvalidOccurrenceIdentityResolution, entry.ProviderObjectID, resolution.State)
	}
}

func activeRemoteIdentitySegments(
	ctx context.Context,
	store RemoteIdentityMaterializationStore,
	generationID remotehistory.HistoryGenerationID,
) (map[corpus.ProviderObjectID]remotehistory.ProviderObjectLifetimeSegment, error) {
	segments, err := store.RemoteHistoryLifetimeSegments(ctx, generationID)
	if err != nil {
		return nil, err
	}
	active := make(map[corpus.ProviderObjectID]remotehistory.ProviderObjectLifetimeSegment)
	for _, segment := range segments {
		if segment.Status != remotehistory.LifetimeSegmentActive {
			continue
		}
		if _, exists := active[segment.ProviderObjectID]; exists {
			return nil, fmt.Errorf("%w: generation=%s object=%s",
				ErrRemoteIdentitySegmentAmbiguous, generationID, segment.ProviderObjectID)
		}
		active[segment.ProviderObjectID] = segment
	}
	return active, nil
}

func validateRemoteSourceContentEvidence(
	snapshot RemoteMetadataSnapshot,
	options RemoteIdentityMaterializationOptions,
) (map[corpus.ProviderObjectID]corpus.ContentEvidence, error) {
	entryByObject := make(map[corpus.ProviderObjectID]RemoteMetadataEntry, len(snapshot.Entries))
	for _, entry := range snapshot.Entries {
		entryByObject[entry.ProviderObjectID] = entry
	}
	out := make(map[corpus.ProviderObjectID]corpus.ContentEvidence, len(options.ContentEvidence))
	for _, item := range options.ContentEvidence {
		if item.GenerationID != snapshot.GenerationID ||
			item.PublicationSequence != snapshot.PublicationSequence ||
			item.ProviderObjectID == "" ||
			!isCanonicalNonEmpty(item.SourceRef) {
			return nil, ErrInvalidRemoteContentEvidence
		}
		entry, ok := entryByObject[item.ProviderObjectID]
		if !ok || entry.Kind != corpus.EntryRegularFile || entry.Size == nil {
			return nil, fmt.Errorf("%w: object=%s is not a regular snapshot entry",
				ErrInvalidRemoteContentEvidence, item.ProviderObjectID)
		}
		if _, duplicate := out[item.ProviderObjectID]; duplicate {
			return nil, fmt.Errorf("%w: duplicate object=%s", ErrInvalidRemoteContentEvidence, item.ProviderObjectID)
		}
		if err := corpus.ValidateContentEvidence(item.Evidence); err != nil || item.Evidence.Size != *entry.Size {
			return nil, fmt.Errorf("%w: object=%s", ErrInvalidRemoteContentEvidence, item.ProviderObjectID)
		}
		out[item.ProviderObjectID] = item.Evidence
	}
	return out, nil
}

func remoteIdentityMutationRequestID(
	scan corpus.ScanSession,
	prepared preparedRemoteMetadataSnapshot,
	objectID corpus.ProviderObjectID,
	kind corpus.IdentityMutationKind,
) corpus.IdentityMutationRequestID {
	payload := strings.Join([]string{
		remoteIdentityMutationRequestIDVersion,
		string(scan.ID),
		string(prepared.snapshot.GenerationID),
		strconv.FormatUint(uint64(prepared.snapshot.PublicationSequence), 10),
		prepared.snapshot.SourceScopeID,
		prepared.fingerprint,
		string(objectID),
		string(kind),
	}, "\x00")
	sum := sha256.Sum256([]byte(payload))
	return corpus.IdentityMutationRequestID("rim_" + hex.EncodeToString(sum[:]))
}
