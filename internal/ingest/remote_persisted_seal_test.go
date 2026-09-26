package ingest_test

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/ingest"
	sqlitestate "github.com/efremov-aleksei-96/keelaryn/internal/state/sqlite"
)

func TestRemoteMetadataCompletionSealsPersistedScanContent(t *testing.T) {
	ctx := context.Background()
	fixture := newGoogleRemoteFixture(t, "account-A", false)
	snapshot := fixture.snapshot(
		remoteMetadataEntry("managed", corpus.EntryOther, 0, 0, fixture.base),
		remoteMetadataEntry("child", corpus.EntryRegularFile, 7, 0, fixture.base.Add(time.Second)),
	)
	injecting := &injectExtraObservationBeforeRemoteCompleteStore{
		Store:    fixture.store,
		scanRoot: fixture.scanRoot,
		at:       fixture.base.Add(30 * time.Second),
	}

	scan, _, err := ingest.MaterializeRemoteMetadata(
		ctx,
		injecting,
		fixture.projection,
		snapshot,
		fixture.base.Add(time.Minute),
	)
	if !errors.Is(err, sqlitestate.ErrRemoteHistoryScanSnapshotMismatch) {
		t.Fatalf("error=%v want ErrRemoteHistoryScanSnapshotMismatch", err)
	}
	stored, scanErr := fixture.store.ScanSession(ctx, scan.ID)
	if scanErr != nil {
		t.Fatal(scanErr)
	}
	if stored.Status != corpus.ScanAborted {
		t.Fatalf("mismatched persisted scan status=%s want ABORTED", stored.Status)
	}
	inventory, invErr := fixture.store.Inventory(ctx, "google-drive", fixture.scanRoot)
	if invErr != nil {
		t.Fatal(invErr)
	}
	if len(inventory) != 0 {
		t.Fatalf("mismatched persisted scan became inventory authority: %#v", inventory)
	}
}

type injectExtraObservationBeforeRemoteCompleteStore struct {
	*sqlitestate.Store
	scanRoot string
	at       time.Time
	injected bool
}

func (s *injectExtraObservationBeforeRemoteCompleteStore) CompleteRemoteHistoryScan(
	ctx context.Context,
	scanID corpus.ScanSessionID,
	finishedAt time.Time,
) (corpus.ScanSession, bool, error) {
	if !s.injected {
		s.injected = true
		if _, err := s.Store.RecordObservationInScan(ctx, scanID, corpus.ObservationRecordInput{
			ProviderObject: corpus.ProviderObject{
				ProviderID:    "google-drive",
				ID:            "injected-extra",
				IdentityState: corpus.ObjectIdentityObserved,
			},
			Locators: []corpus.Locator{{
				ProviderID: "google-drive",
				Root:       s.scanRoot,
				Path:       "file-id/injected-extra",
			}},
			AssignmentState: corpus.AssignmentUnresolved,
			ObservedAt:      s.at,
			Kind:            corpus.EntryRegularFile,
			Size:            1,
			Mode:            0,
			ModifiedAt:      s.at,
		}); err != nil {
			return corpus.ScanSession{}, false, err
		}
	}
	return s.Store.CompleteRemoteHistoryScan(ctx, scanID, finishedAt)
}
