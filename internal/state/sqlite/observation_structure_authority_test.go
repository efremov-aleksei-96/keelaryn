package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestObservationSQLiteStructuralAuthority(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "state.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	base := time.Date(2026, 9, 27, 16, 0, 0, 0, time.UTC)
	scan, err := store.StartScan(ctx, "provider", "root", base)
	if err != nil {
		t.Fatal(err)
	}

	first, err := store.RecordObservationInScan(ctx, scan.ID, corpus.ObservationRecordInput{
		ProviderObject: corpus.ProviderObject{
			ProviderID:    "provider",
			ID:            "object-1",
			IdentityState: corpus.ObjectIdentityObserved,
		},
		Locators: []corpus.Locator{{
			ProviderID: "provider",
			Root:       "root",
			Path:       "path-1",
		}},
		AssignmentState: corpus.AssignmentUnresolved,
		ObservedAt:      base,
		Kind:            corpus.EntryRegularFile,
		Size:            1,
		Mode:            0o600,
		ModifiedAt:      base,
	})
	if err != nil {
		t.Fatal(err)
	}

	if _, err := store.RecordObservationInScan(ctx, scan.ID, corpus.ObservationRecordInput{
		ProviderObject: corpus.ProviderObject{
			ProviderID:    "provider",
			ID:            "object-1",
			IdentityState: corpus.ObjectIdentityObserved,
		},
		Locators: []corpus.Locator{{
			ProviderID: "provider",
			Root:       "root",
			Path:       "path-2",
		}},
		AssignmentState: corpus.AssignmentUnresolved,
		ObservedAt:      base,
		Kind:            corpus.EntryRegularFile,
		Size:            1,
		Mode:            0o600,
		ModifiedAt:      base,
	}); err == nil {
		t.Fatal("duplicate observed provider object in one scan unexpectedly succeeded")
	}

	if _, err := store.RecordObservationInScan(ctx, scan.ID, corpus.ObservationRecordInput{
		ProviderObject: corpus.ProviderObject{
			ProviderID:    "provider",
			ID:            "object-2",
			IdentityState: corpus.ObjectIdentityObserved,
		},
		Locators: []corpus.Locator{{
			ProviderID: "provider",
			Root:       "root",
			Path:       "path-1",
		}},
		AssignmentState: corpus.AssignmentUnresolved,
		ObservedAt:      base,
		Kind:            corpus.EntryRegularFile,
		Size:            1,
		Mode:            0o600,
		ModifiedAt:      base,
	}); err == nil {
		t.Fatal("cross-object locator collision in one scan unexpectedly succeeded")
	}

	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}

	for _, tc := range []struct {
		name  string
		query string
		args  []any
	}{
		{
			name:  "empty occurrence provider",
			query: "INSERT INTO provider_object_occurrences (occurrence_id,provider_id,native_object_id,identity_state) VALUES ('pobjocc_bad_provider','',NULL,'UNRESOLVED')",
		},
		{
			name:  "empty observed native object",
			query: "INSERT INTO provider_object_occurrences (occurrence_id,provider_id,native_object_id,identity_state) VALUES ('pobjocc_bad_native','provider','','OBSERVED')",
		},
		{
			name:  "reuse occurrence for second observation",
			query: "INSERT INTO observations (observation_id,occurrence_id,artifact_id,revision_id,assignment_state,observed_at,kind,size,mode,modified_at,scan_id) VALUES ('obs_reuse',?1,NULL,NULL,'UNRESOLVED',?2,'REGULAR_FILE',1,384,?2,NULL)",
			args:  []any{string(first.ProviderObjectOccurrenceID), base.Format(time.RFC3339Nano)},
		},
	} {
		err := sqlitex.Execute(conn, tc.query, &sqlitex.ExecOptions{Args: tc.args})
		if err == nil {
			store.pool.Put(conn)
			t.Fatalf("%s unexpectedly succeeded", tc.name)
		}
	}

	releaseOccurrence, err := store.authorizeOccurrenceInsertConn(conn, occurrenceInsertAuthorization{
		occurrenceID:  "pobjocc_mode",
		providerID:    "provider",
		identityState: corpus.ObjectIdentityUnresolved,
	})
	if err != nil {
		store.pool.Put(conn)
		t.Fatal(err)
	}
	writeErr := sqlitex.Execute(conn,
		"INSERT INTO provider_object_occurrences (occurrence_id,provider_id,native_object_id,identity_state) VALUES ('pobjocc_mode','provider',NULL,'UNRESOLVED')",
		nil)
	releaseOccurrence()
	if writeErr != nil {
		store.pool.Put(conn)
		t.Fatal(writeErr)
	}
	releaseObservation, err := store.authorizeObservationInsertConn(conn, observationInsertAuthorization{
		observationID:   "obs_mode",
		occurrenceID:    "pobjocc_mode",
		assignmentState: corpus.AssignmentUnresolved,
		observedAt:      base.Format(time.RFC3339Nano),
		kind:            corpus.EntryRegularFile,
		size:            1,
		mode:            4294967296,
		modifiedAt:      base.Format(time.RFC3339Nano),
	})
	if err != nil {
		store.pool.Put(conn)
		t.Fatal(err)
	}
	writeErr = sqlitex.Execute(conn,
		"INSERT INTO observations (observation_id,occurrence_id,artifact_id,revision_id,assignment_state,observed_at,kind,size,mode,modified_at,scan_id) VALUES ('obs_mode','pobjocc_mode',NULL,NULL,'UNRESOLVED',?1,'REGULAR_FILE',1,4294967296,?1,NULL)",
		&sqlitex.ExecOptions{Args: []any{base.Format(time.RFC3339Nano)}})
	releaseObservation()
	if writeErr == nil {
		store.pool.Put(conn)
		t.Fatal("mode outside uint32 unexpectedly succeeded")
	}

	releaseOccurrence, err = store.authorizeOccurrenceInsertConn(conn, occurrenceInsertAuthorization{
		occurrenceID:   "pobjocc_other",
		providerID:     "other",
		nativeObjectID: "object-x",
		identityState:  corpus.ObjectIdentityObserved,
	})
	if err != nil {
		store.pool.Put(conn)
		t.Fatal(err)
	}
	writeErr = sqlitex.Execute(conn,
		"INSERT INTO provider_object_occurrences (occurrence_id,provider_id,native_object_id,identity_state) VALUES ('pobjocc_other','other','object-x','OBSERVED')",
		nil)
	releaseOccurrence()
	if writeErr != nil {
		store.pool.Put(conn)
		t.Fatal(writeErr)
	}
	releaseObservation, err = store.authorizeObservationInsertConn(conn, observationInsertAuthorization{
		observationID:   "obs_scope",
		occurrenceID:    "pobjocc_other",
		assignmentState: corpus.AssignmentUnresolved,
		observedAt:      base.Format(time.RFC3339Nano),
		kind:            corpus.EntryRegularFile,
		size:            1,
		mode:            0,
		modifiedAt:      base.Format(time.RFC3339Nano),
		scanID:          scan.ID,
	})
	if err != nil {
		store.pool.Put(conn)
		t.Fatal(err)
	}
	writeErr = sqlitex.Execute(conn,
		"INSERT INTO observations (observation_id,occurrence_id,artifact_id,revision_id,assignment_state,observed_at,kind,size,mode,modified_at,scan_id) VALUES ('obs_scope','pobjocc_other',NULL,NULL,'UNRESOLVED',?1,'REGULAR_FILE',1,0,?1,?2)",
		&sqlitex.ExecOptions{Args: []any{base.Format(time.RFC3339Nano), string(scan.ID)}})
	releaseObservation()
	if writeErr == nil {
		store.pool.Put(conn)
		t.Fatal("observation provider/scan mismatch unexpectedly succeeded")
	}

	releaseOccurrence, err = store.authorizeOccurrenceInsertConn(conn, occurrenceInsertAuthorization{
		occurrenceID:   "pobjocc_no_locator",
		providerID:     "provider",
		nativeObjectID: "object-no-locator",
		identityState:  corpus.ObjectIdentityObserved,
	})
	if err != nil {
		store.pool.Put(conn)
		t.Fatal(err)
	}
	writeErr = sqlitex.Execute(conn,
		"INSERT INTO provider_object_occurrences (occurrence_id,provider_id,native_object_id,identity_state) VALUES ('pobjocc_no_locator','provider','object-no-locator','OBSERVED')",
		nil)
	releaseOccurrence()
	if writeErr != nil {
		store.pool.Put(conn)
		t.Fatal(writeErr)
	}
	releaseObservation, err = store.authorizeObservationInsertConn(conn, observationInsertAuthorization{
		observationID:   "obs_no_locator",
		occurrenceID:    "pobjocc_no_locator",
		assignmentState: corpus.AssignmentUnresolved,
		observedAt:      base.Format(time.RFC3339Nano),
		kind:            corpus.EntryRegularFile,
		size:            1,
		mode:            0,
		modifiedAt:      base.Format(time.RFC3339Nano),
		scanID:          scan.ID,
	})
	if err != nil {
		store.pool.Put(conn)
		t.Fatal(err)
	}
	writeErr = sqlitex.Execute(conn,
		"INSERT INTO observations (observation_id,occurrence_id,artifact_id,revision_id,assignment_state,observed_at,kind,size,mode,modified_at,scan_id) VALUES ('obs_no_locator','pobjocc_no_locator',NULL,NULL,'UNRESOLVED',?1,'REGULAR_FILE',1,0,?1,?2)",
		&sqlitex.ExecOptions{Args: []any{base.Format(time.RFC3339Nano), string(scan.ID)}})
	releaseObservation()
	if writeErr != nil {
		store.pool.Put(conn)
		t.Fatal(writeErr)
	}
	releaseLocator, err := store.authorizeLocatorInsertConn(conn, locatorInsertAuthorization{
		locatorID:     "loc_bad_scope",
		observationID: "obs_no_locator",
		providerID:    "provider",
		root:          "wrong-root",
		path:          "path-x",
	})
	if err != nil {
		store.pool.Put(conn)
		t.Fatal(err)
	}
	writeErr = sqlitex.Execute(conn,
		"INSERT INTO locators (locator_id,observation_id,provider_id,root,path) VALUES ('loc_bad_scope','obs_no_locator','provider','wrong-root','path-x')",
		nil)
	releaseLocator()
	if writeErr == nil {
		store.pool.Put(conn)
		t.Fatal("locator root/scan mismatch unexpectedly succeeded")
	}
	store.pool.Put(conn)

	if err := store.CompleteScan(ctx, scan.ID, base.Add(time.Second)); err == nil {
		t.Fatal("scan with observation lacking locator unexpectedly completed")
	}
	if err := store.AbortScan(ctx, scan.ID, base.Add(2*time.Second)); err != nil {
		t.Fatal(err)
	}
}

func TestObservationSQLiteAcceptsMultipleLocatorsForOneObservation(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "state.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	base := time.Date(2026, 9, 27, 17, 0, 0, 0, time.UTC)
	scan, err := store.StartScan(ctx, "provider", "root", base)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.RecordObservationInScan(ctx, scan.ID, corpus.ObservationRecordInput{
		ProviderObject: corpus.ProviderObject{
			ProviderID:    "provider",
			ID:            "object-1",
			IdentityState: corpus.ObjectIdentityObserved,
		},
		Locators: []corpus.Locator{
			{ProviderID: "provider", Root: "root", Path: "path-a"},
			{ProviderID: "provider", Root: "root", Path: "path-b"},
		},
		AssignmentState: corpus.AssignmentUnresolved,
		ObservedAt:      base,
		Kind:            corpus.EntryRegularFile,
		Size:            1,
		Mode:            0o600,
		ModifiedAt:      base,
	}); err != nil {
		t.Fatal(err)
	}
	if err := store.CompleteScan(ctx, scan.ID, base.Add(time.Second)); err != nil {
		t.Fatal(err)
	}
}
