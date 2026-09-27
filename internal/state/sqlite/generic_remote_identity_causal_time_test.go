package sqlitestate

import (
	"context"
	"encoding/json"
	"errors"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestGenericRemoteHistoryNewRejectsDecisionBeforeAuthorityCreation(t *testing.T) {
	ctx := context.Background()
	store := openInternalStore(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:v29-new")
	base := time.Date(2026, 9, 27, 2, 0, 0, 0, time.UTC)

	generation, err := store.StartRemoteHistoryGeneration(ctx, scope, fp, remoteHistoryBootstrap(scope, "cursor-1"), base)
	if err != nil { t.Fatal(err) }
	segments, err := store.RemoteHistoryLifetimeSegments(ctx, generation.ID)
	if err != nil { t.Fatal(err) }
	segment := findLatestLifetimeSegment(segments, "id-1")
	scan, err := store.StartScan(ctx, scope.ProviderID, scope.Root, base.Add(time.Minute))
	if err != nil { t.Fatal(err) }
	authority, err := store.CreateRemoteHistoryIdentityAuthority(ctx, generation.ID, segment.ID, base.Add(2*time.Minute))
	if err != nil { t.Fatal(err) }

	beforeArtifacts := internalTableCount(t, store.Path(), "artifacts")
	beforeRequests := internalTableCount(t, store.Path(), "identity_mutation_requests")
	_, err = store.AcceptNewObservationInScan(ctx, corpus.IdentityMutationRequest{
		ID: "req-v29-generic-new", ScanID: scan.ID,
		Observation: observedIdentityInput(scope.ProviderID, scope.Root, "id-1", "a.txt", scan.StartedAt),
		ContentEvidence: ptrInternalEvidence(internalEvidence("v29n", 4)),
		AuthoritySetID: authority.ID,
		DecidedAt: base.Add(90*time.Second),
	})
	if !errors.Is(err, ErrIdentityMutationCausalTime) {
		t.Fatalf("error=%v want ErrIdentityMutationCausalTime", err)
	}
	if internalTableCount(t, store.Path(), "artifacts") != beforeArtifacts ||
		internalTableCount(t, store.Path(), "identity_mutation_requests") != beforeRequests {
		t.Fatal("noncausal generic RemoteHistory NEW mutated identity state")
	}
}

func TestGenericRemoteHistorySameRejectsDecisionBeforeCurrentAuthorityCreation(t *testing.T) {
	ctx := context.Background()
	store := openInternalStore(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:v29-same")
	base := time.Date(2026, 9, 27, 3, 0, 0, 0, time.UTC)

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
		ID: "req-v29-seed", ScanID: scan1.ID,
		Observation: observedIdentityInput(scope.ProviderID, scope.Root, "id-1", "a.txt", scan1.StartedAt),
		ContentEvidence: ptrInternalEvidence(internalEvidence("seed", 4)),
		AuthoritySetID: newAuthority.ID, DecidedAt: scan1.StartedAt,
	})
	if err != nil { t.Fatal(err) }
	if err := store.CompleteScan(ctx, scan1.ID, base.Add(150*time.Second)); err != nil { t.Fatal(err) }

	scan2, err := store.StartScan(ctx, scope.ProviderID, scope.Root, base.Add(3*time.Minute))
	if err != nil { t.Fatal(err) }
	sameAuthority, err := store.CreateRemoteHistoryIdentityAuthority(ctx, generation.ID, segment.ID, base.Add(4*time.Minute))
	if err != nil { t.Fatal(err) }

	beforeObs := internalTableCount(t, store.Path(), "observations")
	beforeRequests := internalTableCount(t, store.Path(), "identity_mutation_requests")
	_, err = store.AcceptSameObservationInScan(ctx, corpus.IdentityMutationRequest{
		ID: "req-v29-generic-same", ScanID: scan2.ID,
		Observation: observedIdentityInput(scope.ProviderID, scope.Root, "id-1", "a.txt", scan2.StartedAt),
		ContentEvidence: ptrInternalEvidence(internalEvidence("seed", 4)),
		AuthoritySetID: sameAuthority.ID,
		DecidedAt: base.Add(210*time.Second),
	})
	if !errors.Is(err, ErrIdentityMutationCausalTime) {
		t.Fatalf("error=%v want ErrIdentityMutationCausalTime", err)
	}
	if internalTableCount(t, store.Path(), "observations") != beforeObs ||
		internalTableCount(t, store.Path(), "identity_mutation_requests") != beforeRequests {
		t.Fatal("noncausal generic RemoteHistory SAME mutated durable state")
	}
	if first.Observation.ArtifactID == "" { t.Fatal("seed Artifact missing") }
}

func TestV29SQLiteRejectsGenericRemoteHistoryDecisionAndReceiptWithoutCapability(t *testing.T) {
	ctx := context.Background()
	store := openInternalStore(t)
	scope := remoteHistoryTestScope()
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:v29-sql")
	base := time.Date(2026, 9, 27, 4, 0, 0, 0, time.UTC)

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
		ID: "req-v29-sql-seed", ScanID: scan1.ID,
		Observation: observedIdentityInput(scope.ProviderID, scope.Root, "id-1", "a.txt", scan1.StartedAt),
		ContentEvidence: ptrInternalEvidence(internalEvidence("seed", 4)),
		AuthoritySetID: newAuthority.ID, DecidedAt: scan1.StartedAt,
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
	defer store.pool.Put(conn)

	releaseOccurrence, err := store.authorizeOccurrenceInsertConn(conn, occurrenceInsertAuthorization{
		occurrenceID:   "pobjocc_v29_generic",
		providerID:     scope.ProviderID,
		nativeObjectID: "id-1",
		identityState:  corpus.ObjectIdentityObserved,
	})
	if err != nil {
		t.Fatal(err)
	}
	writeErr := sqlitex.Execute(conn,
		"INSERT INTO provider_object_occurrences (occurrence_id,provider_id,native_object_id,identity_state) VALUES ('pobjocc_v29_generic',?1,'id-1','OBSERVED')",
		&sqlitex.ExecOptions{Args: []any{string(scope.ProviderID)}})
	releaseOccurrence()
	if writeErr != nil {
		t.Fatal(writeErr)
	}
	releaseSource, err := store.authorizeIdentityMutationConn(conn, scan2.ID, "", "")
	if err != nil { t.Fatal(err) }
	releaseAcceptance, err := store.authorizeIdentityAcceptanceWriteConn(conn, scan2.ID, "OBSERVATION")
	if err != nil {
		releaseSource()
		t.Fatal(err)
	}
	releaseObservation, err := store.authorizeObservationInsertConn(conn, observationInsertAuthorization{
		observationID:   "obs_v29_generic",
		occurrenceID:    "pobjocc_v29_generic",
		artifactID:      first.Observation.ArtifactID,
		assignmentState: corpus.AssignmentAssigned,
		observedAt:      scan2.StartedAt.UTC().Format(time.RFC3339Nano),
		kind:            corpus.EntryRegularFile,
		size:            4,
		mode:            384,
		modifiedAt:      scan2.StartedAt.Add(-time.Minute).UTC().Format(time.RFC3339Nano),
		scanID:          scan2.ID,
	})
	if err != nil {
		releaseAcceptance()
		releaseSource()
		t.Fatal(err)
	}
	err = sqlitex.Execute(conn,
		"INSERT INTO observations (observation_id,occurrence_id,artifact_id,revision_id,assignment_state,observed_at,kind,size,mode,modified_at,scan_id) VALUES ('obs_v29_generic','pobjocc_v29_generic',?1,NULL,'ASSIGNED',?2,'REGULAR_FILE',4,384,?3,?4)",
		&sqlitex.ExecOptions{Args: []any{
			string(first.Observation.ArtifactID),
			scan2.StartedAt.UTC().Format(time.RFC3339Nano),
			scan2.StartedAt.Add(-time.Minute).UTC().Format(time.RFC3339Nano),
			string(scan2.ID),
		}})
	releaseObservation()
	releaseAcceptance()
	releaseSource()
	if err != nil {
		t.Fatal(err)
	}
	decisionAt := base.Add(5*time.Minute)
	insertDecision := func() error {
		return sqlitex.Execute(conn,
			"INSERT INTO accepted_continuity_decisions (decision_id,observation_id,artifact_id,decision_state,policy_id,resolution_json,decided_at,lifetime_segment_id) VALUES ('cont_v29_generic','obs_v29_generic',?1,'RESOLVED_SAME',?2,?3,?4,?5)",
			&sqlitex.ExecOptions{Args: []any{
				string(first.Observation.ArtifactID),
				remoteHistoryLifetimeAuthorityPolicyV1,
				string(resolutionJSON),
				decisionAt.UTC().Format(time.RFC3339Nano),
				string(segment.ID),
			}})
	}
	if err := insertDecision(); err == nil {
		t.Fatal("generic RemoteHistory continuity direct SQL unexpectedly bypassed application authority")
	}

	releaseSource, err = store.authorizeIdentityMutationConn(conn, scan2.ID, "", "")
	if err != nil { t.Fatal(err) }
	releaseAcceptance, err = store.authorizeIdentityAcceptanceWriteConn(conn, scan2.ID, "CONTINUITY")
	if err != nil {
		releaseSource()
		t.Fatal(err)
	}
	if err := insertDecision(); err != nil {
		releaseAcceptance()
		releaseSource()
		t.Fatalf("validated capabilities could not persist generic RemoteHistory decision: %v", err)
	}
	releaseAcceptance()
	releaseSource()

	err = sqlitex.Execute(conn,
		"INSERT INTO identity_mutation_requests (request_id,operation_kind,fingerprint_version,fingerprint_sha256,authority_set_id,observation_id,artifact_id,revision_id,revision_created,decision_kind,decision_id,accepted_at) VALUES ('req_v29_direct_receipt','SAME','test:v1','deadbeef',?1,'obs_v29_generic',?2,NULL,0,'CONTINUITY','cont_v29_generic',?3)",
		&sqlitex.ExecOptions{Args: []any{
			string(sameAuthority.ID),
			string(first.Observation.ArtifactID),
			decisionAt.UTC().Format(time.RFC3339Nano),
		}})
	if err == nil {
		t.Fatal("generic RemoteHistory receipt direct SQL unexpectedly bypassed application authority")
	}
}
