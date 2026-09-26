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
)

func TestRemoteMetadataMaterializationRejectsCrossObjectLocatorCollision(t *testing.T) {
	ctx := context.Background()
	fixture := newGoogleRemoteFixture(t, "account-A", false)
	projection := collidingRemoteProjection{base: fixture.projection}
	snapshot := fixture.snapshot(
		remoteMetadataEntry("managed", corpus.EntryOther, 0, 0, fixture.base),
		remoteMetadataEntry("child", corpus.EntryRegularFile, 7, 0, fixture.base.Add(time.Second)),
	)

	_, _, err := ingest.MaterializeRemoteMetadata(
		ctx,
		fixture.store,
		projection,
		snapshot,
		fixture.base.Add(time.Minute),
	)
	if !errors.Is(err, ingest.ErrRemoteLocatorCollision) {
		t.Fatalf("error=%v want ErrRemoteLocatorCollision", err)
	}

	inventory, invErr := fixture.store.Inventory(ctx, gdrive.ProviderID, fixture.scanRoot)
	if invErr != nil {
		t.Fatal(invErr)
	}
	if len(inventory) != 0 {
		t.Fatalf("locator collision published inventory: %#v", inventory)
	}
}

type collidingRemoteProjection struct {
	base ingest.RemoteScopeProjection
}

func (p collidingRemoteProjection) Membership(
	ctx context.Context,
	scope ingest.RemoteMaterializationScope,
	objectID corpus.ProviderObjectID,
) (ingest.RemoteScopeMembership, error) {
	return p.base.Membership(ctx, scope, objectID)
}

func (p collidingRemoteProjection) ProjectLocators(
	_ context.Context,
	scope ingest.RemoteMaterializationScope,
	_ corpus.ProviderObjectID,
) ([]corpus.Locator, error) {
	return []corpus.Locator{{
		ProviderID: scope.Generation.Scope.ProviderID,
		Root:       scope.ScanRoot,
		Path:       "collision",
	}}, nil
}

var _ ingest.RemoteScopeProjection = collidingRemoteProjection{}
var _ = remotehistory.HistoryGeneration{}
