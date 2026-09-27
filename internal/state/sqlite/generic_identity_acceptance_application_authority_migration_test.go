package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestQualifiedV37DatabaseMigratesToGenericIdentityAcceptanceAuthorityV38(t *testing.T) {
	path := filepath.Join(t.TempDir(), "qualified-v37.db")
	store := openV37GenericIdentityAcceptanceStore(t, path)
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}
	migrated, err := Open(context.Background(), path)
	if err != nil {
		t.Fatal(err)
	}
	if err := migrated.Close(); err != nil {
		t.Fatal(err)
	}
}

func TestV38MigrationRejectsHistoricalOrphanIdentityMutationReceipt(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "orphan-receipt-v37.db")
	store := openV37GenericIdentityAcceptanceStore(t, path)
	at := time.Date(2026, 9, 27, 14, 5, 0, 0, time.UTC)
	artifact, err := store.AdoptArtifact(ctx)
	if err != nil {
		t.Fatal(err)
	}
	scan, err := store.StartScan(ctx, "localfs", "root", at)
	if err != nil {
		t.Fatal(err)
	}
	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO provider_object_occurrences (occurrence_id,provider_id,native_object_id,identity_state) VALUES ('pobjocc_orphan_v37','localfs','obj','OBSERVED')",
		nil); err != nil {
		store.pool.Put(conn)
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO observations (observation_id,occurrence_id,artifact_id,revision_id,assignment_state,observed_at,kind,size,mode,modified_at,scan_id) VALUES ('obs_orphan_v37','pobjocc_orphan_v37',?1,NULL,'ASSIGNED',?2,'OTHER',0,0,?2,?3)",
		&sqlitex.ExecOptions{Args: []any{string(artifact.ID), at.Format(time.RFC3339Nano), string(scan.ID)}}); err != nil {
		store.pool.Put(conn)
		t.Fatal(err)
	}
	authority := corpus.IdentityAuthoritySet{
		ID: "auth_orphan_v37", PolicyID: "test:v1", ProviderID: "localfs",
		IdentityDomain: "local", ScopeID: "root", CurrentObjectID: "obj",
		UniverseCoverage: corpus.CandidateUniverseUnknown, SourceRefs: []string{"source"}, CreatedAt: at,
	}
	if err := store.insertIdentityAuthoritySetConn(conn, authority); err != nil {
		store.pool.Put(conn)
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO identity_mutation_requests (request_id,operation_kind,fingerprint_version,fingerprint_sha256,authority_set_id,observation_id,artifact_id,revision_id,revision_created,decision_kind,decision_id,accepted_at) VALUES ('req_orphan_v37','SAME','identity-mutation-fingerprint:v1','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',?1,'obs_orphan_v37',?2,NULL,0,'CONTINUITY','cont_missing_v37',?3)",
		&sqlitex.ExecOptions{Args: []any{string(authority.ID), string(artifact.ID), at.Format(time.RFC3339Nano)}}); err != nil {
		store.pool.Put(conn)
		t.Fatal(err)
	}
	store.pool.Put(conn)
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}

	migrated, err := Open(ctx, path)
	if err == nil {
		_ = migrated.Close()
		t.Fatal("v38 migration unexpectedly accepted orphan generic identity mutation receipt")
	}
}

func TestV38MigrationPreservesLegacyGenericDecisionWithoutReceipt(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "legacy-decision-v37.db")
	store := openV37GenericIdentityAcceptanceStore(t, path)
	at := time.Date(2026, 9, 27, 14, 6, 0, 0, time.UTC)
	artifact, err := store.AdoptArtifact(ctx)
	if err != nil {
		t.Fatal(err)
	}
	scan, err := store.StartScan(ctx, "localfs", "root", at)
	if err != nil {
		t.Fatal(err)
	}
	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	for _, query := range []string{
		"INSERT INTO provider_object_occurrences (occurrence_id,provider_id,native_object_id,identity_state) VALUES ('pobjocc_legacy_v37','localfs','obj','OBSERVED')",
		"INSERT INTO observations (observation_id,occurrence_id,artifact_id,revision_id,assignment_state,observed_at,kind,size,mode,modified_at,scan_id) VALUES ('obs_legacy_v37','pobjocc_legacy_v37','" + string(artifact.ID) + "',NULL,'ASSIGNED','" + at.Format(time.RFC3339Nano) + "','OTHER',0,0,'" + at.Format(time.RFC3339Nano) + "','" + string(scan.ID) + "')",
		"INSERT INTO accepted_continuity_decisions (decision_id,observation_id,artifact_id,decision_state,policy_id,resolution_json,decided_at,lifetime_segment_id) VALUES ('cont_legacy_v37','obs_legacy_v37','" + string(artifact.ID) + "','RESOLVED_SAME','legacy:v1','{}','" + at.Format(time.RFC3339Nano) + "',NULL)",
	} {
		if err := sqlitex.Execute(conn, query, nil); err != nil {
			store.pool.Put(conn)
			t.Fatal(err)
		}
	}
	store.pool.Put(conn)
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}
	migrated, err := Open(ctx, path)
	if err != nil {
		t.Fatalf("v38 migration rejected pre-receipt legacy decision: %v", err)
	}
	if err := migrated.Close(); err != nil {
		t.Fatal(err)
	}
}

func openV37GenericIdentityAcceptanceStore(t *testing.T, path string) *Store {
	t.Helper()
	partial := sqlitemigration.Schema{
		AppID:      applicationID,
		Migrations: append([]string(nil), schema.Migrations[:37]...),
	}
	store := &Store{path: path}
	pool := sqlitemigration.NewPool(path, partial, sqlitemigration.Options{
		Flags:       sqlite.OpenReadWrite | sqlite.OpenCreate,
		PoolSize:    1,
		PrepareConn: store.prepareConn,
	})
	store.pool = pool
	conn, err := pool.Get(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	pool.Put(conn)
	return store
}
