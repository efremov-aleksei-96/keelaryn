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

func TestQualifiedV31DatabaseMigratesToUniqueRemoteNewV32(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v31-good.db")
	store, err := openPartialRemoteIdentityStore(path, 31)
	if err != nil { t.Fatal(err) }
	scope := remoteHistoryTestScope()
	base := time.Date(2026, 9, 27, 10, 0, 0, 0, time.UTC)
	generation, err := store.StartRemoteHistoryGeneration(
		ctx,
		scope,
		remotehistory.ScopePolicyFingerprint("scope-policy:v1:v32-good"),
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
		ID: "req-v32-good", ScanID: scan.ID,
		Observation: observedIdentityInput(scope.ProviderID, scope.Root, "id-1", "a.txt", scan.StartedAt),
		ContentEvidence: ptrInternalEvidence(internalEvidence("v32-good", 4)),
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

func TestV32RejectsDuplicateFullyLinkedRemoteNewForOneLifetime(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v31-duplicate-new.db")
	store, err := openPartialRemoteIdentityStore(path, 31)
	if err != nil { t.Fatal(err) }
	scope := remoteHistoryTestScope()
	base := time.Date(2026, 9, 27, 11, 0, 0, 0, time.UTC)
	generation, err := store.StartRemoteHistoryGeneration(
		ctx,
		scope,
		remotehistory.ScopePolicyFingerprint("scope-policy:v1:v32-duplicate"),
		remoteHistoryBootstrap(scope, "cursor-1"),
		base,
	)
	if err != nil { t.Fatal(err) }
	segments, err := store.RemoteHistoryLifetimeSegments(ctx, generation.ID)
	if err != nil { t.Fatal(err) }
	segment := findLatestLifetimeSegment(segments, "id-1")
	authority, err := store.CreateRemoteHistoryIdentityAuthority(ctx, generation.ID, segment.ID, base.Add(time.Minute))
	if err != nil { t.Fatal(err) }
	scan1, err := store.StartScan(ctx, scope.ProviderID, scope.Root, base.Add(2*time.Minute))
	if err != nil { t.Fatal(err) }
	first, err := store.AcceptNewObservationInScan(ctx, corpus.IdentityMutationRequest{
		ID: "req-v32-first", ScanID: scan1.ID,
		Observation: observedIdentityInput(scope.ProviderID, scope.Root, "id-1", "a.txt", scan1.StartedAt),
		ContentEvidence: ptrInternalEvidence(internalEvidence("seed", 4)),
		AuthoritySetID: authority.ID,
		DecidedAt: scan1.StartedAt,
	})
	if err != nil { t.Fatal(err) }
	if err := store.CompleteScan(ctx, scan1.ID, base.Add(150*time.Second)); err != nil { t.Fatal(err) }

	scan2, err := store.StartScan(ctx, scope.ProviderID, scope.Root, base.Add(3*time.Minute))
	if err != nil { t.Fatal(err) }
	resolutionJSON, err := json.Marshal(first.Decision.Resolution)
	if err != nil { t.Fatal(err) }

	conn, err := store.pool.Get(ctx)
	if err != nil { t.Fatal(err) }
	if err := sqlitex.Execute(conn,
		"INSERT INTO provider_object_occurrences (occurrence_id,provider_id,native_object_id,identity_state) VALUES ('pobjocc_v32_duplicate',?1,'id-1','OBSERVED')",
		&sqlitex.ExecOptions{Args: []any{string(scope.ProviderID)}}); err != nil {
		store.pool.Put(conn); t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO observations (observation_id,occurrence_id,artifact_id,revision_id,assignment_state,observed_at,kind,size,mode,modified_at,scan_id) VALUES ('obs_v32_duplicate','pobjocc_v32_duplicate',?1,NULL,'ASSIGNED',?2,'REGULAR_FILE',4,384,?3,?4)",
		&sqlitex.ExecOptions{Args: []any{
			string(first.Observation.ArtifactID),
			scan2.StartedAt.UTC().Format(time.RFC3339Nano),
			scan2.StartedAt.Add(-time.Minute).UTC().Format(time.RFC3339Nano),
			string(scan2.ID),
		}}); err != nil {
		store.pool.Put(conn); t.Fatal(err)
	}

	decisionAt := scan2.StartedAt
	release, err := store.authorizeIdentityMutationConn(conn, scan2.ID, "", "")
	if err != nil { store.pool.Put(conn); t.Fatal(err) }
	if err := sqlitex.Execute(conn,
		"INSERT INTO accepted_artifact_admissions (request_id,observation_id,artifact_id,identity_domain,provider_id,native_object_id,decision_state,policy_id,resolution_json,decided_at,lifetime_segment_id) VALUES ('req_v32_duplicate_new','obs_v32_duplicate',?1,?2,?3,'id-1','RESOLVED_NEW',?4,?5,?6,?7)",
		&sqlitex.ExecOptions{Args: []any{
			string(first.Observation.ArtifactID),
			scope.IdentityDomain,
			string(scope.ProviderID),
			remoteHistoryLifetimeAuthorityPolicyV1,
			string(resolutionJSON),
			decisionAt.UTC().Format(time.RFC3339Nano),
			string(segment.ID),
		}}); err != nil {
		release(); store.pool.Put(conn); t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO identity_mutation_requests (request_id,operation_kind,fingerprint_version,fingerprint_sha256,authority_set_id,observation_id,artifact_id,revision_id,revision_created,decision_kind,decision_id,accepted_at) VALUES ('req_v32_duplicate_new','NEW','test:v1','deadbeef',?1,'obs_v32_duplicate',?2,NULL,0,'ADMISSION','req_v32_duplicate_new',?3)",
		&sqlitex.ExecOptions{Args: []any{
			string(authority.ID),
			string(first.Observation.ArtifactID),
			decisionAt.UTC().Format(time.RFC3339Nano),
		}}); err != nil {
		release(); store.pool.Put(conn); t.Fatal(err)
	}
	release()
	store.pool.Put(conn)
	if err := store.Close(); err != nil { t.Fatal(err) }

	v31, err := openPartialRemoteIdentityStore(path, 31)
	if err != nil {
		t.Fatalf("v31 should accept duplicate fully linked NEW provenance and expose the blind spot, got %v", err)
	}
	if err := v31.Close(); err != nil { t.Fatal(err) }

	migrated, err := Open(ctx, path)
	if err == nil {
		_ = migrated.Close()
		t.Fatal("v32 migration unexpectedly accepted two RemoteHistory NEW admissions for one lifetime segment")
	}
}
