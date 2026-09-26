package ingest_test

import (
	"context"
	"errors"
	"path/filepath"
	"reflect"
	"sort"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/ingest"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory/gdrive"
	sqlitestate "github.com/efremov-aleksei-96/keelaryn/internal/state/sqlite"
)

func TestRemoteMetadataMaterializationPublishesExistingInventoryAndReplaysDeterministically(t *testing.T) {
	ctx := context.Background()
	fixture := newGoogleRemoteFixture(t, "account-A", false)
	snapshot := fixture.snapshot(
		remoteMetadataEntry("managed", corpus.EntryOther, 0, 0, fixture.base),
		remoteMetadataEntry("child", corpus.EntryRegularFile, 7, 0, fixture.base.Add(time.Second)),
	)
	// Deliberately reverse input order. Canonical fingerprint/order must not depend
	// on provider enumeration order.
	snapshot.Entries[0], snapshot.Entries[1] = snapshot.Entries[1], snapshot.Entries[0]

	scan, replayed, err := ingest.MaterializeRemoteMetadata(ctx, fixture.store, fixture.projection, snapshot, fixture.base.Add(time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	if replayed || scan.Status != corpus.ScanComplete {
		t.Fatalf("first materialization replayed=%v scan=%#v", replayed, scan)
	}

	inventory, err := fixture.store.Inventory(ctx, gdrive.ProviderID, fixture.scanRoot)
	if err != nil {
		t.Fatal(err)
	}
	if got, want := inventoryPathsRemote(inventory), []string{"file-id/child", "file-id/managed"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("inventory paths=%#v want %#v", got, want)
	}
	for _, item := range inventory {
		if item.ScanID != scan.ID || item.AssignmentState != corpus.AssignmentUnresolved || item.ArtifactID != "" || item.RevisionID != "" {
			t.Fatalf("materializer bypassed unresolved existing inventory semantics: %#v", item)
		}
		observation, err := fixture.store.Observation(ctx, item.ObservationID)
		if err != nil {
			t.Fatal(err)
		}
		if observation.ProviderObject.ProviderID != gdrive.ProviderID ||
			observation.ProviderObject.ID == "" ||
			observation.ProviderObject.IdentityState != corpus.ObjectIdentityObserved {
			t.Fatalf("invalid provider-object observation: %#v", observation.ProviderObject)
		}
	}

	source, err := fixture.store.RemoteHistoryScanSource(ctx, scan.ID)
	if err != nil {
		t.Fatal(err)
	}
	if source.GenerationID != fixture.generation.ID ||
		source.PublicationSequence != 1 ||
		source.SourceScopeID != "managed" ||
		source.MaterializationPolicyID != ingest.LightweightAllMaterializationPolicyID ||
		source.SnapshotFingerprintVersion != ingest.RemoteMetadataSnapshotFingerprintVersion ||
		len(source.SnapshotFingerprintSHA256) != 64 {
		t.Fatalf("source binding=%#v", source)
	}

	// Same facts in the opposite order must fingerprint to the same source and
	// replay the already COMPLETE scan rather than minting a competing inventory.
	snapshot.Entries[0], snapshot.Entries[1] = snapshot.Entries[1], snapshot.Entries[0]
	replayedScan, replayed, err := ingest.MaterializeRemoteMetadata(ctx, fixture.store, fixture.projection, snapshot, fixture.base.Add(2*time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	if !replayed || replayedScan.ID != scan.ID {
		t.Fatalf("deterministic replay scan=%#v replayed=%v want %s", replayedScan, replayed, scan.ID)
	}
}

func TestRemoteMetadataMaterializationRequiresExactProvenInSet(t *testing.T) {
	fixture := newGoogleRemoteFixture(t, "account-A", false)
	snapshot := fixture.snapshot(remoteMetadataEntry("managed", corpus.EntryOther, 0, 0, fixture.base))

	_, _, err := ingest.MaterializeRemoteMetadata(context.Background(), fixture.store, fixture.projection, snapshot, fixture.base.Add(time.Minute))
	if !errors.Is(err, ingest.ErrRemoteMetadataSetMismatch) {
		t.Fatalf("error=%v want ErrRemoteMetadataSetMismatch", err)
	}
	inventory, invErr := fixture.store.Inventory(context.Background(), gdrive.ProviderID, fixture.scanRoot)
	if invErr != nil {
		t.Fatal(invErr)
	}
	if len(inventory) != 0 {
		t.Fatalf("invalid exact-set snapshot published inventory: %#v", inventory)
	}
}

func TestRemoteMetadataMaterializationFailsClosedOnUnknownMembership(t *testing.T) {
	fixture := newGoogleRemoteFixture(t, "account-A", true)
	snapshot := fixture.snapshot(
		remoteMetadataEntry("managed", corpus.EntryOther, 0, 0, fixture.base),
		remoteMetadataEntry("child", corpus.EntryRegularFile, 7, 0, fixture.base.Add(time.Second)),
	)

	_, _, err := ingest.MaterializeRemoteMetadata(context.Background(), fixture.store, fixture.projection, snapshot, fixture.base.Add(time.Minute))
	if !errors.Is(err, ingest.ErrRemoteMembershipUnknown) {
		t.Fatalf("error=%v want ErrRemoteMembershipUnknown", err)
	}
	inventory, invErr := fixture.store.Inventory(context.Background(), gdrive.ProviderID, fixture.scanRoot)
	if invErr != nil {
		t.Fatal(invErr)
	}
	if len(inventory) != 0 {
		t.Fatalf("UNKNOWN membership published inventory: %#v", inventory)
	}
}

func TestRemoteMetadataMaterializationRejectsMissingRequiredFacts(t *testing.T) {
	fixture := newGoogleRemoteFixture(t, "account-A", false)
	managed := remoteMetadataEntry("managed", corpus.EntryOther, 0, 0, fixture.base)
	child := remoteMetadataEntry("child", corpus.EntryRegularFile, 7, 0, fixture.base.Add(time.Second))
	child.Size = nil
	snapshot := fixture.snapshot(managed, child)

	_, _, err := ingest.MaterializeRemoteMetadata(context.Background(), fixture.store, fixture.projection, snapshot, fixture.base.Add(time.Minute))
	if !errors.Is(err, ingest.ErrInvalidRemoteMetadataSnapshot) {
		t.Fatalf("error=%v want ErrInvalidRemoteMetadataSnapshot", err)
	}
}

func TestRemoteMetadataAbortedAttemptDoesNotReplacePreviousCompleteInventory(t *testing.T) {
	ctx := context.Background()
	fixture := newGoogleRemoteFixture(t, "account-A", false)
	baseline := fixture.snapshot(
		remoteMetadataEntry("managed", corpus.EntryOther, 0, 0, fixture.base),
		remoteMetadataEntry("child", corpus.EntryRegularFile, 7, 0, fixture.base.Add(time.Second)),
	)
	first, _, err := ingest.MaterializeRemoteMetadata(ctx, fixture.store, fixture.projection, baseline, fixture.base.Add(time.Minute))
	if err != nil {
		t.Fatal(err)
	}

	// Advance to a new exact provider-history boundary before changing metadata.
	// A different fingerprint for the same publication is a conflict by contract;
	// an interrupted newer publication is the valid authority-preservation case.
	cycle := gdrive.ChangeCycleBundle{
		History: remotehistory.ChangeCycle{
			StreamID:       fixture.scope.StreamID,
			Status:         remotehistory.CycleComplete,
			PreviousCursor: "cursor-1",
			NextCursor:     "cursor-2",
			Coverage:       corpus.ProviderHistoryContinuous,
		},
	}
	if _, err := fixture.store.PublishGoogleDriveRemoteHistoryCycle(
		ctx,
		fixture.generation.ID,
		fixture.scope,
		fixture.scopeFingerprint,
		1,
		"cursor-1",
		cycle,
		fixture.base.Add(90*time.Second),
	); err != nil {
		t.Fatal(err)
	}

	changed := fixture.snapshot(
		remoteMetadataEntry("managed", corpus.EntryOther, 0, 0, fixture.base),
		remoteMetadataEntry("child", corpus.EntryRegularFile, 99, 0, fixture.base.Add(time.Second)),
	)
	changed.PublicationSequence = 2
	failing := &failRemoteMaterializationStore{Store: fixture.store, failAfter: 1}
	failedScan, _, err := ingest.MaterializeRemoteMetadata(ctx, failing, fixture.projection, changed, fixture.base.Add(2*time.Minute))
	if !errors.Is(err, errInjectedRemotePersistence) {
		t.Fatalf("error=%v want injected persistence failure", err)
	}
	storedFailed, err := fixture.store.ScanSession(ctx, failedScan.ID)
	if err != nil {
		t.Fatal(err)
	}
	if storedFailed.Status != corpus.ScanAborted {
		t.Fatalf("failed scan status=%s want ABORTED", storedFailed.Status)
	}

	inventory, err := fixture.store.Inventory(ctx, gdrive.ProviderID, fixture.scanRoot)
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory) != 2 {
		t.Fatalf("inventory=%#v", inventory)
	}
	for _, item := range inventory {
		if item.ScanID != first.ID {
			t.Fatalf("ABORTED scan replaced prior COMPLETE authority: %#v", item)
		}
	}
}

func TestRemoteMetadataMatchingOpenScanIsNotAutoAborted(t *testing.T) {
	ctx := context.Background()
	fixture := newGoogleRemoteFixture(t, "account-A", false)
	snapshot := fixture.snapshot(
		remoteMetadataEntry("managed", corpus.EntryOther, 0, 0, fixture.base),
		remoteMetadataEntry("child", corpus.EntryRegularFile, 7, 0, fixture.base.Add(time.Second)),
	)

	// Simulate a process failure after the OPEN scan was durably created, while
	// recovery/abort also failed. The durable attempt therefore remains OPEN.
	stranded := &strandedOpenRemoteStore{Store: fixture.store}
	openScan, _, err := ingest.MaterializeRemoteMetadata(ctx, stranded, fixture.projection, snapshot, fixture.base.Add(time.Minute))
	if !errors.Is(err, errInjectedRemotePersistence) || !errors.Is(err, errInjectedRemoteAbort) {
		t.Fatalf("error=%v want persistence+abort failures", err)
	}
	stored, err := fixture.store.ScanSession(ctx, openScan.ID)
	if err != nil {
		t.Fatal(err)
	}
	if stored.Status != corpus.ScanOpen {
		t.Fatalf("stranded scan status=%s want OPEN", stored.Status)
	}

	// A later caller can prove that the exact source is still current, but it
	// cannot prove the prior worker is dead. It must not auto-abort the OPEN scan.
	replayedScan, replayed, err := ingest.MaterializeRemoteMetadata(ctx, fixture.store, fixture.projection, snapshot, fixture.base.Add(2*time.Minute))
	if !errors.Is(err, ingest.ErrRemoteMaterializationOpen) {
		t.Fatalf("error=%v want ErrRemoteMaterializationOpen", err)
	}
	if !replayed || replayedScan.ID != openScan.ID {
		t.Fatalf("OPEN reconciliation scan=%#v replayed=%v want %s", replayedScan, replayed, openScan.ID)
	}
	stored, err = fixture.store.ScanSession(ctx, openScan.ID)
	if err != nil {
		t.Fatal(err)
	}
	if stored.Status != corpus.ScanOpen {
		t.Fatalf("existing OPEN scan was mutated by replay: %#v", stored)
	}

	// Recovery is explicit. Once ownership/death is established by the caller,
	// the ordinary durable abort primitive releases the provider/root boundary.
	if err := fixture.store.AbortScan(ctx, openScan.ID, fixture.base.Add(3*time.Minute)); err != nil {
		t.Fatal(err)
	}
}

func TestRemoteMetadataCompleteReplaySurvivesHistoryAdvance(t *testing.T) {
	ctx := context.Background()
	fixture := newGoogleRemoteFixture(t, "account-A", false)
	snapshot := fixture.snapshot(
		remoteMetadataEntry("managed", corpus.EntryOther, 0, 0, fixture.base),
		remoteMetadataEntry("child", corpus.EntryRegularFile, 7, 0, fixture.base.Add(time.Second)),
	)
	first, _, err := ingest.MaterializeRemoteMetadata(ctx, fixture.store, fixture.projection, snapshot, fixture.base.Add(time.Minute))
	if err != nil {
		t.Fatal(err)
	}

	outside := remoteObjectState(fixture.scope, "outside")
	cycle := gdrive.ChangeCycleBundle{
		History: remotehistory.ChangeCycle{
			StreamID:       fixture.scope.StreamID,
			Status:         remotehistory.CycleComplete,
			PreviousCursor: "cursor-1",
			NextCursor:     "cursor-2",
			Coverage:       corpus.ProviderHistoryContinuous,
			Changes: []remotehistory.RemoteChange{{
				Kind:     remotehistory.ChangeUpsert,
				ObjectID: "outside",
				State:    &outside,
			}},
		},
		Topology: []gdrive.TopologyState{topologyPresentRemote("outside", corpus.ProviderObjectID(fixture.scope.Root))},
	}
	if _, err := fixture.store.PublishGoogleDriveRemoteHistoryCycle(
		ctx,
		fixture.generation.ID,
		fixture.scope,
		fixture.scopeFingerprint,
		1,
		"cursor-1",
		cycle,
		fixture.base.Add(90*time.Second),
	); err != nil {
		t.Fatal(err)
	}

	replayedScan, replayed, err := ingest.MaterializeRemoteMetadata(ctx, fixture.store, fixture.projection, snapshot, fixture.base.Add(2*time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	if !replayed || replayedScan.ID != first.ID {
		t.Fatalf("old COMPLETE source did not reconcile after history advance: scan=%#v replayed=%v", replayedScan, replayed)
	}
}

func TestRemoteMetadataMaterializationKeepsManagedRootsIndependent(t *testing.T) {
	ctx := context.Background()
	store, err := sqlitestate.Open(ctx, filepath.Join(t.TempDir(), "state.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	scope := remotehistory.Scope{
		ProviderID:     gdrive.ProviderID,
		IdentityDomain: "account-A",
		StreamID:       "stream-1",
		Root:           "drive-root",
	}
	topology := []gdrive.TopologyState{
		topologyPresentRemote("managed-a", corpus.ProviderObjectID(scope.Root)),
		topologyPresentRemote("managed-b", corpus.ProviderObjectID(scope.Root)),
		topologyPresentRemote("child-a", "managed-a"),
		topologyPresentRemote("child-b", "managed-b"),
	}
	objects := make([]remotehistory.RemoteObjectState, 0, len(topology))
	for _, state := range topology {
		objects = append(objects, remoteObjectState(scope, state.ObjectID))
	}
	bundle := gdrive.BootstrapBundle{
		History: remotehistory.BootstrapResult{
			StreamID: scope.StreamID,
			Status:   remotehistory.BootstrapComplete,
			Objects:  objects,
			Cursor:   "cursor-1",
			Coverage: corpus.ProviderHistoryContinuous,
		},
		Topology: topology,
	}
	base := time.Date(2026, 9, 26, 13, 0, 0, 0, time.UTC)
	fingerprint := remotehistory.ScopePolicyFingerprint("google-drive-history-universe:v1:test")
	generation, err := store.StartGoogleDriveRemoteHistoryGeneration(ctx, scope, fingerprint, bundle, base)
	if err != nil {
		t.Fatal(err)
	}
	for _, root := range []corpus.ProviderObjectID{"managed-a", "managed-b"} {
		if _, err := store.BindGoogleDriveManagedRoot(ctx, generation.ID, root, base.Add(time.Second)); err != nil {
			t.Fatal(err)
		}
	}

	projectionA, err := ingest.NewGoogleDriveManagedRootProjection(store, "managed-a")
	if err != nil {
		t.Fatal(err)
	}
	projectionB, err := ingest.NewGoogleDriveManagedRootProjection(store, "managed-b")
	if err != nil {
		t.Fatal(err)
	}
	rootA, err := ingest.GoogleDriveManagedRootScanRoot(scope.IdentityDomain, "managed-a")
	if err != nil {
		t.Fatal(err)
	}
	rootB, err := ingest.GoogleDriveManagedRootScanRoot(scope.IdentityDomain, "managed-b")
	if err != nil {
		t.Fatal(err)
	}
	if rootA == rootB {
		t.Fatalf("managed roots collapsed to one scan root: %q", rootA)
	}

	snapshotA := ingest.RemoteMetadataSnapshot{
		GenerationID:            generation.ID,
		PublicationSequence:     1,
		ScanRoot:                rootA,
		SourceScopeID:           "managed-a",
		MaterializationPolicyID: ingest.LightweightAllMaterializationPolicyID,
		Entries: []ingest.RemoteMetadataEntry{
			remoteMetadataEntry("managed-a", corpus.EntryOther, 0, 0, base),
			remoteMetadataEntry("child-a", corpus.EntryRegularFile, 10, 0, base.Add(time.Second)),
		},
	}
	scanA, replayed, err := ingest.MaterializeRemoteMetadata(ctx, store, projectionA, snapshotA, base.Add(time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	if replayed || scanA.Status != corpus.ScanComplete {
		t.Fatalf("root A materialization replayed=%v scan=%#v", replayed, scanA)
	}

	snapshotB := ingest.RemoteMetadataSnapshot{
		GenerationID:            generation.ID,
		PublicationSequence:     1,
		ScanRoot:                rootB,
		SourceScopeID:           "managed-b",
		MaterializationPolicyID: ingest.LightweightAllMaterializationPolicyID,
		Entries: []ingest.RemoteMetadataEntry{
			remoteMetadataEntry("managed-b", corpus.EntryOther, 0, 0, base),
			remoteMetadataEntry("child-b", corpus.EntryRegularFile, 20, 0, base.Add(2*time.Second)),
		},
	}
	scanB, replayed, err := ingest.MaterializeRemoteMetadata(ctx, store, projectionB, snapshotB, base.Add(2*time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	if replayed || scanB.Status != corpus.ScanComplete || scanB.ID == scanA.ID {
		t.Fatalf("root B materialization replayed=%v scan=%#v rootA=%s", replayed, scanB, scanA.ID)
	}

	inventoryA, err := store.Inventory(ctx, gdrive.ProviderID, rootA)
	if err != nil {
		t.Fatal(err)
	}
	inventoryB, err := store.Inventory(ctx, gdrive.ProviderID, rootB)
	if err != nil {
		t.Fatal(err)
	}
	if got, want := inventoryPathsRemote(inventoryA), []string{"file-id/child-a", "file-id/managed-a"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("root A inventory=%#v want %#v", got, want)
	}
	if got, want := inventoryPathsRemote(inventoryB), []string{"file-id/child-b", "file-id/managed-b"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("root B inventory=%#v want %#v", got, want)
	}
	for _, item := range inventoryA {
		if item.ScanID != scanA.ID {
			t.Fatalf("root B completion replaced root A authority: %#v", item)
		}
	}
	for _, item := range inventoryB {
		if item.ScanID != scanB.ID {
			t.Fatalf("root B inventory references wrong scan: %#v", item)
		}
	}
}

func TestGoogleDriveManagedRootScanRootSeparatesIdentityDomains(t *testing.T) {
	a, err := ingest.GoogleDriveManagedRootScanRoot("account-A", "same-root")
	if err != nil {
		t.Fatal(err)
	}
	b, err := ingest.GoogleDriveManagedRootScanRoot("account-B", "same-root")
	if err != nil {
		t.Fatal(err)
	}
	if a == b {
		t.Fatalf("same raw managed-root ID collided across identity domains: %q", a)
	}
	a2, err := ingest.GoogleDriveManagedRootScanRoot("account-A", "same-root")
	if err != nil {
		t.Fatal(err)
	}
	if a2 != a {
		t.Fatalf("canonical Google scan root is not deterministic: %q != %q", a2, a)
	}
}

type googleRemoteFixture struct {
	store            *sqlitestate.Store
	projection       *ingest.GoogleDriveManagedRootProjection
	generation       remotehistory.HistoryGeneration
	scope            remotehistory.Scope
	scopeFingerprint remotehistory.ScopePolicyFingerprint
	scanRoot         string
	base             time.Time
}

func newGoogleRemoteFixture(t *testing.T, identityDomain string, includeUnknown bool) googleRemoteFixture {
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

	scope := remotehistory.Scope{
		ProviderID:     gdrive.ProviderID,
		IdentityDomain: identityDomain,
		StreamID:       "stream-1",
		Root:           "drive-root",
	}
	topology := []gdrive.TopologyState{
		topologyPresentRemote("managed", corpus.ProviderObjectID(scope.Root)),
		topologyPresentRemote("child", "managed"),
		topologyPresentRemote("outside", corpus.ProviderObjectID(scope.Root)),
	}
	if includeUnknown {
		topology = append(topology, gdrive.TopologyState{
			ObjectID:        "unknown",
			Presence:        gdrive.TopologyPresent,
			ParentKnowledge: gdrive.ParentUnknown,
		})
	}
	objects := make([]remotehistory.RemoteObjectState, 0, len(topology))
	for _, state := range topology {
		objects = append(objects, remoteObjectState(scope, state.ObjectID))
	}
	bundle := gdrive.BootstrapBundle{
		History: remotehistory.BootstrapResult{
			StreamID: scope.StreamID,
			Status:   remotehistory.BootstrapComplete,
			Objects:  objects,
			Cursor:   "cursor-1",
			Coverage: corpus.ProviderHistoryContinuous,
		},
		Topology: topology,
	}
	base := time.Date(2026, 9, 26, 12, 0, 0, 0, time.UTC)
	fingerprint := remotehistory.ScopePolicyFingerprint("google-drive-history-universe:v1:test")
	generation, err := store.StartGoogleDriveRemoteHistoryGeneration(ctx, scope, fingerprint, bundle, base)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.BindGoogleDriveManagedRoot(ctx, generation.ID, "managed", base.Add(time.Second)); err != nil {
		t.Fatal(err)
	}
	projection, err := ingest.NewGoogleDriveManagedRootProjection(store, "managed")
	if err != nil {
		t.Fatal(err)
	}
	scanRoot, err := ingest.GoogleDriveManagedRootScanRoot(scope.IdentityDomain, "managed")
	if err != nil {
		t.Fatal(err)
	}
	return googleRemoteFixture{
		store:            store,
		projection:       projection,
		generation:       generation,
		scope:            scope,
		scopeFingerprint: fingerprint,
		scanRoot:         scanRoot,
		base:             base,
	}
}

func (f googleRemoteFixture) snapshot(entries ...ingest.RemoteMetadataEntry) ingest.RemoteMetadataSnapshot {
	return ingest.RemoteMetadataSnapshot{
		GenerationID:            f.generation.ID,
		PublicationSequence:     1,
		ScanRoot:                f.scanRoot,
		SourceScopeID:           "managed",
		MaterializationPolicyID: ingest.LightweightAllMaterializationPolicyID,
		Entries:                 entries,
	}
}

func remoteObjectState(scope remotehistory.Scope, objectID corpus.ProviderObjectID) remotehistory.RemoteObjectState {
	return remotehistory.RemoteObjectState{
		ObjectID: objectID,
		Locators: []corpus.Locator{{
			ProviderID: scope.ProviderID,
			Root:       scope.Root,
			Path:       "file-id/" + string(objectID),
		}},
	}
}

func topologyPresentRemote(objectID, parentID corpus.ProviderObjectID) gdrive.TopologyState {
	return gdrive.TopologyState{
		ObjectID:        objectID,
		Presence:        gdrive.TopologyPresent,
		ParentKnowledge: gdrive.ParentKnown,
		ParentObjectID:  parentID,
	}
}

func remoteMetadataEntry(
	objectID corpus.ProviderObjectID,
	kind corpus.EntryKind,
	size int64,
	mode uint32,
	modifiedAt time.Time,
) ingest.RemoteMetadataEntry {
	s := size
	m := mode
	at := modifiedAt
	return ingest.RemoteMetadataEntry{
		ProviderObjectID: objectID,
		Kind:             kind,
		Size:             &s,
		Mode:             &m,
		ModifiedAt:       &at,
	}
}

func inventoryPathsRemote(entries []corpus.InventoryEntry) []string {
	out := make([]string, len(entries))
	for i := range entries {
		out[i] = entries[i].Locator.Path
	}
	sort.Strings(out)
	return out
}

type strandedOpenRemoteStore struct {
	*sqlitestate.Store
}

var errInjectedRemoteAbort = errors.New("injected remote abort failure")

func (s *strandedOpenRemoteStore) RecordObservationInScan(context.Context, corpus.ScanSessionID, corpus.ObservationRecordInput) (corpus.ObservationRecord, error) {
	return corpus.ObservationRecord{}, errInjectedRemotePersistence
}

func (s *strandedOpenRemoteStore) AbortScan(context.Context, corpus.ScanSessionID, time.Time) error {
	return errInjectedRemoteAbort
}

type failRemoteMaterializationStore struct {
	*sqlitestate.Store
	failAfter int
	writes    int
}

var errInjectedRemotePersistence = errors.New("injected remote persistence failure")

func (s *failRemoteMaterializationStore) RecordObservationInScan(
	ctx context.Context,
	scanID corpus.ScanSessionID,
	input corpus.ObservationRecordInput,
) (corpus.ObservationRecord, error) {
	if s.writes >= s.failAfter {
		return corpus.ObservationRecord{}, errInjectedRemotePersistence
	}
	s.writes++
	return s.Store.RecordObservationInScan(ctx, scanID, input)
}
