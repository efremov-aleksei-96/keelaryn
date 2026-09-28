package ingest_test

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/ingest"
	"github.com/efremov-aleksei-96/keelaryn/internal/provider/localfs"
	sqlitestate "github.com/efremov-aleksei-96/keelaryn/internal/state/sqlite"
)

func TestLocalFSIngestPublishesCompleteInventory(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	mustWrite(t, filepath.Join(root, "z.txt"), []byte("z"))
	mustWrite(t, filepath.Join(root, "a.txt"), []byte("a"))
	if err := os.MkdirAll(filepath.Join(root, "nested"), 0o755); err != nil {
		t.Fatal(err)
	}
	mustWrite(t, filepath.Join(root, "nested", "b.txt"), []byte("b"))

	store := openStore(t)
	provider := localfs.New("localfs")
	at := time.Date(2026, 9, 25, 8, 0, 0, 0, time.UTC)

	scan, err := ingest.LocalFS(ctx, store, provider, root, at)
	if err != nil {
		t.Fatal(err)
	}
	if scan.Status != corpus.ScanComplete {
		t.Fatalf("scan status=%q, want COMPLETE", scan.Status)
	}

	inventory, err := store.Inventory(ctx, "localfs", scan.Root)
	if err != nil {
		t.Fatal(err)
	}
	got := inventoryPaths(inventory)
	want := []string{"a.txt", "nested/b.txt", "z.txt"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("inventory paths=%#v, want %#v", got, want)
	}
	for _, entry := range inventory {
		if entry.AssignmentState != corpus.AssignmentUnresolved || entry.ArtifactID != "" || entry.RevisionID != "" {
			t.Fatalf("first-pass ingest invented identity: %#v", entry)
		}
	}
}

func TestLocalFSIngestGroupsHardLinksIntoOneOccurrence(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	original := filepath.Join(root, "original.bin")
	hardlink := filepath.Join(root, "hardlink.bin")
	mustWrite(t, original, []byte("one object"))
	if err := os.Link(original, hardlink); err != nil {
		t.Skipf("hard links unavailable: %v", err)
	}

	store := openStore(t)
	scan, err := ingest.LocalFS(ctx, store, localfs.New("localfs"), root, fixedTime())
	if err != nil {
		t.Fatal(err)
	}
	inventory, err := store.Inventory(ctx, "localfs", scan.Root)
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory) != 2 {
		t.Fatalf("inventory len=%d, want two locators", len(inventory))
	}
	if inventory[0].ObservationID != inventory[1].ObservationID {
		t.Fatalf("hard links became separate occurrences: %#v", inventory)
	}
	observation, err := store.Observation(ctx, inventory[0].ObservationID)
	if err != nil {
		t.Fatal(err)
	}
	if len(observation.Locators) != 2 {
		t.Fatalf("occurrence locators=%d, want 2", len(observation.Locators))
	}
}

func TestLocalFSIngestKeepsIdenticalCopiesDistinct(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	content := []byte("same bytes")
	mustWrite(t, filepath.Join(root, "a.bin"), content)
	mustWrite(t, filepath.Join(root, "b.bin"), content)

	store := openStore(t)
	scan, err := ingest.LocalFS(ctx, store, localfs.New("localfs"), root, fixedTime())
	if err != nil {
		t.Fatal(err)
	}
	inventory, err := store.Inventory(ctx, "localfs", scan.Root)
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory) != 2 {
		t.Fatalf("inventory=%#v", inventory)
	}
	if inventory[0].ObservationID == inventory[1].ObservationID {
		t.Fatal("byte-identical independent files collapsed into one occurrence")
	}
}

func TestLocalFSIngestDoesNotFollowSymlink(t *testing.T) {
	ctx := context.Background()
	base := t.TempDir()
	root := filepath.Join(base, "root")
	outside := filepath.Join(base, "outside")
	if err := os.MkdirAll(root, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(outside, 0o755); err != nil {
		t.Fatal(err)
	}
	mustWrite(t, filepath.Join(outside, "secret.txt"), []byte("secret"))
	if err := os.Symlink(outside, filepath.Join(root, "outside-link")); err != nil {
		t.Skipf("symlink unavailable: %v", err)
	}

	store := openStore(t)
	scan, err := ingest.LocalFS(ctx, store, localfs.New("localfs"), root, fixedTime())
	if err != nil {
		t.Fatal(err)
	}
	inventory, err := store.Inventory(ctx, "localfs", scan.Root)
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory) != 1 || inventory[0].Locator.Path != "outside-link" || inventory[0].Kind != corpus.EntrySymlink {
		t.Fatalf("symlink ingest followed or misclassified target: %#v", inventory)
	}
}

func TestLocalFSIngestEmptyRootReplacesPreviousInventory(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	path := filepath.Join(root, "file.txt")
	mustWrite(t, path, []byte("x"))

	store := openStore(t)
	provider := localfs.New("localfs")
	first, err := ingest.LocalFS(ctx, store, provider, root, fixedTime())
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	secondAt := fixedTime().Add(time.Minute)
	second, err := ingest.LocalFS(ctx, store, provider, root, secondAt)
	if err != nil {
		t.Fatal(err)
	}
	if first.ID == second.ID {
		t.Fatal("two ingests reused scan identity")
	}
	inventory, err := store.Inventory(ctx, "localfs", second.Root)
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory) != 0 {
		t.Fatalf("empty root did not replace inventory: %#v", inventory)
	}
}

func TestLocalFSIngestDiscoveryFailureLeavesPreviousAuthority(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	mustWrite(t, filepath.Join(root, "file.txt"), []byte("x"))

	store := openStore(t)
	provider := localfs.New("localfs")
	first, err := ingest.LocalFS(ctx, store, provider, root, fixedTime())
	if err != nil {
		t.Fatal(err)
	}
	if err := os.RemoveAll(root); err != nil {
		t.Fatal(err)
	}

	if _, err := ingest.LocalFS(ctx, store, provider, root, fixedTime().Add(time.Minute)); err == nil {
		t.Fatal("missing root ingest unexpectedly succeeded")
	}
	inventory, err := store.Inventory(ctx, "localfs", first.Root)
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory) != 1 || inventory[0].Locator.Path != "file.txt" {
		t.Fatalf("discovery failure changed prior authority: %#v", inventory)
	}
}

func TestLocalFSIngestAtomicFailureRollsBackAndKeepsPreviousAuthority(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	mustWrite(t, filepath.Join(root, "old.txt"), []byte("old"))

	store := openStore(t)
	provider := localfs.New("localfs")
	first, err := ingest.LocalFS(ctx, store, provider, root, fixedTime())
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(filepath.Join(root, "old.txt")); err != nil {
		t.Fatal(err)
	}
	mustWrite(t, filepath.Join(root, "a.txt"), []byte("a"))
	mustWrite(t, filepath.Join(root, "b.txt"), []byte("b"))

	failing := &failAtomicStore{Store: store}
	_, err = ingest.LocalFS(ctx, failing, provider, root, fixedTime().Add(time.Minute))
	if !errors.Is(err, errInjectedPersistence) {
		t.Fatalf("error=%v, want injected persistence error", err)
	}
	if open, found, openErr := store.OpenScanForScope(ctx, "localfs", first.Root); openErr != nil {
		t.Fatal(openErr)
	} else if found {
		t.Fatalf("atomic failure stranded OPEN scan: %#v", open)
	}

	inventory, err := store.Inventory(ctx, "localfs", first.Root)
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory) != 1 || inventory[0].Locator.Path != "old.txt" {
		t.Fatalf("failed ingest replaced previous authority: %#v", inventory)
	}
}

func TestLocalFSIngestExactBoundaryReplayReturnsCommittedScan(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	mustWrite(t, filepath.Join(root, "file.txt"), []byte("x"))
	store := openStore(t)
	provider := localfs.New("localfs")
	at := fixedTime()

	first, err := ingest.LocalFS(ctx, store, provider, root, at)
	if err != nil {
		t.Fatal(err)
	}
	second, err := ingest.LocalFS(ctx, store, provider, root, at)
	if err != nil {
		t.Fatal(err)
	}
	if second.ID != first.ID {
		t.Fatalf("exact replay created second scan: first=%s second=%s", first.ID, second.ID)
	}
	receipt, found, err := store.LocalIngestCommitAtBoundary(ctx, "localfs", first.Root, at, false)
	if err != nil {
		t.Fatal(err)
	}
	if !found || receipt.Scan.ID != first.ID || receipt.Bootstrap {
		t.Fatalf("replay receipt=%#v found=%v", receipt, found)
	}
}

func TestLocalFSIngestFinalRootRevalidationRollsBackMixedSnapshot(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	mustWrite(t, filepath.Join(root, "a.txt"), []byte("a"))
	store := openStore(t)
	provider := localfs.New("localfs")

	mutating := &mutateBeforeValidationStore{
		Store: store,
		mutate: func() error {
			return os.WriteFile(filepath.Join(root, "b.txt"), []byte("b"), 0o600)
		},
	}
	_, err := ingest.LocalFS(ctx, mutating, provider, root, fixedTime())
	if !errors.Is(err, ingest.ErrLocalFSSnapshotChanged) {
		t.Fatalf("error=%v, want ErrLocalFSSnapshotChanged", err)
	}
	if open, found, openErr := store.OpenScanForScope(ctx, "localfs", filepath.Clean(root)); openErr != nil {
		t.Fatal(openErr)
	} else if found {
		t.Fatalf("revalidation failure stranded OPEN scan: %#v", open)
	}
	inventory, err := store.Inventory(ctx, "localfs", filepath.Clean(root))
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory) != 0 {
		t.Fatalf("mixed snapshot became authoritative: %#v", inventory)
	}
}

func TestLocalFSIngestSurvivesStoreReopen(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	mustWrite(t, filepath.Join(root, "file.txt"), []byte("x"))
	dbPath := filepath.Join(t.TempDir(), "state.db")

	store, err := sqlitestate.Open(ctx, dbPath)
	if err != nil {
		t.Fatal(err)
	}
	scan, err := ingest.LocalFS(ctx, store, localfs.New("localfs"), root, fixedTime())
	if err != nil {
		t.Fatal(err)
	}
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}

	store, err = sqlitestate.Open(ctx, dbPath)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	inventory, err := store.Inventory(ctx, "localfs", scan.Root)
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory) != 1 || inventory[0].Locator.Path != "file.txt" {
		t.Fatalf("reopened inventory=%#v", inventory)
	}
}

type failAtomicStore struct {
	*sqlitestate.Store
}

var errInjectedPersistence = errors.New("injected persistence failure")

func (s *failAtomicStore) CommitLocalSnapshot(
	ctx context.Context,
	providerID corpus.ProviderID,
	root string,
	observedAt time.Time,
	fingerprintVersion string,
	fingerprintSHA256 string,
	inputs []corpus.ObservationRecordInput,
	finalValidate func(context.Context) error,
) (corpus.ScanSession, error) {
	return s.Store.CommitLocalSnapshot(
		ctx, providerID, root, observedAt, fingerprintVersion, fingerprintSHA256, inputs,
		func(context.Context) error { return errInjectedPersistence },
	)
}

func (s *failAtomicStore) CommitBootstrapLocalSnapshot(
	ctx context.Context,
	providerID corpus.ProviderID,
	root string,
	observedAt time.Time,
	fingerprintVersion string,
	fingerprintSHA256 string,
	inputs []corpus.BootstrapObservationInput,
	finalValidate func(context.Context) error,
) (corpus.ScanSession, error) {
	return s.Store.CommitBootstrapLocalSnapshot(
		ctx, providerID, root, observedAt, fingerprintVersion, fingerprintSHA256, inputs,
		func(context.Context) error { return errInjectedPersistence },
	)
}

type mutateBeforeValidationStore struct {
	*sqlitestate.Store
	mutate func() error
}

func (s *mutateBeforeValidationStore) CommitLocalSnapshot(
	ctx context.Context,
	providerID corpus.ProviderID,
	root string,
	observedAt time.Time,
	fingerprintVersion string,
	fingerprintSHA256 string,
	inputs []corpus.ObservationRecordInput,
	finalValidate func(context.Context) error,
) (corpus.ScanSession, error) {
	return s.Store.CommitLocalSnapshot(
		ctx, providerID, root, observedAt, fingerprintVersion, fingerprintSHA256, inputs,
		func(validateCtx context.Context) error {
			if err := s.mutate(); err != nil {
				return err
			}
			return finalValidate(validateCtx)
		},
	)
}

func (s *mutateBeforeValidationStore) CommitBootstrapLocalSnapshot(
	ctx context.Context,
	providerID corpus.ProviderID,
	root string,
	observedAt time.Time,
	fingerprintVersion string,
	fingerprintSHA256 string,
	inputs []corpus.BootstrapObservationInput,
	finalValidate func(context.Context) error,
) (corpus.ScanSession, error) {
	return s.Store.CommitBootstrapLocalSnapshot(
		ctx, providerID, root, observedAt, fingerprintVersion, fingerprintSHA256, inputs,
		func(validateCtx context.Context) error {
			if err := s.mutate(); err != nil {
				return err
			}
			return finalValidate(validateCtx)
		},
	)
}

func openStore(t *testing.T) *sqlitestate.Store {
	t.Helper()
	store, err := sqlitestate.Open(context.Background(), filepath.Join(t.TempDir(), "state.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := store.Close(); err != nil {
			t.Error(err)
		}
	})
	return store
}

func mustWrite(t *testing.T, path string, content []byte) {
	t.Helper()
	if err := os.WriteFile(path, content, 0o600); err != nil {
		t.Fatal(err)
	}
}

func fixedTime() time.Time {
	return time.Date(2026, 9, 25, 8, 30, 0, 0, time.UTC)
}

func inventoryPaths(entries []corpus.InventoryEntry) []string {
	out := make([]string, len(entries))
	for i := range entries {
		out[i] = entries[i].Locator.Path
	}
	return out
}
