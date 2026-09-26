package sqlitestate

import (
	"context"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestObservationEvidenceSQLiteImmutable(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "state.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	at := time.Date(2026, 9, 27, 11, 0, 0, 0, time.UTC)
	recorded, err := store.RecordObservation(ctx, corpus.ObservationRecordInput{
		ProviderObject: corpus.ProviderObject{
			ProviderID:    "provider",
			ID:            "object-1",
			IdentityState: corpus.ObjectIdentityObserved,
		},
		Locators: []corpus.Locator{{
			ProviderID: "provider",
			Root:       "root",
			Path:       "path",
		}},
		AssignmentState: corpus.AssignmentUnresolved,
		ObservedAt:      at,
		Kind:            corpus.EntryRegularFile,
		Size:            7,
		Mode:            0o600,
		ModifiedAt:      at.Add(-time.Minute),
	})
	if err != nil {
		t.Fatal(err)
	}

	conn, err := store.pool.Get(ctx)
	if err != nil {
		t.Fatal(err)
	}
	attempts := []struct {
		name  string
		query string
		args  []any
	}{
		{"occurrence update", "UPDATE provider_object_occurrences SET provider_id='tampered' WHERE occurrence_id=?1", []any{string(recorded.ProviderObjectOccurrenceID)}},
		{"occurrence delete", "DELETE FROM provider_object_occurrences WHERE occurrence_id=?1", []any{string(recorded.ProviderObjectOccurrenceID)}},
		{"observation update", "UPDATE observations SET size=size+1 WHERE observation_id=?1", []any{string(recorded.ID)}},
		{"observation delete", "DELETE FROM observations WHERE observation_id=?1", []any{string(recorded.ID)}},
		{"locator update", "UPDATE locators SET path='tampered' WHERE locator_id=?1", []any{string(recorded.Locators[0].ID)}},
		{"locator delete", "DELETE FROM locators WHERE locator_id=?1", []any{string(recorded.Locators[0].ID)}},
	}
	for _, attempt := range attempts {
		if err := sqlitex.Execute(conn, attempt.query, &sqlitex.ExecOptions{Args: attempt.args}); err == nil {
			store.pool.Put(conn)
			t.Fatalf("%s unexpectedly succeeded", attempt.name)
		}
	}
	store.pool.Put(conn)

	got, err := store.Observation(ctx, recorded.ID)
	if err != nil {
		t.Fatal(err)
	}
	if got.ProviderObject != recorded.ProviderObject ||
		got.Size != recorded.Size ||
		len(got.Locators) != 1 ||
		got.Locators[0].Locator != recorded.Locators[0].Locator {
		t.Fatalf("immutable observation evidence changed: got=%#v want=%#v", got, recorded)
	}
}
