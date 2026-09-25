package sqlitestate

import (
	"context"
	"fmt"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

func openInternalStore(t *testing.T) *Store {
	t.Helper()
	store, err := Open(context.Background(), filepath.Join(t.TempDir(), "state.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := store.Close(); err != nil {
			t.Error(err)
		}
	})
	return store
}

func internalEvidence(digest string, size int64) corpus.ContentEvidence {
	return corpus.ContentEvidence{Algorithm: corpus.ContentAlgorithmSHA256, Digest: digest, Size: size}
}
func ptrInternalEvidence(value corpus.ContentEvidence) *corpus.ContentEvidence { return &value }

func observedIdentityInput(provider corpus.ProviderID, root string, objectID corpus.ProviderObjectID, path string, at time.Time) corpus.ObservationRecordInput {
	return corpus.ObservationRecordInput{
		ProviderObject: corpus.ProviderObject{ProviderID: provider, ID: objectID, IdentityState: corpus.ObjectIdentityObserved},
		Locators: []corpus.Locator{{ProviderID: provider, Root: root, Path: path}},
		AssignmentState: corpus.AssignmentUnresolved,
		ObservedAt: at, Kind: corpus.EntryRegularFile, Size: 4, Mode: 0o600, ModifiedAt: at.Add(-time.Minute),
	}
}

func seedAuthoritySet(t *testing.T, store *Store, set corpus.IdentityAuthoritySet) {
	t.Helper()
	conn, err := store.pool.Get(context.Background())
	if err != nil { t.Fatal(err) }
	defer store.pool.Put(conn)
	end, err := sqlitex.ImmediateTransaction(conn)
	if err != nil { t.Fatal(err) }
	defer end(&err)
	if err = insertIdentityAuthoritySetConn(conn, set); err != nil { t.Fatal(err) }
}

func sameAuthority(id corpus.IdentityAuthoritySetID, artifactID corpus.ArtifactID, objectID corpus.ProviderObjectID, at time.Time) corpus.IdentityAuthoritySet {
	return corpus.IdentityAuthoritySet{
		ID: id, PolicyID: "test:authority:v1", ProviderID: "drive", IdentityDomain: "drive:test-account",
		ScopeID: "drive-root", CurrentObjectID: objectID, UniverseCoverage: corpus.CandidateUniverseUnknown,
		SourceRefs: []string{"test:same"},
		Candidates: []corpus.IdentityAuthorityCandidate{{ArtifactID: artifactID, Direction: corpus.DirectionSupportsSame, SourceRef: "test:same"}},
		CreatedAt: at,
	}
}

func newAuthority(id corpus.IdentityAuthoritySetID, objectID corpus.ProviderObjectID, candidates []corpus.IdentityAuthorityCandidate, at time.Time) corpus.IdentityAuthoritySet {
	return corpus.IdentityAuthoritySet{
		ID: id, PolicyID: "test:authority:v1", ProviderID: "drive", IdentityDomain: "drive:test-account",
		ScopeID: "drive-root", CurrentObjectID: objectID, UniverseCoverage: corpus.CandidateUniverseComplete,
		GenerationID: "gen-test", LifetimeSegmentID: "seg-" + string(objectID),
		SourceRefs: []string{"test:complete"}, Candidates: candidates, CreatedAt: at,
	}
}

func identityRequest(id corpus.IdentityMutationRequestID, scanID corpus.ScanSessionID, objectID corpus.ProviderObjectID, path string, authorityID corpus.IdentityAuthoritySetID, at time.Time, digest string) corpus.IdentityMutationRequest {
	return corpus.IdentityMutationRequest{
		ID: id, ScanID: scanID,
		Observation: observedIdentityInput("drive", "drive-root", objectID, path, at),
		ContentEvidence: ptrInternalEvidence(internalEvidence(digest, 4)),
		AuthoritySetID: authorityID, DecidedAt: at,
	}
}

func internalTableCount(t *testing.T, path, table string) int64 {
	t.Helper()
	conn, err := sqlite.OpenConn(path, sqlite.OpenReadOnly)
	if err != nil { t.Fatal(err) }
	defer conn.Close()
	var count int64
	query := fmt.Sprintf("SELECT COUNT(*) FROM %s", table)
	if err := sqlitex.Execute(conn, query, &sqlitex.ExecOptions{ResultFunc: func(stmt *sqlite.Stmt) error {
		count = stmt.ColumnInt64(0); return nil
	}}); err != nil { t.Fatal(err) }
	return count
}
