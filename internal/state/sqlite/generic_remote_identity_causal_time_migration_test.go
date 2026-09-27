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

func TestQualifiedV28DatabaseMigratesToGenericRemoteIdentityCausalAuthorityV29(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v28.db")
	store := openV28GenericRemoteIdentityStore(t, path)
	if err := store.Close(); err != nil { t.Fatal(err) }

	store, err := Open(ctx, path)
	if err != nil { t.Fatal(err) }
	defer store.Close()
	conn, err := store.pool.Get(ctx)
	if err != nil { t.Fatal(err) }
	defer store.pool.Put(conn)

	for _, name := range []string{
		"remote_history_continuity_application_causal_guard",
		"remote_history_admission_application_causal_guard",
		"remote_history_identity_mutation_receipt_application_causal_guard",
	} {
		var found bool
		if err := sqlitex.Execute(conn,
			"SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?1",
			&sqlitex.ExecOptions{
				Args: []any{name},
				ResultFunc: func(*sqlite.Stmt) error { found = true; return nil },
			}); err != nil { t.Fatal(err) }
		if !found { t.Fatalf("v28→v29 migration missing %s", name) }
	}
}

func TestV29MigrationRejectsExistingGenericRemoteHistoryReceiptBeforeAuthorityCreation(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v28.db")
	store := openV28GenericRemoteIdentityStore(t, path)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:v29-migration")
	base := time.Date(2026, 9, 27, 5, 0, 0, 0, time.UTC)

	generation, err := store.StartRemoteHistoryGeneration(ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), base)
	if err != nil { t.Fatal(err) }
	segments, err := store.RemoteHistoryLifetimeSegments(ctx, generation.ID)
	if err != nil { t.Fatal(err) }
	segment := findLatestLifetimeSegment(segments, "id-1")
	seedAuthority, err := store.CreateRemoteHistoryIdentityAuthority(ctx, generation.ID, segment.ID, base.Add(time.Minute))
	if err != nil { t.Fatal(err) }
	scan1, err := store.StartScan(ctx, scope.ProviderID, scope.Root, base.Add(2*time.Minute))
	if err != nil { t.Fatal(err) }
	first, err := store.AcceptNewObservationInScan(ctx, corpus.IdentityMutationRequest{
		ID: "req-v29-migration-seed", ScanID: scan1.ID,
		Observation: observedIdentityInput(scope.ProviderID, scope.Root, "id-1", "a.txt", scan1.StartedAt),
		ContentEvidence: ptrInternalEvidence(internalEvidence("seed", 4)),
		AuthoritySetID: seedAuthority.ID, DecidedAt: scan1.StartedAt,
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
		"INSERT INTO provider_object_occurrences (occurrence_id,provider_id,native_object_id,identity_state) VALUES ('pobjocc_v29_migration',?1,'id-1','OBSERVED')",
		&sqlitex.ExecOptions{Args: []any{string(scope.ProviderID)}}); err != nil {
		store.pool.Put(conn); t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO observations (observation_id,occurrence_id,artifact_id,revision_id,assignment_state,observed_at,kind,size,mode,modified_at,scan_id) VALUES ('obs_v29_migration','pobjocc_v29_migration',?1,NULL,'ASSIGNED',?2,'REGULAR_FILE',4,384,?3,?4)",
		&sqlitex.ExecOptions{Args: []any{
			string(first.Observation.ArtifactID),
			scan2.StartedAt.UTC().Format(time.RFC3339Nano),
			scan2.StartedAt.Add(-time.Minute).UTC().Format(time.RFC3339Nano),
			string(scan2.ID),
		}}); err != nil {
		store.pool.Put(conn); t.Fatal(err)
	}
	badTime := base.Add(210*time.Second)
	if err := sqlitex.Execute(conn,
		"INSERT INTO accepted_continuity_decisions (decision_id,observation_id,artifact_id,decision_state,policy_id,resolution_json,decided_at,lifetime_segment_id) VALUES ('cont_v29_migration','obs_v29_migration',?1,'RESOLVED_SAME',?2,?3,?4,?5)",
		&sqlitex.ExecOptions{Args: []any{
			string(first.Observation.ArtifactID),
			remoteHistoryLifetimeAuthorityPolicyV1,
			string(resolutionJSON),
			badTime.UTC().Format(time.RFC3339Nano),
			string(segment.ID),
		}}); err != nil {
		store.pool.Put(conn); t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO identity_mutation_requests (request_id,operation_kind,fingerprint_version,fingerprint_sha256,authority_set_id,observation_id,artifact_id,revision_id,revision_created,decision_kind,decision_id,accepted_at) VALUES ('req_v29_migration_bad','SAME','test:v1','deadbeef',?1,'obs_v29_migration',?2,NULL,0,'CONTINUITY','cont_v29_migration',?3)",
		&sqlitex.ExecOptions{Args: []any{
			string(sameAuthority.ID),
			string(first.Observation.ArtifactID),
			badTime.UTC().Format(time.RFC3339Nano),
		}}); err != nil {
		store.pool.Put(conn); t.Fatal(err)
	}
	store.pool.Put(conn)
	if err := store.Close(); err != nil { t.Fatal(err) }

	migrated, err := Open(ctx, path)
	if err == nil {
		_ = migrated.Close()
		t.Fatal("v29 migration unexpectedly accepted generic RemoteHistory receipt before authority creation")
	}
}

func openV28GenericRemoteIdentityStore(t *testing.T, path string) *Store {
	t.Helper()
	partial := sqlitemigration.Schema{
		AppID: applicationID,
		Migrations: append([]string(nil), schema.Migrations[:28]...),
	}
	store := &Store{path: path}
	pool := sqlitemigration.NewPool(path, partial, sqlitemigration.Options{
		Flags: sqlite.OpenReadWrite | sqlite.OpenCreate,
		PoolSize: 1,
		PrepareConn: store.prepareConn,
	})
	store.pool = pool
	conn, err := pool.Get(context.Background())
	if err != nil { t.Fatal(err) }
	pool.Put(conn)
	return store
}
