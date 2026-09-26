package sqlitestate

import (
	"context"
	"encoding/json"
	"fmt"
	"math"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"github.com/google/uuid"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

type remoteHistoryBootstrapSidecar func(
	conn *sqlite.Conn,
	generation remotehistory.HistoryGeneration,
	objects []remotehistory.RemoteObjectState,
) error

type remoteHistoryCycleSidecar func(
	conn *sqlite.Conn,
	generation remotehistory.HistoryGeneration,
	sequence remotehistory.HistoryPublicationSequence,
	changes []remotehistory.RemoteChange,
) error

func (s *Store) startRemoteHistoryGenerationWithSidecar(
	ctx context.Context,
	scope remotehistory.Scope,
	scopePolicyFingerprint remotehistory.ScopePolicyFingerprint,
	bootstrap remotehistory.BootstrapResult,
	committedAt time.Time,
	sidecar remoteHistoryBootstrapSidecar,
) (out remotehistory.HistoryGeneration, err error) {
	if err := remotehistory.ValidateScope(scope); err != nil {
		return remotehistory.HistoryGeneration{}, err
	}
	if err := remotehistory.ValidateScopePolicyFingerprint(scopePolicyFingerprint); err != nil {
		return remotehistory.HistoryGeneration{}, err
	}
	if committedAt.IsZero() {
		return remotehistory.HistoryGeneration{}, remotehistory.ErrInvalidHistoryGeneration
	}
	if err := remotehistory.ValidateBootstrap(scope, bootstrap); err != nil {
		return remotehistory.HistoryGeneration{}, err
	}
	if bootstrap.Status != remotehistory.BootstrapComplete {
		return remotehistory.HistoryGeneration{}, remotehistory.ErrInvalidHistoryGeneration
	}
	objects, err := canonicalBootstrapObjects(bootstrap.Objects)
	if err != nil {
		return remotehistory.HistoryGeneration{}, err
	}

	conn, err := s.pool.Get(ctx)
	if err != nil {
		return remotehistory.HistoryGeneration{}, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)

	end, err := sqlitex.ImmediateTransaction(conn)
	if err != nil {
		return remotehistory.HistoryGeneration{}, fmt.Errorf("begin remote history bootstrap transaction: %w", err)
	}
	defer end(&err)

	if _, found, err := activeRemoteHistoryGenerationConn(conn, scope); err != nil {
		return remotehistory.HistoryGeneration{}, err
	} else if found {
		return remotehistory.HistoryGeneration{}, ErrActiveHistoryGenerationExists
	}

	generation := remotehistory.HistoryGeneration{
		ID:                     remotehistory.HistoryGenerationID("hgen_" + uuid.NewString()),
		Scope:                  scope,
		ScopePolicyFingerprint: scopePolicyFingerprint,
		Status:                 remotehistory.HistoryGenerationActive,
		CreatedAt:              committedAt.UTC(),
		CurrentSequence:        1,
		CommittedCursor:        bootstrap.Cursor,
	}
	publication := remotehistory.HistoryPublication{
		GenerationID:       generation.ID,
		Sequence:           1,
		Kind:               remotehistory.HistoryPublicationBootstrap,
		CommittedCursor:    bootstrap.Cursor,
		CommittedAt:        committedAt.UTC(),
		FingerprintVersion: remoteHistoryPublicationFingerprintVersion,
	}
	publication.FingerprintSHA256, err = bootstrapPublicationFingerprint(publication, objects)
	if err != nil {
		return remotehistory.HistoryGeneration{}, err
	}

	if err := insertRemoteHistoryGeneration(conn, generation); err != nil {
		return remotehistory.HistoryGeneration{}, err
	}
	if err := insertRemoteHistoryPublication(conn, publication); err != nil {
		return remotehistory.HistoryGeneration{}, err
	}
	for _, object := range objects {
		locatorsJSON, err := marshalCanonicalLocators(object.Locators)
		if err != nil {
			return remotehistory.HistoryGeneration{}, err
		}
		if err := sqlitex.Execute(conn,
			"INSERT INTO remote_history_bootstrap_membership (generation_id, object_id, locators_json) VALUES (?1, ?2, ?3)",
			&sqlitex.ExecOptions{Args: []any{string(generation.ID), string(object.ObjectID), locatorsJSON}}); err != nil {
			return remotehistory.HistoryGeneration{}, fmt.Errorf("insert remote history bootstrap membership: %w", err)
		}
		if err := insertBootstrapLifetimeSegmentConn(conn, generation.ID, object.ObjectID); err != nil {
			return remotehistory.HistoryGeneration{}, err
		}
		if err := sqlitex.Execute(conn,
			"INSERT INTO remote_history_membership (generation_id, object_id, locators_json, last_sequence) VALUES (?1, ?2, ?3, 1)",
			&sqlitex.ExecOptions{Args: []any{string(generation.ID), string(object.ObjectID), locatorsJSON}}); err != nil {
			return remotehistory.HistoryGeneration{}, fmt.Errorf("insert remote history membership: %w", err)
		}
	}
	if sidecar != nil {
		if err := sidecar(conn, generation, objects); err != nil {
			return remotehistory.HistoryGeneration{}, err
		}
	}
	return generation, nil
}

func (s *Store) publishRemoteHistoryCycleWithSidecar(
	ctx context.Context,
	generationID remotehistory.HistoryGenerationID,
	scope remotehistory.Scope,
	scopePolicyFingerprint remotehistory.ScopePolicyFingerprint,
	expectedSequence remotehistory.HistoryPublicationSequence,
	expectedCursor remotehistory.HistoryCursor,
	cycle remotehistory.ChangeCycle,
	committedAt time.Time,
	sidecar remoteHistoryCycleSidecar,
) (out remotehistory.HistoryGeneration, err error) {
	if generationID == "" ||
		expectedSequence == 0 ||
		expectedSequence >= remotehistory.HistoryPublicationSequence(math.MaxInt64) ||
		committedAt.IsZero() {
		return remotehistory.HistoryGeneration{}, remotehistory.ErrInvalidHistoryPublication
	}
	if err := remotehistory.ValidateScope(scope); err != nil {
		return remotehistory.HistoryGeneration{}, err
	}
	if err := remotehistory.ValidateScopePolicyFingerprint(scopePolicyFingerprint); err != nil {
		return remotehistory.HistoryGeneration{}, err
	}
	if err := remotehistory.ValidateCompleteCycle(scope, expectedCursor, cycle); err != nil {
		return remotehistory.HistoryGeneration{}, err
	}

	conn, err := s.pool.Get(ctx)
	if err != nil {
		return remotehistory.HistoryGeneration{}, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)

	end, err := sqlitex.ImmediateTransaction(conn)
	if err != nil {
		return remotehistory.HistoryGeneration{}, fmt.Errorf("begin remote history publication transaction: %w", err)
	}
	defer end(&err)

	generation, err := remoteHistoryGenerationConn(conn, generationID)
	if err != nil {
		return remotehistory.HistoryGeneration{}, err
	}
	if err := requireHistoryScope(generation, scope, scopePolicyFingerprint); err != nil {
		return remotehistory.HistoryGeneration{}, err
	}
	if generation.Status != remotehistory.HistoryGenerationActive {
		return remotehistory.HistoryGeneration{}, ErrHistoryGenerationClosed
	}
	if generation.CurrentSequence != expectedSequence || generation.CommittedCursor != expectedCursor {
		return remotehistory.HistoryGeneration{}, ErrHistoryPublicationConflict
	}

	nextSequence := expectedSequence + 1
	publication := remotehistory.HistoryPublication{
		GenerationID:       generationID,
		Sequence:           nextSequence,
		Kind:               remotehistory.HistoryPublicationIncremental,
		PreviousCursor:     expectedCursor,
		CommittedCursor:    cycle.NextCursor,
		CommittedAt:        committedAt.UTC(),
		FingerprintVersion: remoteHistoryPublicationFingerprintVersion,
	}
	canonicalChanges, err := canonicalChanges(cycle.Changes)
	if err != nil {
		return remotehistory.HistoryGeneration{}, err
	}
	publication.FingerprintSHA256, err = incrementalPublicationFingerprint(publication, canonicalChanges)
	if err != nil {
		return remotehistory.HistoryGeneration{}, err
	}
	if err := insertRemoteHistoryPublication(conn, publication); err != nil {
		return remotehistory.HistoryGeneration{}, err
	}

	for i, change := range canonicalChanges {
		var stateJSON any
		if change.State != nil {
			encoded, err := json.Marshal(change.State)
			if err != nil {
				return remotehistory.HistoryGeneration{}, fmt.Errorf("encode remote history change state: %w", err)
			}
			stateJSON = string(encoded)
		}
		if err := sqlitex.Execute(conn,
			"INSERT INTO remote_history_publication_changes (generation_id, sequence, ordinal, kind, object_id, state_json) VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
			&sqlitex.ExecOptions{Args: []any{
				string(generationID), int64(nextSequence), int64(i), string(change.Kind), string(change.ObjectID), stateJSON,
			}}); err != nil {
			return remotehistory.HistoryGeneration{}, fmt.Errorf("insert remote history publication change: %w", err)
		}
		if err := applyLifetimeChangeConn(conn, generationID, nextSequence, int64(i), change); err != nil {
			return remotehistory.HistoryGeneration{}, err
		}

		switch change.Kind {
		case remotehistory.ChangeUpsert:
			locatorsJSON, err := marshalCanonicalLocators(change.State.Locators)
			if err != nil {
				return remotehistory.HistoryGeneration{}, err
			}
			if err := sqlitex.Execute(conn,
				"INSERT INTO remote_history_membership (generation_id, object_id, locators_json, last_sequence) VALUES (?1, ?2, ?3, ?4) ON CONFLICT (generation_id, object_id) DO UPDATE SET locators_json=excluded.locators_json, last_sequence=excluded.last_sequence",
				&sqlitex.ExecOptions{Args: []any{
					string(generationID), string(change.ObjectID), locatorsJSON, int64(nextSequence),
				}}); err != nil {
				return remotehistory.HistoryGeneration{}, fmt.Errorf("upsert remote history membership: %w", err)
			}
		case remotehistory.ChangeRemoved:
			if err := sqlitex.Execute(conn,
				"DELETE FROM remote_history_membership WHERE generation_id = ?1 AND object_id = ?2",
				&sqlitex.ExecOptions{Args: []any{string(generationID), string(change.ObjectID)}}); err != nil {
				return remotehistory.HistoryGeneration{}, fmt.Errorf("remove remote history membership: %w", err)
			}
		default:
			return remotehistory.HistoryGeneration{}, remotehistory.ErrInvalidHistoryPublication
		}
	}

	if err := sqlitex.Execute(conn,
		"UPDATE remote_history_generations SET current_sequence = ?1, committed_cursor = ?2 WHERE generation_id = ?3 AND status = 'ACTIVE' AND current_sequence = ?4 AND committed_cursor = ?5",
		&sqlitex.ExecOptions{Args: []any{
			int64(nextSequence),
			string(cycle.NextCursor),
			string(generationID),
			int64(expectedSequence),
			string(expectedCursor),
		}}); err != nil {
		return remotehistory.HistoryGeneration{}, fmt.Errorf("advance remote history generation: %w", err)
	}
	if conn.Changes() != 1 {
		return remotehistory.HistoryGeneration{}, ErrHistoryPublicationConflict
	}
	generation.CurrentSequence = nextSequence
	generation.CommittedCursor = cycle.NextCursor

	if sidecar != nil {
		if err := sidecar(conn, generation, nextSequence, canonicalChanges); err != nil {
			return remotehistory.HistoryGeneration{}, err
		}
	}
	return generation, nil
}
