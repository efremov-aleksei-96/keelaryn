package sqlitestate

import (
	"context"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory/gdrive"
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
	if err := sqlitex.Execute(conn,
		"INSERT INTO provider_object_occurrences (occurrence_id,provider_id,native_object_id,identity_state) VALUES ('pobjocc_direct_identity','google-drive','child','OBSERVED')",
		nil); err != nil {
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

func TestSourceBoundIdentityMutationAPICapabilityStillAllowsNewAndSame(t *testing.T) {
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
