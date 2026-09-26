package sqlitestate

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory/gdrive"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestGoogleRemoteMetadataCompletionRevalidatesExactInSet(t *testing.T) {
	fixture := newGoogleRemoteCompletionFixture(t)

	entries := []remotehistory.RemoteMetadataFingerprintEntry{
		fixture.entry("managed", corpus.EntryOther, 0, fixture.base),
	}
	scan, err := fixture.startScan(entries, fixture.scanRoot)
	if err != nil {
		t.Fatal(err)
	}
	if err := fixture.record(scan.ID, entries[0]); err != nil {
		t.Fatal(err)
	}

	if _, _, err := fixture.store.CompleteRemoteHistoryScan(
		context.Background(),
		scan.ID,
		fixture.base.Add(2*time.Minute),
	); !errors.Is(err, ErrRemoteHistoryScanProviderScopeMismatch) {
		t.Fatalf("completion error=%v want ErrRemoteHistoryScanProviderScopeMismatch", err)
	}
	stored, err := fixture.store.ScanSession(context.Background(), scan.ID)
	if err != nil {
		t.Fatal(err)
	}
	if stored.Status != corpus.ScanOpen {
		t.Fatalf("failed exact-IN completion mutated scan: %#v", stored)
	}
	if err := fixture.store.AbortScan(context.Background(), scan.ID, fixture.base.Add(3*time.Minute)); err != nil {
		t.Fatal(err)
	}
}

func TestGoogleRemoteMetadataCompletionRejectsMissingTopologyWatermark(t *testing.T) {
	fixture := newGoogleRemoteCompletionFixture(t)
	entries := []remotehistory.RemoteMetadataFingerprintEntry{
		fixture.entry("managed", corpus.EntryOther, 0, fixture.base),
		fixture.entry("child", corpus.EntryRegularFile, 7, fixture.base.Add(time.Second)),
	}
	scan, err := fixture.startScan(entries, fixture.scanRoot)
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range entries {
		if err := fixture.record(scan.ID, entry); err != nil {
			t.Fatal(err)
		}
	}

	conn, err := fixture.store.pool.Get(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	err = sqlitex.Execute(conn,
		"DELETE FROM gdrive_topology_watermarks WHERE generation_id=?1",
		&sqlitex.ExecOptions{Args: []any{string(fixture.generation.ID)}})
	fixture.store.pool.Put(conn)
	if err != nil {
		t.Fatal(err)
	}

	if _, _, err := fixture.store.CompleteRemoteHistoryScan(
		context.Background(),
		scan.ID,
		fixture.base.Add(2*time.Minute),
	); !errors.Is(err, ErrRemoteHistoryScanProviderScopeMismatch) {
		t.Fatalf("completion error=%v want ErrRemoteHistoryScanProviderScopeMismatch", err)
	}
	if err := fixture.store.AbortScan(context.Background(), scan.ID, fixture.base.Add(3*time.Minute)); err != nil {
		t.Fatal(err)
	}
}

func TestGoogleRemoteMetadataCompletionRejectsNoncanonicalLocatorProjection(t *testing.T) {
	fixture := newGoogleRemoteCompletionFixture(t)
	entries := []remotehistory.RemoteMetadataFingerprintEntry{
		fixture.entry("managed", corpus.EntryOther, 0, fixture.base),
		fixture.entry("child", corpus.EntryRegularFile, 7, fixture.base.Add(time.Second)),
	}
	entries[1].Locators[0].Path = "file-id/not-child"
	scan, err := fixture.startScan(entries, fixture.scanRoot)
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range entries {
		if err := fixture.record(scan.ID, entry); err != nil {
			t.Fatal(err)
		}
	}
	if _, _, err := fixture.store.CompleteRemoteHistoryScan(
		context.Background(),
		scan.ID,
		fixture.base.Add(2*time.Minute),
	); !errors.Is(err, ErrRemoteHistoryScanProviderScopeMismatch) {
		t.Fatalf("completion error=%v want ErrRemoteHistoryScanProviderScopeMismatch", err)
	}
	if err := fixture.store.AbortScan(context.Background(), scan.ID, fixture.base.Add(3*time.Minute)); err != nil {
		t.Fatal(err)
	}
}

func TestGoogleFileIDLocatorPathEscapesNativeObjectID(t *testing.T) {
	got := gdrive.FileIDLocatorPath("a/b %")
	want := "file-id/a%2Fb%20%25"
	if got != want {
		t.Fatalf("locator path=%q want %q", got, want)
	}
}

func TestGoogleRemoteMetadataCompletionRejectsNoncanonicalManagedRootKey(t *testing.T) {
	fixture := newGoogleRemoteCompletionFixture(t)
	badRoot := "google-drive:managed-root:v1:not-canonical"
	entries := []remotehistory.RemoteMetadataFingerprintEntry{
		{
			ProviderObjectID: "managed",
			Locators: []corpus.Locator{{
				ProviderID: gdrive.ProviderID,
				Root:       badRoot,
				Path:       "file-id/managed",
			}},
			Kind:       corpus.EntryOther,
			Size:       0,
			Mode:       0,
			ModifiedAt: fixture.base.Format(time.RFC3339Nano),
		},
		{
			ProviderObjectID: "child",
			Locators: []corpus.Locator{{
				ProviderID: gdrive.ProviderID,
				Root:       badRoot,
				Path:       "file-id/child",
			}},
			Kind:       corpus.EntryRegularFile,
			Size:       7,
			Mode:       0,
			ModifiedAt: fixture.base.Add(time.Second).Format(time.RFC3339Nano),
		},
	}
	scan, err := fixture.startScan(entries, badRoot)
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range entries {
		if err := fixture.record(scan.ID, entry); err != nil {
			t.Fatal(err)
		}
	}
	if _, _, err := fixture.store.CompleteRemoteHistoryScan(
		context.Background(),
		scan.ID,
		fixture.base.Add(2*time.Minute),
	); !errors.Is(err, ErrRemoteHistoryScanProviderScopeMismatch) {
		t.Fatalf("completion error=%v want ErrRemoteHistoryScanProviderScopeMismatch", err)
	}
	if err := fixture.store.AbortScan(context.Background(), scan.ID, fixture.base.Add(3*time.Minute)); err != nil {
		t.Fatal(err)
	}
}

type googleRemoteCompletionFixture struct {
	store      *Store
	generation remotehistory.HistoryGeneration
	scanRoot   string
	base       time.Time
}

func newGoogleRemoteCompletionFixture(t *testing.T) googleRemoteCompletionFixture {
	t.Helper()
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := googleTopologyTestScope()
	fp := remotehistory.ScopePolicyFingerprint("google-drive-history-universe:v1:test")
	base := time.Date(2026, 9, 27, 18, 0, 0, 0, time.UTC)
	generation, err := store.StartGoogleDriveRemoteHistoryGeneration(
		ctx,
		scope,
		fp,
		googleMembershipBootstrapBundle(scope, []gdrive.TopologyState{
			topologyPresent("managed", corpus.ProviderObjectID(scope.Root)),
			topologyPresent("child", "managed"),
		}),
		base,
	)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.BindGoogleDriveManagedRoot(ctx, generation.ID, "managed", base.Add(time.Second)); err != nil {
		t.Fatal(err)
	}
	scanRoot, err := gdrive.ManagedRootScanRoot(scope.IdentityDomain, "managed")
	if err != nil {
		t.Fatal(err)
	}
	return googleRemoteCompletionFixture{
		store:      store,
		generation: generation,
		scanRoot:   scanRoot,
		base:       base,
	}
}

func (f googleRemoteCompletionFixture) entry(
	objectID corpus.ProviderObjectID,
	kind corpus.EntryKind,
	size int64,
	modifiedAt time.Time,
) remotehistory.RemoteMetadataFingerprintEntry {
	return remotehistory.RemoteMetadataFingerprintEntry{
		ProviderObjectID: objectID,
		Locators: []corpus.Locator{{
			ProviderID: gdrive.ProviderID,
			Root:       f.scanRoot,
			Path:       gdrive.FileIDLocatorPath(objectID),
		}},
		Kind:       kind,
		Size:       size,
		Mode:       0,
		ModifiedAt: modifiedAt.UTC().Format(time.RFC3339Nano),
	}
}

func (f googleRemoteCompletionFixture) startScan(
	entries []remotehistory.RemoteMetadataFingerprintEntry,
	scanRoot string,
) (corpus.ScanSession, error) {
	fingerprintEntries := make([]remotehistory.RemoteMetadataFingerprintEntry, len(entries))
	copy(fingerprintEntries, entries)
	fingerprint, err := remotehistory.FingerprintRemoteMetadataSnapshot(remotehistory.RemoteMetadataFingerprintInput{
		GenerationID:            f.generation.ID,
		PublicationSequence:     1,
		ProviderID:              gdrive.ProviderID,
		ScanRoot:                scanRoot,
		SourceScopeID:           "managed",
		MaterializationPolicyID: remotehistory.LightweightAllMaterializationPolicyID,
		Entries:                 fingerprintEntries,
	})
	if err != nil {
		return corpus.ScanSession{}, err
	}
	scan, _, err := f.store.StartRemoteHistoryScan(
		context.Background(),
		scanRoot,
		remotehistory.RemoteScanSourceInput{
			GenerationID:               f.generation.ID,
			PublicationSequence:        1,
			SourceScopeID:              "managed",
			MaterializationPolicyID:    remotehistory.LightweightAllMaterializationPolicyID,
			SnapshotFingerprintVersion: remotehistory.RemoteMetadataSnapshotFingerprintVersion,
			SnapshotFingerprintSHA256:  fingerprint,
		},
		f.base.Add(time.Minute),
	)
	return scan, err
}

func (f googleRemoteCompletionFixture) record(
	scanID corpus.ScanSessionID,
	entry remotehistory.RemoteMetadataFingerprintEntry,
) error {
	modifiedAt, err := time.Parse(time.RFC3339Nano, entry.ModifiedAt)
	if err != nil {
		return err
	}
	_, err = f.store.RecordObservationInScan(context.Background(), scanID, corpus.ObservationRecordInput{
		ProviderObject: corpus.ProviderObject{
			ProviderID:    gdrive.ProviderID,
			ID:            entry.ProviderObjectID,
			IdentityState: corpus.ObjectIdentityObserved,
		},
		Locators:        append([]corpus.Locator(nil), entry.Locators...),
		AssignmentState: corpus.AssignmentUnresolved,
		ObservedAt:      f.base.Add(time.Minute),
		Kind:            entry.Kind,
		Size:            entry.Size,
		Mode:            entry.Mode,
		ModifiedAt:      modifiedAt,
	})
	return err
}
