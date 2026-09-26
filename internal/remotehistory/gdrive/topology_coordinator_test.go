package gdrive_test

import (
	"context"
	"errors"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory/gdrive"
	sqlitestate "github.com/efremov-aleksei-96/keelaryn/internal/state/sqlite"
)

func TestTopologyCoordinatorBootstrapsAdvancesAndBlocksGenericAdvance(t *testing.T) {
	ctx := context.Background()
	config := myDriveConfig()
	scope := config.Scope()
	client := &fakeClient{
		startToken: "fence",
		filePages: []gdrive.FilePage{{Files: []gdrive.FileRecord{
			{ID: "a", Parents: []string{config.Root}},
		}}},
		changePages: map[string]changeResult{
			"fence": {page: gdrive.ChangePage{NewStartPageToken: "cursor-1"}},
			"cursor-1": {page: gdrive.ChangePage{
				Changes: []gdrive.ChangeRecord{{
					FileID: "a",
					File:   &gdrive.FileRecord{ID: "a", Parents: []string{"folder-new"}},
				}},
				NewStartPageToken: "cursor-2",
			}},
		},
	}
	adapter := mustAdapter(t, client, config)
	fingerprint, err := gdrive.ScopePolicyFingerprint(config)
	if err != nil {
		t.Fatal(err)
	}
	store, err := sqlitestate.Open(ctx, filepath.Join(t.TempDir(), "state.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	coordinator, err := gdrive.NewTopologyCoordinator(store, adapter, scope, fingerprint)
	if err != nil {
		t.Fatal(err)
	}
	base := time.Date(2026, 9, 26, 22, 0, 0, 0, time.UTC)
	boot, err := coordinator.Bootstrap(ctx, base)
	if err != nil {
		t.Fatal(err)
	}
	if boot.Status != remotehistory.CoordinatorBootstrapCommitted ||
		boot.Generation.CurrentSequence != 1 ||
		boot.Generation.CommittedCursor != "cursor-1" {
		t.Fatalf("bootstrap=%#v", boot)
	}

	callsBeforeStale := client.calls
	stale, err := coordinator.Advance(ctx, remotehistory.ExpectedHistoryPrestate{
		GenerationID: boot.Generation.ID,
		Sequence:     99,
		Cursor:       "cursor-1",
	}, base.Add(time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	if stale.Status != remotehistory.CoordinatorPrestateChanged {
		t.Fatalf("stale=%#v", stale)
	}
	if client.calls != callsBeforeStale {
		t.Fatalf("stale prestate called provider: before=%d after=%d", callsBeforeStale, client.calls)
	}

	published, err := coordinator.Advance(ctx, remotehistory.ExpectedHistoryPrestate{
		GenerationID: boot.Generation.ID,
		Sequence:     1,
		Cursor:       "cursor-1",
	}, base.Add(2*time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	if published.Status != remotehistory.CoordinatorPublished ||
		published.Generation.CurrentSequence != 2 ||
		published.Generation.CommittedCursor != "cursor-2" {
		t.Fatalf("published=%#v", published)
	}

	genericCycle := remotehistory.ChangeCycle{
		StreamID:       scope.StreamID,
		Status:         remotehistory.CycleComplete,
		PreviousCursor: "cursor-2",
		NextCursor:     "cursor-3",
		Coverage:       corpus.ProviderHistoryContinuous,
		Changes: []remotehistory.RemoteChange{{
			Kind:     remotehistory.ChangeUpsert,
			ObjectID: "a",
			State: &remotehistory.RemoteObjectState{
				ObjectID: "a",
				Locators: []corpus.Locator{{
					ProviderID: scope.ProviderID,
					Root:       scope.Root,
					Path:       "file-id/a",
				}},
			},
		}},
	}
	_, err = store.PublishRemoteHistoryCycle(
		ctx,
		boot.Generation.ID,
		scope,
		fingerprint,
		2,
		"cursor-2",
		genericCycle,
		base.Add(3*time.Minute),
	)
	if !errors.Is(err, sqlitestate.ErrTopologyManagedGenerationRequiresSidecar) {
		t.Fatalf("generic publish error=%v", err)
	}

	current, err := store.RemoteHistoryGeneration(ctx, boot.Generation.ID)
	if err != nil {
		t.Fatal(err)
	}
	if current.CurrentSequence != 2 || current.CommittedCursor != "cursor-2" {
		t.Fatalf("generic guard failed to preserve prestate: %#v", current)
	}
}

func TestTopologyCoordinatorClosesOnExplicitHistoryGap(t *testing.T) {
	ctx := context.Background()
	config := myDriveConfig()
	scope := config.Scope()
	client := &fakeClient{
		startToken: "fence",
		filePages: []gdrive.FilePage{{Files: []gdrive.FileRecord{
			{ID: "a", Parents: []string{config.Root}},
		}}},
		changePages: map[string]changeResult{
			"fence":    {page: gdrive.ChangePage{NewStartPageToken: "cursor-1"}},
			"cursor-1": {err: gdrive.ErrClientHistoryGap},
		},
	}
	adapter := mustAdapter(t, client, config)
	fingerprint, err := gdrive.ScopePolicyFingerprint(config)
	if err != nil {
		t.Fatal(err)
	}
	store, err := sqlitestate.Open(ctx, filepath.Join(t.TempDir(), "state.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	coordinator, err := gdrive.NewTopologyCoordinator(store, adapter, scope, fingerprint)
	if err != nil {
		t.Fatal(err)
	}
	base := time.Date(2026, 9, 26, 23, 0, 0, 0, time.UTC)
	boot, err := coordinator.Bootstrap(ctx, base)
	if err != nil {
		t.Fatal(err)
	}
	closed, err := coordinator.Advance(ctx, remotehistory.ExpectedHistoryPrestate{
		GenerationID: boot.Generation.ID,
		Sequence:     1,
		Cursor:       "cursor-1",
	}, base.Add(time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	if closed.Status != remotehistory.CoordinatorClosed ||
		closed.CycleStatus != remotehistory.CycleGap ||
		closed.Generation.Status != remotehistory.HistoryGenerationClosed ||
		closed.Generation.CurrentSequence != 1 ||
		closed.Generation.CommittedCursor != "cursor-1" {
		t.Fatalf("closed=%#v", closed)
	}
}
