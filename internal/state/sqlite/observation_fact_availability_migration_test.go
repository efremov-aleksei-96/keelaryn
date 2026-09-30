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

func TestQualifiedV45DatabaseMigratesObservationFactsToKnownV46(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "v45.db")
	store := &Store{path: path}
	v45 := sqlitemigration.Schema{
		AppID:      applicationID,
		Migrations: append([]string(nil), schema.Migrations[:45]...),
	}
	store.pool = sqlitemigration.NewPool(path, v45, sqlitemigration.Options{
		Flags:       sqlite.OpenReadWrite | sqlite.OpenCreate,
		PoolSize:    1,
		PrepareConn: store.prepareConn,
	})

	at := time.Date(2026, 9, 30, 9, 0, 0, 0, time.UTC)
	recorded, err := store.RecordObservation(ctx, corpus.ObservationRecordInput{
		ProviderObject: corpus.ProviderObject{
			ProviderID:    "provider",
			ID:            "known-object",
			IdentityState: corpus.ObjectIdentityObserved,
		},
		Locators: []corpus.Locator{{
			ProviderID: "provider",
			Root:       "root",
			Path:       "known",
		}},
		AssignmentState: corpus.AssignmentUnresolved,
		ObservedAt:      at,
		Kind:            corpus.EntryRegularFile,
		Size:            corpus.KnownSize(7),
		Mode:            corpus.KnownMode(0o600),
		ModifiedAt:      corpus.KnownModifiedAt(at.Add(-time.Minute)),
	})
	if err != nil {
		t.Fatal(err)
	}

	_, err = store.RecordObservation(ctx, corpus.ObservationRecordInput{
		ProviderObject: corpus.ProviderObject{
			ProviderID:    "provider",
			ID:            "unknown-object",
			IdentityState: corpus.ObjectIdentityObserved,
		},
		Locators: []corpus.Locator{{
			ProviderID: "provider",
			Root:       "root",
			Path:       "unknown",
		}},
		AssignmentState: corpus.AssignmentUnresolved,
		ObservedAt:      at.Add(time.Second),
		Kind:            corpus.EntryOther,
	})
	if !errors.Is(err, ErrInvalidObservation) {
		t.Fatalf("pre-v46 unavailable facts error=%v, want ErrInvalidObservation", err)
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

	var sizeKnown, modeKnown, modifiedKnown int64
	if err := sqlitex.Execute(conn,
		"SELECT size_known, mode_known, modified_at_known FROM observations WHERE observation_id=?1",
		&sqlitex.ExecOptions{
			Args: []any{string(recorded.ID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				sizeKnown = stmt.ColumnInt64(0)
				modeKnown = stmt.ColumnInt64(1)
				modifiedKnown = stmt.ColumnInt64(2)
				return nil
			},
		}); err != nil {
		t.Fatal(err)
	}
	if sizeKnown != 1 || modeKnown != 1 || modifiedKnown != 1 {
		t.Fatalf("migrated known flags=%d/%d/%d", sizeKnown, modeKnown, modifiedKnown)
	}

	migrated.pool.Put(conn)

	loaded, err := migrated.Observation(ctx, recorded.ID)
	if err != nil {
		t.Fatal(err)
	}
	if !equalInt64Fact(loaded.Size, recorded.Size) ||
		!equalUint32Fact(loaded.Mode, recorded.Mode) ||
		!equalTimeFact(loaded.ModifiedAt, recorded.ModifiedAt) {
		t.Fatalf("migrated observation changed: got=%#v want=%#v", loaded, recorded)
	}
}
