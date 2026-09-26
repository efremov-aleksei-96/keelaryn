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
	ErrGoogleManagedRootBindingNotFound = errors.New("Google Drive managed-root binding not found")
	ErrGoogleManagedRootBindingStale    = errors.New("Google Drive managed-root binding no longer matches current provider-object lifetime")
)

func (s *Store) BindGoogleDriveManagedRoot(
	ctx context.Context,
	generationID remotehistory.HistoryGenerationID,
	managedRootObjectID corpus.ProviderObjectID,
	createdAt time.Time,
) (out gdrive.ManagedRootBinding, err error) {
	if generationID == "" || managedRootObjectID == "" || createdAt.IsZero() {
		return gdrive.ManagedRootBinding{}, gdrive.ErrInvalidTopologyState
	}

	conn, err := s.pool.Get(ctx)
	if err != nil {
		return gdrive.ManagedRootBinding{}, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)

	end, err := sqlitex.ImmediateTransaction(conn)
	if err != nil {
		return gdrive.ManagedRootBinding{}, fmt.Errorf("begin Google managed-root binding transaction: %w", err)
	}
	defer end(&err)

	generation, err := remoteHistoryGenerationConn(conn, generationID)
	if err != nil {
		return gdrive.ManagedRootBinding{}, err
	}
	if generation.Scope.ProviderID != gdrive.ProviderID {
		return gdrive.ManagedRootBinding{}, fmt.Errorf("%w: provider=%s", gdrive.ErrInvalidTopologyState, generation.Scope.ProviderID)
	}

	if existing, found, err := googleManagedRootBindingConn(conn, generationID, managedRootObjectID); err != nil {
		return gdrive.ManagedRootBinding{}, err
	} else if found {
		if managedRootObjectID != corpus.ProviderObjectID(generation.Scope.Root) {
			segment, active, err := activeLifetimeSegmentConn(conn, generationID, managedRootObjectID)
			if err != nil {
				return gdrive.ManagedRootBinding{}, err
			}
			if !active || segment.StartPublicationSequence > existing.BoundSequence {
				return gdrive.ManagedRootBinding{}, fmt.Errorf(
					"%w: generation=%s root=%s",
					ErrGoogleManagedRootBindingStale,
					generationID,
					managedRootObjectID,
				)
			}
		}
		return existing, nil
	}

	if managedRootObjectID != corpus.ProviderObjectID(generation.Scope.Root) {
		if _, active, err := activeLifetimeSegmentConn(conn, generationID, managedRootObjectID); err != nil {
			return gdrive.ManagedRootBinding{}, err
		} else if !active {
			return gdrive.ManagedRootBinding{}, fmt.Errorf(
				"%w: managed root has no active provider-object lifetime segment",
				gdrive.ErrInvalidTopologyState,
			)
		}
	}

	binding := gdrive.ManagedRootBinding{
		GenerationID:        generationID,
		ManagedRootObjectID: managedRootObjectID,
		BoundSequence:       generation.CurrentSequence,
		CreatedAt:           createdAt.UTC(),
	}
	if err := gdrive.ValidateManagedRootBinding(binding); err != nil {
		return gdrive.ManagedRootBinding{}, err
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO gdrive_managed_root_bindings (generation_id, managed_root_object_id, bound_sequence, created_at) VALUES (?1,?2,?3,?4)",
		&sqlitex.ExecOptions{Args: []any{
			string(binding.GenerationID),
			string(binding.ManagedRootObjectID),
			int64(binding.BoundSequence),
			binding.CreatedAt.Format(time.RFC3339Nano),
		}}); err != nil {
		return gdrive.ManagedRootBinding{}, fmt.Errorf("insert Google managed-root binding: %w", err)
	}
	return binding, nil
}

func (s *Store) GoogleDriveManagedRootMembership(
	ctx context.Context,
	generationID remotehistory.HistoryGenerationID,
	expectedSequence remotehistory.HistoryPublicationSequence,
	managedRootObjectID corpus.ProviderObjectID,
	objectID corpus.ProviderObjectID,
) (gdrive.MembershipResult, error) {
	result := gdrive.MembershipResult{
		State:               gdrive.MembershipUnknown,
		GenerationID:        generationID,
		PublicationSequence: expectedSequence,
		ManagedRootObjectID: managedRootObjectID,
		ObjectID:            objectID,
	}
	if generationID == "" || expectedSequence == 0 || managedRootObjectID == "" || objectID == "" {
		return result, gdrive.ErrInvalidTopologyState
	}

	conn, err := s.pool.Get(ctx)
	if err != nil {
		return result, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)

	generation, err := remoteHistoryGenerationConn(conn, generationID)
	if err != nil {
		return result, err
	}
	if generation.Scope.ProviderID != gdrive.ProviderID {
		result.Reason = gdrive.UnknownScopeMismatch
		return result, nil
	}

	binding, found, err := googleManagedRootBindingConn(conn, generationID, managedRootObjectID)
	if err != nil {
		return result, err
	}
	if !found {
		return result, fmt.Errorf(
			"%w: generation=%s root=%s",
			ErrGoogleManagedRootBindingNotFound,
			generationID,
			managedRootObjectID,
		)
	}
	if binding.BoundSequence > expectedSequence {
		result.Reason = gdrive.UnknownTopologyStale
		return result, nil
	}
	if managedRootObjectID != corpus.ProviderObjectID(generation.Scope.Root) {
		segment, active, err := activeLifetimeSegmentConn(conn, generationID, managedRootObjectID)
		if err != nil {
			return result, err
		}
		if !active || segment.StartPublicationSequence > binding.BoundSequence {
			result.Reason = gdrive.UnknownLifetimeMismatch
			result.TerminalObjectID = managedRootObjectID
			return result, nil
		}
	}

	watermark, found, err := googleTopologyWatermarkConn(conn, generationID)
	if err != nil {
		return result, err
	}
	if !found ||
		generation.CurrentSequence != expectedSequence ||
		watermark != expectedSequence {
		result.Reason = gdrive.UnknownTopologyStale
		return result, nil
	}

	if managedRootObjectID != corpus.ProviderObjectID(generation.Scope.Root) {
		rootNode, found, err := googleTopologyNodeConn(conn, generationID, managedRootObjectID)
		if err != nil {
			return result, err
		}
		if !found || rootNode.Presence != gdrive.TopologyPresent {
			result.Reason = gdrive.UnknownObjectUnavailable
			result.TerminalObjectID = managedRootObjectID
			return result, nil
		}
		rootSegment, active, err := activeLifetimeSegmentConn(conn, generationID, managedRootObjectID)
		if err != nil {
			return result, err
		}
		if !active || !topologyNodeEvidenceCoversCurrentLifetime(rootNode, rootSegment) {
			result.Reason = gdrive.UnknownLifetimeMismatch
			result.TerminalObjectID = managedRootObjectID
			return result, nil
		}
	}
	if objectID == managedRootObjectID {
		result.State = gdrive.MembershipIn
		result.TerminalObjectID = managedRootObjectID
		return result, nil
	}
	if objectID == corpus.ProviderObjectID(generation.Scope.Root) {
		if managedRootObjectID == objectID {
			result.State = gdrive.MembershipIn
		} else {
			result.State = gdrive.MembershipOut
		}
		result.TerminalObjectID = objectID
		return result, nil
	}

	nodeCount, err := googleTopologyNodeCountConn(conn, generationID)
	if err != nil {
		return result, err
	}
	visited := make(map[corpus.ProviderObjectID]struct{}, int(nodeCount))
	current := objectID

	for steps := int64(0); steps <= nodeCount; steps++ {
		if current == managedRootObjectID {
			result.State = gdrive.MembershipIn
			result.TerminalObjectID = current
			return result, nil
		}
		if current == corpus.ProviderObjectID(generation.Scope.Root) {
			result.State = gdrive.MembershipOut
			result.TerminalObjectID = current
			return result, nil
		}
		if _, duplicate := visited[current]; duplicate {
			result.Reason = gdrive.UnknownCycle
			result.TerminalObjectID = current
			return result, nil
		}
		visited[current] = struct{}{}

		node, found, err := googleTopologyNodeConn(conn, generationID, current)
		if err != nil {
			return result, err
		}
		if !found {
			if current == objectID {
				result.Reason = gdrive.UnknownObjectUnavailable
			} else {
				result.Reason = gdrive.UnknownMissingParent
			}
			result.TerminalObjectID = current
			return result, nil
		}
		if node.LastPublicationSequence > expectedSequence {
			result.Reason = gdrive.UnknownTopologyStale
			result.TerminalObjectID = current
			return result, nil
		}
		if node.Presence != gdrive.TopologyPresent {
			if current == objectID {
				result.Reason = gdrive.UnknownObjectUnavailable
			} else {
				result.Reason = gdrive.UnknownMissingParent
			}
			result.TerminalObjectID = current
			return result, nil
		}
		currentSegment, active, err := activeLifetimeSegmentConn(conn, generationID, current)
		if err != nil {
			return result, err
		}
		if !active || !topologyNodeEvidenceCoversCurrentLifetime(node, currentSegment) {
			result.Reason = gdrive.UnknownLifetimeMismatch
			result.TerminalObjectID = current
			return result, nil
		}
		switch node.ParentKnowledge {
		case gdrive.ParentKnown:
			parentID := node.ParentObjectID
			if parentID != corpus.ProviderObjectID(generation.Scope.Root) {
				parentNode, found, err := googleTopologyNodeConn(conn, generationID, parentID)
				if err != nil {
					return result, err
				}
				if !found || parentNode.Presence != gdrive.TopologyPresent {
					result.Reason = gdrive.UnknownMissingParent
					result.TerminalObjectID = parentID
					return result, nil
				}
				parentSegment, active, err := activeLifetimeSegmentConn(conn, generationID, parentID)
				if err != nil {
					return result, err
				}
				if !active || !topologyEdgeEvidenceCoversParentLifetime(node, parentSegment) {
					result.Reason = gdrive.UnknownLifetimeMismatch
					result.TerminalObjectID = parentID
					return result, nil
				}
			}
			current = parentID
		case gdrive.ParentUnknown:
			result.Reason = gdrive.UnknownMissingParent
			result.TerminalObjectID = current
			return result, nil
		default:
			result.Reason = gdrive.UnknownMissingParent
			result.TerminalObjectID = current
			return result, nil
		}
	}

	result.Reason = gdrive.UnknownCycle
	result.TerminalObjectID = current
	return result, nil
}

func topologyNodeEvidenceCoversCurrentLifetime(
	node gdrive.TopologyNode,
	segment remotehistory.ProviderObjectLifetimeSegment,
) bool {
	return historyEvidencePositionAtOrAfterSegmentStart(
		node.LastPublicationSequence,
		node.LastChangeOrdinal,
		segment,
	)
}

func topologyEdgeEvidenceCoversParentLifetime(
	childNode gdrive.TopologyNode,
	parentSegment remotehistory.ProviderObjectLifetimeSegment,
) bool {
	return historyEvidencePositionAtOrAfterSegmentStart(
		childNode.LastPublicationSequence,
		childNode.LastChangeOrdinal,
		parentSegment,
	)
}

func historyEvidencePositionAtOrAfterSegmentStart(
	sequence remotehistory.HistoryPublicationSequence,
	ordinal *int64,
	segment remotehistory.ProviderObjectLifetimeSegment,
) bool {
	if sequence != segment.StartPublicationSequence {
		return sequence > segment.StartPublicationSequence
	}
	return ordinalValue(ordinal) >= ordinalValue(segment.StartChangeOrdinal)
}

func googleManagedRootBindingConn(
	conn *sqlite.Conn,
	generationID remotehistory.HistoryGenerationID,
	managedRootObjectID corpus.ProviderObjectID,
) (gdrive.ManagedRootBinding, bool, error) {
	var binding gdrive.ManagedRootBinding
	var createdText string
	var found bool
	err := sqlitex.Execute(conn,
		"SELECT bound_sequence,created_at FROM gdrive_managed_root_bindings WHERE generation_id=?1 AND managed_root_object_id=?2",
		&sqlitex.ExecOptions{
			Args: []any{string(generationID), string(managedRootObjectID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				found = true
				binding.GenerationID = generationID
				binding.ManagedRootObjectID = managedRootObjectID
				binding.BoundSequence = remotehistory.HistoryPublicationSequence(stmt.ColumnInt64(0))
				createdText = stmt.ColumnText(1)
				return nil
			},
		})
	if err != nil {
		return gdrive.ManagedRootBinding{}, false, fmt.Errorf("query Google managed-root binding: %w", err)
	}
	if !found {
		return gdrive.ManagedRootBinding{}, false, nil
	}
	binding.CreatedAt, err = time.Parse(time.RFC3339Nano, createdText)
	if err != nil {
		return gdrive.ManagedRootBinding{}, false, fmt.Errorf("parse Google managed-root binding time: %w", err)
	}
	if err := gdrive.ValidateManagedRootBinding(binding); err != nil {
		return gdrive.ManagedRootBinding{}, false, err
	}
	return binding, true, nil
}

func googleTopologyWatermarkConn(
	conn *sqlite.Conn,
	generationID remotehistory.HistoryGenerationID,
) (remotehistory.HistoryPublicationSequence, bool, error) {
	var sequence remotehistory.HistoryPublicationSequence
	var found bool
	err := sqlitex.Execute(conn,
		"SELECT publication_sequence FROM gdrive_topology_watermarks WHERE generation_id=?1",
		&sqlitex.ExecOptions{
			Args: []any{string(generationID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				found = true
				sequence = remotehistory.HistoryPublicationSequence(stmt.ColumnInt64(0))
				return nil
			},
		})
	if err != nil {
		return 0, false, fmt.Errorf("query Google topology watermark: %w", err)
	}
	return sequence, found, nil
}

func googleTopologyNodeConn(
	conn *sqlite.Conn,
	generationID remotehistory.HistoryGenerationID,
	objectID corpus.ProviderObjectID,
) (gdrive.TopologyNode, bool, error) {
	var node gdrive.TopologyNode
	var parentID string
	var found bool
	err := sqlitex.Execute(conn,
		"SELECT presence,parent_state,COALESCE(parent_id,''),drive_id,last_sequence,last_ordinal FROM gdrive_topology_nodes WHERE generation_id=?1 AND object_id=?2",
		&sqlitex.ExecOptions{
			Args: []any{string(generationID), string(objectID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				found = true
				node.GenerationID = generationID
				node.ObjectID = objectID
				node.Presence = gdrive.TopologyPresence(stmt.ColumnText(0))
				node.ParentKnowledge = gdrive.ParentKnowledge(stmt.ColumnText(1))
				parentID = stmt.ColumnText(2)
				node.DriveID = stmt.ColumnText(3)
				node.LastPublicationSequence = remotehistory.HistoryPublicationSequence(stmt.ColumnInt64(4))
				ordinal := stmt.ColumnInt64(5)
				if ordinal >= 0 {
					node.LastChangeOrdinal = &ordinal
				}
				return nil
			},
		})
	if err != nil {
		return gdrive.TopologyNode{}, false, fmt.Errorf("query Google topology node: %w", err)
	}
	if !found {
		return gdrive.TopologyNode{}, false, nil
	}
	node.ParentObjectID = corpus.ProviderObjectID(parentID)
	if err := gdrive.ValidateTopologyNode(node); err != nil {
		return gdrive.TopologyNode{}, false, err
	}
	return node, true, nil
}

func googleTopologyNodeCountConn(
	conn *sqlite.Conn,
	generationID remotehistory.HistoryGenerationID,
) (int64, error) {
	var count int64
	if err := sqlitex.Execute(conn,
		"SELECT COUNT(*) FROM gdrive_topology_nodes WHERE generation_id=?1",
		&sqlitex.ExecOptions{
			Args: []any{string(generationID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				count = stmt.ColumnInt64(0)
				return nil
			},
		}); err != nil {
		return 0, fmt.Errorf("count Google topology nodes: %w", err)
	}
	return count, nil
}
