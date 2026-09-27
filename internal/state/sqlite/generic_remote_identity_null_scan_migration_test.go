package sqlitestate

import (
	"context"
	"encoding/json"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestQualifiedV29DatabaseMigratesToRemoteIdentityExistingStateValidationV30(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v29.db")
	store := openV29RemoteIdentityStore(t, path)
	if err := store.Close(); err != nil { t.Fatal(err) }

	store, err := Open(ctx, path)
	if err != nil { t.Fatal(err) }
	defer store.Close()
}

func TestV30RejectsNullScanRemoteIdentityReceiptThatV29MigrationMissed(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v28-bad.db")
	store := openV28GenericRemoteIdentityStore(t, path)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:v30-null-scan")
	base := time.Date(2026, 9, 27, 6, 0, 0, 0, time.UTC)

	generation, err := store.StartRemoteHistoryGeneration(ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), base)
	if err != nil { t.Fatal(err) }
	segments, err := store.RemoteHistoryLifetimeSegments(ctx, generation.ID)
	if err != nil { t.Fatal(err) }
	segment := findLatestLifetimeSegment(segments, "id-1")

	seedAuthority, err := store.CreateRemoteHistoryIdentityAuthority(ctx, generation.ID, segment.ID, base.Add(time.Minute))
	if err != nil { t.Fatal(err) }
	scan, err := store.StartScan(ctx, scope.ProviderID, scope.Root, base.Add(2*time.Minute))
	if err != nil { t.Fatal(err) }
	seed, err := store.AcceptNewObservationInScan(ctx, corpus.IdentityMutationRequest{
		ID: "req-v30-null-seed", ScanID: scan.ID,
		Observation: observedIdentityInput(scope.ProviderID, scope.Root, "id-1", "a.txt", scan.StartedAt),
		ContentEvidence: ptrInternalEvidence(internalEvidence("seed", 4)),
		AuthoritySetID: seedAuthority.ID,
		DecidedAt: scan.StartedAt,
	})
	if err != nil { t.Fatal(err) }
	if err := store.CompleteScan(ctx, scan.ID, base.Add(3*time.Minute)); err != nil { t.Fatal(err) }

	sameAuthority, err := store.CreateRemoteHistoryIdentityAuthority(ctx, generation.ID, segment.ID, base.Add(4*time.Minute))
	if err != nil { t.Fatal(err) }
	resolution, err := candidateResolutionFromAuthority(sameAuthority)
	if err != nil { t.Fatal(err) }
	resolutionJSON, err := json.Marshal(resolution)
	if err != nil { t.Fatal(err) }

	conn, err := store.pool.Get(ctx)
	if err != nil { t.Fatal(err) }
	if err := sqlitex.Execute(conn,
		"INSERT INTO provider_object_occurrences (occurrence_id,provider_id,native_object_id,identity_state) VALUES ('pobjocc_v30_null_scan',?1,'id-1','OBSERVED')",
		&sqlitex.ExecOptions{Args: []any{string(scope.ProviderID)}}); err != nil {
		store.pool.Put(conn); t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO observations (observation_id,occurrence_id,artifact_id,revision_id,assignment_state,observed_at,kind,size,mode,modified_at,scan_id) VALUES ('obs_v30_null_scan','pobjocc_v30_null_scan',?1,NULL,'ASSIGNED',?2,'REGULAR_FILE',4,384,?2,NULL)",
		&sqlitex.ExecOptions{Args: []any{string(seed.Observation.ArtifactID), badTime}}); err != nil {
		store.pool.Put(conn); t.Fatal(err)
	}
	nullScanObservationID := corpus.ObservationID("obs_v30_null_scan")
	badTime := base.Add(5*time.Minute).UTC().Format(time.RFC3339Nano)
	if err := sqlitex.Execute(conn,
		"INSERT INTO accepted_continuity_decisions (decision_id,observation_id,artifact_id,decision_state,policy_id,resolution_json,decided_at,lifetime_segment_id) VALUES ('cont_v30_null_scan',?1,?2,'RESOLVED_SAME',?3,?4,?5,?6)",
		&sqlitex.ExecOptions{Args: []any{
			string(nullScanObservationID),
			string(seed.Observation.ArtifactID),
			remoteHistoryLifetimeAuthorityPolicyV1,
			string(resolutionJSON),
			badTime,
			string(segment.ID),
		}}); err != nil {
		store.pool.Put(conn); t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO identity_mutation_requests (request_id,operation_kind,fingerprint_version,fingerprint_sha256,authority_set_id,observation_id,artifact_id,revision_id,revision_created,decision_kind,decision_id,accepted_at) VALUES ('req_v30_null_scan','SAME','test:v1','deadbeef',?1,?2,?3,NULL,0,'CONTINUITY','cont_v30_null_scan',?4)",
		&sqlitex.ExecOptions{Args: []any{
			string(sameAuthority.ID),
			string(nullScanObservationID),
			string(seed.Observation.ArtifactID),
			badTime,
		}}); err != nil {
		store.pool.Put(conn); t.Fatal(err)
	}
	store.pool.Put(conn)
	if err := store.Close(); err != nil { t.Fatal(err) }

	v29, err := openPartialRemoteIdentityStore(path, 29)
	if err != nil {
		t.Fatalf("v29 migration should expose the historical blind spot, got error: %v", err)
	}
	if err := v29.Close(); err != nil { t.Fatal(err) }

	migrated, err := Open(ctx, path)
	if err == nil {
		_ = migrated.Close()
		t.Fatal("v30 migration unexpectedly accepted RemoteHistory identity receipt with no ScanSession")
	}
}

func openV29RemoteIdentityStore(t *testing.T, path string) *Store {
	t.Helper()
	store, err := openPartialRemoteIdentityStore(path, 29)
	if err != nil { t.Fatal(err) }
	return store
}

func openPartialRemoteIdentityStore(path string, migrations int) (*Store, error) {
	partial := sqlitemigration.Schema{
		AppID: applicationID,
		Migrations: append([]string(nil), schema.Migrations[:migrations]...),
	}
	store := &Store{path: path}
	pool := sqlitemigration.NewPool(path, partial, sqlitemigration.Options{
		Flags: sqlite.OpenReadWrite | sqlite.OpenCreate,
		PoolSize: 1,
		PrepareConn: store.prepareConn,
	})
	store.pool = pool
	conn, err := pool.Get(context.Background())
	if err != nil {
		_ = pool.Close()
		return nil, err
	}
	pool.Put(conn)
	return store, nil
}
