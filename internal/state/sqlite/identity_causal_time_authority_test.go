package sqlitestate

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory/gdrive"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestRemoteHistoryIdentityAuthorityRejectsCreatedBeforeSourcePublication(t *testing.T) {
	ctx := context.Background()
	fixture := newGoogleRemoteCompletionFixture(t)
	segments, err := fixture.store.RemoteHistoryLifetimeSegments(ctx, fixture.generation.ID)
	if err != nil {
		t.Fatal(err)
	}
	segment := findLatestLifetimeSegment(segments, "child")
	if _, err := fixture.store.CreateRemoteHistoryIdentityAuthority(
		ctx,
		fixture.generation.ID,
		segment.ID,
		fixture.base.Add(-time.Nanosecond),
	); !errors.Is(err, ErrRemoteHistoryIdentityAuthorityCausalTime) {
		t.Fatalf("error=%v want ErrRemoteHistoryIdentityAuthorityCausalTime", err)
	}
}

func TestSourceBoundIdentityMutationRejectsDecisionBeforeScanOrAuthority(t *testing.T) {
	ctx := context.Background()
	for _, tc := range []struct {
		name            string
		authorityOffset time.Duration
		decisionOffset  time.Duration
	}{
		{name: "before scan", authorityOffset: time.Minute, decisionOffset: time.Minute - time.Nanosecond},
		{name: "before authority", authorityOffset: time.Minute + time.Second, decisionOffset: time.Minute},
	} {
		t.Run(tc.name, func(t *testing.T) {
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
				ctx,
				fixture.generation.ID,
				segment.ID,
				fixture.base.Add(tc.authorityOffset),
			)
			if err != nil {
				t.Fatal(err)
			}
			entry := entries[1]
			modifiedAt, err := time.Parse(time.RFC3339Nano, entry.ModifiedAt)
			if err != nil {
				t.Fatal(err)
			}
			beforeArtifacts := internalTableCount(t, fixture.store.Path(), "artifacts")
			beforeRequests := internalTableCount(t, fixture.store.Path(), "identity_mutation_requests")
			_, err = fixture.store.AcceptNewObservationInScan(ctx, corpus.IdentityMutationRequest{
				ID: corpus.IdentityMutationRequestID("req-causal-" + tc.name),
				ScanID: scan.ID,
				Observation: corpus.ObservationRecordInput{
					ProviderObject: corpus.ProviderObject{
						ProviderID: gdrive.ProviderID,
						ID: "child",
						IdentityState: corpus.ObjectIdentityObserved,
					},
					Locators: append([]corpus.Locator(nil), entry.Locators...),
					AssignmentState: corpus.AssignmentUnresolved,
					ObservedAt: scan.StartedAt,
					Kind: entry.Kind,
					Size: entry.Size,
					Mode: entry.Mode,
					ModifiedAt: modifiedAt,
				},
				AuthoritySetID: authority.ID,
				DecidedAt: fixture.base.Add(tc.decisionOffset),
			})
			if !errors.Is(err, ErrIdentityMutationCausalTime) {
				t.Fatalf("error=%v want ErrIdentityMutationCausalTime", err)
			}
			if internalTableCount(t, fixture.store.Path(), "artifacts") != beforeArtifacts ||
				internalTableCount(t, fixture.store.Path(), "identity_mutation_requests") != beforeRequests {
				t.Fatal("noncausal identity decision mutated durable state")
			}
			if err := fixture.store.AbortScan(ctx, scan.ID, scan.StartedAt.Add(2*time.Second)); err != nil {
				t.Fatal(err)
			}
		})
	}
}

func TestV28SQLiteRejectsAuthorizedNoncausalSourceIdentityWrites(t *testing.T) {
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
	release, err := fixture.store.authorizeIdentityMutationConn(conn, scan.ID, "", "")
	if err != nil {
		t.Fatal(err)
	}
	defer release()
	if err := sqlitex.Execute(conn,
		"INSERT INTO provider_object_occurrences (occurrence_id,provider_id,native_object_id,identity_state) VALUES ('pobjocc_v28_bad_time','google-drive','child','OBSERVED')",
		nil); err != nil {
		t.Fatal(err)
	}
	err = sqlitex.Execute(conn,
		"INSERT INTO observations (observation_id,occurrence_id,artifact_id,revision_id,assignment_state,observed_at,kind,size,mode,modified_at,scan_id) VALUES ('obs_v28_bad_time','pobjocc_v28_bad_time',?1,NULL,'ASSIGNED',?2,'REGULAR_FILE',7,0,?3,?4)",
		&sqlitex.ExecOptions{Args: []any{
			string(artifact.ID),
			scan.StartedAt.Add(time.Nanosecond).UTC().Format(time.RFC3339Nano),
			fixture.base.Add(time.Second).UTC().Format(time.RFC3339Nano),
			string(scan.ID),
		}})
	if err == nil {
		t.Fatal("authorized source-bound assigned Observation with noncausal time unexpectedly succeeded")
	}
}

func TestV28SQLiteRejectsRemoteLifetimeBindingBeforeAuthorityCreation(t *testing.T) {
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
	release, err := fixture.store.authorizeIdentityMutationConn(conn, "", segment.ID, authority.ID)
	if err != nil {
		t.Fatal(err)
	}
	defer release()
	_, _, err = insertProviderLifetimeArtifactBindingConn(conn, ProviderLifetimeArtifactBinding{
		LifetimeSegmentID: segment.ID,
		ArtifactID: artifact.ID,
		PolicyID: remoteHistoryLifetimeAuthorityPolicyV1,
		AuthoritySetID: authority.ID,
		AcceptedAt: authority.CreatedAt.Add(-time.Nanosecond),
	})
	if err == nil {
		t.Fatal("authorized lifetime binding before authority creation unexpectedly succeeded")
	}
}
