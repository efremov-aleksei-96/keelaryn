package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestQualifiedV24DatabaseMigratesToCanonicalScanObservationTimeAuthorityV25(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v24.db")
	pool := openSchemaVersionPoolForCanonicalTimeTest(t, path, 24)
	if err := pool.Close(); err != nil {
		t.Fatal(err)
	}

	store, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer store.pool.Put(conn)

	for _, name := range []string{
		"scan_sessions_insert_canonical_time_guard",
		"scan_sessions_update_canonical_time_guard",
		"observations_insert_canonical_time_guard",
	} {
		var found bool
		if err := sqlitex.Execute(conn,
			"SELECT 1 FROM sqlite_master WHERE name=?1 AND type='trigger'",
			&sqlitex.ExecOptions{
				Args: []any{name},
				ResultFunc: func(*sqlite.Stmt) error {
					found = true
					return nil
				},
			}); err != nil {
			t.Fatal(err)
		}
		if !found {
			t.Fatalf("v24→v25 migration missing %s", name)
		}
	}
}

func TestV25MigrationRejectsExistingNoncanonicalScanOrObservationTime(t *testing.T) {
	for _, tc := range []struct {
		name string
		seed func(*testing.T, *sqlitemigration.Pool)
	}{
		{
			name: "scan start",
			seed: func(t *testing.T, pool *sqlitemigration.Pool) {
				conn, err := pool.Get(context.Background())
				if err != nil {
					t.Fatal(err)
				}
				defer pool.Put(conn)
				if err := sqlitex.Execute(conn,
					"INSERT INTO scan_sessions (scan_id,provider_id,root,status,started_at,finished_at) VALUES ('scan_bad_time','provider','root','OPEN','2026-09-27 15:00:00',NULL)",
					nil); err != nil {
					t.Fatal(err)
				}
			},
		},
		{
			name: "observation time",
			seed: func(t *testing.T, pool *sqlitemigration.Pool) {
				conn, err := pool.Get(context.Background())
				if err != nil {
					t.Fatal(err)
				}
				defer pool.Put(conn)
				if err := sqlitex.Execute(conn,
					"INSERT INTO provider_object_occurrences (occurrence_id,provider_id,native_object_id,identity_state) VALUES ('pobjocc_bad_time','provider','obj','OBSERVED')",
					nil); err != nil {
					t.Fatal(err)
				}
				if err := sqlitex.Execute(conn,
					"INSERT INTO observations (observation_id,occurrence_id,artifact_id,revision_id,assignment_state,observed_at,kind,size,mode,modified_at,scan_id) VALUES ('obs_bad_time','pobjocc_bad_time',NULL,NULL,'UNRESOLVED','2026-09-27','REGULAR_FILE',1,0,'2026-09-27T15:00:00Z',NULL)",
					nil); err != nil {
					t.Fatal(err)
				}
			},
		},
	} {
		t.Run(tc.name, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "v24.db")
			pool := openSchemaVersionPoolForCanonicalTimeTest(t, path, 24)
			tc.seed(t, pool)
			if err := pool.Close(); err != nil {
				t.Fatal(err)
			}
			store, err := Open(context.Background(), path)
			if err == nil {
				_ = store.Close()
				t.Fatal("v25 migration unexpectedly accepted noncanonical durable time")
			}
		})
	}
}

func TestCanonicalScanObservationTimeGuardsRejectSQLiteAcceptedNoncanonicalForms(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	base := time.Date(2026, 9, 27, 15, 0, 0, 123456789, time.UTC)

	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	err = sqlitex.Execute(conn,
		"INSERT INTO scan_sessions (scan_id,provider_id,root,status,started_at,finished_at) VALUES ('scan_noncanonical','provider','root','OPEN','2026-09-27 15:00:00',NULL)",
		nil)
	store.pool.Put(conn)
	if err == nil {
		t.Fatal("noncanonical scan timestamp unexpectedly accepted")
	}

	scan, err := store.StartScan(ctx, corpus.ProviderID("provider"), "root", base)
	if err != nil {
		t.Fatal(err)
	}
	conn, err = store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO provider_object_occurrences (occurrence_id,provider_id,native_object_id,identity_state) VALUES ('pobjocc_noncanonical','provider','obj','OBSERVED')",
		nil); err != nil {
		store.pool.Put(conn)
		t.Fatal(err)
	}
	err = sqlitex.Execute(conn,
		"INSERT INTO observations (observation_id,occurrence_id,artifact_id,revision_id,assignment_state,observed_at,kind,size,mode,modified_at,scan_id) VALUES ('obs_noncanonical','pobjocc_noncanonical',NULL,NULL,'UNRESOLVED','2026-09-27T24:00:00Z','REGULAR_FILE',1,0,?1,?2)",
		&sqlitex.ExecOptions{Args: []any{
			base.UTC().Format(time.RFC3339Nano),
			string(scan.ID),
		}})
	store.pool.Put(conn)
	if err == nil {
		t.Fatal("noncanonical observation timestamp unexpectedly accepted")
	}

	if err := store.AbortScan(ctx, scan.ID, base.Add(time.Second)); err != nil {
		t.Fatal(err)
	}
}

func openSchemaVersionPoolForCanonicalTimeTest(t *testing.T, path string, version int) *sqlitemigration.Pool {
	t.Helper()
	partial := sqlitemigration.Schema{
		AppID:      applicationID,
		Migrations: append([]string(nil), schema.Migrations[:version]...),
	}
	pool := sqlitemigration.NewPool(path, partial, sqlitemigration.Options{
		Flags:    sqlite.OpenReadWrite | sqlite.OpenCreate,
		PoolSize: 1,
		PrepareConn: func(conn *sqlite.Conn) error {
			return sqlitex.ExecuteTransient(conn, "PRAGMA foreign_keys = ON", nil)
		},
	})
	conn, err := pool.Get(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	pool.Put(conn)
	return pool
}
