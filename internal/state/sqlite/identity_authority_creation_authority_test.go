package sqlitestate

import (
	"context"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestIdentityAuthorityCreationApplicationAuthorityRejectsDirectSQL(t *testing.T) {
	ctx := context.Background()
	store := openInternalStore(t)
	artifact, err := store.AdoptArtifact(ctx)
	if err != nil { t.Fatal(err) }
	at := time.Date(2026, 9, 27, 12, 30, 0, 0, time.UTC)
	conn, err := store.pool.Get(ctx)
	if err != nil { t.Fatal(err) }
	defer store.pool.Put(conn)

	if err := sqlitex.Execute(conn,
		"INSERT INTO identity_authority_sets (authority_set_id,policy_id,provider_id,identity_domain,scope_id,current_object_id,universe_coverage,generation_id,lifetime_segment_id,source_refs_json,created_at,sealed_at) VALUES ('auth_direct_v36','test:v1','drive','domain','root','obj','UNKNOWN',NULL,NULL,'[\"source\"]',?1,NULL)",
		&sqlitex.ExecOptions{Args: []any{at.Format(time.RFC3339Nano)}}); err == nil {
		t.Fatal("direct identity authority set insert unexpectedly succeeded")
	}

	set := corpus.IdentityAuthoritySet{
		ID: "auth_v36_phases",
		PolicyID: "test:v1",
		ProviderID: "drive",
		IdentityDomain: "domain",
		ScopeID: "root",
		CurrentObjectID: "obj",
		UniverseCoverage: corpus.CandidateUniverseUnknown,
		SourceRefs: []string{"source"},
		CreatedAt: at,
		Candidates: []corpus.IdentityAuthorityCandidate{{
			ArtifactID: artifact.ID,
			Direction: corpus.DirectionSupportsSame,
			SourceRef: "candidate-source",
		}},
	}
	if err := store.insertIdentityAuthoritySetConn(conn, set); err != nil {
		t.Fatal(err)
	}
}

func TestIdentityAuthorityCreationCapabilityIsExactPerPhase(t *testing.T) {
	ctx := context.Background()
	store := openInternalStore(t)
	conn, err := store.pool.Get(ctx)
	if err != nil { t.Fatal(err) }
	defer store.pool.Put(conn)

	release, err := store.authorizeIdentityAuthorityWriteConn(conn, identityAuthorityWriteAuthorization{
		kind: "SET",
		authoritySetID: "auth_expected_v36",
		policyID: "test:v1",
		providerID: "drive",
		identityDomain: "domain",
		scopeID: "root",
		currentObjectID: "obj",
		universeCoverage: corpus.CandidateUniverseUnknown,
		sourceRefsJSON: "[\"source\"]",
		createdAt: "2026-09-27T12:31:00Z",
	})
	if err != nil { t.Fatal(err) }
	defer release()
	if err := sqlitex.Execute(conn,
		"INSERT INTO identity_authority_sets (authority_set_id,policy_id,provider_id,identity_domain,scope_id,current_object_id,universe_coverage,generation_id,lifetime_segment_id,source_refs_json,created_at,sealed_at) VALUES ('auth_wrong_v36','test:v1','drive','domain','root','obj','UNKNOWN',NULL,NULL,'[\"source\"]','2026-09-27T12:31:00Z',NULL)",
		nil); err == nil {
		t.Fatal("authority SET capability authorized the wrong row")
	}
}
