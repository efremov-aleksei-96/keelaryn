package sqlitestate_test

import (
	"context"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	sqlitestate "github.com/efremov-aleksei-96/keelaryn/internal/state/sqlite"
)

func TestObservationPersistsUnavailableFactsWithoutExposingSentinels(t *testing.T) {
	ctx := context.Background()
	store, err := sqlitestate.Open(ctx, filepath.Join(t.TempDir(), "state.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	at := time.Date(2026, 9, 30, 0, 0, 0, 0, time.UTC)
	record, err := store.RecordObservation(ctx, corpus.ObservationRecordInput{
		ProviderObject:  corpus.ProviderObject{ProviderID: "remote", ID: "object", IdentityState: corpus.ObjectIdentityObserved},
		Locators:        []corpus.Locator{{ProviderID: "remote", Root: "root", Path: "id:object"}},
		AssignmentState: corpus.AssignmentUnresolved, ObservedAt: at, Kind: corpus.EntryOther,
	})
	if err != nil {
		t.Fatal(err)
	}
	if record.Size != nil || record.Mode != nil || record.ModifiedAt != nil {
		t.Fatalf("record exposed sentinels %#v", record)
	}
	loaded, err := store.Observation(ctx, record.ID)
	if err != nil {
		t.Fatal(err)
	}
	if loaded.Size != nil || loaded.Mode != nil || loaded.ModifiedAt != nil {
		t.Fatalf("loaded exposed sentinels %#v", loaded)
	}
}
