package sqlitestate

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
)

func TestGenericPublishRejectsTopologyManagedGenerationWithoutMutation(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := googleTopologyTestScope()
	fp := remotehistory.ScopePolicyFingerprint("google-drive-history-universe:v1:test")

	generation, err := store.StartGoogleDriveRemoteHistoryGeneration(
		ctx, scope, fp, googleTopologyBootstrapBundle(scope), time.Now().UTC(),
	)
	if err != nil {
		t.Fatal(err)
	}
	assertGoogleTopologyWatermark(t, store, generation.ID, 1)

	cycle := remotehistory.ChangeCycle{
		StreamID:       scope.StreamID,
		Status:         remotehistory.CycleComplete,
		PreviousCursor: "cursor-1",
		NextCursor:     "cursor-2",
		Coverage:       corpus.ProviderHistoryContinuous,
		Changes: []remotehistory.RemoteChange{{
			Kind:     remotehistory.ChangeUpsert,
			ObjectID: "id-1",
			State:    googleTopologyObject(scope, "id-1"),
		}},
	}
	_, err = store.PublishRemoteHistoryCycle(
		ctx, generation.ID, scope, fp, 1, "cursor-1", cycle, time.Now().UTC(),
	)
	if !errors.Is(err, ErrTopologyManagedGenerationRequiresSidecar) {
		t.Fatalf("error=%v want ErrTopologyManagedGenerationRequiresSidecar", err)
	}

	got, err := store.RemoteHistoryGeneration(ctx, generation.ID)
	if err != nil {
		t.Fatal(err)
	}
	if got.CurrentSequence != 1 || got.CommittedCursor != "cursor-1" {
		t.Fatalf("generic publish changed generation: %#v", got)
	}
	assertGoogleTopologyWatermark(t, store, generation.ID, 1)
	if got := internalTableCount(t, store.Path(), "remote_history_publications"); got != 1 {
		t.Fatalf("remote_history_publications=%d want=1", got)
	}
}
