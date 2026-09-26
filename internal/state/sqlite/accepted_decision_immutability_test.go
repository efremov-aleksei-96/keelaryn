package sqlitestate

import (
	"context"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestAcceptedRemoteHistoryContinuityIsImmutable(t *testing.T) {
	ctx := context.Background()
	store := openInternalStore(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:test")
	base := time.Date(2026, 9, 26, 19, 30, 0, 0, time.UTC)

	generation, err := store.StartRemoteHistoryGeneration(ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), base)
	if err != nil { t.Fatal(err) }
	segments, err := store.RemoteHistoryLifetimeSegments(ctx, generation.ID)
	if err != nil { t.Fatal(err) }
	segment := findLatestLifetimeSegment(segments, "id-1")

	newAuthority, err := store.CreateRemoteHistoryIdentityAuthority(ctx, generation.ID, segment.ID, base.Add(time.Minute))
	if err != nil { t.Fatal(err) }
	scan1, err := store.StartScan(ctx, scope.ProviderID, scope.Root, base.Add(2*time.Minute))
	if err != nil { t.Fatal(err) }
	first, err := store.AcceptNewObservationInScan(ctx, corpus.IdentityMutationRequest{
		ID: "req-rh-immutable-seed", ScanID: scan1.ID,
		Observation: observedIdentityInput(scope.ProviderID, scope.Root, "id-1", "a.txt", base.Add(2*time.Minute)),
		ContentEvidence: ptrInternalEvidence(internalEvidence("same", 4)),
		AuthoritySetID: newAuthority.ID, DecidedAt: base.Add(2*time.Minute),
	})
	if err != nil { t.Fatal(err) }
	if err := store.CompleteScan(ctx, scan1.ID, base.Add(3*time.Minute)); err != nil { t.Fatal(err) }

	sameAuthority, err := store.CreateRemoteHistoryIdentityAuthority(ctx, generation.ID, segment.ID, base.Add(4*time.Minute))
	if err != nil { t.Fatal(err) }
	scan2, err := store.StartScan(ctx, scope.ProviderID, scope.Root, base.Add(5*time.Minute))
	if err != nil { t.Fatal(err) }
	same, err := store.AcceptSameObservationInScan(ctx, corpus.IdentityMutationRequest{
		ID: "req-rh-immutable-same", ScanID: scan2.ID,
		Observation: observedIdentityInput(scope.ProviderID, scope.Root, "id-1", "a.txt", base.Add(5*time.Minute)),
		ContentEvidence: ptrInternalEvidence(internalEvidence("same", 4)),
		AuthoritySetID: sameAuthority.ID, DecidedAt: base.Add(5*time.Minute),
	})
	if err != nil { t.Fatal(err) }
	if same.Observation.ArtifactID != first.Observation.ArtifactID ||
		same.Decision.LifetimeSegmentID != string(segment.ID) {
		t.Fatalf("same acceptance=%#v", same)
	}

	conn, err := store.pool.Get(ctx)
	if err != nil { t.Fatal(err) }
	defer store.pool.Put(conn)
	for name, query := range map[string]string{
		"update": "UPDATE accepted_continuity_decisions SET policy_id='tamper' WHERE observation_id='" + string(same.Observation.ID) + "'",
		"delete": "DELETE FROM accepted_continuity_decisions WHERE observation_id='" + string(same.Observation.ID) + "'",
	} {
		t.Run(name, func(t *testing.T) {
			if err := sqlitex.Execute(conn, query, nil); err == nil {
				t.Fatal("accepted continuity mutation unexpectedly succeeded")
			}
		})
	}
}
