package remotehistory_test

import (
	"context"
	"errors"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
)

func TestConsumeChangesCommitsOnlyTerminalCursor(t *testing.T) {
	scope := testScope()
	fake := &fakeAdapter{pages: []pageResult{
		{page: remotehistory.ChangePage{
			StreamID: scope.StreamID,
			Status: remotehistory.PageMore,
			Continuation: "page-2",
			Changes: []remotehistory.RemoteChange{upsert("id-1", "a.txt")},
		}},
		{page: remotehistory.ChangePage{
			StreamID: scope.StreamID,
			Status: remotehistory.PageTerminal,
			NextCursor: "cursor-2",
			Changes: []remotehistory.RemoteChange{removed("id-2")},
		}},
	}}
	cycle, err := remotehistory.ConsumeChanges(context.Background(), fake, scope, "cursor-1")
	if err != nil {
		t.Fatal(err)
	}
	if cycle.Status != remotehistory.CycleComplete ||
		cycle.PreviousCursor != "cursor-1" ||
		cycle.NextCursor != "cursor-2" ||
		cycle.Coverage != corpus.ProviderHistoryContinuous {
		t.Fatalf("cycle=%#v", cycle)
	}
	if len(cycle.Changes) != 2 {
		t.Fatalf("changes=%#v", cycle.Changes)
	}
	if len(fake.calls) != 2 ||
		fake.calls[0].committed != "cursor-1" || fake.calls[0].continuation != "" ||
		fake.calls[1].committed != "cursor-1" || fake.calls[1].continuation != "page-2" {
		t.Fatalf("calls=%#v", fake.calls)
	}
}

func TestInterruptedCycleRetainsPreviousCommittedCursor(t *testing.T) {
	scope := testScope()
	injected := errors.New("transport interrupted")
	fake := &fakeAdapter{pages: []pageResult{
		{page: remotehistory.ChangePage{
			StreamID: scope.StreamID,
			Status: remotehistory.PageMore,
			Continuation: "page-2",
			Changes: []remotehistory.RemoteChange{upsert("id-1", "a.txt")},
		}},
		{err: injected},
	}}
	cycle, err := remotehistory.ConsumeChanges(context.Background(), fake, scope, "cursor-1")
	if !errors.Is(err, injected) {
		t.Fatalf("error=%v", err)
	}
	if cycle.Status != remotehistory.CycleInterrupted ||
		cycle.NextCursor != "cursor-1" ||
		cycle.Coverage != corpus.ProviderHistoryUnknown {
		t.Fatalf("interrupted cycle advanced authority: %#v", cycle)
	}
}

func TestGapAndInvalidCursorNeverAdvanceCoverage(t *testing.T) {
	for _, status := range []remotehistory.PageStatus{
		remotehistory.PageGap,
		remotehistory.PageInvalidCursor,
		remotehistory.PageScopeMismatch,
		remotehistory.PageInsufficientHistory,
	} {
		t.Run(string(status), func(t *testing.T) {
			scope := testScope()
			fake := &fakeAdapter{pages: []pageResult{{page: remotehistory.ChangePage{
				StreamID: scope.StreamID,
				Status: status,
			}}}}
			cycle, err := remotehistory.ConsumeChanges(context.Background(), fake, scope, "cursor-1")
			if err != nil {
				t.Fatal(err)
			}
			if cycle.NextCursor != "cursor-1" || cycle.Coverage != corpus.ProviderHistoryUnknown || len(cycle.Changes) != 0 {
				t.Fatalf("failure cycle advanced authority: %#v", cycle)
			}
		})
	}
}

func TestIntermediatePageCannotCarryDurableCursor(t *testing.T) {
	scope := testScope()
	fake := &fakeAdapter{pages: []pageResult{{page: remotehistory.ChangePage{
		StreamID: scope.StreamID,
		Status: remotehistory.PageMore,
		Continuation: "page-2",
		NextCursor: "cursor-should-not-commit",
	}}}}
	cycle, err := remotehistory.ConsumeChanges(context.Background(), fake, scope, "cursor-1")
	if !errors.Is(err, remotehistory.ErrInvalidHistoryPage) {
		t.Fatalf("error=%v, want ErrInvalidHistoryPage", err)
	}
	if cycle.NextCursor != "cursor-1" || cycle.Coverage != corpus.ProviderHistoryUnknown {
		t.Fatalf("invalid page advanced authority: %#v", cycle)
	}
}

func TestStreamMismatchFailsClosed(t *testing.T) {
	scope := testScope()
	fake := &fakeAdapter{pages: []pageResult{{page: remotehistory.ChangePage{
		StreamID: "other-stream",
		Status: remotehistory.PageTerminal,
		NextCursor: "cursor-2",
	}}}}
	cycle, err := remotehistory.ConsumeChanges(context.Background(), fake, scope, "cursor-1")
	if !errors.Is(err, remotehistory.ErrInvalidHistoryPage) {
		t.Fatalf("error=%v", err)
	}
	if cycle.NextCursor != "cursor-1" || cycle.Coverage != corpus.ProviderHistoryUnknown {
		t.Fatalf("stream mismatch advanced authority: %#v", cycle)
	}
}

func TestStableLifetimeIdentityBecomesConclusiveOnlyAfterContinuousCycle(t *testing.T) {
	scope := testScope()
	comparison := corpus.ProviderIdentityComparison{
		Previous: corpus.ProviderIdentityRef{IdentityDomain: scope.IdentityDomain, ObjectID: "file-1"},
		Current: corpus.ProviderIdentityRef{IdentityDomain: scope.IdentityDomain, ObjectID: "file-1"},
		Coverage: corpus.ProviderHistoryUnknown,
	}
	before, err := corpus.ProviderIdentityEvidence(corpus.GoogleDriveFileIDContract(), comparison)
	if err != nil {
		t.Fatal(err)
	}
	if before.Strength != corpus.EvidenceSupporting {
		t.Fatalf("unknown-gap evidence=%#v", before)
	}

	fake := &fakeAdapter{pages: []pageResult{{page: remotehistory.ChangePage{
		StreamID: scope.StreamID,
		Status: remotehistory.PageTerminal,
		NextCursor: "cursor-2",
	}}}}
	cycle, err := remotehistory.ConsumeChanges(context.Background(), fake, scope, "cursor-1")
	if err != nil {
		t.Fatal(err)
	}
	comparison.Coverage = cycle.Coverage
	after, err := corpus.ProviderIdentityEvidence(corpus.GoogleDriveFileIDContract(), comparison)
	if err != nil {
		t.Fatal(err)
	}
	if after.Strength != corpus.EvidenceConclusive || after.Direction != corpus.DirectionSupportsSame {
		t.Fatalf("continuous evidence=%#v", after)
	}
}

func TestBootstrapValidationRequiresTerminalCursorAndContinuousCoverage(t *testing.T) {
	scope := testScope()
	valid := remotehistory.BootstrapResult{
		StreamID: scope.StreamID,
		Status: remotehistory.BootstrapComplete,
		Cursor: "cursor-1",
		Coverage: corpus.ProviderHistoryContinuous,
		Objects: []remotehistory.RemoteObjectState{{
			ObjectID: "id-1",
			Locators: []corpus.Locator{{ProviderID: "drive", Root: "root", Path: "a.txt"}},
		}},
	}
	if err := remotehistory.ValidateBootstrap(scope, valid); err != nil {
		t.Fatal(err)
	}

	invalid := valid
	invalid.Cursor = ""
	if !errors.Is(remotehistory.ValidateBootstrap(scope, invalid), remotehistory.ErrInvalidBootstrapResult) {
		t.Fatal("COMPLETE bootstrap without cursor accepted")
	}

	gap := remotehistory.BootstrapResult{
		StreamID: scope.StreamID,
		Status: remotehistory.BootstrapGap,
		Coverage: corpus.ProviderHistoryUnknown,
	}
	if err := remotehistory.ValidateBootstrap(scope, gap); err != nil {
		t.Fatal(err)
	}
}

func TestRemovedChangeIsScopeRemovalNotInventedDeletionState(t *testing.T) {
	scope := testScope()
	fake := &fakeAdapter{pages: []pageResult{{page: remotehistory.ChangePage{
		StreamID: scope.StreamID,
		Status: remotehistory.PageTerminal,
		NextCursor: "cursor-2",
		Changes: []remotehistory.RemoteChange{removed("id-1")},
	}}}}
	cycle, err := remotehistory.ConsumeChanges(context.Background(), fake, scope, "cursor-1")
	if err != nil {
		t.Fatal(err)
	}
	if cycle.Changes[0].Kind != remotehistory.ChangeRemoved || cycle.Changes[0].State != nil {
		t.Fatalf("removed change invented current/deletion state: %#v", cycle.Changes[0])
	}
}

type pageResult struct {
	page remotehistory.ChangePage
	err  error
}

type readCall struct {
	committed    remotehistory.HistoryCursor
	continuation remotehistory.ContinuationToken
}

type fakeAdapter struct {
	pages []pageResult
	calls []readCall
}

func (f *fakeAdapter) Bootstrap(context.Context, remotehistory.Scope) (remotehistory.BootstrapResult, error) {
	panic("not used")
}

func (f *fakeAdapter) ReadChanges(_ context.Context, _ remotehistory.Scope, committed remotehistory.HistoryCursor, continuation remotehistory.ContinuationToken) (remotehistory.ChangePage, error) {
	f.calls = append(f.calls, readCall{committed: committed, continuation: continuation})
	if len(f.pages) == 0 {
		return remotehistory.ChangePage{}, errors.New("unexpected extra page")
	}
	next := f.pages[0]
	f.pages = f.pages[1:]
	return next.page, next.err
}

func testScope() remotehistory.Scope {
	return remotehistory.Scope{
		ProviderID: "drive",
		IdentityDomain: "drive:user-1",
		StreamID: "drive:user-1:changes",
		Root: "root",
	}
}

func upsert(id corpus.ProviderObjectID, path string) remotehistory.RemoteChange {
	return remotehistory.RemoteChange{
		Kind: remotehistory.ChangeUpsert,
		ObjectID: id,
		State: &remotehistory.RemoteObjectState{
			ObjectID: id,
			Locators: []corpus.Locator{{
				ProviderID: "drive",
				Root: "root",
				Path: path,
			}},
		},
	}
}

func removed(id corpus.ProviderObjectID) remotehistory.RemoteChange {
	return remotehistory.RemoteChange{
		Kind: remotehistory.ChangeRemoved,
		ObjectID: id,
	}
}
