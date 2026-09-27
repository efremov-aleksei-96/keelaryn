package sqlitestate

import (
	"errors"
	"fmt"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory/gdrive"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

const (
	googleDriveTopologyWriteAuthorizationFunction = "keelaryn_gdrive_topology_write_authorized"
	googleDriveManagedRootBindingInsertAuthorizationFunction = "keelaryn_gdrive_managed_root_binding_insert_authorized"

	googleDriveTopologyWriteBootstrap   = "BOOTSTRAP"
	googleDriveTopologyWriteIncremental = "INCREMENTAL"
	googleDriveTopologyWriteManagedRoot = "MANAGED_ROOT"
)

var ErrGoogleDriveHistoricalAuthorityInvalid = errors.New("historical Google Drive topology authority is invalid")

type googleDriveTopologyAuthorizedEntry struct {
	ordinal      int64
	evidenceKind gdrive.TopologyEvidenceKind
	state        gdrive.TopologyState
}

type googleDriveTopologyWriteAuthorization struct {
	phase               string
	generationID        remotehistory.HistoryGenerationID
	sequence            remotehistory.HistoryPublicationSequence
	entries             map[string]googleDriveTopologyAuthorizedEntry
	managedRootObjectID corpus.ProviderObjectID
	createdAt           string
}

func googleDriveTopologyEntryKey(ordinal int64, objectID corpus.ProviderObjectID) string {
	return fmt.Sprintf("%d\x00%s", ordinal, objectID)
}

func googleBootstrapTopologyAuthorizationEntries(topology map[corpus.ProviderObjectID]gdrive.TopologyState) map[string]googleDriveTopologyAuthorizedEntry {
	out := make(map[string]googleDriveTopologyAuthorizedEntry, len(topology))
	for objectID, state := range topology {
		out[googleDriveTopologyEntryKey(-1, objectID)] = googleDriveTopologyAuthorizedEntry{
			ordinal: -1, evidenceKind: gdrive.TopologyEvidenceBootstrap, state: state,
		}
	}
	return out
}

func googleIncrementalTopologyAuthorizationEntries(
	changes []remotehistory.RemoteChange,
	topology []gdrive.TopologyState,
) map[string]googleDriveTopologyAuthorizedEntry {
	out := make(map[string]googleDriveTopologyAuthorizedEntry, len(topology))
	for i, state := range topology {
		kind := gdrive.TopologyEvidenceUpsert
		if i < len(changes) && changes[i].Kind == remotehistory.ChangeRemoved {
			kind = gdrive.TopologyEvidenceRemoved
		}
		ordinal := int64(i)
		out[googleDriveTopologyEntryKey(ordinal, state.ObjectID)] = googleDriveTopologyAuthorizedEntry{
			ordinal: ordinal, evidenceKind: kind, state: state,
		}
	}
	return out
}

func (s *Store) registerGoogleDriveTopologyWriteAuthorizationConn(conn *sqlite.Conn) error {
	auth := &googleDriveTopologyWriteAuthorization{}
	if err := conn.CreateFunction(googleDriveTopologyWriteAuthorizationFunction, &sqlite.FunctionImpl{
		NArgs: 9, Deterministic: false, AllowIndirect: true,
		Scalar: func(_ sqlite.Context, args []sqlite.Value) (sqlite.Value, error) {
			if googleDriveTopologyWriteAuthorized(
				*auth,
				args[0].Text(), args[1].Text(), args[2].Text(), args[3].Text(),
				args[4].Text(), args[5].Text(), args[6].Text(), args[7].Text(), args[8].Text(),
			) {
				return sqlite.IntegerValue(1), nil
			}
			return sqlite.IntegerValue(0), nil
		},
	}); err != nil {
		return fmt.Errorf("register Google Drive topology write authorization function: %w", err)
	}
	if err := conn.CreateFunction(googleDriveManagedRootBindingInsertAuthorizationFunction, &sqlite.FunctionImpl{
		NArgs: 4, Deterministic: false, AllowIndirect: true,
		Scalar: func(_ sqlite.Context, args []sqlite.Value) (sqlite.Value, error) {
			if auth.phase == googleDriveTopologyWriteManagedRoot &&
				string(auth.generationID) == args[0].Text() &&
				string(auth.managedRootObjectID) == args[1].Text() &&
				fmt.Sprint(auth.sequence) == args[2].Text() &&
				auth.createdAt == args[3].Text() {
				return sqlite.IntegerValue(1), nil
			}
			return sqlite.IntegerValue(0), nil
		},
	}); err != nil {
		return fmt.Errorf("register Google Drive managed-root binding authorization function: %w", err)
	}
	s.gdriveTopologyWriteAuthorizations.Store(conn, auth)
	return nil
}

func googleDriveTopologyWriteAuthorized(
	auth googleDriveTopologyWriteAuthorization,
	kind, generationID, sequenceText, ordinalText, objectID, presence, parentState, parentID, driveID string,
) bool {
	if auth.generationID == "" || string(auth.generationID) != generationID {
		return false
	}
	switch kind {
	case "WATERMARK_INSERT":
		return (auth.phase == googleDriveTopologyWriteBootstrap || auth.phase == googleDriveTopologyWriteIncremental) &&
			fmt.Sprint(auth.sequence) == sequenceText
	case "WATERMARK_DELETE":
		return auth.phase == googleDriveTopologyWriteIncremental &&
			auth.sequence > 1 && fmt.Sprint(auth.sequence-1) == sequenceText
	}
	if auth.phase != googleDriveTopologyWriteBootstrap && auth.phase != googleDriveTopologyWriteIncremental ||
		fmt.Sprint(auth.sequence) != sequenceText {
		return false
	}
	var ordinal int64
	if _, err := fmt.Sscan(ordinalText, &ordinal); err != nil {
		return false
	}
	entry, ok := auth.entries[googleDriveTopologyEntryKey(ordinal, corpus.ProviderObjectID(objectID))]
	if !ok {
		return false
	}
	if kind == "EVIDENCE_"+string(entry.evidenceKind) {
		// exact authoritative provider evidence
	} else if kind == "NODE_WRITE" {
		// rebuildable projection is authorized only from the exact validated evidence entry
	} else {
		return false
	}
	return string(entry.state.ObjectID) == objectID &&
		string(entry.state.Presence) == presence &&
		string(entry.state.ParentKnowledge) == parentState &&
		string(entry.state.ParentObjectID) == parentID &&
		entry.state.DriveID == driveID
}

func (s *Store) authorizeGoogleDriveTopologyWriteConn(conn *sqlite.Conn, auth googleDriveTopologyWriteAuthorization) (func(), error) {
	if auth.generationID == "" || auth.sequence == 0 {
		return nil, fmt.Errorf("Google Drive topology write authorization target is incomplete")
	}
	switch auth.phase {
	case googleDriveTopologyWriteBootstrap:
		if auth.sequence != 1 || auth.entries == nil {
			return nil, fmt.Errorf("invalid Google Drive bootstrap topology authorization")
		}
	case googleDriveTopologyWriteIncremental:
		if auth.sequence < 2 || auth.entries == nil {
			return nil, fmt.Errorf("invalid Google Drive incremental topology authorization")
		}
	case googleDriveTopologyWriteManagedRoot:
		if auth.managedRootObjectID == "" || auth.createdAt == "" || auth.entries != nil {
			return nil, fmt.Errorf("invalid Google Drive managed-root binding authorization")
		}
	default:
		return nil, fmt.Errorf("invalid Google Drive topology write authorization phase %q", auth.phase)
	}
	value, ok := s.gdriveTopologyWriteAuthorizations.Load(conn)
	if !ok {
		return nil, fmt.Errorf("Google Drive topology write authorization state missing for connection")
	}
	state, ok := value.(*googleDriveTopologyWriteAuthorization)
	if !ok || state == nil {
		return nil, fmt.Errorf("Google Drive topology write authorization state invalid")
	}
	if state.phase != "" {
		return nil, fmt.Errorf("Google Drive topology write authorization already active")
	}
	*state = auth
	return func() { *state = googleDriveTopologyWriteAuthorization{} }, nil
}

func verifyGoogleDriveHistoricalAuthorityConn(conn *sqlite.Conn) error {
	var topologyGenerations []remotehistory.HistoryGenerationID
	if err := sqlitex.Execute(conn, `
SELECT generation_id FROM (
	SELECT generation_id FROM gdrive_topology_evidence
	UNION SELECT generation_id FROM gdrive_topology_nodes
	UNION SELECT generation_id FROM gdrive_topology_watermarks
) ORDER BY generation_id`,
		&sqlitex.ExecOptions{ResultFunc: func(stmt *sqlite.Stmt) error {
			topologyGenerations = append(topologyGenerations, remotehistory.HistoryGenerationID(stmt.ColumnText(0)))
			return nil
		}}); err != nil {
		return fmt.Errorf("%w: list topology generations: %v", ErrGoogleDriveHistoricalAuthorityInvalid, err)
	}
	for _, generationID := range topologyGenerations {
		generation, err := remoteHistoryGenerationConn(conn, generationID)
		if err != nil {
			return fmt.Errorf("%w: %v", ErrGoogleDriveHistoricalAuthorityInvalid, err)
		}
		if generation.Scope.ProviderID != gdrive.ProviderID {
			return fmt.Errorf("%w: topology generation=%s provider=%s", ErrGoogleDriveHistoricalAuthorityInvalid, generationID, generation.Scope.ProviderID)
		}
		if err := verifyGoogleDriveTopologyEvidenceSemanticsConn(conn, generationID); err != nil {
			return err
		}
		if err := verifyGoogleDriveTopologyNodesSemanticsConn(conn, generationID); err != nil {
			return err
		}
		if err := verifyGoogleDriveTopologyProjectionConn(conn, generationID, generation.CurrentSequence); err != nil {
			return fmt.Errorf("%w: generation=%s: %v", ErrGoogleDriveHistoricalAuthorityInvalid, generationID, err)
		}
	}
	return verifyGoogleDriveManagedRootBindingsHistoricalConn(conn)
}

func verifyGoogleDriveTopologyEvidenceSemanticsConn(conn *sqlite.Conn, generationID remotehistory.HistoryGenerationID) error {
	return sqlitex.Execute(conn, `
SELECT sequence,ordinal,evidence_kind,object_id,presence,parent_state,COALESCE(parent_id,''),drive_id
FROM gdrive_topology_evidence
WHERE generation_id=?1
ORDER BY sequence,ordinal,object_id`,
		&sqlitex.ExecOptions{Args: []any{string(generationID)}, ResultFunc: func(stmt *sqlite.Stmt) error {
			ordinal := stmt.ColumnInt64(1)
			var changeOrdinal *int64
			if ordinal >= 0 {
				value := ordinal
				changeOrdinal = &value
			}
			evidence := gdrive.TopologyEvidence{
				GenerationID: generationID,
				PublicationSequence: remotehistory.HistoryPublicationSequence(stmt.ColumnInt64(0)),
				ChangeOrdinal: changeOrdinal,
				Kind: gdrive.TopologyEvidenceKind(stmt.ColumnText(2)),
				ObjectID: corpus.ProviderObjectID(stmt.ColumnText(3)),
				Presence: gdrive.TopologyPresence(stmt.ColumnText(4)),
				ParentKnowledge: gdrive.ParentKnowledge(stmt.ColumnText(5)),
				ParentObjectID: corpus.ProviderObjectID(stmt.ColumnText(6)),
				DriveID: stmt.ColumnText(7),
			}
			if err := gdrive.ValidateTopologyEvidence(evidence); err != nil {
				return fmt.Errorf("%w: generation=%s evidence=%s/%d: %v", ErrGoogleDriveHistoricalAuthorityInvalid, generationID, evidence.ObjectID, evidence.PublicationSequence, err)
			}
			return nil
		}})
}

func verifyGoogleDriveTopologyNodesSemanticsConn(conn *sqlite.Conn, generationID remotehistory.HistoryGenerationID) error {
	var objectIDs []corpus.ProviderObjectID
	if err := sqlitex.Execute(conn,
		"SELECT object_id FROM gdrive_topology_nodes WHERE generation_id=?1 ORDER BY object_id",
		&sqlitex.ExecOptions{Args: []any{string(generationID)}, ResultFunc: func(stmt *sqlite.Stmt) error {
			objectIDs = append(objectIDs, corpus.ProviderObjectID(stmt.ColumnText(0)))
			return nil
		}}); err != nil {
		return fmt.Errorf("%w: generation=%s node list: %v", ErrGoogleDriveHistoricalAuthorityInvalid, generationID, err)
	}
	for _, objectID := range objectIDs {
		if _, found, err := googleTopologyNodeConn(conn, generationID, objectID); err != nil {
			return fmt.Errorf("%w: generation=%s node=%s: %v", ErrGoogleDriveHistoricalAuthorityInvalid, generationID, objectID, err)
		} else if !found {
			return fmt.Errorf("%w: generation=%s node=%s disappeared", ErrGoogleDriveHistoricalAuthorityInvalid, generationID, objectID)
		}
	}
	return nil
}

func verifyGoogleDriveManagedRootBindingsHistoricalConn(conn *sqlite.Conn) error {
	type bindingKey struct {
		generationID remotehistory.HistoryGenerationID
		objectID corpus.ProviderObjectID
	}
	var keys []bindingKey
	if err := sqlitex.Execute(conn,
		"SELECT generation_id,managed_root_object_id FROM gdrive_managed_root_bindings ORDER BY generation_id,managed_root_object_id",
		&sqlitex.ExecOptions{ResultFunc: func(stmt *sqlite.Stmt) error {
			keys = append(keys, bindingKey{
				generationID: remotehistory.HistoryGenerationID(stmt.ColumnText(0)),
				objectID: corpus.ProviderObjectID(stmt.ColumnText(1)),
			})
			return nil
		}}); err != nil {
		return fmt.Errorf("%w: list managed-root bindings: %v", ErrGoogleDriveHistoricalAuthorityInvalid, err)
	}
	for _, key := range keys {
		generation, err := remoteHistoryGenerationConn(conn, key.generationID)
		if err != nil {
			return fmt.Errorf("%w: %v", ErrGoogleDriveHistoricalAuthorityInvalid, err)
		}
		if generation.Scope.ProviderID != gdrive.ProviderID {
			return fmt.Errorf("%w: managed-root generation=%s provider=%s", ErrGoogleDriveHistoricalAuthorityInvalid, key.generationID, generation.Scope.ProviderID)
		}
		binding, found, err := googleManagedRootBindingConn(conn, key.generationID, key.objectID)
		if err != nil {
			return fmt.Errorf("%w: managed-root generation=%s object=%s: %v", ErrGoogleDriveHistoricalAuthorityInvalid, key.generationID, key.objectID, err)
		}
		if !found || binding.BoundSequence > generation.CurrentSequence {
			return fmt.Errorf("%w: invalid managed-root generation=%s object=%s", ErrGoogleDriveHistoricalAuthorityInvalid, key.generationID, key.objectID)
		}
	}
	return nil
}

func googleDriveTopologyAuthorizationCreatedAt(t time.Time) string {
	return t.UTC().Format(time.RFC3339Nano)
}
