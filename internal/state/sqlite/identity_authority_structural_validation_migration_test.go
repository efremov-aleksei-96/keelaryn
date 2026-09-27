package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"

	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestQualifiedV36DatabaseMigratesToIdentityAuthorityStructuralValidationV37(t *testing.T) {
	path := filepath.Join(t.TempDir(), "qualified-v36.db")
	store := openV35IdentityAuthorityCreationStore(t, path)
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}
	migrateIdentityAuthorityStoreThroughV36(t, path)

	migrated, err := Open(context.Background(), path)
	if err != nil {
		t.Fatal(err)
	}
	if err := migrated.Close(); err != nil {
		t.Fatal(err)
	}
}

func TestV37MigrationRejectsHistoricalStructurallyInvalidIdentityAuthoritySet(t *testing.T) {
	const validAt = "2026-09-27T12:40:00Z"
	cases := []struct {
		name         string
		policyID     string
		generationID any
		segmentID    any
		sourceRefs   string
		createdAt    string
	}{
		{name: "blank-policy", policyID: "   ", sourceRefs: "[\"source\"]", createdAt: validAt},
		{name: "empty-source-refs", policyID: "test:v1", sourceRefs: "[]", createdAt: validAt},
		{name: "malformed-timestamp", policyID: "test:v1", sourceRefs: "[\"source\"]", createdAt: "not-a-time"},
		{name: "unpaired-generation", policyID: "test:v1", generationID: "gen-forged", sourceRefs: "[\"source\"]", createdAt: validAt},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "forged-v35.db")
			store := openV35IdentityAuthorityCreationStore(t, path)
			conn, err := store.pool.Get(context.Background())
			if err != nil {
				t.Fatal(err)
			}
			err = sqlitex.Execute(conn,
				"INSERT INTO identity_authority_sets (authority_set_id,policy_id,provider_id,identity_domain,scope_id,current_object_id,universe_coverage,generation_id,lifetime_segment_id,source_refs_json,created_at,sealed_at) VALUES ('auth_forged_v35',?1,'drive','domain','root','obj','UNKNOWN',?2,?3,?4,?5,?5)",
				&sqlitex.ExecOptions{Args: []any{tc.policyID, tc.generationID, tc.segmentID, tc.sourceRefs, tc.createdAt}})
			store.pool.Put(conn)
			if err != nil {
				t.Fatal(err)
			}
			if err := store.Close(); err != nil {
				t.Fatal(err)
			}

			migrateIdentityAuthorityStoreThroughV36(t, path)
			migrated, err := Open(context.Background(), path)
			if err == nil {
				_ = migrated.Close()
				t.Fatal("v37 migration unexpectedly accepted structurally invalid historical identity authority")
			}
		})
	}
}

func TestV37MigrationRejectsHistoricalStructurallyInvalidIdentityAuthorityCandidate(t *testing.T) {
	const at = "2026-09-27T12:41:00Z"
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "forged-candidate-v35.db")
	store := openV35IdentityAuthorityCreationStore(t, path)
	artifact, err := store.AdoptArtifact(ctx)
	if err != nil {
		t.Fatal(err)
	}
	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	err = sqlitex.Execute(conn,
		"INSERT INTO identity_authority_sets (authority_set_id,policy_id,provider_id,identity_domain,scope_id,current_object_id,universe_coverage,generation_id,lifetime_segment_id,source_refs_json,created_at,sealed_at) VALUES ('auth_candidate_v35','test:v1','drive','domain','root','obj','UNKNOWN',NULL,NULL,'[\"source\"]',?1,NULL)",
		&sqlitex.ExecOptions{Args: []any{at}})
	if err == nil {
		err = sqlitex.Execute(conn,
			"INSERT INTO identity_authority_candidates (authority_set_id,artifact_id,direction,source_ref) VALUES ('auth_candidate_v35',?1,'SUPPORTS_SAME','   ')",
			&sqlitex.ExecOptions{Args: []any{string(artifact.ID)}})
	}
	if err == nil {
		err = sqlitex.Execute(conn,
			"UPDATE identity_authority_sets SET sealed_at=created_at WHERE authority_set_id='auth_candidate_v35'",
			nil)
	}
	store.pool.Put(conn)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}

	migrateIdentityAuthorityStoreThroughV36(t, path)
	migrated, err := Open(ctx, path)
	if err == nil {
		_ = migrated.Close()
		t.Fatal("v37 migration unexpectedly accepted structurally invalid historical identity authority candidate")
	}
}

func migrateIdentityAuthorityStoreThroughV36(t *testing.T, path string) {
	t.Helper()
	partial := sqlitemigration.Schema{
		AppID:      applicationID,
		Migrations: append([]string(nil), schema.Migrations[:36]...),
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
	if err := pool.Close(); err != nil {
		t.Fatal(err)
	}
}
