package sqlitestate

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory/gdrive"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

var (
	ErrGoogleDriveTopologyBundle     = errors.New("invalid Google Drive topology bundle")
	ErrGoogleDriveTopologyProjection = errors.New("Google Drive topology projection is not aligned with RemoteHistory")
)

func (s *Store) StartGoogleDriveRemoteHistoryGeneration(
	ctx context.Context,
	scope remotehistory.Scope,
	scopePolicyFingerprint remotehistory.ScopePolicyFingerprint,
	bundle gdrive.BootstrapBundle,
	committedAt time.Time,
) (remotehistory.HistoryGeneration, error) {
	topology, err := validateGoogleBootstrapBundle(scope, bundle)
	if err != nil {
		return remotehistory.HistoryGeneration{}, err
	}
	return s.startRemoteHistoryGenerationWithSidecar(
		ctx,
		scope,
		scopePolicyFingerprint,
		bundle.History,
		committedAt,
		func(conn *sqlite.Conn, generation remotehistory.HistoryGeneration, objects []remotehistory.RemoteObjectState) error {
			for _, object := range objects {
				state, ok := topology[object.ObjectID]
				if !ok {
					return fmt.Errorf("%w: missing bootstrap state for %s", ErrGoogleDriveTopologyBundle, object.ObjectID)
				}
				if err := insertGoogleTopologyEvidenceConn(
					conn, generation.ID, 1, -1, gdrive.TopologyEvidenceBootstrap, state,
				); err != nil {
					return err
				}
				if err := upsertGoogleTopologyNodeConn(conn, generation.ID, 1, -1, state); err != nil {
					return err
				}
			}
			if err := insertGoogleTopologyWatermarkConn(conn, generation.ID, 1); err != nil {
				return err
			}
			return nil
		},
	)
}

func (s *Store) PublishGoogleDriveRemoteHistoryCycle(
	ctx context.Context,
	generationID remotehistory.HistoryGenerationID,
	scope remotehistory.Scope,
	scopePolicyFingerprint remotehistory.ScopePolicyFingerprint,
	expectedSequence remotehistory.HistoryPublicationSequence,
	expectedCursor remotehistory.HistoryCursor,
	bundle gdrive.ChangeCycleBundle,
	committedAt time.Time,
) (remotehistory.HistoryGeneration, error) {
	topology, err := validateGoogleChangeCycleBundle(scope, expectedCursor, bundle)
	if err != nil {
		return remotehistory.HistoryGeneration{}, err
	}
	return s.publishRemoteHistoryCycleWithSidecar(
		ctx,
		generationID,
		scope,
		scopePolicyFingerprint,
		expectedSequence,
		expectedCursor,
		bundle.History,
		committedAt,
		func(
			conn *sqlite.Conn,
			generation remotehistory.HistoryGeneration,
			sequence remotehistory.HistoryPublicationSequence,
			changes []remotehistory.RemoteChange,
		) error {
			if len(changes) != len(topology) {
				return ErrGoogleDriveTopologyBundle
			}
			if err := sqlitex.Execute(conn,
				"DELETE FROM gdrive_topology_watermarks WHERE generation_id=?1 AND publication_sequence=?2",
				&sqlitex.ExecOptions{Args: []any{string(generation.ID), int64(sequence - 1)}}); err != nil {
				return fmt.Errorf("remove Google Drive topology watermark: %w", err)
			}
			if conn.Changes() != 1 {
				return fmt.Errorf("%w: expected watermark at sequence %d", ErrGoogleDriveTopologyProjection, sequence-1)
			}

			for i, change := range changes {
				state := topology[i]
				if state.ObjectID != change.ObjectID {
					return fmt.Errorf("%w: ordinal %d object mismatch", ErrGoogleDriveTopologyBundle, i)
				}
				kind := gdrive.TopologyEvidenceUpsert
				if change.Kind == remotehistory.ChangeRemoved {
					kind = gdrive.TopologyEvidenceRemoved
				}
				if err := insertGoogleTopologyEvidenceConn(
					conn, generation.ID, sequence, int64(i), kind, state,
				); err != nil {
					return err
				}
				if err := upsertGoogleTopologyNodeConn(conn, generation.ID, sequence, int64(i), state); err != nil {
					return err
				}
			}
			if err := insertGoogleTopologyWatermarkConn(conn, generation.ID, sequence); err != nil {
				return err
			}
			return nil
		},
	)
}

func validateGoogleBootstrapBundle(
	scope remotehistory.Scope,
	bundle gdrive.BootstrapBundle,
) (map[corpus.ProviderObjectID]gdrive.TopologyState, error) {
	if scope.ProviderID != gdrive.ProviderID {
		return nil, fmt.Errorf("%w: provider=%s", ErrGoogleDriveTopologyBundle, scope.ProviderID)
	}
	if err := remotehistory.ValidateBootstrap(scope, bundle.History); err != nil {
		return nil, err
	}
	if bundle.History.Status != remotehistory.BootstrapComplete ||
		len(bundle.History.Objects) != len(bundle.Topology) {
		return nil, ErrGoogleDriveTopologyBundle
	}

	topology := make(map[corpus.ProviderObjectID]gdrive.TopologyState, len(bundle.Topology))
	for _, state := range bundle.Topology {
		if err := gdrive.ValidateTopologyState(state); err != nil {
			return nil, err
		}
		if state.Presence != gdrive.TopologyPresent {
			return nil, ErrGoogleDriveTopologyBundle
		}
		if _, duplicate := topology[state.ObjectID]; duplicate {
			return nil, fmt.Errorf("%w: duplicate object %s", ErrGoogleDriveTopologyBundle, state.ObjectID)
		}
		topology[state.ObjectID] = state
	}
	for _, object := range bundle.History.Objects {
		if _, ok := topology[object.ObjectID]; !ok {
			return nil, fmt.Errorf("%w: history object %s has no topology", ErrGoogleDriveTopologyBundle, object.ObjectID)
		}
	}
	return topology, nil
}

func validateGoogleChangeCycleBundle(
	scope remotehistory.Scope,
	expectedCursor remotehistory.HistoryCursor,
	bundle gdrive.ChangeCycleBundle,
) ([]gdrive.TopologyState, error) {
	if scope.ProviderID != gdrive.ProviderID {
		return nil, fmt.Errorf("%w: provider=%s", ErrGoogleDriveTopologyBundle, scope.ProviderID)
	}
	if err := remotehistory.ValidateCompleteCycle(scope, expectedCursor, bundle.History); err != nil {
		return nil, err
	}
	if len(bundle.History.Changes) != len(bundle.Topology) {
		return nil, ErrGoogleDriveTopologyBundle
	}
	out := append([]gdrive.TopologyState(nil), bundle.Topology...)
	for i, change := range bundle.History.Changes {
		state := out[i]
		if err := gdrive.ValidateTopologyState(state); err != nil {
			return nil, err
		}
		if state.ObjectID != change.ObjectID {
			return nil, fmt.Errorf("%w: ordinal %d object mismatch", ErrGoogleDriveTopologyBundle, i)
		}
		switch change.Kind {
		case remotehistory.ChangeUpsert:
			if state.Presence != gdrive.TopologyPresent {
				return nil, fmt.Errorf("%w: UPSERT ordinal %d lacks PRESENT topology", ErrGoogleDriveTopologyBundle, i)
			}
		case remotehistory.ChangeRemoved:
			if state.Presence != gdrive.TopologyUnavailable {
				return nil, fmt.Errorf("%w: REMOVED ordinal %d lacks UNAVAILABLE topology", ErrGoogleDriveTopologyBundle, i)
			}
		default:
			return nil, remotehistory.ErrInvalidHistoryPublication
		}
	}
	return out, nil
}

func insertGoogleTopologyEvidenceConn(
	conn *sqlite.Conn,
	generationID remotehistory.HistoryGenerationID,
	sequence remotehistory.HistoryPublicationSequence,
	ordinal int64,
	kind gdrive.TopologyEvidenceKind,
	state gdrive.TopologyState,
) error {
	if err := sqlitex.Execute(conn,
		"INSERT INTO gdrive_topology_evidence (generation_id, sequence, ordinal, evidence_kind, object_id, presence, parent_state, parent_id, drive_id) VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9)",
		&sqlitex.ExecOptions{Args: []any{
			string(generationID),
			int64(sequence),
			ordinal,
			string(kind),
			string(state.ObjectID),
			string(state.Presence),
			string(state.ParentKnowledge),
			nullableGoogleParent(state.ParentObjectID),
			state.DriveID,
		}}); err != nil {
		return fmt.Errorf("insert Google Drive topology evidence: %w", err)
	}
	return nil
}

func upsertGoogleTopologyNodeConn(
	conn *sqlite.Conn,
	generationID remotehistory.HistoryGenerationID,
	sequence remotehistory.HistoryPublicationSequence,
	ordinal int64,
	state gdrive.TopologyState,
) error {
	if err := sqlitex.Execute(conn,
		"INSERT INTO gdrive_topology_nodes (generation_id, object_id, presence, parent_state, parent_id, drive_id, last_sequence, last_ordinal) VALUES (?1,?2,?3,?4,?5,?6,?7,?8) ON CONFLICT (generation_id, object_id) DO UPDATE SET presence=excluded.presence, parent_state=excluded.parent_state, parent_id=excluded.parent_id, drive_id=excluded.drive_id, last_sequence=excluded.last_sequence, last_ordinal=excluded.last_ordinal",
		&sqlitex.ExecOptions{Args: []any{
			string(generationID),
			string(state.ObjectID),
			string(state.Presence),
			string(state.ParentKnowledge),
			nullableGoogleParent(state.ParentObjectID),
			state.DriveID,
			int64(sequence),
			ordinal,
		}}); err != nil {
		return fmt.Errorf("upsert Google Drive topology node: %w", err)
	}
	return nil
}

func insertGoogleTopologyWatermarkConn(
	conn *sqlite.Conn,
	generationID remotehistory.HistoryGenerationID,
	sequence remotehistory.HistoryPublicationSequence,
) error {
	if err := sqlitex.Execute(conn,
		"INSERT INTO gdrive_topology_watermarks (generation_id, publication_sequence) VALUES (?1,?2)",
		&sqlitex.ExecOptions{Args: []any{string(generationID), int64(sequence)}}); err != nil {
		return fmt.Errorf("insert Google Drive topology watermark: %w", err)
	}
	return nil
}

func nullableGoogleParent(parent corpus.ProviderObjectID) any {
	if parent == "" {
		return nil
	}
	return string(parent)
}
