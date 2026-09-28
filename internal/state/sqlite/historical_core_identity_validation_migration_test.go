package sqlitestate

import (
	"context"
	"encoding/json"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestQualifiedV42DatabaseMigratesToHistoricalCoreIdentityValidationV43(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v42.db")
	partial := sqlitemigration.Schema{AppID: applicationID, Migrations: append([]string(nil), schema.Migrations[:42]...)}
	store := &Store{path:path}
	pool := sqlitemigration.NewPool(path, partial, sqlitemigration.Options{
		Flags: sqlite.OpenReadWrite|sqlite.OpenCreate, PoolSize:1, PrepareConn:store.prepareConn,
	})
	store.pool=pool
	conn,err:=pool.Get(ctx); if err!=nil {t.Fatal(err)}
	pool.Put(conn); if err:=pool.Close();err!=nil{t.Fatal(err)}
	reopened,err:=Open(ctx,path); if err!=nil{t.Fatal(err)}
	defer reopened.Close()
}

func TestV43MigrationRejectsHistoricalInvalidRevisionEvidence(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v34-invalid-revision.db")
	store := openV34CoreIdentityStore(t,path)
	conn,err:=store.pool.Get(ctx); if err!=nil{t.Fatal(err)}
	if err:=sqlitex.Execute(conn,"INSERT INTO artifacts (artifact_id) VALUES ('art_bad_evidence')",nil);err!=nil{
		store.pool.Put(conn);t.Fatal(err)
	}
	if err:=sqlitex.Execute(conn,
		"INSERT INTO revisions (revision_id,artifact_id,sequence,content_algorithm,content_digest,content_size) VALUES ('rev_bad_evidence','art_bad_evidence',1,'','',1)",nil);err!=nil{
		store.pool.Put(conn);t.Fatal(err)
	}
	store.pool.Put(conn); if err:=store.Close();err!=nil{t.Fatal(err)}
	reopened,err:=Open(ctx,path); if reopened!=nil{_ = reopened.Close()}
	if err==nil{t.Fatal("v43 migration unexpectedly accepted invalid historical Revision evidence")}
}

func TestV43MigrationRejectsHistoricalProviderBindingWithoutNewProvenance(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v34-orphan-binding.db")
	store := openV34CoreIdentityStore(t,path)
	conn,err:=store.pool.Get(ctx); if err!=nil{t.Fatal(err)}
	at:=time.Date(2026,9,28,8,0,0,0,time.UTC).Format(time.RFC3339Nano)
	if err:=sqlitex.Execute(conn,"INSERT INTO artifacts (artifact_id) VALUES ('art_orphan_binding')",nil);err!=nil{
		store.pool.Put(conn);t.Fatal(err)
	}
	if err:=sqlitex.Execute(conn,
		"INSERT INTO provider_artifact_bindings (identity_domain,provider_id,native_object_id,artifact_id,policy_id,accepted_at) VALUES ('local','localfs','obj','art_orphan_binding','local:v1',?1)",
		&sqlitex.ExecOptions{Args:[]any{at}});err!=nil{
		store.pool.Put(conn);t.Fatal(err)
	}
	store.pool.Put(conn); if err:=store.Close();err!=nil{t.Fatal(err)}
	reopened,err:=Open(ctx,path); if reopened!=nil{_ = reopened.Close()}
	if err==nil{t.Fatal("v43 migration unexpectedly accepted provider binding without NEW admission provenance")}
}

func TestV43MigrationRejectsMalformedLegacyAdmissionResolution(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v37-malformed-admission.db")
	store := openV37GenericIdentityAcceptanceStore(t,path)
	at:=time.Date(2026,9,28,8,5,0,0,time.UTC)
	artifact,err:=store.AdoptArtifact(ctx); if err!=nil{t.Fatal(err)}
	scan,err:=store.StartScan(ctx,"localfs","root",at); if err!=nil{t.Fatal(err)}
	conn,err:=store.pool.Get(ctx); if err!=nil{t.Fatal(err)}
	for _,query:=range []string{
		"INSERT INTO provider_object_occurrences (occurrence_id,provider_id,native_object_id,identity_state) VALUES ('pobjocc_bad_admission_v37','localfs','obj','OBSERVED')",
		"INSERT INTO observations (observation_id,occurrence_id,artifact_id,revision_id,assignment_state,observed_at,kind,size,mode,modified_at,scan_id) VALUES ('obs_bad_admission_v37','pobjocc_bad_admission_v37','"+string(artifact.ID)+"',NULL,'ASSIGNED','"+at.Format(time.RFC3339Nano)+"','OTHER',0,0,'"+at.Format(time.RFC3339Nano)+"','"+string(scan.ID)+"')",
	}{
		if err:=sqlitex.Execute(conn,query,nil);err!=nil{store.pool.Put(conn);t.Fatal(err)}
	}
	binding:=corpus.ProviderArtifactBinding{
		IdentityDomain:"local",ProviderID:"localfs",ProviderObjectID:"obj",
		ArtifactID:artifact.ID,PolicyID:"legacy:v1",AcceptedAt:at,
	}
	if err:=store.insertProviderArtifactBindingConn(conn,binding);err!=nil{store.pool.Put(conn);t.Fatal(err)}
	if err:=sqlitex.Execute(conn,
		"INSERT INTO accepted_artifact_admissions (request_id,observation_id,artifact_id,identity_domain,provider_id,native_object_id,decision_state,policy_id,resolution_json,decided_at,lifetime_segment_id) VALUES ('req_bad_admission_v37','obs_bad_admission_v37',?1,'local','localfs','obj','RESOLVED_NEW','legacy:v1','{}',?2,NULL)",
		&sqlitex.ExecOptions{Args:[]any{string(artifact.ID),at.Format(time.RFC3339Nano)}});err!=nil{
		store.pool.Put(conn);t.Fatal(err)
	}
	store.pool.Put(conn); if err:=store.Close();err!=nil{t.Fatal(err)}
	reopened,err:=Open(ctx,path); if reopened!=nil{_ = reopened.Close()}
	if err==nil{t.Fatal("v43 migration unexpectedly accepted malformed legacy admission resolution")}
}

func TestHistoricalDecisionValidatorsAcceptCanonicalPayloads(t *testing.T) {
	candidates,err:=corpus.ResolveCandidateSet([]corpus.ArtifactCandidateInput{{
		ArtifactID:"art_same",
		Evidence:[]corpus.DecisionEvidence{{Source:"test",Direction:corpus.DirectionSupportsSame,Strength:corpus.EvidenceConclusive}},
	}})
	if err!=nil{t.Fatal(err)}
	raw,err:=json.Marshal(candidates);if err!=nil{t.Fatal(err)}
	if !historicalContinuityResolutionValid(string(raw),string(corpus.CandidateSetResolvedSame),"art_same"){
		t.Fatal("canonical continuity payload rejected")
	}
}
