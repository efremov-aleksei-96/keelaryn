package ingest_test

import (
	"context"
	"errors"
	"path/filepath"
	"sort"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/ingest"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory/gdrive"
	sqlitestate "github.com/efremov-aleksei-96/keelaryn/internal/state/sqlite"
)

func TestGoogleDriveLiveBootstrapMaterializesExactManagedRootAndReplays(t *testing.T) {
	ctx := context.Background()
	store, client, adapter, scope, fingerprint, base := newLiveBootstrapFixture(t)
	result, err := ingest.BootstrapGoogleDriveLiveMetadata(ctx, store, adapter, scope, fingerprint, "managed", base)
	if err != nil {
		t.Fatal(err)
	}
	if result.Coordinator.Status != remotehistory.CoordinatorBootstrapCommitted ||
		result.Generation.CurrentSequence != 1 ||
		result.Generation.CommittedCursor != "cursor-1" ||
		result.Scan.Status != corpus.ScanComplete ||
		result.ScanReplayed ||
		result.MetadataCount != 4 {
		t.Fatalf("result=%#v", result)
	}

	scanRoot, err := ingest.GoogleDriveManagedRootScanRoot(scope.IdentityDomain, "managed")
	if err != nil {
		t.Fatal(err)
	}
	inventory, err := store.Inventory(ctx, gdrive.ProviderID, scanRoot)
	if err != nil {
		t.Fatal(err)
	}
	if got, want := liveInventoryObjectIDs(t, store, inventory), []string{"blob", "managed", "native", "shortcut"}; !sameLiveStrings(got, want) {
		t.Fatalf("inventory objects=%#v want=%#v", got, want)
	}
	for _, item := range inventory {
		observation, err := store.Observation(ctx, item.ObservationID)
		if err != nil {
			t.Fatal(err)
		}
		if observation.Mode != nil {
			t.Fatalf("Drive observation invented mode: %#v", observation)
		}
		switch observation.ProviderObject.ID {
		case "blob":
			if observation.Kind != corpus.EntryRegularFile || observation.Size == nil || *observation.Size != 7 ||
				observation.ModifiedAt == nil || !observation.ModifiedAt.Equal(base.Add(2*time.Minute)) {
				t.Fatalf("blob observation=%#v", observation)
			}
		case "native":
			if observation.Kind != corpus.EntryRegularFile || observation.Size == nil || *observation.Size != 12 {
				t.Fatalf("native observation=%#v", observation)
			}
		case "managed", "shortcut":
			if observation.Kind != corpus.EntryOther || observation.Size != nil {
				t.Fatalf("non-file observation=%#v", observation)
			}
		}
	}
	if _, ok := findLiveInventoryObject(t, store, inventory, "outside"); ok {
		t.Fatal("outside object entered managed-root inventory")
	}

	client.terminalCursor = "cursor-1"
	replayed, err := ingest.BootstrapGoogleDriveLiveMetadata(ctx, store, adapter, scope, fingerprint, "managed", base.Add(10*time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	if !replayed.ScanReplayed || replayed.Scan.ID != result.Scan.ID ||
		replayed.Coordinator.Status != remotehistory.CoordinatorAlreadyActive {
		t.Fatalf("replay=%#v first=%#v", replayed, result)
	}
}

func TestGoogleDriveLiveBootstrapRejectsChangedProviderBoundaryOnRecovery(t *testing.T) {
	ctx := context.Background()
	store, client, adapter, scope, fingerprint, base := newLiveBootstrapFixture(t)
	first, err := ingest.BootstrapGoogleDriveLiveMetadata(ctx, store, adapter, scope, fingerprint, "managed", base)
	if err != nil {
		t.Fatal(err)
	}
	client.terminalCursor = "cursor-2"
	_, err = ingest.BootstrapGoogleDriveLiveMetadata(ctx, store, adapter, scope, fingerprint, "managed", base.Add(10*time.Minute))
	if !errors.Is(err, ingest.ErrGoogleDriveLiveBootstrapPrestateChanged) {
		t.Fatalf("error=%v want ErrGoogleDriveLiveBootstrapPrestateChanged", err)
	}
	scanRoot, _ := ingest.GoogleDriveManagedRootScanRoot(scope.IdentityDomain, "managed")
	inventory, invErr := store.Inventory(ctx, gdrive.ProviderID, scanRoot)
	if invErr != nil {
		t.Fatal(invErr)
	}
	for _, item := range inventory {
		if item.ScanID != first.Scan.ID {
			t.Fatalf("changed provider boundary mutated inventory: %#v", item)
		}
	}
}

type liveBootstrapClient struct {
	files          []gdrive.FileRecord
	terminalCursor string
}

func (c *liveBootstrapClient) ResolveMyDriveRoot(context.Context, gdrive.Config) (string, error) {
	return "drive-root", nil
}

func (c *liveBootstrapClient) StartPageToken(context.Context, gdrive.Config) (string, error) {
	return "fence-1", nil
}

func (c *liveBootstrapClient) ListFiles(context.Context, gdrive.Config, string) (gdrive.FilePage, error) {
	files := make([]gdrive.FileRecord, len(c.files))
	copy(files, c.files)
	return gdrive.FilePage{Files: files}, nil
}

func (c *liveBootstrapClient) ListChanges(context.Context, gdrive.Config, string) (gdrive.ChangePage, error) {
	blob := gdrive.FileRecord{
		ID: "blob", Parents: []string{"managed"}, MimeType: "application/octet-stream",
		Size: 7, SizeKnown: true, ModifiedTime: time.Date(2026, 9, 30, 12, 2, 0, 0, time.UTC).Format(time.RFC3339Nano),
	}
	return gdrive.ChangePage{
		Changes:           []gdrive.ChangeRecord{{ChangeType: "file", FileID: "blob", File: &blob}},
		NewStartPageToken: c.terminalCursor,
	}, nil
}

func newLiveBootstrapFixture(t *testing.T) (
	*sqlitestate.Store,
	*liveBootstrapClient,
	*gdrive.Adapter,
	remotehistory.Scope,
	remotehistory.ScopePolicyFingerprint,
	time.Time,
) {
	t.Helper()
	ctx := context.Background()
	store, err := sqlitestate.Open(ctx, filepath.Join(t.TempDir(), "state.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := store.Close(); err != nil {
			t.Error(err)
		}
	})
	base := time.Date(2026, 9, 30, 12, 0, 0, 0, time.UTC)
	client := &liveBootstrapClient{
		terminalCursor: "cursor-1",
		files: []gdrive.FileRecord{
			{ID: "managed", Parents: []string{"drive-root"}, MimeType: "application/vnd.google-apps.folder", ModifiedTime: base.Format(time.RFC3339Nano)},
			{ID: "blob", Parents: []string{"managed"}, MimeType: "application/octet-stream", Size: 1, SizeKnown: true, ModifiedTime: base.Add(time.Minute).Format(time.RFC3339Nano)},
			{ID: "native", Parents: []string{"managed"}, MimeType: "application/vnd.google-apps.document", Size: 12, SizeKnown: true, ModifiedTime: base.Add(time.Minute).Format(time.RFC3339Nano)},
			{ID: "shortcut", Parents: []string{"managed"}, MimeType: "application/vnd.google-apps.shortcut", ModifiedTime: base.Add(time.Minute).Format(time.RFC3339Nano), ShortcutTargetID: "native"},
			{ID: "outside", Parents: []string{"drive-root"}, MimeType: "application/octet-stream", Size: 99, SizeKnown: true, ModifiedTime: base.Add(time.Minute).Format(time.RFC3339Nano)},
		},
	}
	config := gdrive.Config{
		IdentityDomain: "google-drive:user:test-live",
		StreamID:       "google-drive:user:test-live:my-drive:changes",
		Root:           "drive-root",
		Kind:           gdrive.StreamMyDrive,
	}
	adapter, err := gdrive.New(client, config)
	if err != nil {
		t.Fatal(err)
	}
	return store, client, adapter, config.Scope(),
		remotehistory.ScopePolicyFingerprint("google-drive-history-universe:v1:test-live"), base
}

func liveInventoryObjectIDs(t *testing.T, store *sqlitestate.Store, inventory []corpus.InventoryEntry) []string {
	t.Helper()
	out := make([]string, 0, len(inventory))
	for _, item := range inventory {
		observation, err := store.Observation(context.Background(), item.ObservationID)
		if err != nil {
			t.Fatal(err)
		}
		out = append(out, string(observation.ProviderObject.ID))
	}
	sort.Strings(out)
	return out
}

func findLiveInventoryObject(t *testing.T, store *sqlitestate.Store, inventory []corpus.InventoryEntry, objectID corpus.ProviderObjectID) (corpus.ObservationRecord, bool) {
	t.Helper()
	for _, item := range inventory {
		observation, err := store.Observation(context.Background(), item.ObservationID)
		if err != nil {
			t.Fatal(err)
		}
		if observation.ProviderObject.ID == objectID {
			return observation, true
		}
	}
	return corpus.ObservationRecord{}, false
}

func sameLiveStrings(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
