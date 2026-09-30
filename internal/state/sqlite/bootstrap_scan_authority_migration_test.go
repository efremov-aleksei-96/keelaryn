package sqlitestate

import (
	"context"
	"errors"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestV39MigrationDoesNotInventBootstrapAuthorityForHistoricalScan(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "historical-v38.db")
	store := openV38BootstrapAuthorityStore(t, path)
	at := time.Date(2026, 9, 27, 16, 5, 0, 0, time.UTC)
	scan, err := store.StartScan(ctx, "localfs", "/corpus", at)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}

	migrated, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer migrated.Close()

	conn, err := migrated.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	var count int64
	if err := sqlitex.Execute(conn,
		"SELECT COUNT(*) FROM bootstrap_scan_authorities WHERE scan_id=?1",
		&sqlitex.ExecOptions{
			Args: []any{string(scan.ID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				count = stmt.ColumnInt64(0)
				return nil
			},
		}); err != nil {
		migrated.pool.Put(conn)
		t.Fatal(err)
	}
	migrated.pool.Put(conn)
	if count != 0 {
		t.Fatalf("historical scan received invented bootstrap authority count=%d", count)
	}

	input := corpus.ObservationRecordInput{
		ProviderObject: corpus.ProviderObject{
			ProviderID:    "localfs",
			ID:            "obj-historical-v38",
			IdentityState: corpus.ObjectIdentityObserved,
		},
		Locators: []corpus.Locator{{
			ProviderID: "localfs",
			Root:       "/corpus",
			Path:       "file.txt",
		}},
		AssignmentState: corpus.AssignmentUnresolved,
		ObservedAt:      at,
		Kind:            corpus.EntryOther,
		ModifiedAt:      corpus.KnownModifiedAt(at),
	}
	_, err = migrated.AdoptObservationInScan(ctx, scan.ID, input, nil)
	if !errors.Is(err, ErrBootstrapScanAuthorityRequired) {
		t.Fatalf("adoption error=%v, want ErrBootstrapScanAuthorityRequired", err)
	}
}

func TestQualifiedV38DatabaseMigratesToBootstrapAuthorityV39(t *testing.T) {
	path := filepath.Join(t.TempDir(), "qualified-v38.db")
	store := openV38BootstrapAuthorityStore(t, path)
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}
	migrated, err := Open(context.Background(), path)
	if err != nil {
		t.Fatal(err)
	}
	if err := migrated.Close(); err != nil {
		t.Fatal(err)
	}
}

func openV38BootstrapAuthorityStore(t *testing.T, path string) *Store {
	t.Helper()
	partial := sqlitemigration.Schema{
		AppID:      applicationID,
		Migrations: append([]string(nil), schema.Migrations[:38]...),
	}
	store := &Store{path: path}
	pool := sqlitemigration.NewPool(path, partial, sqlitemigration.Options{
		Flags:       sqlite.OpenReadWrite | sqlite.OpenCreate,
		PoolSize:    1,
		PrepareConn: store.prepareConn,
	})
	store.pool = pool
	conn, err := pool.Get(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	pool.Put(conn)
	return store
}
