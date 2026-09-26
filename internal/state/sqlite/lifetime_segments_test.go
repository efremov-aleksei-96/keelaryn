package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestLifetimeSegmentsTrackRemovalAndReappearanceInOrder(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")

	generation, err := store.StartRemoteHistoryGeneration(
		ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"),
		time.Date(2026, 9, 26, 12, 0, 0, 0, time.UTC),
	)
	if err != nil {
		t.Fatal(err)
	}
	segments, err := store.RemoteHistoryLifetimeSegments(ctx, generation.ID)
	if err != nil {
		t.Fatal(err)
	}
	if len(segments) != 2 {
		t.Fatalf("bootstrap segments=%#v", segments)
	}
	if segments[0].Status != remotehistory.LifetimeSegmentActive ||
		segments[0].StartKind != remotehistory.LifetimeSegmentStartBootstrap {
		t.Fatalf("bootstrap segment=%#v", segments[0])
	}
	if err := store.VerifyRemoteHistoryLifetimeSegments(ctx, generation.ID); err != nil {
		t.Fatal(err)
	}

	cycle := remotehistory.ChangeCycle{
		StreamID:       scope.StreamID,
		Status:         remotehistory.CycleComplete,
		PreviousCursor: "cursor-1",
		NextCursor:     "cursor-2",
		Coverage:       corpus.ProviderHistoryContinuous,
		Changes: []remotehistory.RemoteChange{
			historyUpsert(scope, "id-1", "a-v2.txt"),
			{Kind: remotehistory.ChangeRemoved, ObjectID: "id-1"},
			historyUpsert(scope, "id-1", "a-v3.txt"),
			{Kind: remotehistory.ChangeRemoved, ObjectID: "id-missing"},
		},
	}
	generation, err = store.PublishRemoteHistoryCycle(
		ctx, generation.ID, scope, fp, 1, "cursor-1", cycle,
		time.Date(2026, 9, 26, 12, 1, 0, 0, time.UTC),
	)
	if err != nil {
		t.Fatal(err)
	}
	if generation.CurrentSequence != 2 {
		t.Fatalf("sequence=%d", generation.CurrentSequence)
	}

	segments, err = store.RemoteHistoryLifetimeSegments(ctx, generation.ID)
	if err != nil {
		t.Fatal(err)
	}
	var id1 []remotehistory.ProviderObjectLifetimeSegment
	var missing int
	for _, segment := range segments {
		if segment.ProviderObjectID == "id-1" {
			id1 = append(id1, segment)
		}
		if segment.ProviderObjectID == "id-missing" {
			missing++
		}
	}
	if missing != 0 {
		t.Fatal("REMOVED while absent invented a lifetime segment")
	}
	if len(id1) != 2 {
		t.Fatalf("id-1 segments=%#v", id1)
	}
	first, second := id1[0], id1[1]
	if first.Status != remotehistory.LifetimeSegmentClosed ||
		first.ClosureReason != remotehistory.LifetimeSegmentClosedRemovedFromScope ||
		first.LastPresentPublicationSequence != 2 ||
		first.LastPresentChangeOrdinal == nil || *first.LastPresentChangeOrdinal != 0 ||
		first.EndPublicationSequence == nil || *first.EndPublicationSequence != 2 ||
		first.EndChangeOrdinal == nil || *first.EndChangeOrdinal != 1 {
		t.Fatalf("first segment=%#v", first)
	}
	if second.Status != remotehistory.LifetimeSegmentActive ||
		second.StartKind != remotehistory.LifetimeSegmentStartUpsert ||
		second.StartPublicationSequence != 2 ||
		second.StartChangeOrdinal == nil || *second.StartChangeOrdinal != 2 ||
		second.ID == first.ID {
		t.Fatalf("reappearance segment=%#v first=%#v", second, first)
	}
	if err := store.VerifyRemoteHistoryLifetimeSegments(ctx, generation.ID); err != nil {
		t.Fatal(err)
	}

	gap := remotehistory.ChangeCycle{
		StreamID:       scope.StreamID,
		Status:         remotehistory.CycleGap,
		PreviousCursor: "cursor-2",
		NextCursor:     "cursor-2",
		Coverage:       corpus.ProviderHistoryUnknown,
	}
	if _, err := store.CloseRemoteHistoryGeneration(
		ctx, generation.ID, scope, fp, 2, "cursor-2", gap,
		time.Date(2026, 9, 26, 12, 2, 0, 0, time.UTC),
	); err != nil {
		t.Fatal(err)
	}
	segments, err = store.RemoteHistoryLifetimeSegments(ctx, generation.ID)
	if err != nil {
		t.Fatal(err)
	}
	for _, segment := range segments {
		if segment.Status != remotehistory.LifetimeSegmentClosed {
			t.Fatalf("generation close left ACTIVE segment: %#v", segment)
		}
	}
	if id1After := findLatestLifetimeSegment(segments, "id-1"); id1After.ClosureReason != remotehistory.LifetimeSegmentClosedHistoryGeneration {
		t.Fatalf("current id-1 segment closure=%#v", id1After)
	}
	if err := store.VerifyRemoteHistoryLifetimeSegments(ctx, generation.ID); err != nil {
		t.Fatal(err)
	}
}

func TestLifetimeSegmentRebootstrapSameNativeIDGetsNewSegment(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")

	g1, err := store.StartRemoteHistoryGeneration(ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), time.Now())
	if err != nil {
		t.Fatal(err)
	}
	s1, err := store.RemoteHistoryLifetimeSegments(ctx, g1.ID)
	if err != nil {
		t.Fatal(err)
	}
	first := findLatestLifetimeSegment(s1, "id-1")

	gap := remotehistory.ChangeCycle{
		StreamID: scope.StreamID, Status: remotehistory.CycleGap,
		PreviousCursor: "cursor-1", NextCursor: "cursor-1",
		Coverage: corpus.ProviderHistoryUnknown,
	}
	if _, err := store.CloseRemoteHistoryGeneration(ctx, g1.ID, scope, fp, 1, "cursor-1", gap, time.Now().Add(time.Second)); err != nil {
		t.Fatal(err)
	}

	g2, err := store.StartRemoteHistoryGeneration(ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-9"), time.Now().Add(2*time.Second))
	if err != nil {
		t.Fatal(err)
	}
	s2, err := store.RemoteHistoryLifetimeSegments(ctx, g2.ID)
	if err != nil {
		t.Fatal(err)
	}
	second := findLatestLifetimeSegment(s2, "id-1")
	if first.ID == second.ID {
		t.Fatalf("rebootstrap reused segment ID %q", first.ID)
	}
	if first.ProviderObjectID != second.ProviderObjectID {
		t.Fatalf("test setup changed native identity: %#v %#v", first, second)
	}
}

func TestLifetimeSegmentProjectionSurvivesReopenAndVerifies(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "state.db")
	store, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")
	generation, err := store.StartRemoteHistoryGeneration(ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), time.Now())
	if err != nil {
		t.Fatal(err)
	}
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}

	store, err = Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.VerifyRemoteHistoryLifetimeSegments(ctx, generation.ID); err != nil {
		t.Fatal(err)
	}
	segments, err := store.RemoteHistoryLifetimeSegments(ctx, generation.ID)
	if err != nil {
		t.Fatal(err)
	}
	if len(segments) != 2 {
		t.Fatalf("reopened segments=%#v", segments)
	}
}

func TestLifetimeSegmentSQLiteProtectsIdentityAndClosedState(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")
	generation, err := store.StartRemoteHistoryGeneration(ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), time.Now())
	if err != nil {
		t.Fatal(err)
	}
	segments, err := store.RemoteHistoryLifetimeSegments(ctx, generation.ID)
	if err != nil {
		t.Fatal(err)
	}
	target := findLatestLifetimeSegment(segments, "id-1")

	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"UPDATE provider_object_lifetime_segments SET object_id='tampered' WHERE lifetime_segment_id=?1",
		&sqlitex.ExecOptions{Args: []any{string(target.ID)}}); err == nil {
		store.pool.Put(conn)
		t.Fatal("lifetime segment identity tamper unexpectedly succeeded")
	}
	if err := sqlitex.Execute(conn,
		"DELETE FROM provider_object_lifetime_segments WHERE lifetime_segment_id=?1",
		&sqlitex.ExecOptions{Args: []any{string(target.ID)}}); err == nil {
		store.pool.Put(conn)
		t.Fatal("lifetime segment delete unexpectedly succeeded")
	}
	store.pool.Put(conn)

	gap := remotehistory.ChangeCycle{
		StreamID: scope.StreamID, Status: remotehistory.CycleGap,
		PreviousCursor: "cursor-1", NextCursor: "cursor-1",
		Coverage: corpus.ProviderHistoryUnknown,
	}
	if _, err := store.CloseRemoteHistoryGeneration(ctx, generation.ID, scope, fp, 1, "cursor-1", gap, time.Now().Add(time.Second)); err != nil {
		t.Fatal(err)
	}
	conn, err = store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer store.pool.Put(conn)
	if err := sqlitex.Execute(conn,
		"UPDATE provider_object_lifetime_segments SET status='ACTIVE', end_sequence=NULL, end_ordinal=NULL, closure_reason=NULL WHERE lifetime_segment_id=?1",
		&sqlitex.ExecOptions{Args: []any{string(target.ID)}}); err == nil {
		t.Fatal("closed lifetime segment reopened through direct SQL")
	}
}

func TestLifetimeSegmentProjectionVerifierDetectsHistoryMismatch(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")
	generation, err := store.StartRemoteHistoryGeneration(ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), time.Now())
	if err != nil {
		t.Fatal(err)
	}

	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	// This update has a shape allowed for normal projection continuation, but
	// there is no matching immutable publication evidence. Reconstruction must
	// therefore detect the divergence.
	err = sqlitex.Execute(conn,
		"UPDATE provider_object_lifetime_segments SET last_present_sequence=2, last_present_ordinal=0 WHERE generation_id=?1 AND object_id='id-1'",
		&sqlitex.ExecOptions{Args: []any{string(generation.ID)}})
	store.pool.Put(conn)
	if err != nil {
		t.Fatalf("test projection drift injection failed: %v", err)
	}
	if err := store.VerifyRemoteHistoryLifetimeSegments(ctx, generation.ID); err == nil {
		t.Fatal("projection verifier failed to detect history mismatch")
	}
}

func findLatestLifetimeSegment(segments []remotehistory.ProviderObjectLifetimeSegment, objectID corpus.ProviderObjectID) remotehistory.ProviderObjectLifetimeSegment {
	var out remotehistory.ProviderObjectLifetimeSegment
	for _, segment := range segments {
		if segment.ProviderObjectID == objectID {
			out = segment
		}
	}
	return out
}
