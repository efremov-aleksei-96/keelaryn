package sqlitestate

import (
	"encoding/json"
	"errors"
	"fmt"
	"reflect"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

const remoteHistoryWriteAuthorizationFunction = "keelaryn_remote_history_write_authorized"

const (
	remoteHistoryWriteBootstrap   = "BOOTSTRAP"
	remoteHistoryWriteIncremental = "INCREMENTAL"
	remoteHistoryWriteClose       = "CLOSE"
)

var ErrRemoteHistoryHistoricalAuthorityInvalid = errors.New("historical RemoteHistory authority is invalid")

type remoteHistoryWriteAuthorization struct {
	phase             string
	generationID      remotehistory.HistoryGenerationID
	sequence          remotehistory.HistoryPublicationSequence
	fingerprintSHA256 string
}

type remoteHistoryMembershipProjectionState struct {
	locators []corpus.Locator
	sequence remotehistory.HistoryPublicationSequence
}

func (s *Store) registerRemoteHistoryWriteAuthorizationConn(conn *sqlite.Conn) error {
	auth := &remoteHistoryWriteAuthorization{}
	if err := conn.CreateFunction(remoteHistoryWriteAuthorizationFunction, &sqlite.FunctionImpl{
		NArgs: 4, Deterministic: false, AllowIndirect: true,
		Scalar: func(_ sqlite.Context, args []sqlite.Value) (sqlite.Value, error) {
			if remoteHistoryWriteAuthorized(*auth, args[0].Text(), args[1].Text(), args[2].Text(), args[3].Text()) {
				return sqlite.IntegerValue(1), nil
			}
			return sqlite.IntegerValue(0), nil
		},
	}); err != nil {
		return fmt.Errorf("register RemoteHistory write authorization function: %w", err)
	}
	s.remoteHistoryWriteAuthorizations.Store(conn, auth)
	return nil
}

func remoteHistoryWriteAuthorized(auth remoteHistoryWriteAuthorization, kind, generationID, sequence, fingerprint string) bool {
	if auth.phase == "" || auth.generationID == "" || auth.sequence == 0 ||
		string(auth.generationID) != generationID || fmt.Sprint(auth.sequence) != sequence {
		return false
	}
	switch kind {
	case "GENERATION_INSERT":
		return auth.phase == remoteHistoryWriteBootstrap && auth.sequence == 1
	case "GENERATION_ADVANCE":
		return auth.phase == remoteHistoryWriteIncremental
	case "GENERATION_CLOSE":
		return auth.phase == remoteHistoryWriteClose
	case "PUBLICATION_INSERT":
		return (auth.phase == remoteHistoryWriteBootstrap || auth.phase == remoteHistoryWriteIncremental) &&
			auth.fingerprintSHA256 != "" && auth.fingerprintSHA256 == fingerprint
	case "BOOTSTRAP_MEMBERSHIP_INSERT":
		return auth.phase == remoteHistoryWriteBootstrap && auth.sequence == 1
	case "CHANGE_INSERT", "MEMBERSHIP_UPDATE", "MEMBERSHIP_DELETE":
		return auth.phase == remoteHistoryWriteIncremental
	case "MEMBERSHIP_INSERT", "LIFETIME_INSERT":
		return auth.phase == remoteHistoryWriteBootstrap || auth.phase == remoteHistoryWriteIncremental
	case "LIFETIME_UPDATE":
		return auth.phase == remoteHistoryWriteIncremental || auth.phase == remoteHistoryWriteClose
	default:
		return false
	}
}

func (s *Store) authorizeRemoteHistoryWriteConn(conn *sqlite.Conn, auth remoteHistoryWriteAuthorization) (func(), error) {
	if auth.generationID == "" || auth.sequence == 0 {
		return nil, fmt.Errorf("RemoteHistory write authorization target is incomplete")
	}
	switch auth.phase {
	case remoteHistoryWriteBootstrap:
		if auth.sequence != 1 || auth.fingerprintSHA256 == "" {
			return nil, fmt.Errorf("invalid RemoteHistory bootstrap write authorization")
		}
	case remoteHistoryWriteIncremental:
		if auth.sequence < 2 || auth.fingerprintSHA256 == "" {
			return nil, fmt.Errorf("invalid RemoteHistory incremental write authorization")
		}
	case remoteHistoryWriteClose:
		if auth.fingerprintSHA256 != "" {
			return nil, fmt.Errorf("invalid RemoteHistory close write authorization")
		}
	default:
		return nil, fmt.Errorf("invalid RemoteHistory write authorization phase %q", auth.phase)
	}
	value, ok := s.remoteHistoryWriteAuthorizations.Load(conn)
	if !ok {
		return nil, fmt.Errorf("RemoteHistory write authorization state missing for connection")
	}
	state, ok := value.(*remoteHistoryWriteAuthorization)
	if !ok || state == nil {
		return nil, fmt.Errorf("RemoteHistory write authorization state invalid")
	}
	if state.phase != "" {
		return nil, fmt.Errorf("RemoteHistory write authorization already active")
	}
	*state = auth
	return func() { *state = remoteHistoryWriteAuthorization{} }, nil
}

func verifyRemoteHistoryHistoricalAuthorityConn(conn *sqlite.Conn) error {
	var generationIDs []remotehistory.HistoryGenerationID
	if err := sqlitex.Execute(conn,
		"SELECT generation_id FROM remote_history_generations ORDER BY generation_id",
		&sqlitex.ExecOptions{ResultFunc: func(stmt *sqlite.Stmt) error {
			generationIDs = append(generationIDs, remotehistory.HistoryGenerationID(stmt.ColumnText(0)))
			return nil
		}}); err != nil {
		return fmt.Errorf("%w: list generations: %v", ErrRemoteHistoryHistoricalAuthorityInvalid, err)
	}
	for _, generationID := range generationIDs {
		if err := verifyRemoteHistoryGenerationHistoricalAuthorityConn(conn, generationID); err != nil {
			return err
		}
	}
	return nil
}

func verifyRemoteHistoryGenerationHistoricalAuthorityConn(conn *sqlite.Conn, generationID remotehistory.HistoryGenerationID) error {
	generation, err := remoteHistoryGenerationConn(conn, generationID)
	if err != nil {
		return fmt.Errorf("%w: %v", ErrRemoteHistoryHistoricalAuthorityInvalid, err)
	}
	publications, err := remoteHistoryPublicationsConn(conn, generationID)
	if err != nil {
		return err
	}
	if len(publications) == 0 {
		return fmt.Errorf("%w: generation=%s has no publication", ErrRemoteHistoryHistoricalAuthorityInvalid, generationID)
	}

	expectedMembership := make(map[corpus.ProviderObjectID]remoteHistoryMembershipProjectionState)
	var previousCursor remotehistory.HistoryCursor

	for i, publication := range publications {
		expectedSequence := remotehistory.HistoryPublicationSequence(i + 1)
		if publication.Sequence != expectedSequence ||
			publication.FingerprintVersion != remoteHistoryPublicationFingerprintVersion ||
			(i > 0 && publication.PreviousCursor != previousCursor) {
			return fmt.Errorf("%w: generation=%s publication=%d chain mismatch", ErrRemoteHistoryHistoricalAuthorityInvalid, generationID, publication.Sequence)
		}

		switch publication.Kind {
		case remotehistory.HistoryPublicationBootstrap:
			if publication.Sequence != 1 || publication.PreviousCursor != "" {
				return fmt.Errorf("%w: generation=%s malformed bootstrap publication", ErrRemoteHistoryHistoricalAuthorityInvalid, generationID)
			}
			objects, err := remoteHistoryBootstrapObjectsConn(conn, generationID)
			if err != nil {
				return err
			}
			bootstrap := remotehistory.BootstrapResult{
				StreamID: generation.Scope.StreamID,
				Status: remotehistory.BootstrapComplete,
				Objects: objects,
				Cursor: publication.CommittedCursor,
				Coverage: corpus.ProviderHistoryContinuous,
			}
			if err := remotehistory.ValidateBootstrap(generation.Scope, bootstrap); err != nil {
				return fmt.Errorf("%w: generation=%s bootstrap: %v", ErrRemoteHistoryHistoricalAuthorityInvalid, generationID, err)
			}
			canonical, err := canonicalBootstrapObjects(objects)
			if err != nil {
				return fmt.Errorf("%w: generation=%s bootstrap canonicalization: %v", ErrRemoteHistoryHistoricalAuthorityInvalid, generationID, err)
			}
			want, err := bootstrapPublicationFingerprint(publication, canonical)
			if err != nil {
				return err
			}
			if publication.FingerprintSHA256 != want {
				return fmt.Errorf("%w: generation=%s publication=1 fingerprint mismatch", ErrRemoteHistoryHistoricalAuthorityInvalid, generationID)
			}
			for _, object := range canonical {
				expectedMembership[object.ObjectID] = remoteHistoryMembershipProjectionState{locators: object.Locators, sequence: 1}
			}

		case remotehistory.HistoryPublicationIncremental:
			changes, err := remoteHistoryChangesConn(conn, generationID, publication.Sequence)
			if err != nil {
				return err
			}
			cycle := remotehistory.ChangeCycle{
				StreamID: generation.Scope.StreamID,
				Status: remotehistory.CycleComplete,
				PreviousCursor: publication.PreviousCursor,
				NextCursor: publication.CommittedCursor,
				Changes: changes,
				Coverage: corpus.ProviderHistoryContinuous,
			}
			if err := remotehistory.ValidateCompleteCycle(generation.Scope, publication.PreviousCursor, cycle); err != nil {
				return fmt.Errorf("%w: generation=%s publication=%d: %v", ErrRemoteHistoryHistoricalAuthorityInvalid, generationID, publication.Sequence, err)
			}
			canonical, err := canonicalChanges(changes)
			if err != nil {
				return fmt.Errorf("%w: generation=%s publication=%d canonicalization: %v", ErrRemoteHistoryHistoricalAuthorityInvalid, generationID, publication.Sequence, err)
			}
			want, err := incrementalPublicationFingerprint(publication, canonical)
			if err != nil {
				return err
			}
			if publication.FingerprintSHA256 != want {
				return fmt.Errorf("%w: generation=%s publication=%d fingerprint mismatch", ErrRemoteHistoryHistoricalAuthorityInvalid, generationID, publication.Sequence)
			}
			for _, change := range canonical {
				switch change.Kind {
				case remotehistory.ChangeUpsert:
					expectedMembership[change.ObjectID] = remoteHistoryMembershipProjectionState{locators: change.State.Locators, sequence: publication.Sequence}
				case remotehistory.ChangeRemoved:
					delete(expectedMembership, change.ObjectID)
				}
			}
		default:
			return fmt.Errorf("%w: generation=%s publication=%d invalid kind", ErrRemoteHistoryHistoricalAuthorityInvalid, generationID, publication.Sequence)
		}
		previousCursor = publication.CommittedCursor
	}

	last := publications[len(publications)-1]
	if generation.CurrentSequence != last.Sequence || generation.CommittedCursor != last.CommittedCursor {
		return fmt.Errorf("%w: generation=%s head does not match publication chain", ErrRemoteHistoryHistoricalAuthorityInvalid, generationID)
	}
	if err := verifyRemoteHistoryMembershipProjectionConn(conn, generationID, expectedMembership); err != nil {
		return err
	}
	actualLifetime, err := lifetimeSegmentsConn(conn, generationID)
	if err != nil {
		return fmt.Errorf("%w: generation=%s lifetime query: %v", ErrRemoteHistoryHistoricalAuthorityInvalid, generationID, err)
	}
	expectedLifetime, err := deriveLifetimeSegmentsConn(conn, generationID)
	if err != nil {
		return fmt.Errorf("%w: generation=%s lifetime derivation: %v", ErrRemoteHistoryHistoricalAuthorityInvalid, generationID, err)
	}
	if !reflect.DeepEqual(actualLifetime, expectedLifetime) {
		return fmt.Errorf("%w: generation=%s lifetime projection mismatch", ErrRemoteHistoryHistoricalAuthorityInvalid, generationID)
	}
	return nil
}

func remoteHistoryPublicationsConn(conn *sqlite.Conn, generationID remotehistory.HistoryGenerationID) ([]remotehistory.HistoryPublication, error) {
	var out []remotehistory.HistoryPublication
	err := sqlitex.Execute(conn,
		"SELECT sequence,kind,previous_cursor,committed_cursor,committed_at,fingerprint_version,fingerprint_sha256 FROM remote_history_publications WHERE generation_id=?1 ORDER BY sequence",
		&sqlitex.ExecOptions{Args: []any{string(generationID)}, ResultFunc: func(stmt *sqlite.Stmt) error {
			committedAt, err := time.Parse(time.RFC3339Nano, stmt.ColumnText(4))
			if err != nil {
				return err
			}
			out = append(out, remotehistory.HistoryPublication{
				GenerationID: generationID,
				Sequence: remotehistory.HistoryPublicationSequence(stmt.ColumnInt64(0)),
				Kind: remotehistory.HistoryPublicationKind(stmt.ColumnText(1)),
				PreviousCursor: remotehistory.HistoryCursor(stmt.ColumnText(2)),
				CommittedCursor: remotehistory.HistoryCursor(stmt.ColumnText(3)),
				CommittedAt: committedAt,
				FingerprintVersion: stmt.ColumnText(5),
				FingerprintSHA256: stmt.ColumnText(6),
			})
			return nil
		}})
	if err != nil {
		return nil, fmt.Errorf("%w: generation=%s publications: %v", ErrRemoteHistoryHistoricalAuthorityInvalid, generationID, err)
	}
	return out, nil
}

func remoteHistoryBootstrapObjectsConn(conn *sqlite.Conn, generationID remotehistory.HistoryGenerationID) ([]remotehistory.RemoteObjectState, error) {
	var out []remotehistory.RemoteObjectState
	err := sqlitex.Execute(conn,
		"SELECT object_id,locators_json FROM remote_history_bootstrap_membership WHERE generation_id=?1 ORDER BY object_id",
		&sqlitex.ExecOptions{Args: []any{string(generationID)}, ResultFunc: func(stmt *sqlite.Stmt) error {
			var locators []corpus.Locator
			if err := json.Unmarshal([]byte(stmt.ColumnText(1)), &locators); err != nil {
				return err
			}
			out = append(out, remotehistory.RemoteObjectState{ObjectID: corpus.ProviderObjectID(stmt.ColumnText(0)), Locators: locators})
			return nil
		}})
	if err != nil {
		return nil, fmt.Errorf("%w: generation=%s bootstrap evidence: %v", ErrRemoteHistoryHistoricalAuthorityInvalid, generationID, err)
	}
	return out, nil
}

func remoteHistoryChangesConn(conn *sqlite.Conn, generationID remotehistory.HistoryGenerationID, sequence remotehistory.HistoryPublicationSequence) ([]remotehistory.RemoteChange, error) {
	var out []remotehistory.RemoteChange
	err := sqlitex.Execute(conn,
		"SELECT kind,object_id,state_json FROM remote_history_publication_changes WHERE generation_id=?1 AND sequence=?2 ORDER BY ordinal",
		&sqlitex.ExecOptions{Args: []any{string(generationID), int64(sequence)}, ResultFunc: func(stmt *sqlite.Stmt) error {
			change := remotehistory.RemoteChange{Kind: remotehistory.ChangeKind(stmt.ColumnText(0)), ObjectID: corpus.ProviderObjectID(stmt.ColumnText(1))}
			if !stmt.ColumnIsNull(2) {
				var state remotehistory.RemoteObjectState
				if err := json.Unmarshal([]byte(stmt.ColumnText(2)), &state); err != nil {
					return err
				}
				change.State = &state
			}
			out = append(out, change)
			return nil
		}})
	if err != nil {
		return nil, fmt.Errorf("%w: generation=%s publication=%d changes: %v", ErrRemoteHistoryHistoricalAuthorityInvalid, generationID, sequence, err)
	}
	return out, nil
}

func verifyRemoteHistoryMembershipProjectionConn(
	conn *sqlite.Conn,
	generationID remotehistory.HistoryGenerationID,
	expected map[corpus.ProviderObjectID]remoteHistoryMembershipProjectionState,
) error {
	actual := make(map[corpus.ProviderObjectID]remoteHistoryMembershipProjectionState)
	err := sqlitex.Execute(conn,
		"SELECT object_id,locators_json,last_sequence FROM remote_history_membership WHERE generation_id=?1",
		&sqlitex.ExecOptions{Args: []any{string(generationID)}, ResultFunc: func(stmt *sqlite.Stmt) error {
			var locators []corpus.Locator
			if err := json.Unmarshal([]byte(stmt.ColumnText(1)), &locators); err != nil {
				return err
			}
			actual[corpus.ProviderObjectID(stmt.ColumnText(0))] = remoteHistoryMembershipProjectionState{locators: canonicalLocators(locators), sequence: remotehistory.HistoryPublicationSequence(stmt.ColumnInt64(2))}
			return nil
		}})
	if err != nil {
		return fmt.Errorf("%w: generation=%s membership query: %v", ErrRemoteHistoryHistoricalAuthorityInvalid, generationID, err)
	}
	normalizedExpected := make(map[corpus.ProviderObjectID]remoteHistoryMembershipProjectionState, len(expected))
	for objectID, state := range expected {
		normalizedExpected[objectID] = remoteHistoryMembershipProjectionState{locators: canonicalLocators(state.locators), sequence: state.sequence}
	}
	if !reflect.DeepEqual(actual, normalizedExpected) {
		return fmt.Errorf("%w: generation=%s membership projection mismatch", ErrRemoteHistoryHistoricalAuthorityInvalid, generationID)
	}
	return nil
}
