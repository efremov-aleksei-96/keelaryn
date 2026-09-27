package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestGenericScanObservationApplicationAuthorityRejectsDirectSQL(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "state.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	base := time.Date(2026, 9, 27, 17, 0, 0, 0, time.UTC)
	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO scan_sessions (scan_id, provider_id, root, status, started_at, finished_at) VALUES ('scan_forged','provider','root','OPEN',?1,NULL)",
		&sqlitex.ExecOptions{Args: []any{base.Format(time.RFC3339Nano)}}); err == nil {
		store.pool.Put(conn)
		t.Fatal("direct OPEN scan insert unexpectedly succeeded")
	}
	store.pool.Put(conn)

	scan, err := store.StartScan(ctx, "provider", "root", base)
	if err != nil {
		t.Fatal(err)
	}

	conn, err = store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"UPDATE scan_sessions SET status='COMPLETE', finished_at=?1 WHERE scan_id=?2",
		&sqlitex.ExecOptions{Args: []any{base.Add(time.Second).Format(time.RFC3339Nano), string(scan.ID)}}); err == nil {
		store.pool.Put(conn)
		t.Fatal("direct scan completion unexpectedly succeeded")
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO provider_object_occurrences (occurrence_id,provider_id,native_object_id,identity_state) VALUES ('pobjocc_forged','provider','object-forged','OBSERVED')",
		nil); err == nil {
		store.pool.Put(conn)
		t.Fatal("direct ProviderObject occurrence insert unexpectedly succeeded")
	}

	occurrenceID := corpus.ProviderObjectOccurrenceID("pobjocc_setup")
	releaseOccurrence, err := store.authorizeOccurrenceInsertConn(conn, occurrenceInsertAuthorization{
		occurrenceID: occurrenceID, providerID: "provider", nativeObjectID: "object-setup", identityState: corpus.ObjectIdentityObserved,
	})
	if err != nil {
		store.pool.Put(conn)
		t.Fatal(err)
	}
	setupErr := sqlitex.Execute(conn,
		"INSERT INTO provider_object_occurrences (occurrence_id,provider_id,native_object_id,identity_state) VALUES (?1,'provider','object-setup','OBSERVED')",
		&sqlitex.ExecOptions{Args: []any{string(occurrenceID)}})
	releaseOccurrence()
	if setupErr != nil {
		store.pool.Put(conn)
		t.Fatal(setupErr)
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO observations (observation_id,occurrence_id,artifact_id,revision_id,assignment_state,observed_at,kind,size,mode,modified_at,scan_id) VALUES ('obs_forged',?1,NULL,NULL,'UNRESOLVED',?2,'REGULAR_FILE',1,0,?2,?3)",
		&sqlitex.ExecOptions{Args: []any{string(occurrenceID), base.Format(time.RFC3339Nano), string(scan.ID)}}); err == nil {
		store.pool.Put(conn)
		t.Fatal("direct Observation insert unexpectedly succeeded")
	}
	store.pool.Put(conn)

	record, err := store.RecordObservationInScan(ctx, scan.ID, corpus.ObservationRecordInput{
		ProviderObject: corpus.ProviderObject{ProviderID: "provider", ID: "object-legit", IdentityState: corpus.ObjectIdentityObserved},
		Locators: []corpus.Locator{{ProviderID: "provider", Root: "root", Path: "path-a"}},
		AssignmentState: corpus.AssignmentUnresolved,
		ObservedAt: base,
		Kind: corpus.EntryRegularFile,
		Size: 1,
		ModifiedAt: base,
	})
	if err != nil {
		t.Fatal(err)
	}

	conn, err = store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO locators (locator_id,observation_id,provider_id,root,path) VALUES ('loc_forged',?1,'provider','root','path-b')",
		&sqlitex.ExecOptions{Args: []any{string(record.ID)}}); err == nil {
		store.pool.Put(conn)
		t.Fatal("direct Locator insert unexpectedly succeeded")
	}
	store.pool.Put(conn)

	if err := store.CompleteScan(ctx, scan.ID, base.Add(2*time.Second)); err != nil {
		t.Fatal(err)
	}
}

func TestGenericScanObservationApplicationAuthorityAllowsDirectObservationAPI(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "state.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	at := time.Date(2026, 9, 27, 17, 5, 0, 0, time.UTC)
	if _, err := store.RecordObservation(ctx, corpus.ObservationRecordInput{
		ProviderObject: corpus.ProviderObject{ProviderID: "provider", ID: "object", IdentityState: corpus.ObjectIdentityObserved},
		Locators: []corpus.Locator{{ProviderID: "provider", Root: "root", Path: "path"}},
		AssignmentState: corpus.AssignmentUnresolved,
		ObservedAt: at,
		Kind: corpus.EntryRegularFile,
		Size: 1,
		ModifiedAt: at,
	}); err != nil {
		t.Fatal(err)
	}
}
