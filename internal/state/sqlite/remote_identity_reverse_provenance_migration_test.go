package sqlitestate

import (
	"context"
	"encoding/json"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestQualifiedV30DatabaseMigratesToReverseRemoteIdentityProvenanceV31(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v30-good.db")
	store, err := openPartialRemoteIdentityStore(path, 30)
	if err != nil { t.Fatal(err) }
	scope := remoteHistoryTestScope()
	base := time.Date(2026, 9, 27, 7, 0, 0, 0, time.UTC)
	generation, err := store.StartRemoteHistoryGeneration(
		ctx,
		scope,
		remotehistory.ScopePolicyFingerprint("scope-policy:v1:v31-good"),
		remoteHistoryBootstrap(scope, "cursor-1"),
		base,
	)
	if err != nil { t.Fatal(err) }
	segments, err := store.RemoteHistoryLifetimeSegments(ctx, generation.ID)
	if err != nil { t.Fatal(err) }
	segment := findLatestLifetimeSegment(segments, "id-1")
	authority, err := store.CreateRemoteHistoryIdentityAuthority(ctx, generation.ID, segment.ID, base.Add(time.Minute))
	if err != nil { t.Fatal(err) }
	scan, err := store.StartScan(ctx, scope.ProviderID, scope.Root, base.Add(2*time.Minute))
	if err != nil { t.Fatal(err) }
	if _, err := store.AcceptNewObservationInScan(ctx, corpus.IdentityMutationRequest{
		ID: "req-v31-good", ScanID: scan.ID,
		Observation: observedIdentityInput(scope.ProviderID, scope.Root, "id-1", "a.txt", scan.StartedAt),
		ContentEvidence: ptrInternalEvidence(internalEvidence("v31-good", 4)),
		AuthoritySetID: authority.ID,
		DecidedAt: scan.StartedAt,
	}); err != nil {
		t.Fatal(err)
	}
	if err := store.Close(); err != nil { t.Fatal(err) }

	migrated, err := Open(ctx, path)
	if err != nil { t.Fatal(err) }
	defer migrated.Close()
}

func TestV31RejectsOrphanRemoteContinuityDecisionWithoutReceipt(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v30-orphan-continuity.db")
	store, err := openPartialRemoteIdentityStore(path, 30)
	if err != nil { t.Fatal(err) }
	scope := remoteHistoryTestScope()
	base := time.Date(2026, 9, 27, 8, 0, 0, 0, time.UTC)
	generation, err := store.StartRemoteHistoryGeneration(
		ctx,
		scope,
		remotehistory.ScopePolicyFingerprint("scope-policy:v1:v31-cont"),
		remoteHistoryBootstrap(scope, "cursor-1"),
		base,
	)
	if err != nil { t.Fatal(err) }
	segments, err := store.RemoteHistoryLifetimeSegments(ctx, generation.ID)
	if err != nil { t.Fatal(err) }
	segment := findLatestLifetimeSegment(segments, "id-1")
	newAuthority, err := store.CreateRemoteHistoryIdentityAuthority(ctx, generation.ID, segment.ID, base.Add(time.Minute))
	if err != nil { t.Fatal(err) }
	scan1, err := store.StartScan(ctx, scope.ProviderID, scope.Root, base.Add(2*time.Minute))
	if err != nil { t.Fatal(err) }
	seed, err := store.AcceptNewObservationInScan(ctx, corpus.IdentityMutationRequest{
		ID: "req-v31-cont-seed", ScanID: scan1.ID,
		Observation: observedIdentityInput(scope.ProviderID, scope.Root, "id-1", "a.txt", scan1.StartedAt),
		ContentEvidence: ptrInternalEvidence(internalEvidence("seed", 4)),
		AuthoritySetID: newAuthority.ID,
		DecidedAt: scan1.StartedAt,
	})
	if err != nil { t.Fatal(err) }
	if err := store.CompleteScan(ctx, scan1.ID, base.Add(150*time.Second)); err != nil { t.Fatal(err) }

	scan2, err := store.StartScan(ctx, scope.ProviderID, scope.Root, base.Add(3*time.Minute))
	if err != nil { t.Fatal(err) }
	sameAuthority, err := store.CreateRemoteHistoryIdentityAuthority(ctx, generation.ID, segment.ID, base.Add(4*time.Minute))
	if err != nil { t.Fatal(err) }
	resolution, err := candidateResolutionFromAuthority(sameAuthority)
	if err != nil { t.Fatal(err) }
	resolutionJSON, err := json.Marshal(resolution)
	if err != nil { t.Fatal(err) }

	conn, err := store.pool.Get(ctx)
	if err != nil { t.Fatal(err) }
	if err := sqlitex.Execute(conn,
		"INSERT INTO provider_object_occurrences (occurrence_id,provider_id,native_object_id,identity_state) VALUES ('pobjocc_v31_orphan_cont',?1,'id-1','OBSERVED')",
		&sqlitex.ExecOptions{Args: []any{string(scope.ProviderID)}}); err != nil {
		store.pool.Put(conn); t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO observations (observation_id,occurrence_id,artifact_id,revision_id,assignment_state,observed_at,kind,size,mode,modified_at,scan_id) VALUES ('obs_v31_orphan_cont','pobjocc_v31_orphan_cont',?1,NULL,'ASSIGNED',?2,'REGULAR_FILE',4,384,?3,?4)",
		&sqlitex.ExecOptions{Args: []any{
			string(seed.Observation.ArtifactID),
			scan2.StartedAt.UTC().Format(time.RFC3339Nano),
			scan2.StartedAt.Add(-time.Minute).UTC().Format(time.RFC3339Nano),
			string(scan2.ID),
		}}); err != nil {
		store.pool.Put(conn); t.Fatal(err)
	}
	decisionAt := base.Add(5*time.Minute)
	release, err := store.authorizeIdentityMutationConn(conn, scan2.ID, "", "")
	if err != nil { store.pool.Put(conn); t.Fatal(err) }
	if err := sqlitex.Execute(conn,
		"INSERT INTO accepted_continuity_decisions (decision_id,observation_id,artifact_id,decision_state,policy_id,resolution_json,decided_at,lifetime_segment_id) VALUES ('cont_v31_orphan','obs_v31_orphan_cont',?1,'RESOLVED_SAME',?2,?3,?4,?5)",
		&sqlitex.ExecOptions{Args: []any{
			string(seed.Observation.ArtifactID),
			remoteHistoryLifetimeAuthorityPolicyV1,
			string(resolutionJSON),
			decisionAt.UTC().Format(time.RFC3339Nano),
			string(segment.ID),
		}}); err != nil {
		release(); store.pool.Put(conn); t.Fatal(err)
	}
	release()
	store.pool.Put(conn)
	if err := store.Close(); err != nil { t.Fatal(err) }

	migrated, err := Open(ctx, path)
	if err == nil {
		_ = migrated.Close()
		t.Fatal("v31 migration unexpectedly accepted RemoteHistory continuity without identity mutation receipt")
	}
}

func TestV31RejectsOrphanRemoteLifetimeBindingWithoutAdmissionReceipt(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v30-orphan-binding.db")
	store, err := openPartialRemoteIdentityStore(path, 30)
	if err != nil { t.Fatal(err) }
	scope := remoteHistoryTestScope()
	base := time.Date(2026, 9, 27, 9, 0, 0, 0, time.UTC)
	generation, err := store.StartRemoteHistoryGeneration(
		ctx,
		scope,
		remotehistory.ScopePolicyFingerprint("scope-policy:v1:v31-binding"),
		remoteHistoryBootstrap(scope, "cursor-1"),
		base,
	)
	if err != nil { t.Fatal(err) }
	segments, err := store.RemoteHistoryLifetimeSegments(ctx, generation.ID)
	if err != nil { t.Fatal(err) }
	segment := findLatestLifetimeSegment(segments, "id-1")
	authority, err := store.CreateRemoteHistoryIdentityAuthority(ctx, generation.ID, segment.ID, base.Add(time.Minute))
	if err != nil { t.Fatal(err) }
	artifact, err := store.AdoptArtifact(ctx)
	if err != nil { t.Fatal(err) }
	scan, err := store.StartScan(ctx, scope.ProviderID, scope.Root, base.Add(2*time.Minute))
	if err != nil { t.Fatal(err) }

	conn, err := store.pool.Get(ctx)
	if err != nil { t.Fatal(err) }
	release, err := store.authorizeIdentityMutationConn(conn, scan.ID, segment.ID, authority.ID)
	if err != nil { store.pool.Put(conn); t.Fatal(err) }
	_, _, err = insertProviderLifetimeArtifactBindingConn(conn, ProviderLifetimeArtifactBinding{
		LifetimeSegmentID: segment.ID,
		ArtifactID: artifact.ID,
		PolicyID: remoteHistoryLifetimeAuthorityPolicyV1,
		AuthoritySetID: authority.ID,
		AcceptedAt: scan.StartedAt,
	})
	release()
	store.pool.Put(conn)
	if err != nil { t.Fatal(err) }
	if err := store.Close(); err != nil { t.Fatal(err) }

	migrated, err := Open(ctx, path)
	if err == nil {
		_ = migrated.Close()
		t.Fatal("v31 migration unexpectedly accepted RemoteHistory lifetime binding without admission receipt")
	}
}
