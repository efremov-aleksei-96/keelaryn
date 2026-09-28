package ingest_test

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/ingest"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory/gdrive"
	sqlitestate "github.com/efremov-aleksei-96/keelaryn/internal/state/sqlite"
)

func TestRemoteIdentityMaterializationHistoryAdvanceBeforeSameAcceptanceFailsClosed(t *testing.T) {
	ctx := context.Background()
	fixture := newGoogleRemoteFixture(t, "account-A", false)

	baselineSnapshot := fixture.snapshot(
		remoteMetadataEntry("managed", corpus.EntryOther, 0, 0, fixture.base),
		remoteMetadataEntry("child", corpus.EntryRegularFile, 7, 0, fixture.base.Add(time.Second)),
	)
	baselineScan, _, err := ingest.MaterializeRemoteMetadataWithIdentity(
		ctx,
		fixture.store,
		fixture.projection,
		baselineSnapshot,
		ingest.RemoteIdentityMaterializationOptions{},
		fixture.base.Add(time.Minute),
	)
	if err != nil {
		t.Fatal(err)
	}

	advanceGoogleRemoteFixture(t, fixture, "cursor-1", "cursor-2", fixture.base.Add(90*time.Second))

	snapshot := fixture.snapshot(
		remoteMetadataEntry("managed", corpus.EntryOther, 0, 0, fixture.base),
		remoteMetadataEntry("child", corpus.EntryRegularFile, 7, 0, fixture.base.Add(time.Second)),
	)
	snapshot.PublicationSequence = 2
	options := ingest.RemoteIdentityMaterializationOptions{
		ContentEvidence: []ingest.RemoteSourceContentEvidence{{
			GenerationID:        fixture.generation.ID,
			PublicationSequence: 2,
			ProviderObjectID:    "child",
			SourceRef:           "deterministic-test:child:publication-2",
			Evidence: corpus.ContentEvidence{
				Algorithm: corpus.ContentAlgorithmSHA256,
				Digest:    "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
				Size:      7,
			},
		}},
	}
	racingStore := &advanceRemoteHistoryBeforeSameStore{
		Store:            fixture.store,
		generationID:     fixture.generation.ID,
		scope:            fixture.scope,
		scopeFingerprint: fixture.scopeFingerprint,
		committedAt:      fixture.base.Add(150 * time.Second),
	}

	failedScan, _, err := ingest.MaterializeRemoteMetadataWithIdentity(
		ctx,
		racingStore,
		fixture.projection,
		snapshot,
		options,
		fixture.base.Add(2*time.Minute),
	)
	if !errors.Is(err, sqlitestate.ErrRemoteHistoryScanSourceAdvanced) {
		t.Fatalf("error=%v want ErrRemoteHistoryScanSourceAdvanced", err)
	}
	if !racingStore.advanced {
		t.Fatal("test did not advance RemoteHistory at the SAME mutation boundary")
	}
	stored, scanErr := fixture.store.ScanSession(ctx, failedScan.ID)
	if scanErr != nil {
		t.Fatal(scanErr)
	}
	if stored.Status != corpus.ScanAborted {
		t.Fatalf("failed source-bound identity scan status=%s want ABORTED", stored.Status)
	}

	inventory, invErr := fixture.store.Inventory(ctx, gdrive.ProviderID, fixture.scanRoot)
	if invErr != nil {
		t.Fatal(invErr)
	}
	if len(inventory) != 2 {
		t.Fatalf("inventory=%#v", inventory)
	}
	for _, item := range inventory {
		if item.ScanID != baselineScan.ID {
			t.Fatalf("stale identity attempt replaced prior COMPLETE inventory: %#v", item)
		}
	}
}

type advanceRemoteHistoryBeforeSameStore struct {
	*sqlitestate.Store
	generationID     remotehistory.HistoryGenerationID
	scope            remotehistory.Scope
	scopeFingerprint remotehistory.ScopePolicyFingerprint
	committedAt      time.Time
	advanced         bool
}

func (s *advanceRemoteHistoryBeforeSameStore) AcceptSameObservationInScan(
	ctx context.Context,
	request corpus.IdentityMutationRequest,
) (corpus.ContinuityAcceptance, error) {
	if !s.advanced {
		cycle := gdrive.ChangeCycleBundle{
			History: remotehistory.ChangeCycle{
				StreamID:       s.scope.StreamID,
				Status:         remotehistory.CycleComplete,
				PreviousCursor: "cursor-2",
				NextCursor:     "cursor-3",
				Coverage:       corpus.ProviderHistoryContinuous,
			},
		}
		if _, err := s.Store.PublishGoogleDriveRemoteHistoryCycle(
			ctx,
			s.generationID,
			s.scope,
			s.scopeFingerprint,
			2,
			"cursor-2",
			cycle,
			s.committedAt,
		); err != nil {
			return corpus.ContinuityAcceptance{}, err
		}
		s.advanced = true
	}
	return s.Store.AcceptSameObservationInScan(ctx, request)
}
