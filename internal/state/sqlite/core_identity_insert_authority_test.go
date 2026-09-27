package sqlitestate

import (
	"context"
	"testing"
	"time"

	"zombiezen.com/go/sqlite/sqlitex"
)

func TestCoreIdentityInsertApplicationAuthorityRejectsDirectSQL(t *testing.T) {
	ctx := context.Background()
	store := openInternalStore(t)

	conn, err := store.pool.Get(ctx)
	if err != nil { t.Fatal(err) }
	if err := sqlitex.Execute(conn, "INSERT INTO artifacts (artifact_id) VALUES ('art_direct_v35')", nil); err == nil {
		store.pool.Put(conn)
		t.Fatal("direct Artifact insert unexpectedly succeeded")
	}
	store.pool.Put(conn)

	artifact, err := store.AdoptArtifact(ctx)
	if err != nil { t.Fatal(err) }

	conn, err = store.pool.Get(ctx)
	if err != nil { t.Fatal(err) }
	if err := sqlitex.Execute(conn,
		"INSERT INTO revisions (revision_id,artifact_id,sequence,content_algorithm,content_digest,content_size) VALUES ('rev_direct_v35',?1,1,'sha256','deadbeef',4)",
		&sqlitex.ExecOptions{Args: []any{string(artifact.ID)}}); err == nil {
		store.pool.Put(conn)
		t.Fatal("direct Revision insert unexpectedly succeeded")
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO provider_artifact_bindings (identity_domain,provider_id,native_object_id,artifact_id,policy_id,accepted_at) VALUES ('domain','provider','object',?1,'policy',?2)",
		&sqlitex.ExecOptions{Args: []any{
			string(artifact.ID),
			time.Date(2026, 9, 27, 8, 0, 0, 0, time.UTC).Format(time.RFC3339Nano),
		}}); err == nil {
		store.pool.Put(conn)
		t.Fatal("direct provider Artifact binding insert unexpectedly succeeded")
	}
	store.pool.Put(conn)

	revision, err := store.ObserveRevision(ctx, artifact.ID, internalEvidence("v35-authorized", 4))
	if err != nil { t.Fatal(err) }
	if !revision.Created || revision.Current.Sequence != 1 {
		t.Fatalf("legitimate Revision observation=%#v", revision)
	}
}

func TestCoreIdentityInsertCapabilityIsExactPerRow(t *testing.T) {
	ctx := context.Background()
	store := openInternalStore(t)
	conn, err := store.pool.Get(ctx)
	if err != nil { t.Fatal(err) }
	defer store.pool.Put(conn)

	release, err := store.authorizeCoreIdentityInsertConn(conn, coreIdentityInsertAuthorization{
		kind: "ARTIFACT", artifactID: "art_expected_v35",
	})
	if err != nil { t.Fatal(err) }
	defer release()
	if err := sqlitex.Execute(conn, "INSERT INTO artifacts (artifact_id) VALUES ('art_wrong_v35')", nil); err == nil {
		t.Fatal("Artifact capability authorized the wrong row")
	}
}
