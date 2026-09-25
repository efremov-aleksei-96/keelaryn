package gdrive_test

import (
	"context"
	"errors"
	"reflect"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory/gdrive"
)

func TestBootstrapUsesFenceEnumerationCatchUpWithoutGap(t *testing.T) {
	client := &fakeClient{
		startToken: "cursor-fence",
		filePages: []gdrive.FilePage{
			{
				Files: []gdrive.FileRecord{
					{ID: "a", Parents: []string{"root"}},
					{ID: "b", Parents: []string{"root"}},
					{ID: "outside", Parents: []string{"other-root"}},
					{ID: "shared", Parents: []string{"root"}, DriveID: "shared-drive"},
				},
				NextPageToken: "files-2",
			},
			{Files: []gdrive.FileRecord{{ID: "child", Parents: []string{"a"}}}},
		},
		changePages: map[string]changeResult{
			"cursor-fence": {page: gdrive.ChangePage{
				Changes: []gdrive.ChangeRecord{
					{ChangeType: "file", FileID: "b", Removed: true},
					{ChangeType: "file", FileID: "c", File: &gdrive.FileRecord{ID: "c"}},
				},
				NextPageToken: "changes-2",
			}},
			"changes-2": {page: gdrive.ChangePage{
				Changes: []gdrive.ChangeRecord{
					{ChangeType: "drive"},
					{ChangeType: "file", FileID: "child", File: &gdrive.FileRecord{ID: "child", Trashed: true}},
				},
				NewStartPageToken: "cursor-terminal",
			}},
		},
	}
	adapter := mustAdapter(t, client, myDriveConfig())

	result, err := adapter.Bootstrap(context.Background(), myDriveConfig().Scope())
	if err != nil {
		t.Fatal(err)
	}
	if result.Status != remotehistory.BootstrapComplete || result.Cursor != "cursor-terminal" || result.Coverage != corpus.ProviderHistoryContinuous {
		t.Fatalf("result=%#v", result)
	}
	got := objectIDs(result.Objects)
	want := []string{"a", "c"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("objects=%v want=%v", got, want)
	}
	if !reflect.DeepEqual(client.fileTokens, []string{"", "files-2"}) {
		t.Fatalf("file tokens=%v", client.fileTokens)
	}
	if !reflect.DeepEqual(client.changeTokens, []string{"cursor-fence", "changes-2"}) {
		t.Fatalf("change tokens=%v", client.changeTokens)
	}
}

func TestReadChangesPreservesCommittedCursorUntilTerminalPage(t *testing.T) {
	client := &fakeClient{changePages: map[string]changeResult{
		"cursor-1": {page: gdrive.ChangePage{
			Changes:       []gdrive.ChangeRecord{{FileID: "a", File: &gdrive.FileRecord{ID: "a"}}},
			NextPageToken: "page-2",
		}},
		"page-2": {page: gdrive.ChangePage{
			Changes:           []gdrive.ChangeRecord{{FileID: "b", Removed: true}},
			NewStartPageToken: "cursor-2",
		}},
	}}
	adapter := mustAdapter(t, client, myDriveConfig())

	cycle, err := remotehistory.ConsumeChanges(context.Background(), adapter, myDriveConfig().Scope(), "cursor-1")
	if err != nil {
		t.Fatal(err)
	}
	if cycle.Status != remotehistory.CycleComplete || cycle.PreviousCursor != "cursor-1" || cycle.NextCursor != "cursor-2" || cycle.Coverage != corpus.ProviderHistoryContinuous {
		t.Fatalf("cycle=%#v", cycle)
	}
	if !reflect.DeepEqual(client.changeTokens, []string{"cursor-1", "page-2"}) {
		t.Fatalf("change tokens=%v", client.changeTokens)
	}
	if len(cycle.Changes) != 2 || cycle.Changes[0].Kind != remotehistory.ChangeUpsert || cycle.Changes[1].Kind != remotehistory.ChangeRemoved {
		t.Fatalf("changes=%#v", cycle.Changes)
	}
}

func TestScopeMismatchFailsClosedWithoutClientCalls(t *testing.T) {
	client := &fakeClient{}
	adapter := mustAdapter(t, client, myDriveConfig())
	wrong := myDriveConfig().Scope()
	wrong.IdentityDomain = "google-drive:user:other"

	bootstrap, err := adapter.Bootstrap(context.Background(), wrong)
	if err != nil {
		t.Fatal(err)
	}
	if bootstrap.Status != remotehistory.BootstrapScopeMismatch || bootstrap.Cursor != "" || bootstrap.Coverage != corpus.ProviderHistoryUnknown {
		t.Fatalf("bootstrap=%#v", bootstrap)
	}
	page, err := adapter.ReadChanges(context.Background(), wrong, "cursor-1", "")
	if err != nil {
		t.Fatal(err)
	}
	if page.Status != remotehistory.PageScopeMismatch || page.NextCursor != "" || len(page.Changes) != 0 {
		t.Fatalf("page=%#v", page)
	}
	if client.calls != 0 {
		t.Fatalf("client calls=%d", client.calls)
	}
}

func TestClientFaultsMapToExplicitHistoryStates(t *testing.T) {
	cases := []struct {
		name       string
		err        error
		pageStatus remotehistory.PageStatus
		bootStatus remotehistory.BootstrapStatus
	}{
		{"gap", gdrive.ErrClientHistoryGap, remotehistory.PageGap, remotehistory.BootstrapGap},
		{"invalid", gdrive.ErrClientInvalidCursor, remotehistory.PageInvalidCursor, remotehistory.BootstrapGap},
		{"scope", gdrive.ErrClientScopeMismatch, remotehistory.PageScopeMismatch, remotehistory.BootstrapScopeMismatch},
		{"insufficient", gdrive.ErrClientInsufficientHistory, remotehistory.PageInsufficientHistory, remotehistory.BootstrapInsufficientHistory},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			client := &fakeClient{startErr: tc.err, changePages: map[string]changeResult{"cursor-1": {err: tc.err}}}
			adapter := mustAdapter(t, client, myDriveConfig())
			bootstrap, err := adapter.Bootstrap(context.Background(), myDriveConfig().Scope())
			if err != nil {
				t.Fatal(err)
			}
			if bootstrap.Status != tc.bootStatus || bootstrap.Cursor != "" || bootstrap.Coverage != corpus.ProviderHistoryUnknown {
				t.Fatalf("bootstrap=%#v", bootstrap)
			}
			page, err := adapter.ReadChanges(context.Background(), myDriveConfig().Scope(), "cursor-1", "")
			if err != nil {
				t.Fatal(err)
			}
			if page.Status != tc.pageStatus || page.NextCursor != "" || len(page.Changes) != 0 {
				t.Fatalf("page=%#v", page)
			}
		})
	}
}

func TestSharedDriveScopeAndShortcutKeepDriveObjectIdentity(t *testing.T) {
	config := gdrive.Config{
		IdentityDomain: "google-drive:shared:drive-1",
		StreamID:       "google-drive:shared:drive-1:changes",
		Root:           "drive-1",
		Kind:           gdrive.StreamSharedDrive,
		DriveID:        "drive-1",
	}
	client := &fakeClient{
		startToken: "fence",
		filePages: []gdrive.FilePage{{Files: []gdrive.FileRecord{
			{ID: "shortcut", DriveID: "drive-1", Parents: []string{"drive-1"}, ShortcutTargetID: "target"},
			{ID: "other-drive", DriveID: "drive-2", Parents: []string{"drive-1"}},
		}}},
		changePages: map[string]changeResult{"fence": {page: gdrive.ChangePage{NewStartPageToken: "terminal"}}},
	}
	adapter := mustAdapter(t, client, config)

	result, err := adapter.Bootstrap(context.Background(), config.Scope())
	if err != nil {
		t.Fatal(err)
	}
	if got := objectIDs(result.Objects); !reflect.DeepEqual(got, []string{"shortcut"}) {
		t.Fatalf("objects=%v", got)
	}
	if result.Objects[0].ObjectID == "target" {
		t.Fatal("shortcut target ID became provider-object identity")
	}
}

func TestRemovedAndTrashedAreRemovalFromScopeNotPhysicalDeletionClaims(t *testing.T) {
	client := &fakeClient{changePages: map[string]changeResult{"cursor-1": {page: gdrive.ChangePage{
		Changes: []gdrive.ChangeRecord{
			{FileID: "removed", Removed: true},
			{FileID: "trashed", File: &gdrive.FileRecord{ID: "trashed", Trashed: true}},
		},
		NewStartPageToken: "cursor-2",
	}}}}
	adapter := mustAdapter(t, client, myDriveConfig())

	page, err := adapter.ReadChanges(context.Background(), myDriveConfig().Scope(), "cursor-1", "")
	if err != nil {
		t.Fatal(err)
	}
	for _, change := range page.Changes {
		if change.Kind != remotehistory.ChangeRemoved || change.State != nil {
			t.Fatalf("change=%#v", change)
		}
	}
}

func TestInvalidPaginationFailsClosed(t *testing.T) {
	for _, page := range []gdrive.ChangePage{
		{},
		{NextPageToken: "next", NewStartPageToken: "terminal"},
	} {
		client := &fakeClient{changePages: map[string]changeResult{"cursor-1": {page: page}}}
		adapter := mustAdapter(t, client, myDriveConfig())
		_, err := adapter.ReadChanges(context.Background(), myDriveConfig().Scope(), "cursor-1", "")
		if !errors.Is(err, gdrive.ErrInvalidClientResponse) {
			t.Fatalf("error=%v", err)
		}
	}
}

func TestConfigRejectsAmbiguousStreamDefinitions(t *testing.T) {
	bad := []gdrive.Config{
		{},
		{IdentityDomain: "id", StreamID: "s", Root: "root", Kind: gdrive.StreamMyDrive, DriveID: "must-be-empty"},
		{IdentityDomain: "id", StreamID: "s", Root: "different", Kind: gdrive.StreamSharedDrive, DriveID: "drive"},
	}
	for _, config := range bad {
		if _, err := gdrive.New(&fakeClient{}, config); !errors.Is(err, gdrive.ErrInvalidConfig) {
			t.Fatalf("config=%#v error=%v", config, err)
		}
	}
}

func myDriveConfig() gdrive.Config {
	return gdrive.Config{
		IdentityDomain: "google-drive:user:user-1",
		StreamID:       "google-drive:user:user-1:my-drive:changes",
		Root:           "root",
		Kind:           gdrive.StreamMyDrive,
	}
}

func mustAdapter(t *testing.T, client gdrive.Client, config gdrive.Config) *gdrive.Adapter {
	t.Helper()
	adapter, err := gdrive.New(client, config)
	if err != nil {
		t.Fatal(err)
	}
	return adapter
}

func objectIDs(objects []remotehistory.RemoteObjectState) []string {
	ids := make([]string, len(objects))
	for i, object := range objects {
		ids[i] = string(object.ObjectID)
	}
	return ids
}

type changeResult struct {
	page gdrive.ChangePage
	err  error
}

type fakeClient struct {
	startToken   string
	startErr     error
	filePages    []gdrive.FilePage
	fileIndex    int
	fileTokens   []string
	changePages  map[string]changeResult
	changeTokens []string
	calls        int
}

func (f *fakeClient) StartPageToken(context.Context, gdrive.Config) (string, error) {
	f.calls++
	return f.startToken, f.startErr
}

func (f *fakeClient) ListFiles(_ context.Context, _ gdrive.Config, token string) (gdrive.FilePage, error) {
	f.calls++
	f.fileTokens = append(f.fileTokens, token)
	if f.fileIndex >= len(f.filePages) {
		return gdrive.FilePage{}, nil
	}
	page := f.filePages[f.fileIndex]
	f.fileIndex++
	return page, nil
}

func (f *fakeClient) ListChanges(_ context.Context, _ gdrive.Config, token string) (gdrive.ChangePage, error) {
	f.calls++
	f.changeTokens = append(f.changeTokens, token)
	result, ok := f.changePages[token]
	if !ok {
		return gdrive.ChangePage{}, errors.New("unexpected change token: " + token)
	}
	return result.page, result.err
}
