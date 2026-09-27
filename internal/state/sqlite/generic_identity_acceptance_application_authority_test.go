package sqlitestate

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestGenericObservationAPIsRejectDirectAssignedIdentity(t *testing.T) {
	ctx := context.Background()
	store := openInternalStore(t)
	artifact, err := store.AdoptArtifact(ctx)
	if err != nil {
		t.Fatal(err)
	}
	input := genericIdentityUnresolvedObservationInput()
	input.ArtifactID = artifact.ID
	input.AssignmentState = corpus.AssignmentAssigned
	if _, err := store.RecordObservation(ctx, input); !errors.Is(err, ErrInvalidObservation) {
		t.Fatalf("RecordObservation error=%v, want ErrInvalidObservation", err)
	}

	scan, err := store.StartScan(ctx, "drive", "root", time.Date(2026, 9, 27, 13, 50, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	input.ProviderObject = corpus.ProviderObject{ProviderID: "drive", ID: "obj-scan", IdentityState: corpus.ObjectIdentityObserved}
	input.Locators = []corpus.Locator{{ProviderID: "drive", Root: "root", Path: "x"}}
	if _, err := store.RecordObservationInScan(ctx, scan.ID, input); !errors.Is(err, ErrInvalidObservation) {
		t.Fatalf("RecordObservationInScan error=%v, want ErrInvalidObservation", err)
	}
}

func TestGenericIdentityAcceptanceApplicationAuthorityRejectsDirectSQL(t *testing.T) {
	ctx := context.Background()
	store := openInternalStore(t)
	at := time.Date(2026, 9, 27, 13, 55, 0, 0, time.UTC)
	scan, err := store.StartBootstrapScan(ctx, "drive", "root", at)
	if err != nil {
		t.Fatal(err)
	}
	input := genericIdentityUnresolvedObservationInput()
	input.ProviderObject = corpus.ProviderObject{ProviderID: "drive", ID: "obj", IdentityState: corpus.ObjectIdentityObserved}
	input.Locators = []corpus.Locator{{ProviderID: "drive", Root: "root", Path: "x"}}
	input.ObservedAt = at
	input.ModifiedAt = at
	adopted, err := store.AdoptObservationInScan(ctx, scan.ID, input, nil)
	if err != nil {
		t.Fatal(err)
	}

	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer store.pool.Put(conn)

	if err := sqlitex.Execute(conn,
		"INSERT INTO provider_object_occurrences (occurrence_id,provider_id,native_object_id,identity_state) VALUES ('pobjocc_direct_v38','drive','obj-direct','OBSERVED')",
		nil); err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO observations (observation_id,occurrence_id,artifact_id,revision_id,assignment_state,observed_at,kind,size,mode,modified_at,scan_id) VALUES ('obs_direct_v38','pobjocc_direct_v38',?1,NULL,'ASSIGNED',?2,'OTHER',0,0,?2,?3)",
		&sqlitex.ExecOptions{Args: []any{string(adopted.ArtifactID), at.Format(time.RFC3339Nano), string(scan.ID)}}); err == nil {
		t.Fatal("direct assigned Observation unexpectedly succeeded")
	}

	if err := sqlitex.Execute(conn,
		"INSERT INTO accepted_continuity_decisions (decision_id,observation_id,artifact_id,decision_state,policy_id,resolution_json,decided_at,lifetime_segment_id) VALUES ('cont_direct_v38',?1,?2,'RESOLVED_SAME','legacy:test','{}',?3,NULL)",
		&sqlitex.ExecOptions{Args: []any{string(adopted.ID), string(adopted.ArtifactID), at.Format(time.RFC3339Nano)}}); err == nil {
		t.Fatal("direct continuity acceptance unexpectedly succeeded")
	}

	if err := sInsertTestProviderBinding(store, conn, adopted.ArtifactID, at); err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO accepted_artifact_admissions (request_id,observation_id,artifact_id,identity_domain,provider_id,native_object_id,decision_state,policy_id,resolution_json,decided_at,lifetime_segment_id) VALUES ('req_direct_v38',?1,?2,'test-domain','drive','obj-admission','RESOLVED_NEW','test-policy','{}',?3,NULL)",
		&sqlitex.ExecOptions{Args: []any{string(adopted.ID), string(adopted.ArtifactID), at.Format(time.RFC3339Nano)}}); err == nil {
		t.Fatal("direct Artifact admission unexpectedly succeeded")
	}

	authority := corpus.IdentityAuthoritySet{
		ID: "auth_direct_receipt_v38", PolicyID: "test-policy", ProviderID: "drive",
		IdentityDomain: "test-domain", ScopeID: "root", CurrentObjectID: "obj",
		UniverseCoverage: corpus.CandidateUniverseUnknown, SourceRefs: []string{"test"}, CreatedAt: at,
	}
	if err := store.insertIdentityAuthoritySetConn(conn, authority); err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO identity_mutation_requests (request_id,operation_kind,fingerprint_version,fingerprint_sha256,authority_set_id,observation_id,artifact_id,revision_id,revision_created,decision_kind,decision_id,accepted_at) VALUES ('req_receipt_direct_v38','SAME','identity-mutation-fingerprint:v1','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',?1,?2,?3,NULL,0,'CONTINUITY','cont_missing_v38',?4)",
		&sqlitex.ExecOptions{Args: []any{string(authority.ID), string(adopted.ID), string(adopted.ArtifactID), at.Format(time.RFC3339Nano)}}); err == nil {
		t.Fatal("direct identity mutation receipt unexpectedly succeeded")
	}
}

func sInsertTestProviderBinding(store *Store, conn *sqlite.Conn, artifactID corpus.ArtifactID, at time.Time) error {
	return store.insertProviderArtifactBindingConn(conn, corpus.ProviderArtifactBinding{
		IdentityDomain: "test-domain", ProviderID: "drive", ProviderObjectID: "obj-admission",
		ArtifactID: artifactID, PolicyID: "test-policy", AcceptedAt: at,
	})
}

func genericIdentityUnresolvedObservationInput() corpus.ObservationRecordInput {
	at := time.Date(2026, 9, 27, 13, 45, 0, 0, time.UTC)
	return corpus.ObservationRecordInput{
		ProviderObject: corpus.ProviderObject{
			ProviderID:    "localfs",
			ID:            "obj-generic-v38",
			IdentityState: corpus.ObjectIdentityObserved,
		},
		Locators: []corpus.Locator{{
			ProviderID: "localfs",
			Root:       "root",
			Path:       "x",
		}},
		AssignmentState: corpus.AssignmentUnresolved,
		ObservedAt:      at,
		Kind:            corpus.EntryOther,
		Size:            0,
		Mode:            0o600,
		ModifiedAt:      at,
	}
}
