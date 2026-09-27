package sqlitestate

import (
	"context"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory/gdrive"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestSourceBoundAssignedObservationRejectsDirectSQLWithoutIdentityCapability(t *testing.T) {
	ctx := context.Background()
	fixture := newGoogleRemoteCompletionFixture(t)
	entries := []remotehistory.RemoteMetadataFingerprintEntry{
		fixture.entry("managed", corpus.EntryOther, 0, fixture.base),
		fixture.entry("child", corpus.EntryRegularFile, 7, fixture.base.Add(time.Second)),
	}
	scan, err := fixture.startScan(entries, fixture.scanRoot)
	if err != nil {
		t.Fatal(err)
	}
	artifact, err := fixture.store.AdoptArtifact(ctx)
	if err != nil {
		t.Fatal(err)
	}
	conn, err := fixture.store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer fixture.store.pool.Put(conn)
	releaseOccurrence, err := fixture.store.authorizeOccurrenceInsertConn(conn, occurrenceInsertAuthorization{
		occurrenceID:   "pobjocc_direct_identity",
		providerID:     "google-drive",
		nativeObjectID: "child",
		identityState:  corpus.ObjectIdentityObserved,
	})
	if err != nil {
		t.Fatal(err)
	}
	writeErr := sqlitex.Execute(conn,
		"INSERT INTO provider_object_occurrences (occurrence_id,provider_id,native_object_id,identity_state) VALUES ('pobjocc_direct_identity','google-drive','child','OBSERVED')",
		nil)
	releaseOccurrence()
	if writeErr != nil {
		t.Fatal(writeErr)
	}
	releaseAcceptance, err := fixture.store.authorizeIdentityAcceptanceWriteConn(conn, scan.ID, "OBSERVATION")
	if err != nil {
		t.Fatal(err)
	}
	releaseObservation, err := fixture.store.authorizeObservationInsertConn(conn, observationInsertAuthorization{
		observationID:   "obs_direct_identity",
		occurrenceID:    "pobjocc_direct_identity",
		artifactID:      artifact.ID,
		assignmentState: corpus.AssignmentAssigned,
		observedAt:      scan.StartedAt.UTC().Format(time.RFC3339Nano),
		kind:            corpus.EntryRegularFile,
		size:            7,
		mode:            0,
		modifiedAt:      fixture.base.Add(time.Second).UTC().Format(time.RFC3339Nano),
		scanID:          scan.ID,
	})
	if err != nil {
		releaseAcceptance()
		t.Fatal(err)
	}
	err = sqlitex.Execute(conn,
		"INSERT INTO observations (observation_id,occurrence_id,artifact_id,revision_id,assignment_state,observed_at,kind,size,mode,modified_at,scan_id) VALUES ('obs_direct_identity','pobjocc_direct_identity',?1,NULL,'ASSIGNED',?2,'REGULAR_FILE',7,0,?3,?4)",
		&sqlitex.ExecOptions{Args: []any{
			string(artifact.ID),
			scan.StartedAt.UTC().Format(time.RFC3339Nano),
			fixture.base.Add(time.Second).UTC().Format(time.RFC3339Nano),
			string(scan.ID),
		}})
	releaseObservation()
	releaseAcceptance()
	if err == nil {
		t.Fatal("direct source-bound assigned Observation unexpectedly succeeded")
	}
}

func TestRemoteHistoryLifetimeBindingRejectsDirectSQLWithoutIdentityCapability(t *testing.T) {
	ctx := context.Background()
	fixture := newGoogleRemoteCompletionFixture(t)
	segments, err := fixture.store.RemoteHistoryLifetimeSegments(ctx, fixture.generation.ID)
	if err != nil {
		t.Fatal(err)
	}
	segment := findLatestLifetimeSegment(segments, "child")
	authority, err := fixture.store.CreateRemoteHistoryIdentityAuthority(
		ctx, fixture.generation.ID, segment.ID, fixture.base.Add(time.Minute),
	)
	if err != nil {
		t.Fatal(err)
	}
	artifact, err := fixture.store.AdoptArtifact(ctx)
	if err != nil {
		t.Fatal(err)
	}
	conn, err := fixture.store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer fixture.store.pool.Put(conn)
	err = sqlitex.Execute(conn,
		"INSERT INTO provider_lifetime_artifact_bindings (lifetime_segment_id,artifact_id,policy_id,source_authority_set_id,accepted_at) VALUES (?1,?2,?3,?4,?5)",
		&sqlitex.ExecOptions{Args: []any{
			string(segment.ID),
			string(artifact.ID),
			remoteHistoryLifetimeAuthorityPolicyV1,
			string(authority.ID),
			fixture.base.Add(time.Minute).UTC().Format(time.RFC3339Nano),
		}})
	if err == nil {
		t.Fatal("direct RemoteHistory lifetime binding unexpectedly succeeded")
	}
}

func TestSourceBoundIdentityMutationAPICapabilityStillAllowsNew(t *testing.T) {
	ctx := context.Background()
	fixture := newGoogleRemoteCompletionFixture(t)
	entries := []remotehistory.RemoteMetadataFingerprintEntry{
		fixture.entry("managed", corpus.EntryOther, 0, fixture.base),
		fixture.entry("child", corpus.EntryRegularFile, 7, fixture.base.Add(time.Second)),
	}
	scan, err := fixture.startScan(entries, fixture.scanRoot)
	if err != nil {
		t.Fatal(err)
	}
	segments, err := fixture.store.RemoteHistoryLifetimeSegments(ctx, fixture.generation.ID)
	if err != nil {
		t.Fatal(err)
	}
	segment := findLatestLifetimeSegment(segments, "child")
	authority, err := fixture.store.CreateRemoteHistoryIdentityAuthority(
		ctx, fixture.generation.ID, segment.ID, scan.StartedAt,
	)
	if err != nil {
		t.Fatal(err)
	}
	modifiedAt, _ := time.Parse(time.RFC3339Nano, entries[1].ModifiedAt)
	accepted, err := fixture.store.AcceptNewObservationInScan(ctx, corpus.IdentityMutationRequest{
		ID: "req-capability-new",
		ScanID: scan.ID,
		Observation: corpus.ObservationRecordInput{
			ProviderObject: corpus.ProviderObject{
				ProviderID:gdrive.ProviderID, ID:"child", IdentityState:corpus.ObjectIdentityObserved,
			},
			Locators: append([]corpus.Locator(nil), entries[1].Locators...),
			AssignmentState: corpus.AssignmentUnresolved,
			ObservedAt: scan.StartedAt,
			Kind: entries[1].Kind, Size: entries[1].Size, Mode: entries[1].Mode, ModifiedAt: modifiedAt,
		},
		AuthoritySetID: authority.ID,
		DecidedAt: scan.StartedAt,
	})
	if err != nil {
		t.Fatal(err)
	}
	if accepted.Observation.ArtifactID == "" {
		t.Fatal("authorized NEW did not assign Artifact")
	}
	if err := fixture.store.AbortScan(ctx, scan.ID, scan.StartedAt.Add(time.Second)); err != nil {
		t.Fatal(err)
	}
}

func TestSourceBoundAcceptedContinuityRejectsDirectSQLWithoutIdentityCapability(t *testing.T) {
	ctx := context.Background()
	fixture := newGoogleRemoteCompletionFixture(t)
	entries := []remotehistory.RemoteMetadataFingerprintEntry{
		fixture.entry("managed", corpus.EntryOther, 0, fixture.base),
		fixture.entry("child", corpus.EntryRegularFile, 7, fixture.base.Add(time.Second)),
	}
	scan, err := fixture.startScan(entries, fixture.scanRoot)
	if err != nil {
		t.Fatal(err)
	}
	modifiedAt, _ := time.Parse(time.RFC3339Nano, entries[1].ModifiedAt)
	observation, err := fixture.store.RecordObservationInScan(ctx, scan.ID, corpus.ObservationRecordInput{
		ProviderObject: corpus.ProviderObject{
			ProviderID: gdrive.ProviderID, ID: "child", IdentityState: corpus.ObjectIdentityObserved,
		},
		Locators: append([]corpus.Locator(nil), entries[1].Locators...),
		AssignmentState: corpus.AssignmentUnresolved,
		ObservedAt: scan.StartedAt,
		Kind: entries[1].Kind, Size: entries[1].Size, Mode: entries[1].Mode, ModifiedAt: modifiedAt,
	})
	if err != nil {
		t.Fatal(err)
	}
	artifact, err := fixture.store.AdoptArtifact(ctx)
	if err != nil {
		t.Fatal(err)
	}
	conn, err := fixture.store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer fixture.store.pool.Put(conn)
	err = sqlitex.Execute(conn,
		"INSERT INTO accepted_continuity_decisions (decision_id,observation_id,artifact_id,decision_state,policy_id,resolution_json,decided_at,lifetime_segment_id) VALUES ('cont_direct_guard',?1,?2,'RESOLVED_SAME','test-policy','{}',?3,NULL)",
		&sqlitex.ExecOptions{Args: []any{
			string(observation.ID),
			string(artifact.ID),
			scan.StartedAt.UTC().Format(time.RFC3339Nano),
		}})
	if err == nil {
		t.Fatal("direct source-bound continuity decision unexpectedly succeeded")
	}
}

func TestSourceBoundAcceptedAdmissionRejectsDirectSQLWithoutIdentityCapability(t *testing.T) {
	ctx := context.Background()
	fixture := newGoogleRemoteCompletionFixture(t)
	entries := []remotehistory.RemoteMetadataFingerprintEntry{
		fixture.entry("managed", corpus.EntryOther, 0, fixture.base),
		fixture.entry("child", corpus.EntryRegularFile, 7, fixture.base.Add(time.Second)),
	}
	scan, err := fixture.startScan(entries, fixture.scanRoot)
	if err != nil {
		t.Fatal(err)
	}
	modifiedAt, _ := time.Parse(time.RFC3339Nano, entries[1].ModifiedAt)
	observation, err := fixture.store.RecordObservationInScan(ctx, scan.ID, corpus.ObservationRecordInput{
		ProviderObject: corpus.ProviderObject{
			ProviderID: gdrive.ProviderID, ID: "child", IdentityState: corpus.ObjectIdentityObserved,
		},
		Locators: append([]corpus.Locator(nil), entries[1].Locators...),
		AssignmentState: corpus.AssignmentUnresolved,
		ObservedAt: scan.StartedAt,
		Kind: entries[1].Kind, Size: entries[1].Size, Mode: entries[1].Mode, ModifiedAt: modifiedAt,
	})
	if err != nil {
		t.Fatal(err)
	}
	artifact, err := fixture.store.AdoptArtifact(ctx)
	if err != nil {
		t.Fatal(err)
	}
	conn, err := fixture.store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer fixture.store.pool.Put(conn)
	if err := fixture.store.insertProviderArtifactBindingConn(conn, corpus.ProviderArtifactBinding{
		IdentityDomain:   "test-domain",
		ProviderID:       gdrive.ProviderID,
		ProviderObjectID: "child",
		ArtifactID:       artifact.ID,
		PolicyID:         "test-policy",
		AcceptedAt:       scan.StartedAt,
	}); err != nil {
		t.Fatal(err)
	}
	err = sqlitex.Execute(conn,
		"INSERT INTO accepted_artifact_admissions (request_id,observation_id,artifact_id,identity_domain,provider_id,native_object_id,decision_state,policy_id,resolution_json,decided_at,lifetime_segment_id) VALUES ('req_direct_admission_guard',?1,?2,'test-domain','google-drive','child','RESOLVED_NEW','test-policy','{}',?3,NULL)",
		&sqlitex.ExecOptions{Args: []any{
			string(observation.ID),
			string(artifact.ID),
			scan.StartedAt.UTC().Format(time.RFC3339Nano),
		}})
	if err == nil {
		t.Fatal("direct source-bound admission unexpectedly succeeded")
	}
}

func TestSourceBoundIdentityMutationReceiptRejectsDirectSQLWithoutIdentityCapability(t *testing.T) {
	ctx := context.Background()
	fixture := newGoogleRemoteCompletionFixture(t)
	entries := []remotehistory.RemoteMetadataFingerprintEntry{
		fixture.entry("managed", corpus.EntryOther, 0, fixture.base),
		fixture.entry("child", corpus.EntryRegularFile, 7, fixture.base.Add(time.Second)),
	}
	scan, err := fixture.startScan(entries, fixture.scanRoot)
	if err != nil {
		t.Fatal(err)
	}
	modifiedAt, _ := time.Parse(time.RFC3339Nano, entries[1].ModifiedAt)
	observation, err := fixture.store.RecordObservationInScan(ctx, scan.ID, corpus.ObservationRecordInput{
		ProviderObject: corpus.ProviderObject{
			ProviderID: gdrive.ProviderID, ID: "child", IdentityState: corpus.ObjectIdentityObserved,
		},
		Locators: append([]corpus.Locator(nil), entries[1].Locators...),
		AssignmentState: corpus.AssignmentUnresolved,
		ObservedAt: scan.StartedAt,
		Kind: entries[1].Kind, Size: entries[1].Size, Mode: entries[1].Mode, ModifiedAt: modifiedAt,
	})
	if err != nil {
		t.Fatal(err)
	}
	segments, err := fixture.store.RemoteHistoryLifetimeSegments(ctx, fixture.generation.ID)
	if err != nil {
		t.Fatal(err)
	}
	segment := findLatestLifetimeSegment(segments, "child")
	authority, err := fixture.store.CreateRemoteHistoryIdentityAuthority(
		ctx, fixture.generation.ID, segment.ID, scan.StartedAt,
	)
	if err != nil {
		t.Fatal(err)
	}
	artifact, err := fixture.store.AdoptArtifact(ctx)
	if err != nil {
		t.Fatal(err)
	}
	conn, err := fixture.store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer fixture.store.pool.Put(conn)
	err = sqlitex.Execute(conn,
		"INSERT INTO identity_mutation_requests (request_id,operation_kind,fingerprint_version,fingerprint_sha256,authority_set_id,observation_id,artifact_id,revision_id,revision_created,decision_kind,decision_id,accepted_at) VALUES ('req_direct_receipt_guard','NEW','identity-mutation-fingerprint:v1','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',?1,?2,?3,NULL,0,'ADMISSION','req_direct_receipt_guard',?4)",
		&sqlitex.ExecOptions{Args: []any{
			string(authority.ID),
			string(observation.ID),
			string(artifact.ID),
			scan.StartedAt.UTC().Format(time.RFC3339Nano),
		}})
	if err == nil {
		t.Fatal("direct source-bound identity mutation receipt unexpectedly succeeded")
	}
}

func TestIdentityMutationAuthorizationReleaseClearsConnectionCapability(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer store.pool.Put(conn)

	release, err := store.authorizeIdentityMutationConn(
		conn,
		"scan-capability-test",
		"segment-capability-test",
		"authority-capability-test",
	)
	if err != nil {
		t.Fatal(err)
	}
	assertIdentityMutationCapabilitySQL(t, conn, 1)
	release()
	assertIdentityMutationCapabilitySQL(t, conn, 0)

	releaseAgain, err := store.authorizeIdentityMutationConn(conn, "scan-capability-test-2", "", "")
	if err != nil {
		t.Fatal(err)
	}
	var scanOnly int64
	if err := sqlitex.Execute(conn,
		"SELECT keelaryn_source_identity_mutation_authorized('scan-capability-test-2')",
		&sqlitex.ExecOptions{ResultFunc: func(stmt *sqlite.Stmt) error {
			scanOnly = stmt.ColumnInt64(0)
			return nil
		}}); err != nil {
		t.Fatal(err)
	}
	if scanOnly != 1 {
		t.Fatalf("reused scan capability=%d want 1", scanOnly)
	}
	releaseAgain()
}

func assertIdentityMutationCapabilitySQL(t *testing.T, conn *sqlite.Conn, want int64) {
	t.Helper()
	var scanAuthorized, bindingAuthorized int64
	if err := sqlitex.Execute(conn,
		"SELECT keelaryn_source_identity_mutation_authorized('scan-capability-test'), keelaryn_remote_history_binding_authorized('segment-capability-test','authority-capability-test')",
		&sqlitex.ExecOptions{ResultFunc: func(stmt *sqlite.Stmt) error {
			scanAuthorized = stmt.ColumnInt64(0)
			bindingAuthorized = stmt.ColumnInt64(1)
			return nil
		}}); err != nil {
		t.Fatal(err)
	}
	if scanAuthorized != want || bindingAuthorized != want {
		t.Fatalf("capability scan=%d binding=%d want=%d", scanAuthorized, bindingAuthorized, want)
	}
}
