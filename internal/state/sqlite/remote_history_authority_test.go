package sqlitestate

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestRemoteHistoryAuthorityProducerNewThenSameAfterLifetimeBinding(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")
	base := time.Date(2026, 9, 26, 14, 0, 0, 0, time.UTC)

	generation, err := store.StartRemoteHistoryGeneration(ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), base)
	if err != nil {
		t.Fatal(err)
	}
	segments, err := store.RemoteHistoryLifetimeSegments(ctx, generation.ID)
	if err != nil {
		t.Fatal(err)
	}
	segment := findLatestLifetimeSegment(segments, "id-1")

	first, err := store.CreateRemoteHistoryIdentityAuthority(ctx, generation.ID, segment.ID, base.Add(time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	if first.UniverseCoverage != corpus.CandidateUniverseComplete || len(first.Candidates) != 0 {
		t.Fatalf("unbound current segment authority=%#v", first)
	}
	if first.GenerationID != string(generation.ID) || first.LifetimeSegmentID != string(segment.ID) {
		t.Fatalf("authority lost history scope: %#v", first)
	}
	replay, err := store.CreateRemoteHistoryIdentityAuthority(ctx, generation.ID, segment.ID, base.Add(2*time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	if replay.ID != first.ID || !replay.CreatedAt.Equal(first.CreatedAt) {
		t.Fatalf("authority replay was not deterministic: first=%#v replay=%#v", first, replay)
	}

	artifact, err := store.AdoptArtifact(ctx)
	if err != nil {
		t.Fatal(err)
	}
	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	end, err := sqlitex.ImmediateTransaction(conn)
	if err != nil {
		store.pool.Put(conn)
		t.Fatal(err)
	}
	binding, created, bindErr := insertProviderLifetimeArtifactBindingConn(conn, ProviderLifetimeArtifactBinding{
		LifetimeSegmentID: segment.ID,
		ArtifactID:        artifact.ID,
		PolicyID:          remoteHistoryLifetimeAuthorityPolicyV1,
		AuthoritySetID:    first.ID,
		AcceptedAt:        base.Add(3 * time.Minute),
	})
	end(&bindErr)
	store.pool.Put(conn)
	if bindErr != nil {
		t.Fatal(bindErr)
	}
	if !created || binding.ArtifactID != artifact.ID {
		t.Fatalf("binding=%#v created=%v", binding, created)
	}

	second, err := store.CreateRemoteHistoryIdentityAuthority(ctx, generation.ID, segment.ID, base.Add(4*time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	if second.ID == first.ID {
		t.Fatal("binding-state change reused unbound authority ID")
	}
	if second.UniverseCoverage != corpus.CandidateUniverseUnknown || len(second.Candidates) != 1 {
		t.Fatalf("bound current segment authority=%#v", second)
	}
	if second.Candidates[0].ArtifactID != artifact.ID || second.Candidates[0].Direction != corpus.DirectionSupportsSame {
		t.Fatalf("SAME authority candidate=%#v", second.Candidates[0])
	}
	resolution, err := candidateResolutionFromAuthority(second)
	if err != nil {
		t.Fatal(err)
	}
	if resolution.State != corpus.CandidateSetResolvedSame || resolution.SelectedArtifactID != artifact.ID {
		t.Fatalf("resolution=%#v", resolution)
	}
}

func TestRemoteHistoryAuthorityPriorSegmentBindingBlocksAutoNew(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")
	base := time.Date(2026, 9, 26, 15, 0, 0, 0, time.UTC)

	g1, err := store.StartRemoteHistoryGeneration(ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), base)
	if err != nil {
		t.Fatal(err)
	}
	s1, _ := store.RemoteHistoryLifetimeSegments(ctx, g1.ID)
	oldSegment := findLatestLifetimeSegment(s1, "id-1")
	oldAuthority, err := store.CreateRemoteHistoryIdentityAuthority(ctx, g1.ID, oldSegment.ID, base.Add(time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	artifact, err := store.AdoptArtifact(ctx)
	if err != nil {
		t.Fatal(err)
	}
	seedLifetimeBinding(t, store, ProviderLifetimeArtifactBinding{
		LifetimeSegmentID: oldSegment.ID,
		ArtifactID: artifact.ID,
		PolicyID: remoteHistoryLifetimeAuthorityPolicyV1,
		AuthoritySetID: oldAuthority.ID,
		AcceptedAt: base.Add(2*time.Minute),
	})

	gap := remotehistory.ChangeCycle{
		StreamID: scope.StreamID,
		Status: remotehistory.CycleGap,
		PreviousCursor: "cursor-1",
		NextCursor: "cursor-1",
		Coverage: corpus.ProviderHistoryUnknown,
	}
	if _, err := store.CloseRemoteHistoryGeneration(ctx, g1.ID, scope, fp, 1, "cursor-1", gap, base.Add(3*time.Minute)); err != nil {
		t.Fatal(err)
	}
	g2, err := store.StartRemoteHistoryGeneration(ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-9"), base.Add(4*time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	s2, _ := store.RemoteHistoryLifetimeSegments(ctx, g2.ID)
	current := findLatestLifetimeSegment(s2, "id-1")
	authority, err := store.CreateRemoteHistoryIdentityAuthority(ctx, g2.ID, current.ID, base.Add(5*time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	if authority.UniverseCoverage != corpus.CandidateUniverseUnknown || len(authority.Candidates) != 0 {
		t.Fatalf("prior segment binding did not block auto-NEW: %#v", authority)
	}
	if !hasSourceRefPrefix(authority.SourceRefs, "prior-lifetime-binding:") {
		t.Fatalf("authority lacks prior binding provenance: %#v", authority.SourceRefs)
	}
	resolution, err := occurrenceResolutionFromAuthority(authority)
	if err != nil {
		t.Fatal(err)
	}
	if resolution.State != corpus.OccurrenceIdentityUnresolved {
		t.Fatalf("blocked authority unexpectedly resolved: %#v", resolution)
	}
}

func TestRemoteHistoryAuthorityLegacyBindingBlocksAutoNew(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")
	base := time.Date(2026, 9, 26, 16, 0, 0, 0, time.UTC)

	generation, err := store.StartRemoteHistoryGeneration(ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), base)
	if err != nil {
		t.Fatal(err)
	}
	artifact, err := store.AdoptArtifact(ctx)
	if err != nil {
		t.Fatal(err)
	}
	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	err = sqlitex.Execute(conn,
		"INSERT INTO provider_artifact_bindings (identity_domain, provider_id, native_object_id, artifact_id, policy_id, accepted_at) VALUES (?1, ?2, ?3, ?4, 'legacy:test', ?5)",
		&sqlitex.ExecOptions{Args: []any{
			scope.IdentityDomain, string(scope.ProviderID), "id-1", string(artifact.ID), base.UTC().Format(time.RFC3339Nano),
		}})
	store.pool.Put(conn)
	if err != nil {
		t.Fatal(err)
	}
	segments, _ := store.RemoteHistoryLifetimeSegments(ctx, generation.ID)
	segment := findLatestLifetimeSegment(segments, "id-1")
	authority, err := store.CreateRemoteHistoryIdentityAuthority(ctx, generation.ID, segment.ID, base.Add(time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	if authority.UniverseCoverage != corpus.CandidateUniverseUnknown || len(authority.Candidates) != 0 {
		t.Fatalf("legacy binding did not block auto-NEW: %#v", authority)
	}
	if !hasSourceRefPrefix(authority.SourceRefs, "legacy-provider-binding:") {
		t.Fatalf("authority lacks legacy blocker provenance: %#v", authority.SourceRefs)
	}
}

func TestRemoteHistoryAuthorityRejectsProjectionDrift(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")
	base := time.Date(2026, 9, 26, 17, 0, 0, 0, time.UTC)

	generation, err := store.StartRemoteHistoryGeneration(ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), base)
	if err != nil {
		t.Fatal(err)
	}
	segments, _ := store.RemoteHistoryLifetimeSegments(ctx, generation.ID)
	segment := findLatestLifetimeSegment(segments, "id-1")

	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	err = sqlitex.Execute(conn,
		"UPDATE provider_object_lifetime_segments SET last_present_sequence=2, last_present_ordinal=0 WHERE lifetime_segment_id=?1",
		&sqlitex.ExecOptions{Args: []any{string(segment.ID)}})
	store.pool.Put(conn)
	if err != nil {
		t.Fatal(err)
	}
	_, err = store.CreateRemoteHistoryIdentityAuthority(ctx, generation.ID, segment.ID, base.Add(time.Minute))
	if !errors.Is(err, ErrLifetimeSegmentProjectionDrift) {
		t.Fatalf("error=%v, want projection drift", err)
	}
}

func TestLifetimeBindingIsImmutableAndSingleArtifact(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")
	base := time.Date(2026, 9, 26, 18, 0, 0, 0, time.UTC)

	generation, err := store.StartRemoteHistoryGeneration(ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), base)
	if err != nil {
		t.Fatal(err)
	}
	segments, _ := store.RemoteHistoryLifetimeSegments(ctx, generation.ID)
	segment := findLatestLifetimeSegment(segments, "id-1")
	authority, err := store.CreateRemoteHistoryIdentityAuthority(ctx, generation.ID, segment.ID, base.Add(time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	firstArtifact, _ := store.AdoptArtifact(ctx)
	secondArtifact, _ := store.AdoptArtifact(ctx)
	seedLifetimeBinding(t, store, ProviderLifetimeArtifactBinding{
		LifetimeSegmentID: segment.ID,
		ArtifactID: firstArtifact.ID,
		PolicyID: remoteHistoryLifetimeAuthorityPolicyV1,
		AuthoritySetID: authority.ID,
		AcceptedAt: base.Add(2*time.Minute),
	})

	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	end, err := sqlitex.ImmediateTransaction(conn)
	if err != nil {
		store.pool.Put(conn)
		t.Fatal(err)
	}
	_, _, conflict := insertProviderLifetimeArtifactBindingConn(conn, ProviderLifetimeArtifactBinding{
		LifetimeSegmentID: segment.ID,
		ArtifactID: secondArtifact.ID,
		PolicyID: remoteHistoryLifetimeAuthorityPolicyV1,
		AuthoritySetID: authority.ID,
		AcceptedAt: base.Add(3*time.Minute),
	})
	end(&conflict)
	store.pool.Put(conn)
	if !errors.Is(conflict, ErrProviderLifetimeArtifactBindingConflict) {
		t.Fatalf("conflict=%v", conflict)
	}

	conn, err = store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"UPDATE provider_lifetime_artifact_bindings SET artifact_id=?1 WHERE lifetime_segment_id=?2",
		&sqlitex.ExecOptions{Args: []any{string(secondArtifact.ID), string(segment.ID)}}); err == nil {
		store.pool.Put(conn)
		t.Fatal("lifetime binding UPDATE unexpectedly succeeded")
	}
	if err := sqlitex.Execute(conn,
		"DELETE FROM provider_lifetime_artifact_bindings WHERE lifetime_segment_id=?1",
		&sqlitex.ExecOptions{Args: []any{string(segment.ID)}}); err == nil {
		store.pool.Put(conn)
		t.Fatal("lifetime binding DELETE unexpectedly succeeded")
	}
	store.pool.Put(conn)
}

func TestRemoteHistoryPolicyAuthorityCannotReferenceBogusSegment(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	base := time.Date(2026, 9, 26, 19, 0, 0, 0, time.UTC)
	set := corpus.IdentityAuthoritySet{
		ID: "authrh_bogus",
		PolicyID: remoteHistoryLifetimeAuthorityPolicyV1,
		ProviderID: "drive",
		IdentityDomain: "drive:user-1",
		ScopeID: "root",
		CurrentObjectID: "id-1",
		UniverseCoverage: corpus.CandidateUniverseComplete,
		GenerationID: "hgen_bogus",
		LifetimeSegmentID: "hseg_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		SourceRefs: []string{"bogus"},
		CreatedAt: base,
	}
	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	end, err := sqlitex.ImmediateTransaction(conn)
	if err != nil {
		store.pool.Put(conn)
		t.Fatal(err)
	}
	insertErr := insertIdentityAuthoritySetConn(conn, set)
	end(&insertErr)
	store.pool.Put(conn)
	if insertErr == nil {
		t.Fatal("bogus RemoteHistory authority unexpectedly persisted")
	}
}

func seedLifetimeBinding(t *testing.T, store *Store, binding ProviderLifetimeArtifactBinding) {
	t.Helper()
	conn, err := store.pool.Get(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	end, err := sqlitex.ImmediateTransaction(conn)
	if err != nil {
		store.pool.Put(conn)
		t.Fatal(err)
	}
	_, _, bindErr := insertProviderLifetimeArtifactBindingConn(conn, binding)
	end(&bindErr)
	store.pool.Put(conn)
	if bindErr != nil {
		t.Fatal(bindErr)
	}
}

func hasSourceRefPrefix(refs []string, prefix string) bool {
	for _, ref := range refs {
		if strings.HasPrefix(ref, prefix) {
			return true
		}
	}
	return false
}
