package sqlitestate

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestRemoteHistoryNewAcceptanceCreatesLifetimeBindingAtomically(t *testing.T) {
	ctx := context.Background()
	store := openInternalStore(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")
	base := time.Date(2026, 9, 26, 16, 30, 0, 0, time.UTC)

	generation, err := store.StartRemoteHistoryGeneration(ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), base)
	if err != nil { t.Fatal(err) }
	segments, err := store.RemoteHistoryLifetimeSegments(ctx, generation.ID)
	if err != nil { t.Fatal(err) }
	segment := findLatestLifetimeSegment(segments, "id-1")
	authority, err := store.CreateRemoteHistoryIdentityAuthority(ctx, generation.ID, segment.ID, base.Add(time.Minute))
	if err != nil { t.Fatal(err) }
	if authority.UniverseCoverage != corpus.CandidateUniverseComplete { t.Fatalf("authority=%#v", authority) }

	scan, err := store.StartScan(ctx, scope.ProviderID, scope.Root, base.Add(2*time.Minute))
	if err != nil { t.Fatal(err) }
	request := corpus.IdentityMutationRequest{
		ID: "req-rh-new", ScanID: scan.ID,
		Observation: observedIdentityInput(scope.ProviderID, scope.Root, "id-1", "a.txt", base.Add(2*time.Minute)),
		ContentEvidence: ptrInternalEvidence(internalEvidence("rh-new", 4)),
		AuthoritySetID: authority.ID, DecidedAt: base.Add(2*time.Minute),
	}
	got, err := store.AcceptNewObservationInScan(ctx, request)
	if err != nil { t.Fatal(err) }
	binding, err := store.ProviderLifetimeArtifactBinding(ctx, segment.ID)
	if err != nil { t.Fatal(err) }
	if binding.ArtifactID != got.Observation.ArtifactID || binding.AuthoritySetID != authority.ID {
		t.Fatalf("lifetime binding=%#v acceptance=%#v", binding, got)
	}
	if got.Decision.PolicyID != remoteHistoryLifetimeAuthorityPolicyV1 {
		t.Fatalf("policy=%q", got.Decision.PolicyID)
	}

	conn, err := store.pool.Get(ctx)
	if err != nil { t.Fatal(err) }
	defer store.pool.Put(conn)
	var storedSegment string
	if err := sqlitex.Execute(conn,
		"SELECT COALESCE(lifetime_segment_id,'') FROM accepted_artifact_admissions WHERE request_id='req-rh-new'",
		&sqlitex.ExecOptions{ResultFunc: func(stmt *sqlite.Stmt) error {
			storedSegment = stmt.ColumnText(0)
			return nil
		}}); err != nil { t.Fatal(err) }
	if storedSegment != string(segment.ID) {
		t.Fatalf("stored lifetime_segment_id=%q want=%q", storedSegment, segment.ID)
	}
}

func TestRemoteHistorySameUsesLifetimeBindingNotNakedBinding(t *testing.T) {
	ctx := context.Background()
	store := openInternalStore(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")
	base := time.Date(2026, 9, 26, 17, 0, 0, 0, time.UTC)

	generation, err := store.StartRemoteHistoryGeneration(ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), base)
	if err != nil { t.Fatal(err) }
	segments, _ := store.RemoteHistoryLifetimeSegments(ctx, generation.ID)
	segment := findLatestLifetimeSegment(segments, "id-1")
	newAuthority, err := store.CreateRemoteHistoryIdentityAuthority(ctx, generation.ID, segment.ID, base.Add(time.Minute))
	if err != nil { t.Fatal(err) }
	scan1, err := store.StartScan(ctx, scope.ProviderID, scope.Root, base.Add(2*time.Minute))
	if err != nil { t.Fatal(err) }
	first, err := store.AcceptNewObservationInScan(ctx, corpus.IdentityMutationRequest{
		ID: "req-rh-seed", ScanID: scan1.ID,
		Observation: observedIdentityInput(scope.ProviderID, scope.Root, "id-1", "a.txt", base.Add(2*time.Minute)),
		ContentEvidence: ptrInternalEvidence(internalEvidence("seed", 4)),
		AuthoritySetID: newAuthority.ID, DecidedAt: base.Add(2*time.Minute),
	})
	if err != nil { t.Fatal(err) }
	if err := store.CompleteScan(ctx, scan1.ID, base.Add(3*time.Minute)); err != nil { t.Fatal(err) }

	conflicting, err := store.AdoptArtifact(ctx)
	if err != nil { t.Fatal(err) }
	conn, err := store.pool.Get(ctx)
	if err != nil { t.Fatal(err) }
	if err := sqlitex.Execute(conn,
		"UPDATE provider_artifact_bindings SET artifact_id=?1 WHERE identity_domain=?2 AND provider_id=?3 AND native_object_id='id-1'",
		&sqlitex.ExecOptions{Args: []any{string(conflicting.ID), scope.IdentityDomain, string(scope.ProviderID)}}); err != nil {
		store.pool.Put(conn)
		t.Fatal(err)
	}
	store.pool.Put(conn)

	sameAuthority, err := store.CreateRemoteHistoryIdentityAuthority(ctx, generation.ID, segment.ID, base.Add(4*time.Minute))
	if err != nil { t.Fatal(err) }
	if len(sameAuthority.Candidates) != 1 || sameAuthority.Candidates[0].ArtifactID != first.Observation.ArtifactID {
		t.Fatalf("same authority=%#v", sameAuthority)
	}

	scan2, err := store.StartScan(ctx, scope.ProviderID, scope.Root, base.Add(5*time.Minute))
	if err != nil { t.Fatal(err) }
	same, err := store.AcceptSameObservationInScan(ctx, corpus.IdentityMutationRequest{
		ID: "req-rh-same", ScanID: scan2.ID,
		Observation: observedIdentityInput(scope.ProviderID, scope.Root, "id-1", "a.txt", base.Add(5*time.Minute)),
		ContentEvidence: ptrInternalEvidence(internalEvidence("seed", 4)),
		AuthoritySetID: sameAuthority.ID, DecidedAt: base.Add(5*time.Minute),
	})
	if err != nil { t.Fatal(err) }
	if same.Observation.ArtifactID != first.Observation.ArtifactID {
		t.Fatalf("SAME followed naked binding instead of segment binding: %#v", same)
	}
}

func TestRemoteHistoryStaleAuthorityFailsBeforeIdentityMutation(t *testing.T) {
	ctx := context.Background()
	store := openInternalStore(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")
	base := time.Date(2026, 9, 26, 18, 0, 0, 0, time.UTC)

	generation, err := store.StartRemoteHistoryGeneration(ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), base)
	if err != nil { t.Fatal(err) }
	segments, _ := store.RemoteHistoryLifetimeSegments(ctx, generation.ID)
	segment := findLatestLifetimeSegment(segments, "id-1")
	stale, err := store.CreateRemoteHistoryIdentityAuthority(ctx, generation.ID, segment.ID, base.Add(time.Minute))
	if err != nil { t.Fatal(err) }

	cycle := remotehistory.ChangeCycle{
		StreamID: scope.StreamID, Status: remotehistory.CycleComplete,
		PreviousCursor: "cursor-1", NextCursor: "cursor-2",
		Coverage: corpus.ProviderHistoryContinuous,
		Changes: []remotehistory.RemoteChange{historyUpsert(scope, "id-1", "a-renamed.txt")},
	}
	if _, err := store.PublishRemoteHistoryCycle(ctx, generation.ID, scope, fp, 1, "cursor-1", cycle, base.Add(2*time.Minute)); err != nil {
		t.Fatal(err)
	}
	scan, err := store.StartScan(ctx, scope.ProviderID, scope.Root, base.Add(3*time.Minute))
	if err != nil { t.Fatal(err) }
	beforeArtifacts := internalTableCount(t, store.Path(), "artifacts")
	beforeRequests := internalTableCount(t, store.Path(), "identity_mutation_requests")
	_, err = store.AcceptNewObservationInScan(ctx, corpus.IdentityMutationRequest{
		ID: "req-rh-stale", ScanID: scan.ID,
		Observation: observedIdentityInput(scope.ProviderID, scope.Root, "id-1", "a-renamed.txt", base.Add(3*time.Minute)),
		ContentEvidence: ptrInternalEvidence(internalEvidence("stale", 4)),
		AuthoritySetID: stale.ID, DecidedAt: base.Add(3*time.Minute),
	})
	if !errors.Is(err, ErrRemoteHistoryIdentityAuthorityCollision) {
		t.Fatalf("error=%v, want stale RemoteHistory authority rejection", err)
	}
	if internalTableCount(t, store.Path(), "artifacts") != beforeArtifacts ||
		internalTableCount(t, store.Path(), "identity_mutation_requests") != beforeRequests {
		t.Fatal("stale authority mutated identity state")
	}
}
