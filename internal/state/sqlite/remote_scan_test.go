package sqlitestate

import (
	"context"
	"errors"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory/gdrive"
	"zombiezen.com/go/sqlite/sqlitex"
)

const (
	remoteScanFingerprintA = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	remoteScanFingerprintB = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
)

func TestRemoteHistoryScanRejectsStartBeforeSourcePublication(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")
	base := time.Date(2026, 9, 27, 21, 0, 0, 0, time.UTC)
	generation, err := store.StartRemoteHistoryGeneration(
		ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), base,
	)
	if err != nil {
		t.Fatal(err)
	}
	source := remoteScanSourceInput(generation.ID, 1, "scope", remoteScanFingerprintA)
	if _, _, err := store.StartRemoteHistoryScan(
		ctx, "managed-root", source, base.Add(-time.Nanosecond),
	); !errors.Is(err, ErrRemoteHistoryScanStartedBeforeSource) {
		t.Fatalf("start error=%v want ErrRemoteHistoryScanStartedBeforeSource", err)
	}
	scan, replayed, err := store.StartRemoteHistoryScan(ctx, "managed-root", source, base)
	if err != nil {
		t.Fatal(err)
	}
	if replayed || !scan.StartedAt.Equal(base) {
		t.Fatalf("equal-time source start replayed=%v scan=%#v", replayed, scan)
	}
	if err := store.AbortScan(ctx, scan.ID, base); err != nil {
		t.Fatal(err)
	}
}

func TestRemoteScanSourceSQLiteRejectsScanBeforeSourcePublication(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")
	base := time.Date(2026, 9, 27, 21, 30, 0, 0, time.UTC)
	generation, err := store.StartRemoteHistoryGeneration(
		ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), base,
	)
	if err != nil {
		t.Fatal(err)
	}
	scan, err := store.StartScan(ctx, scope.ProviderID, "managed-root", base.Add(-time.Nanosecond))
	if err != nil {
		t.Fatal(err)
	}
	source := remoteScanSourceInput(generation.ID, 1, "scope", remoteScanFingerprintA)
	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	err = sqlitex.Execute(conn,
		"INSERT INTO remote_scan_sources (scan_id,generation_id,publication_sequence,source_scope_id,materialization_policy_id,snapshot_fingerprint_version,snapshot_fingerprint_sha256) VALUES (?1,?2,?3,?4,?5,?6,?7)",
		&sqlitex.ExecOptions{Args: []any{
			string(scan.ID),
			string(source.GenerationID),
			int64(source.PublicationSequence),
			source.SourceScopeID,
			source.MaterializationPolicyID,
			source.SnapshotFingerprintVersion,
			source.SnapshotFingerprintSHA256,
		}})
	store.pool.Put(conn)
	if err == nil {
		t.Fatal("direct SQL pre-publication remote scan source unexpectedly succeeded")
	}
	if err := store.AbortScan(ctx, scan.ID, base); err != nil {
		t.Fatal(err)
	}
}

func TestRemoteHistoryScanStartReplayGuardedCompleteAndReconcile(t *testing.T) {
	ctx := context.Background()
	fixture, scan, source := qualifiedGoogleRemoteScan(t)
	store := fixture.store
	base := fixture.base
	scanRoot := fixture.scanRoot

	if scan.Status != corpus.ScanOpen {
		t.Fatalf("start scan=%#v", scan)
	}
	storedSource, err := store.RemoteHistoryScanSource(ctx, scan.ID)
	if err != nil {
		t.Fatal(err)
	}
	if storedSource != source {
		t.Fatalf("source=%#v want=%#v", storedSource, source)
	}
	state, err := store.ReconcileRemoteHistoryScan(ctx, scan.ID)
	if err != nil {
		t.Fatal(err)
	}
	if state != remotehistory.RemoteScanSourceCurrent {
		t.Fatalf("source state=%q want CURRENT", state)
	}

	replayedScan, replayed, err := store.StartRemoteHistoryScan(ctx, scanRoot, source.RemoteScanSourceInput, base.Add(90*time.Second))
	if err != nil {
		t.Fatal(err)
	}
	if !replayed || replayedScan.ID != scan.ID {
		t.Fatalf("OPEN replay scan=%#v replayed=%v", replayedScan, replayed)
	}

	if err := store.CompleteScan(ctx, scan.ID, base.Add(2*time.Minute)); !errors.Is(err, ErrRemoteHistoryScanRequiresGuardedCompletion) {
		t.Fatalf("generic complete error=%v", err)
	}
	stillOpen, err := store.ScanSession(ctx, scan.ID)
	if err != nil {
		t.Fatal(err)
	}
	if stillOpen.Status != corpus.ScanOpen {
		t.Fatalf("generic complete mutated source-bound scan: %#v", stillOpen)
	}

	completed, replayed, err := store.CompleteRemoteHistoryScan(ctx, scan.ID, base.Add(2*time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	if replayed || completed.Status != corpus.ScanComplete {
		t.Fatalf("remote complete=%#v replayed=%v", completed, replayed)
	}
	completedAgain, replayed, err := store.CompleteRemoteHistoryScan(ctx, scan.ID, base.Add(3*time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	if !replayed || completedAgain.ID != scan.ID || completedAgain.Status != corpus.ScanComplete {
		t.Fatalf("complete replay=%#v replayed=%v", completedAgain, replayed)
	}

	cycle := gdrive.ChangeCycleBundle{History: remotehistory.ChangeCycle{
		StreamID:       fixture.generation.Scope.StreamID,
		Status:         remotehistory.CycleComplete,
		PreviousCursor: "cursor-1",
		NextCursor:     "cursor-2",
		Coverage:       corpus.ProviderHistoryContinuous,
	}}
	if _, err := store.PublishGoogleDriveRemoteHistoryCycle(
		ctx,
		fixture.generation.ID,
		fixture.generation.Scope,
		remotehistory.ScopePolicyFingerprint("google-drive-history-universe:v1:test"),
		1,
		"cursor-1",
		cycle,
		base.Add(4*time.Minute),
	); err != nil {
		t.Fatal(err)
	}
	state, err = store.ReconcileRemoteHistoryScan(ctx, scan.ID)
	if err != nil {
		t.Fatal(err)
	}
	if state != remotehistory.RemoteScanSourceAdvanced {
		t.Fatalf("completed scan source state=%q want ADVANCED", state)
	}

	timeoutReplay, replayed, err := store.StartRemoteHistoryScan(ctx, scanRoot, source.RemoteScanSourceInput, base.Add(5*time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	if !replayed || timeoutReplay.ID != scan.ID || timeoutReplay.Status != corpus.ScanComplete {
		t.Fatalf("post-advance COMPLETE replay=%#v replayed=%v", timeoutReplay, replayed)
	}
}

func TestRemoteHistoryScanAdvanceBlocksCompletionAbortAllowsNewCurrentAttempt(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")
	base := time.Date(2026, 9, 27, 6, 0, 0, 0, time.UTC)
	generation, err := store.StartRemoteHistoryGeneration(
		ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), base,
	)
	if err != nil {
		t.Fatal(err)
	}
	scanRoot := "drive:user-1:managed:managed-b"
	source1 := remoteScanSourceInput(generation.ID, 1, "managed-b", remoteScanFingerprintA)
	scan1, _, err := store.StartRemoteHistoryScan(ctx, scanRoot, source1, base.Add(time.Second))
	if err != nil {
		t.Fatal(err)
	}

	conflict := remoteScanSourceInput(generation.ID, 1, "managed-b", remoteScanFingerprintB)
	if _, _, err := store.StartRemoteHistoryScan(ctx, scanRoot, conflict, base.Add(2*time.Second)); !errors.Is(err, ErrRemoteHistoryScanSourceConflict) {
		t.Fatalf("different source while OPEN error=%v", err)
	}

	cycle := remotehistory.ChangeCycle{
		StreamID:       scope.StreamID,
		Status:         remotehistory.CycleComplete,
		PreviousCursor: "cursor-1",
		NextCursor:     "cursor-2",
		Coverage:       corpus.ProviderHistoryContinuous,
	}
	generation, err = store.PublishRemoteHistoryCycle(
		ctx, generation.ID, scope, fp, 1, "cursor-1", cycle, base.Add(3*time.Second),
	)
	if err != nil {
		t.Fatal(err)
	}
	state, err := store.ReconcileRemoteHistoryScan(ctx, scan1.ID)
	if err != nil {
		t.Fatal(err)
	}
	if state != remotehistory.RemoteScanSourceAdvanced {
		t.Fatalf("state=%q want ADVANCED", state)
	}
	if _, _, err := store.CompleteRemoteHistoryScan(ctx, scan1.ID, base.Add(4*time.Second)); !errors.Is(err, ErrRemoteHistoryScanSourceAdvanced) {
		t.Fatalf("completion after source advance error=%v", err)
	}
	got, err := store.ScanSession(ctx, scan1.ID)
	if err != nil {
		t.Fatal(err)
	}
	if got.Status != corpus.ScanOpen {
		t.Fatalf("failed completion mutated scan: %#v", got)
	}
	if err := store.AbortScan(ctx, scan1.ID, base.Add(5*time.Second)); err != nil {
		t.Fatal(err)
	}

	source2 := remoteScanSourceInput(generation.ID, 2, "managed-b", remoteScanFingerprintB)
	scan2, replayed, err := store.StartRemoteHistoryScan(ctx, scanRoot, source2, base.Add(6*time.Second))
	if err != nil {
		t.Fatal(err)
	}
	if replayed || scan2.ID == scan1.ID {
		t.Fatalf("new current attempt scan=%#v replayed=%v", scan2, replayed)
	}

	gap := remotehistory.ChangeCycle{
		StreamID:       scope.StreamID,
		Status:         remotehistory.CycleGap,
		PreviousCursor: "cursor-2",
		NextCursor:     "cursor-2",
		Coverage:       corpus.ProviderHistoryUnknown,
	}
	if _, err := store.CloseRemoteHistoryGeneration(
		ctx, generation.ID, scope, fp, 2, "cursor-2", gap, base.Add(7*time.Second),
	); err != nil {
		t.Fatal(err)
	}
	state, err = store.ReconcileRemoteHistoryScan(ctx, scan2.ID)
	if err != nil {
		t.Fatal(err)
	}
	if state != remotehistory.RemoteScanSourceClosed {
		t.Fatalf("closed source state=%q", state)
	}
	if _, _, err := store.CompleteRemoteHistoryScan(ctx, scan2.ID, base.Add(8*time.Second)); !errors.Is(err, ErrRemoteHistoryScanSourceClosed) {
		t.Fatalf("completion from closed generation error=%v", err)
	}
	if err := store.AbortScan(ctx, scan2.ID, base.Add(9*time.Second)); err != nil {
		t.Fatal(err)
	}
}

func TestRemoteHistoryScanSourceIsImmutableAndSurvivesReopen(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "state.db")
	store, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")
	base := time.Date(2026, 9, 27, 7, 0, 0, 0, time.UTC)
	generation, err := store.StartRemoteHistoryGeneration(
		ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), base,
	)
	if err != nil {
		t.Fatal(err)
	}
	source := remoteScanSourceInput(generation.ID, 1, "managed-c", remoteScanFingerprintA)
	scan, _, err := store.StartRemoteHistoryScan(
		ctx, "drive:user-1:managed:managed-c", source, base.Add(time.Second),
	)
	if err != nil {
		t.Fatal(err)
	}

	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"UPDATE remote_scan_sources SET source_scope_id='tamper' WHERE scan_id=?1",
		&sqlitex.ExecOptions{Args: []any{string(scan.ID)}}); err == nil {
		store.pool.Put(conn)
		t.Fatal("remote scan source update unexpectedly succeeded")
	}
	if err := sqlitex.Execute(conn,
		"DELETE FROM remote_scan_sources WHERE scan_id=?1",
		&sqlitex.ExecOptions{Args: []any{string(scan.ID)}}); err == nil {
		store.pool.Put(conn)
		t.Fatal("remote scan source delete unexpectedly succeeded")
	}
	store.pool.Put(conn)

	if err := store.Close(); err != nil {
		t.Fatal(err)
	}
	store, err = Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	reopened, err := store.RemoteHistoryScanSource(ctx, scan.ID)
	if err != nil {
		t.Fatal(err)
	}
	if reopened.ScanID != scan.ID || reopened.RemoteScanSourceInput != source {
		t.Fatalf("reopened source=%#v want=%#v", reopened, source)
	}
	reopenedScan, err := store.ScanSession(ctx, scan.ID)
	if err != nil {
		t.Fatal(err)
	}
	if reopenedScan.Status != corpus.ScanOpen {
		t.Fatalf("reopened scan=%#v", reopenedScan)
	}
}

func TestRemoteScanSourceInputValidationFailsClosed(t *testing.T) {
	valid := remoteScanSourceInput("hgen_x", 1, "scope", remoteScanFingerprintA)
	if err := remotehistory.ValidateRemoteScanSourceInput(valid); err != nil {
		t.Fatal(err)
	}
	cases := []remotehistory.RemoteScanSourceInput{
		{},
		{GenerationID: "hgen_x", PublicationSequence: 1, SourceScopeID: "scope", MaterializationPolicyID: "p", SnapshotFingerprintVersion: "v1", SnapshotFingerprintSHA256: "ABC"},
		{GenerationID: "hgen_x", PublicationSequence: 1, SourceScopeID: "scope", MaterializationPolicyID: "p", SnapshotFingerprintVersion: "v1", SnapshotFingerprintSHA256: "zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz"},
		{
			GenerationID: "hgen_x", PublicationSequence: 1, SourceScopeID: "scope",
			MaterializationPolicyID: "other-policy:v1",
			SnapshotFingerprintVersion: remotehistory.RemoteMetadataSnapshotFingerprintVersion,
			SnapshotFingerprintSHA256: remoteScanFingerprintA,
		},
		{
			GenerationID: "hgen_x", PublicationSequence: 1, SourceScopeID: "scope",
			MaterializationPolicyID: remotehistory.LightweightAllMaterializationPolicyID,
			SnapshotFingerprintVersion: "other-snapshot:v1",
			SnapshotFingerprintSHA256: remoteScanFingerprintA,
		},
		{
			GenerationID: "hgen_x", PublicationSequence: 1, SourceScopeID: "scope",
			MaterializationPolicyID: "other-policy:v1",
			SnapshotFingerprintVersion: "other-snapshot:v1",
			SnapshotFingerprintSHA256: remoteScanFingerprintA,
		},
	}
	for i, input := range cases {
		if err := remotehistory.ValidateRemoteScanSourceInput(input); err == nil {
			t.Fatalf("case %d unexpectedly validated: %#v", i, input)
		}
	}
}


func TestRemoteHistoryCompletionRejectsPersistedUnknownSourceContract(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")
	base := time.Date(2026, 9, 27, 8, 30, 0, 0, time.UTC)
	generation, err := store.StartRemoteHistoryGeneration(
		ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), base,
	)
	if err != nil {
		t.Fatal(err)
	}

	scan, err := store.StartScan(ctx, scope.ProviderID, "managed-unknown-contract", base.Add(time.Second))
	if err != nil {
		t.Fatal(err)
	}
	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	err = sqlitex.Execute(conn,
		"INSERT INTO remote_scan_sources (scan_id,generation_id,publication_sequence,source_scope_id,materialization_policy_id,snapshot_fingerprint_version,snapshot_fingerprint_sha256) VALUES (?1,?2,1,'managed-unknown','other-policy:v1','other-snapshot:v1',?3)",
		&sqlitex.ExecOptions{Args: []any{
			string(scan.ID),
			string(generation.ID),
			remoteScanFingerprintA,
		}})
	store.pool.Put(conn)
	if err != nil {
		t.Fatalf("seed historical unknown source contract: %v", err)
	}

	if _, _, err := store.CompleteRemoteHistoryScan(ctx, scan.ID, base.Add(2*time.Second)); !errors.Is(err, remotehistory.ErrInvalidRemoteScanSource) {
		t.Fatalf("completion error=%v, want ErrInvalidRemoteScanSource", err)
	}
	got, err := store.ScanSession(ctx, scan.ID)
	if err != nil {
		t.Fatal(err)
	}
	if got.Status != corpus.ScanOpen {
		t.Fatalf("scan status=%s, want OPEN after rejected unknown contract", got.Status)
	}
}


func TestRemoteHistoryScanSQLiteGuardsBoundSessionAuthority(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")
	base := time.Date(2026, 9, 27, 8, 0, 0, 0, time.UTC)
	generation, err := store.StartRemoteHistoryGeneration(
		ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), base,
	)
	if err != nil {
		t.Fatal(err)
	}
	source := remoteScanSourceInput(generation.ID, 1, "managed-guard", remoteScanFingerprintA)
	scanRoot := "drive:user-1:managed:managed-guard"
	scan, replayed, err := store.StartRemoteHistoryScan(ctx, scanRoot, source, base.Add(time.Second))
	if err != nil {
		t.Fatal(err)
	}
	if replayed {
		t.Fatal("new source-bound scan unexpectedly replayed")
	}

	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	tamper := []string{
		"UPDATE scan_sessions SET provider_id='tampered-provider' WHERE scan_id=?1",
		"UPDATE scan_sessions SET root='tampered-root' WHERE scan_id=?1",
		"UPDATE scan_sessions SET started_at='2026-01-01T00:00:00Z' WHERE scan_id=?1",
	}
	for _, query := range tamper {
		if err := sqlitex.Execute(conn, query, &sqlitex.ExecOptions{Args: []any{string(scan.ID)}}); err == nil {
			store.pool.Put(conn)
			t.Fatalf("source-bound scan provenance tamper unexpectedly succeeded: %s", query)
		}
	}
	store.pool.Put(conn)

	got, err := store.ScanSession(ctx, scan.ID)
	if err != nil {
		t.Fatal(err)
	}
	if got.ProviderID != scope.ProviderID || got.Root != scanRoot || !got.StartedAt.Equal(scan.StartedAt) || got.Status != corpus.ScanOpen {
		t.Fatalf("scan mutated after rejected provenance tamper: %#v", got)
	}

	cycle := remotehistory.ChangeCycle{
		StreamID:       scope.StreamID,
		Status:         remotehistory.CycleComplete,
		PreviousCursor: "cursor-1",
		NextCursor:     "cursor-2",
		Coverage:       corpus.ProviderHistoryContinuous,
	}
	if _, err := store.PublishRemoteHistoryCycle(
		ctx, generation.ID, scope, fp, 1, "cursor-1", cycle, base.Add(2*time.Second),
	); err != nil {
		t.Fatal(err)
	}

	conn, err = store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"UPDATE scan_sessions SET status='COMPLETE', finished_at=?1 WHERE scan_id=?2",
		&sqlitex.ExecOptions{Args: []any{
			base.Add(3 * time.Second).UTC().Format(time.RFC3339Nano),
			string(scan.ID),
		}}); err == nil {
		store.pool.Put(conn)
		t.Fatal("direct stale remote scan completion unexpectedly succeeded")
	}
	store.pool.Put(conn)

	got, err = store.ScanSession(ctx, scan.ID)
	if err != nil {
		t.Fatal(err)
	}
	if got.Status != corpus.ScanOpen {
		t.Fatalf("stale direct completion mutated scan: %#v", got)
	}

	if err := store.AbortScan(ctx, scan.ID, base.Add(4*time.Second)); err != nil {
		t.Fatal(err)
	}
	conn, err = store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"UPDATE scan_sessions SET status='OPEN', finished_at=NULL WHERE scan_id=?1",
		&sqlitex.ExecOptions{Args: []any{string(scan.ID)}}); err == nil {
		store.pool.Put(conn)
		t.Fatal("terminal source-bound scan rewrite unexpectedly succeeded")
	}
	store.pool.Put(conn)
}



func qualifiedGoogleRemoteScan(t *testing.T) (googleRemoteCompletionFixture, corpus.ScanSession, remotehistory.RemoteScanSource) {
	t.Helper()
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
	source, err := fixture.store.RemoteHistoryScanSource(context.Background(), scan.ID)
	if err != nil {
		t.Fatal(err)
	}
	return fixture, scan, source
}

func remoteScanSourceInput(
	generationID remotehistory.HistoryGenerationID,
	sequence remotehistory.HistoryPublicationSequence,
	scopeID string,
	fingerprint string,
) remotehistory.RemoteScanSourceInput {
	return remotehistory.RemoteScanSourceInput{
		GenerationID:               generationID,
		PublicationSequence:        sequence,
		SourceScopeID:              scopeID,
		MaterializationPolicyID:    remotehistory.LightweightAllMaterializationPolicyID,
		SnapshotFingerprintVersion: remotehistory.RemoteMetadataSnapshotFingerprintVersion,
		SnapshotFingerprintSHA256:  fingerprint,
	}
}
