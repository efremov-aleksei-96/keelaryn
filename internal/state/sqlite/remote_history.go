package sqlitestate

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"sort"
	"strings"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"github.com/google/uuid"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

const remoteHistoryPublicationFingerprintVersion = "remote-history-publication:v1"

var (
	ErrActiveHistoryGenerationExists = errors.New("active remote history generation already exists")
	ErrHistoryGenerationNotFound      = errors.New("remote history generation not found")
	ErrHistoryGenerationClosed        = errors.New("remote history generation is closed")
	ErrHistoryPublicationConflict     = errors.New("remote history publication prestate conflict")
	ErrHistoryScopeMismatch           = errors.New("remote history scope/policy mismatch")
)

func (s *Store) StartRemoteHistoryGeneration(
	ctx context.Context,
	scope remotehistory.Scope,
	scopePolicyFingerprint remotehistory.ScopePolicyFingerprint,
	bootstrap remotehistory.BootstrapResult,
	committedAt time.Time,
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
		if err := sqlitex.Execute(conn,
			"INSERT INTO remote_history_membership (generation_id, object_id, locators_json, last_sequence) VALUES (?1, ?2, ?3, 1)",
			&sqlitex.ExecOptions{Args: []any{string(generation.ID), string(object.ObjectID), locatorsJSON}}); err != nil {
			return remotehistory.HistoryGeneration{}, fmt.Errorf("insert remote history membership: %w", err)
		}
	}
	return generation, nil
}

func (s *Store) PublishRemoteHistoryCycle(
	ctx context.Context,
	generationID remotehistory.HistoryGenerationID,
	scope remotehistory.Scope,
	scopePolicyFingerprint remotehistory.ScopePolicyFingerprint,
	expectedSequence remotehistory.HistoryPublicationSequence,
	expectedCursor remotehistory.HistoryCursor,
	cycle remotehistory.ChangeCycle,
	committedAt time.Time,
) (out remotehistory.HistoryGeneration, err error) {
	if generationID == "" || expectedSequence == 0 || expectedSequence >= remotehistory.HistoryPublicationSequence(math.MaxInt64) || committedAt.IsZero() {
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

		switch change.Kind {
		case remotehistory.ChangeUpsert:
			locatorsJSON, err := marshalCanonicalLocators(change.State.Locators)
			if err != nil {
				return remotehistory.HistoryGeneration{}, err
			}
			if err := sqlitex.Execute(conn,
				"INSERT INTO remote_history_membership (generation_id, object_id, locators_json, last_sequence) VALUES (?1, ?2, ?3, ?4) ON CONFLICT (generation_id, object_id) DO UPDATE SET locators_json=excluded.locators_json, last_sequence=excluded.last_sequence",
				&sqlitex.ExecOptions{Args: []any{string(generationID), string(change.ObjectID), locatorsJSON, int64(nextSequence)}}); err != nil {
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
			int64(nextSequence), string(cycle.NextCursor), string(generationID), int64(expectedSequence), string(expectedCursor),
		}}); err != nil {
		return remotehistory.HistoryGeneration{}, fmt.Errorf("advance remote history generation: %w", err)
	}
	if conn.Changes() != 1 {
		return remotehistory.HistoryGeneration{}, ErrHistoryPublicationConflict
	}
	generation.CurrentSequence = nextSequence
	generation.CommittedCursor = cycle.NextCursor
	return generation, nil
}

func (s *Store) CloseRemoteHistoryGeneration(
	ctx context.Context,
	generationID remotehistory.HistoryGenerationID,
	scope remotehistory.Scope,
	scopePolicyFingerprint remotehistory.ScopePolicyFingerprint,
	expectedSequence remotehistory.HistoryPublicationSequence,
	expectedCursor remotehistory.HistoryCursor,
	failure remotehistory.ChangeCycle,
	closedAt time.Time,
) (out remotehistory.HistoryGeneration, err error) {
	if generationID == "" || expectedSequence == 0 || closedAt.IsZero() {
		return remotehistory.HistoryGeneration{}, remotehistory.ErrInvalidHistoryFailure
	}
	if err := remotehistory.ValidateScopePolicyFingerprint(scopePolicyFingerprint); err != nil {
		return remotehistory.HistoryGeneration{}, err
	}
	reason, err := remotehistory.TrustBreakReason(scope, expectedCursor, failure)
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
		return remotehistory.HistoryGeneration{}, fmt.Errorf("begin remote history close transaction: %w", err)
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

	if err := sqlitex.Execute(conn,
		"UPDATE remote_history_generations SET status='CLOSED', closed_at=?1, closure_reason=?2 WHERE generation_id=?3 AND status='ACTIVE' AND current_sequence=?4 AND committed_cursor=?5",
		&sqlitex.ExecOptions{Args: []any{
			closedAt.UTC().Format(time.RFC3339Nano), string(reason), string(generationID), int64(expectedSequence), string(expectedCursor),
		}}); err != nil {
		return remotehistory.HistoryGeneration{}, fmt.Errorf("close remote history generation: %w", err)
	}
	if conn.Changes() != 1 {
		return remotehistory.HistoryGeneration{}, ErrHistoryPublicationConflict
	}
	generation.Status = remotehistory.HistoryGenerationClosed
	generation.ClosedAt = closedAt.UTC()
	generation.ClosureReason = reason
	return generation, nil
}

func (s *Store) RemoteHistoryGeneration(ctx context.Context, generationID remotehistory.HistoryGenerationID) (remotehistory.HistoryGeneration, error) {
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return remotehistory.HistoryGeneration{}, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)
	return remoteHistoryGenerationConn(conn, generationID)
}

func (s *Store) ActiveRemoteHistoryGeneration(ctx context.Context, scope remotehistory.Scope) (remotehistory.HistoryGeneration, bool, error) {
	if err := remotehistory.ValidateScope(scope); err != nil {
		return remotehistory.HistoryGeneration{}, false, err
	}
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return remotehistory.HistoryGeneration{}, false, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)
	return activeRemoteHistoryGenerationConn(conn, scope)
}

func (s *Store) RemoteHistoryMembership(ctx context.Context, generationID remotehistory.HistoryGenerationID) ([]remotehistory.HistoryMembership, error) {
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return nil, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)
	if _, err := remoteHistoryGenerationConn(conn, generationID); err != nil {
		return nil, err
	}

	var out []remotehistory.HistoryMembership
	err = sqlitex.Execute(conn,
		"SELECT object_id, locators_json, last_sequence FROM remote_history_membership WHERE generation_id=?1 ORDER BY object_id",
		&sqlitex.ExecOptions{
			Args: []any{string(generationID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				var locators []corpus.Locator
				if err := json.Unmarshal([]byte(stmt.ColumnText(1)), &locators); err != nil {
					return err
				}
				out = append(out, remotehistory.HistoryMembership{
					GenerationID: generationID,
					Object: remotehistory.RemoteObjectState{
						ObjectID: corpus.ProviderObjectID(stmt.ColumnText(0)),
						Locators: locators,
					},
					LastPublicationSequence: remotehistory.HistoryPublicationSequence(stmt.ColumnInt64(2)),
				})
				return nil
			},
		})
	if err != nil {
		return nil, fmt.Errorf("query remote history membership: %w", err)
	}
	return out, nil
}

func (s *Store) RemoteHistoryPublications(ctx context.Context, generationID remotehistory.HistoryGenerationID) ([]remotehistory.HistoryPublication, error) {
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return nil, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)
	if _, err := remoteHistoryGenerationConn(conn, generationID); err != nil {
		return nil, err
	}

	var out []remotehistory.HistoryPublication
	err = sqlitex.Execute(conn,
		"SELECT sequence, kind, previous_cursor, committed_cursor, committed_at, fingerprint_version, fingerprint_sha256 FROM remote_history_publications WHERE generation_id=?1 ORDER BY sequence",
		&sqlitex.ExecOptions{
			Args: []any{string(generationID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				at, err := time.Parse(time.RFC3339Nano, stmt.ColumnText(4))
				if err != nil {
					return err
				}
				out = append(out, remotehistory.HistoryPublication{
					GenerationID:       generationID,
					Sequence:           remotehistory.HistoryPublicationSequence(stmt.ColumnInt64(0)),
					Kind:               remotehistory.HistoryPublicationKind(stmt.ColumnText(1)),
					PreviousCursor:     remotehistory.HistoryCursor(stmt.ColumnText(2)),
					CommittedCursor:    remotehistory.HistoryCursor(stmt.ColumnText(3)),
					CommittedAt:        at,
					FingerprintVersion: stmt.ColumnText(5),
					FingerprintSHA256:  stmt.ColumnText(6),
				})
				return nil
			},
		})
	if err != nil {
		return nil, fmt.Errorf("query remote history publications: %w", err)
	}
	return out, nil
}

func insertRemoteHistoryGeneration(conn *sqlite.Conn, generation remotehistory.HistoryGeneration) error {
	if err := sqlitex.Execute(conn,
		"INSERT INTO remote_history_generations (generation_id, provider_id, identity_domain, stream_id, root, scope_policy_fingerprint, status, created_at, closed_at, closure_reason, current_sequence, committed_cursor) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, NULL, NULL, ?9, ?10)",
		&sqlitex.ExecOptions{Args: []any{
			string(generation.ID),
			string(generation.Scope.ProviderID),
			generation.Scope.IdentityDomain,
			string(generation.Scope.StreamID),
			generation.Scope.Root,
			string(generation.ScopePolicyFingerprint),
			string(generation.Status),
			generation.CreatedAt.UTC().Format(time.RFC3339Nano),
			int64(generation.CurrentSequence),
			string(generation.CommittedCursor),
		}}); err != nil {
		if strings.Contains(err.Error(), "UNIQUE constraint failed") {
			return ErrActiveHistoryGenerationExists
		}
		return fmt.Errorf("insert remote history generation: %w", err)
	}
	return nil
}

func insertRemoteHistoryPublication(conn *sqlite.Conn, publication remotehistory.HistoryPublication) error {
	if err := sqlitex.Execute(conn,
		"INSERT INTO remote_history_publications (generation_id, sequence, kind, previous_cursor, committed_cursor, committed_at, fingerprint_version, fingerprint_sha256) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
		&sqlitex.ExecOptions{Args: []any{
			string(publication.GenerationID),
			int64(publication.Sequence),
			string(publication.Kind),
			string(publication.PreviousCursor),
			string(publication.CommittedCursor),
			publication.CommittedAt.UTC().Format(time.RFC3339Nano),
			publication.FingerprintVersion,
			publication.FingerprintSHA256,
		}}); err != nil {
		return fmt.Errorf("insert remote history publication: %w", err)
	}
	return nil
}

func remoteHistoryGenerationConn(conn *sqlite.Conn, generationID remotehistory.HistoryGenerationID) (remotehistory.HistoryGeneration, error) {
	if generationID == "" {
		return remotehistory.HistoryGeneration{}, remotehistory.ErrInvalidHistoryGeneration
	}
	var generation remotehistory.HistoryGeneration
	var createdText, closedText string
	var found bool
	err := sqlitex.Execute(conn,
		"SELECT provider_id, identity_domain, stream_id, root, scope_policy_fingerprint, status, created_at, COALESCE(closed_at,''), COALESCE(closure_reason,''), current_sequence, committed_cursor FROM remote_history_generations WHERE generation_id=?1",
		&sqlitex.ExecOptions{
			Args: []any{string(generationID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				found = true
				generation.ID = generationID
				generation.Scope = remotehistory.Scope{
					ProviderID:     corpus.ProviderID(stmt.ColumnText(0)),
					IdentityDomain: stmt.ColumnText(1),
					StreamID:       remotehistory.HistoryStreamID(stmt.ColumnText(2)),
					Root:           stmt.ColumnText(3),
				}
				generation.ScopePolicyFingerprint = remotehistory.ScopePolicyFingerprint(stmt.ColumnText(4))
				generation.Status = remotehistory.HistoryGenerationStatus(stmt.ColumnText(5))
				createdText = stmt.ColumnText(6)
				closedText = stmt.ColumnText(7)
				generation.ClosureReason = remotehistory.HistoryClosureReason(stmt.ColumnText(8))
				generation.CurrentSequence = remotehistory.HistoryPublicationSequence(stmt.ColumnInt64(9))
				generation.CommittedCursor = remotehistory.HistoryCursor(stmt.ColumnText(10))
				return nil
			},
		})
	if err != nil {
		return remotehistory.HistoryGeneration{}, fmt.Errorf("query remote history generation: %w", err)
	}
	if !found {
		return remotehistory.HistoryGeneration{}, fmt.Errorf("%w: %s", ErrHistoryGenerationNotFound, generationID)
	}
	generation.CreatedAt, err = time.Parse(time.RFC3339Nano, createdText)
	if err != nil {
		return remotehistory.HistoryGeneration{}, fmt.Errorf("parse remote history generation creation: %w", err)
	}
	if closedText != "" {
		generation.ClosedAt, err = time.Parse(time.RFC3339Nano, closedText)
		if err != nil {
			return remotehistory.HistoryGeneration{}, fmt.Errorf("parse remote history generation closure: %w", err)
		}
	}
	return generation, nil
}

func activeRemoteHistoryGenerationConn(conn *sqlite.Conn, scope remotehistory.Scope) (remotehistory.HistoryGeneration, bool, error) {
	var id remotehistory.HistoryGenerationID
	err := sqlitex.Execute(conn,
		"SELECT generation_id FROM remote_history_generations WHERE provider_id=?1 AND identity_domain=?2 AND stream_id=?3 AND root=?4 AND status='ACTIVE' LIMIT 1",
		&sqlitex.ExecOptions{
			Args: []any{string(scope.ProviderID), scope.IdentityDomain, string(scope.StreamID), scope.Root},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				id = remotehistory.HistoryGenerationID(stmt.ColumnText(0))
				return nil
			},
		})
	if err != nil {
		return remotehistory.HistoryGeneration{}, false, fmt.Errorf("query active remote history generation: %w", err)
	}
	if id == "" {
		return remotehistory.HistoryGeneration{}, false, nil
	}
	generation, err := remoteHistoryGenerationConn(conn, id)
	return generation, true, err
}

func requireHistoryScope(generation remotehistory.HistoryGeneration, scope remotehistory.Scope, fingerprint remotehistory.ScopePolicyFingerprint) error {
	if generation.Scope != scope || generation.ScopePolicyFingerprint != fingerprint {
		return ErrHistoryScopeMismatch
	}
	return nil
}

func canonicalBootstrapObjects(objects []remotehistory.RemoteObjectState) ([]remotehistory.RemoteObjectState, error) {
	out := make([]remotehistory.RemoteObjectState, len(objects))
	seen := make(map[corpus.ProviderObjectID]struct{}, len(objects))
	for i, object := range objects {
		if object.ObjectID == "" {
			return nil, remotehistory.ErrInvalidHistoryPublication
		}
		if _, duplicate := seen[object.ObjectID]; duplicate {
			return nil, remotehistory.ErrInvalidHistoryPublication
		}
		seen[object.ObjectID] = struct{}{}
		out[i] = object
		out[i].Locators = canonicalLocators(object.Locators)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ObjectID < out[j].ObjectID })
	return out, nil
}

func canonicalChanges(changes []remotehistory.RemoteChange) ([]remotehistory.RemoteChange, error) {
	out := make([]remotehistory.RemoteChange, len(changes))
	for i, change := range changes {
		out[i] = change
		if change.State != nil {
			state := *change.State
			state.Locators = canonicalLocators(change.State.Locators)
			out[i].State = &state
		}
	}
	return out, nil
}

func canonicalLocators(locators []corpus.Locator) []corpus.Locator {
	out := append([]corpus.Locator(nil), locators...)
	sort.Slice(out, func(i, j int) bool {
		if out[i].ProviderID != out[j].ProviderID {
			return out[i].ProviderID < out[j].ProviderID
		}
		if out[i].Root != out[j].Root {
			return out[i].Root < out[j].Root
		}
		return out[i].Path < out[j].Path
	})
	if out == nil {
		out = []corpus.Locator{}
	}
	return out
}

func marshalCanonicalLocators(locators []corpus.Locator) (string, error) {
	encoded, err := json.Marshal(canonicalLocators(locators))
	if err != nil {
		return "", fmt.Errorf("encode remote history locators: %w", err)
	}
	return string(encoded), nil
}

func bootstrapPublicationFingerprint(publication remotehistory.HistoryPublication, objects []remotehistory.RemoteObjectState) (string, error) {
	return fingerprintJSON(struct {
		Version         string                                   `json:"version"`
		GenerationID    remotehistory.HistoryGenerationID        `json:"generation_id"`
		Sequence        remotehistory.HistoryPublicationSequence `json:"sequence"`
		Kind            remotehistory.HistoryPublicationKind     `json:"kind"`
		CommittedCursor remotehistory.HistoryCursor              `json:"committed_cursor"`
		Objects         []remotehistory.RemoteObjectState        `json:"objects"`
	}{
		Version: remoteHistoryPublicationFingerprintVersion,
		GenerationID: publication.GenerationID,
		Sequence: publication.Sequence,
		Kind: publication.Kind,
		CommittedCursor: publication.CommittedCursor,
		Objects: objects,
	})
}

func incrementalPublicationFingerprint(publication remotehistory.HistoryPublication, changes []remotehistory.RemoteChange) (string, error) {
	return fingerprintJSON(struct {
		Version         string                                   `json:"version"`
		GenerationID    remotehistory.HistoryGenerationID        `json:"generation_id"`
		Sequence        remotehistory.HistoryPublicationSequence `json:"sequence"`
		Kind            remotehistory.HistoryPublicationKind     `json:"kind"`
		PreviousCursor  remotehistory.HistoryCursor              `json:"previous_cursor"`
		CommittedCursor remotehistory.HistoryCursor              `json:"committed_cursor"`
		Changes         []remotehistory.RemoteChange             `json:"changes"`
	}{
		Version: remoteHistoryPublicationFingerprintVersion,
		GenerationID: publication.GenerationID,
		Sequence: publication.Sequence,
		Kind: publication.Kind,
		PreviousCursor: publication.PreviousCursor,
		CommittedCursor: publication.CommittedCursor,
		Changes: changes,
	})
}

func fingerprintJSON(value any) (string, error) {
	encoded, err := json.Marshal(value)
	if err != nil {
		return "", fmt.Errorf("encode remote history publication fingerprint: %w", err)
	}
	sum := sha256.Sum256(encoded)
	return hex.EncodeToString(sum[:]), nil
}
