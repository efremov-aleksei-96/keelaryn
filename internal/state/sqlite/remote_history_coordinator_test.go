package sqlitestate

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
)

func TestRemoteHistoryCoordinatorBootstrapIsReconciledBeforeProviderRead(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("test-policy:v1")
	adapter := &scriptedCoordinatorAdapter{
		bootstrap: remoteHistoryBootstrap(scope, "cursor-1"),
	}
	coordinator, err := remotehistory.NewCoordinator(store, adapter, scope, fp)
	if err != nil {
		t.Fatal(err)
	}
	at := time.Date(2026, 9, 26, 14, 0, 0, 0, time.UTC)

	first, err := coordinator.Bootstrap(ctx, at)
	if err != nil {
		t.Fatal(err)
	}
	if first.Status != remotehistory.CoordinatorBootstrapCommitted ||
		first.Generation.CurrentSequence != 1 ||
		first.Generation.CommittedCursor != "cursor-1" {
		t.Fatalf("first=%#v", first)
	}
	second, err := coordinator.Bootstrap(ctx, at.Add(time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	if second.Status != remotehistory.CoordinatorAlreadyActive ||
		second.Generation.ID != first.Generation.ID {
		t.Fatalf("second=%#v", second)
	}
	if adapter.bootstrapCalls != 1 {
		t.Fatalf("bootstrap provider calls=%d want=1", adapter.bootstrapCalls)
	}
}

func TestRemoteHistoryCoordinatorPublishesOnceAndStaleExpectedPrestateSkipsProvider(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("test-policy:v1")
	adapter := &scriptedCoordinatorAdapter{
		bootstrap: remoteHistoryBootstrap(scope, "cursor-1"),
	}
	coordinator, err := remotehistory.NewCoordinator(store, adapter, scope, fp)
	if err != nil {
		t.Fatal(err)
	}
	base := time.Date(2026, 9, 26, 14, 30, 0, 0, time.UTC)
	boot, err := coordinator.Bootstrap(ctx, base)
	if err != nil {
		t.Fatal(err)
	}

	adapter.steps = []coordinatorPageStep{{page: remotehistory.ChangePage{
		StreamID: scope.StreamID,
		Status:   remotehistory.PageTerminal,
		Changes: []remotehistory.RemoteChange{
			historyUpsert(scope, "id-1", "renamed.txt"),
		},
		NextCursor: "cursor-2",
	}}}
	expected := remotehistory.ExpectedHistoryPrestate{
		GenerationID: boot.Generation.ID,
		Sequence:     boot.Generation.CurrentSequence,
		Cursor:       boot.Generation.CommittedCursor,
	}
	published, err := coordinator.Advance(ctx, expected, base.Add(time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	if published.Status != remotehistory.CoordinatorPublished ||
		published.Generation.CurrentSequence != 2 ||
		published.Generation.CommittedCursor != "cursor-2" {
		t.Fatalf("published=%#v", published)
	}
	if adapter.readCalls != 1 {
		t.Fatalf("read calls=%d want=1", adapter.readCalls)
	}

	stale, err := coordinator.Advance(ctx, expected, base.Add(2*time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	if stale.Status != remotehistory.CoordinatorPrestateChanged ||
		stale.Generation.CurrentSequence != 2 ||
		stale.Generation.CommittedCursor != "cursor-2" {
		t.Fatalf("stale=%#v", stale)
	}
	if adapter.readCalls != 1 {
		t.Fatalf("stale expected prestate called provider: reads=%d", adapter.readCalls)
	}
}

func TestRemoteHistoryCoordinatorTransportErrorMutatesNothing(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("test-policy:v1")
	adapter := &scriptedCoordinatorAdapter{
		bootstrap: remoteHistoryBootstrap(scope, "cursor-1"),
	}
	coordinator, err := remotehistory.NewCoordinator(store, adapter, scope, fp)
	if err != nil {
		t.Fatal(err)
	}
	base := time.Date(2026, 9, 26, 15, 0, 0, 0, time.UTC)
	boot, err := coordinator.Bootstrap(ctx, base)
	if err != nil {
		t.Fatal(err)
	}
	transportErr := errors.New("synthetic transport interruption")
	adapter.steps = []coordinatorPageStep{{err: transportErr}}

	expected := remotehistory.ExpectedHistoryPrestate{
		GenerationID: boot.Generation.ID,
		Sequence:     1,
		Cursor:       "cursor-1",
	}
	result, err := coordinator.Advance(ctx, expected, base.Add(time.Minute))
	if !errors.Is(err, transportErr) {
		t.Fatalf("err=%v result=%#v", err, result)
	}
	current, err := store.RemoteHistoryGeneration(ctx, boot.Generation.ID)
	if err != nil {
		t.Fatal(err)
	}
	if current.Status != remotehistory.HistoryGenerationActive ||
		current.CurrentSequence != 1 ||
		current.CommittedCursor != "cursor-1" {
		t.Fatalf("transport error mutated generation: %#v", current)
	}
	publications, err := store.RemoteHistoryPublications(ctx, boot.Generation.ID)
	if err != nil {
		t.Fatal(err)
	}
	if len(publications) != 1 {
		t.Fatalf("transport error appended publication: %#v", publications)
	}
}

func TestRemoteHistoryCoordinatorExplicitGapClosesGenerationWithoutCursorAdvance(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("test-policy:v1")
	adapter := &scriptedCoordinatorAdapter{
		bootstrap: remoteHistoryBootstrap(scope, "cursor-1"),
	}
	coordinator, err := remotehistory.NewCoordinator(store, adapter, scope, fp)
	if err != nil {
		t.Fatal(err)
	}
	base := time.Date(2026, 9, 26, 15, 30, 0, 0, time.UTC)
	boot, err := coordinator.Bootstrap(ctx, base)
	if err != nil {
		t.Fatal(err)
	}
	adapter.steps = []coordinatorPageStep{{page: remotehistory.ChangePage{
		StreamID: scope.StreamID,
		Status:   remotehistory.PageGap,
	}}}

	closed, err := coordinator.Advance(ctx, remotehistory.ExpectedHistoryPrestate{
		GenerationID: boot.Generation.ID,
		Sequence:     1,
		Cursor:       "cursor-1",
	}, base.Add(time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	if closed.Status != remotehistory.CoordinatorClosed ||
		closed.Generation.Status != remotehistory.HistoryGenerationClosed ||
		closed.Generation.ClosureReason != remotehistory.HistoryClosureGap ||
		closed.Generation.CurrentSequence != 1 ||
		closed.Generation.CommittedCursor != "cursor-1" {
		t.Fatalf("closed=%#v", closed)
	}
}

func TestRemoteHistoryCoordinatorPolicyMismatchStopsBeforeProviderCall(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := remoteHistoryTestScope()
	adapter := &scriptedCoordinatorAdapter{
		bootstrap: remoteHistoryBootstrap(scope, "cursor-1"),
	}
	first, err := remotehistory.NewCoordinator(store, adapter, scope, "policy:v1")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := first.Bootstrap(ctx, time.Now()); err != nil {
		t.Fatal(err)
	}
	before := adapter.bootstrapCalls

	second, err := remotehistory.NewCoordinator(store, adapter, scope, "policy:v2")
	if err != nil {
		t.Fatal(err)
	}
	_, err = second.Bootstrap(ctx, time.Now().Add(time.Second))
	if !errors.Is(err, remotehistory.ErrCoordinatorPolicyMismatch) {
		t.Fatalf("err=%v", err)
	}
	if adapter.bootstrapCalls != before {
		t.Fatalf("policy mismatch called provider: before=%d after=%d", before, adapter.bootstrapCalls)
	}
}

func TestRemoteHistoryCoordinatorIncompleteBootstrapCreatesNoGeneration(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := remoteHistoryTestScope()
	adapter := &scriptedCoordinatorAdapter{bootstrap: remotehistory.BootstrapResult{
		StreamID: scope.StreamID,
		Status:   remotehistory.BootstrapInsufficientHistory,
		Coverage: corpus.ProviderHistoryUnknown,
	}}
	coordinator, err := remotehistory.NewCoordinator(store, adapter, scope, "policy:v1")
	if err != nil {
		t.Fatal(err)
	}
	result, err := coordinator.Bootstrap(ctx, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	if result.Status != remotehistory.CoordinatorNoMutation ||
		result.BootstrapStatus != remotehistory.BootstrapInsufficientHistory {
		t.Fatalf("result=%#v", result)
	}
	if _, found, err := store.ActiveRemoteHistoryGeneration(ctx, scope); err != nil {
		t.Fatal(err)
	} else if found {
		t.Fatal("incomplete bootstrap created ACTIVE generation")
	}
}

type coordinatorPageStep struct {
	page remotehistory.ChangePage
	err  error
}

type scriptedCoordinatorAdapter struct {
	bootstrap      remotehistory.BootstrapResult
	bootstrapErr   error
	bootstrapCalls int
	steps          []coordinatorPageStep
	readCalls      int
}

func (a *scriptedCoordinatorAdapter) Bootstrap(context.Context, remotehistory.Scope) (remotehistory.BootstrapResult, error) {
	a.bootstrapCalls++
	return a.bootstrap, a.bootstrapErr
}

func (a *scriptedCoordinatorAdapter) ReadChanges(context.Context, remotehistory.Scope, remotehistory.HistoryCursor, remotehistory.ContinuationToken) (remotehistory.ChangePage, error) {
	a.readCalls++
	if len(a.steps) == 0 {
		return remotehistory.ChangePage{}, errors.New("unexpected provider read")
	}
	step := a.steps[0]
	a.steps = a.steps[1:]
	return step.page, step.err
}
