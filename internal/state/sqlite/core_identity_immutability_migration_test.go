package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"
	"time"

	"zombiezen.com/go/sqlite/sqlitex"
)

func TestQualifiedV32DatabaseMigratesToCoreIdentityImmutabilityV33(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v32.db")
	store, err := openPartialRemoteIdentityStore(path, 32)
	if err != nil { t.Fatal(err) }
	if err := store.Close(); err != nil { t.Fatal(err) }

	migrated, err := Open(ctx, path)
	if err != nil { t.Fatal(err) }
	defer migrated.Close()
}

func TestV33CoreIdentityRowsRejectUpdateAndDelete(t *testing.T) {
	ctx := context.Background()
	store := openV33GoogleTopologyStore(t, filepath.Join(t.TempDir(), "v33-core.db"))
	defer store.Close()

	artifact, err := store.AdoptArtifact(ctx)
	if err != nil { t.Fatal(err) }
	otherArtifact, err := store.AdoptArtifact(ctx)
	if err != nil { t.Fatal(err) }

	revision, err := store.ObserveRevision(ctx, artifact.ID, internalEvidence("immutable-revision", 4))
	if err != nil { t.Fatal(err) }

	conn, err := store.pool.Get(ctx)
	if err != nil { t.Fatal(err) }
	defer store.pool.Put(conn)

	for name, query := range map[string]string{
		"artifact update": "UPDATE artifacts SET artifact_id='art_tampered' WHERE artifact_id='" + string(artifact.ID) + "'",
		"artifact delete": "DELETE FROM artifacts WHERE artifact_id='" + string(otherArtifact.ID) + "'",
		"revision update": "UPDATE revisions SET content_digest='tampered' WHERE revision_id='" + string(revision.Current.Revision.ID) + "'",
		"revision delete": "DELETE FROM revisions WHERE revision_id='" + string(revision.Current.Revision.ID) + "'",
	} {
		t.Run(name, func(t *testing.T) {
			if err := sqlitex.Execute(conn, query, nil); err == nil {
				t.Fatalf("%s unexpectedly succeeded", name)
			}
		})
	}

	acceptedAt := time.Date(2026, 9, 27, 12, 0, 0, 0, time.UTC).Format(time.RFC3339Nano)
	if err := sqlitex.Execute(conn,
		"INSERT INTO provider_artifact_bindings (identity_domain,provider_id,native_object_id,artifact_id,policy_id,accepted_at) VALUES ('test-domain','test-provider','object-1',?1,'test:local',?2)",
		&sqlitex.ExecOptions{Args: []any{string(otherArtifact.ID), acceptedAt}}); err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"UPDATE provider_artifact_bindings SET policy_id='tampered' WHERE identity_domain='test-domain' AND provider_id='test-provider' AND native_object_id='object-1'",
		nil); err == nil {
		t.Fatal("provider Artifact binding update unexpectedly succeeded")
	}
	if err := sqlitex.Execute(conn,
		"DELETE FROM provider_artifact_bindings WHERE identity_domain='test-domain' AND provider_id='test-provider' AND native_object_id='object-1'",
		nil); err == nil {
		t.Fatal("provider Artifact binding delete unexpectedly succeeded")
	}
}
