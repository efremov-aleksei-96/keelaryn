package sqlitestate

import (
	"context"
	"errors"
	"fmt"
	"reflect"
	"sort"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

var (
	ErrLifetimeSegmentNotFound       = errors.New("provider object lifetime segment not found")
	ErrLifetimeSegmentProjectionDrift = errors.New("provider object lifetime segment projection drift")
)

func insertBootstrapLifetimeSegmentConn(conn *sqlite.Conn, generationID remotehistory.HistoryGenerationID, objectID corpus.ProviderObjectID) error {
	segmentID, err := remotehistory.ProviderLifetimeSegmentID(
		generationID, objectID, remotehistory.LifetimeSegmentStartBootstrap, 1, nil,
	)
	if err != nil {
		return err
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO provider_object_lifetime_segments (lifetime_segment_id, generation_id, object_id, start_kind, start_sequence, start_ordinal, last_present_sequence, last_present_ordinal, status, end_sequence, end_ordinal, closure_reason) VALUES (?1, ?2, ?3, 'BOOTSTRAP', 1, NULL, 1, NULL, 'ACTIVE', NULL, NULL, NULL)",
		&sqlitex.ExecOptions{Args: []any{string(segmentID), string(generationID), string(objectID)}}); err != nil {
		return fmt.Errorf("insert bootstrap lifetime segment: %w", err)
	}
	return nil
}

func applyLifetimeChangeConn(
	conn *sqlite.Conn,
	generationID remotehistory.HistoryGenerationID,
	sequence remotehistory.HistoryPublicationSequence,
	ordinal int64,
	change remotehistory.RemoteChange,
) error {
	active, found, err := activeLifetimeSegmentConn(conn, generationID, change.ObjectID)
	if err != nil {
		return err
	}
	switch change.Kind {
	case remotehistory.ChangeUpsert:
		if found {
			if err := sqlitex.Execute(conn,
				"UPDATE provider_object_lifetime_segments SET last_present_sequence=?1, last_present_ordinal=?2 WHERE lifetime_segment_id=?3 AND status='ACTIVE'",
				&sqlitex.ExecOptions{Args: []any{int64(sequence), ordinal, string(active.ID)}}); err != nil {
				return fmt.Errorf("continue lifetime segment: %w", err)
			}
			if conn.Changes() != 1 {
				return ErrLifetimeSegmentProjectionDrift
			}
			return nil
		}
		startOrdinal := ordinal
		segmentID, err := remotehistory.ProviderLifetimeSegmentID(
			generationID, change.ObjectID, remotehistory.LifetimeSegmentStartUpsert, sequence, &startOrdinal,
		)
		if err != nil {
			return err
		}
		if err := sqlitex.Execute(conn,
			"INSERT INTO provider_object_lifetime_segments (lifetime_segment_id, generation_id, object_id, start_kind, start_sequence, start_ordinal, last_present_sequence, last_present_ordinal, status, end_sequence, end_ordinal, closure_reason) VALUES (?1, ?2, ?3, 'UPSERT', ?4, ?5, ?4, ?5, 'ACTIVE', NULL, NULL, NULL)",
			&sqlitex.ExecOptions{Args: []any{
				string(segmentID), string(generationID), string(change.ObjectID), int64(sequence), ordinal,
			}}); err != nil {
			return fmt.Errorf("insert UPSERT lifetime segment: %w", err)
		}
		return nil

	case remotehistory.ChangeRemoved:
		if !found {
			return nil
		}
		if err := sqlitex.Execute(conn,
			"UPDATE provider_object_lifetime_segments SET status='CLOSED', end_sequence=?1, end_ordinal=?2, closure_reason='REMOVED_FROM_SCOPE' WHERE lifetime_segment_id=?3 AND status='ACTIVE'",
			&sqlitex.ExecOptions{Args: []any{int64(sequence), ordinal, string(active.ID)}}); err != nil {
			return fmt.Errorf("close lifetime segment on REMOVED: %w", err)
		}
		if conn.Changes() != 1 {
			return ErrLifetimeSegmentProjectionDrift
		}
		return nil

	default:
		return remotehistory.ErrInvalidHistoryPublication
	}
}

func closeLifetimeSegmentsForGenerationConn(
	conn *sqlite.Conn,
	generationID remotehistory.HistoryGenerationID,
	endSequence remotehistory.HistoryPublicationSequence,
) error {
	if err := sqlitex.Execute(conn,
		"UPDATE provider_object_lifetime_segments SET status='CLOSED', end_sequence=?1, end_ordinal=NULL, closure_reason='HISTORY_GENERATION_CLOSED' WHERE generation_id=?2 AND status='ACTIVE'",
		&sqlitex.ExecOptions{Args: []any{int64(endSequence), string(generationID)}}); err != nil {
		return fmt.Errorf("close generation lifetime segments: %w", err)
	}
	return nil
}

func (s *Store) RemoteHistoryLifetimeSegments(
	ctx context.Context,
	generationID remotehistory.HistoryGenerationID,
) ([]remotehistory.ProviderObjectLifetimeSegment, error) {
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return nil, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)
	if _, err := remoteHistoryGenerationConn(conn, generationID); err != nil {
		return nil, err
	}
	return lifetimeSegmentsConn(conn, generationID)
}

func (s *Store) VerifyRemoteHistoryLifetimeSegments(
	ctx context.Context,
	generationID remotehistory.HistoryGenerationID,
) error {
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)

	actual, err := lifetimeSegmentsConn(conn, generationID)
	if err != nil {
		return err
	}
	expected, err := deriveLifetimeSegmentsConn(conn, generationID)
	if err != nil {
		return err
	}
	if !reflect.DeepEqual(actual, expected) {
		return fmt.Errorf("%w: generation=%s actual=%#v expected=%#v", ErrLifetimeSegmentProjectionDrift, generationID, actual, expected)
	}
	return nil
}

func activeLifetimeSegmentConn(
	conn *sqlite.Conn,
	generationID remotehistory.HistoryGenerationID,
	objectID corpus.ProviderObjectID,
) (remotehistory.ProviderObjectLifetimeSegment, bool, error) {
	var segment remotehistory.ProviderObjectLifetimeSegment
	var found bool
	err := sqlitex.Execute(conn,
		"SELECT lifetime_segment_id, start_kind, start_sequence, start_ordinal, last_present_sequence, last_present_ordinal FROM provider_object_lifetime_segments WHERE generation_id=?1 AND object_id=?2 AND status='ACTIVE' LIMIT 1",
		&sqlitex.ExecOptions{
			Args: []any{string(generationID), string(objectID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				found = true
				segment.ID = remotehistory.ProviderObjectLifetimeSegmentID(stmt.ColumnText(0))
				segment.GenerationID = generationID
				segment.ProviderObjectID = objectID
				segment.StartKind = remotehistory.LifetimeSegmentStartKind(stmt.ColumnText(1))
				segment.StartPublicationSequence = remotehistory.HistoryPublicationSequence(stmt.ColumnInt64(2))
				segment.StartChangeOrdinal = nullableInt64Column(stmt, 3)
				segment.LastPresentPublicationSequence = remotehistory.HistoryPublicationSequence(stmt.ColumnInt64(4))
				segment.LastPresentChangeOrdinal = nullableInt64Column(stmt, 5)
				segment.Status = remotehistory.LifetimeSegmentActive
				return nil
			},
		})
	if err != nil {
		return remotehistory.ProviderObjectLifetimeSegment{}, false, fmt.Errorf("query active lifetime segment: %w", err)
	}
	if found {
		if err := remotehistory.ValidateProviderObjectLifetimeSegment(segment); err != nil {
			return remotehistory.ProviderObjectLifetimeSegment{}, false, fmt.Errorf("validate active lifetime segment: %w", err)
		}
	}
	return segment, found, nil
}

func lifetimeSegmentsConn(
	conn *sqlite.Conn,
	generationID remotehistory.HistoryGenerationID,
) ([]remotehistory.ProviderObjectLifetimeSegment, error) {
	var out []remotehistory.ProviderObjectLifetimeSegment
	err := sqlitex.Execute(conn,
		"SELECT lifetime_segment_id, object_id, start_kind, start_sequence, start_ordinal, last_present_sequence, last_present_ordinal, status, end_sequence, end_ordinal, COALESCE(closure_reason,'') FROM provider_object_lifetime_segments WHERE generation_id=?1 ORDER BY object_id, start_sequence, COALESCE(start_ordinal,-1), lifetime_segment_id",
		&sqlitex.ExecOptions{
			Args: []any{string(generationID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				segment := remotehistory.ProviderObjectLifetimeSegment{
					ID:                     remotehistory.ProviderObjectLifetimeSegmentID(stmt.ColumnText(0)),
					GenerationID:           generationID,
					ProviderObjectID:       corpus.ProviderObjectID(stmt.ColumnText(1)),
					StartKind:              remotehistory.LifetimeSegmentStartKind(stmt.ColumnText(2)),
					StartPublicationSequence: remotehistory.HistoryPublicationSequence(stmt.ColumnInt64(3)),
					StartChangeOrdinal:     nullableInt64Column(stmt, 4),
					LastPresentPublicationSequence: remotehistory.HistoryPublicationSequence(stmt.ColumnInt64(5)),
					LastPresentChangeOrdinal: nullableInt64Column(stmt, 6),
					Status:                 remotehistory.LifetimeSegmentStatus(stmt.ColumnText(7)),
					EndChangeOrdinal:       nullableInt64Column(stmt, 9),
					ClosureReason:          remotehistory.LifetimeSegmentClosureReason(stmt.ColumnText(10)),
				}
				if !stmt.ColumnIsNull(8) {
					value := remotehistory.HistoryPublicationSequence(stmt.ColumnInt64(8))
					segment.EndPublicationSequence = &value
				}
				if err := remotehistory.ValidateProviderObjectLifetimeSegment(segment); err != nil {
					return err
				}
				out = append(out, segment)
				return nil
			},
		})
	if err != nil {
		return nil, fmt.Errorf("query lifetime segments: %w", err)
	}
	return out, nil
}

func deriveLifetimeSegmentsConn(
	conn *sqlite.Conn,
	generationID remotehistory.HistoryGenerationID,
) ([]remotehistory.ProviderObjectLifetimeSegment, error) {
	generation, err := remoteHistoryGenerationConn(conn, generationID)
	if err != nil {
		return nil, err
	}

	var segments []remotehistory.ProviderObjectLifetimeSegment
	active := make(map[corpus.ProviderObjectID]int)

	err = sqlitex.Execute(conn,
		"SELECT object_id FROM remote_history_bootstrap_membership WHERE generation_id=?1 ORDER BY object_id",
		&sqlitex.ExecOptions{
			Args: []any{string(generationID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				objectID := corpus.ProviderObjectID(stmt.ColumnText(0))
				id, err := remotehistory.ProviderLifetimeSegmentID(
					generationID, objectID, remotehistory.LifetimeSegmentStartBootstrap, 1, nil,
				)
				if err != nil {
					return err
				}
				active[objectID] = len(segments)
				segments = append(segments, remotehistory.ProviderObjectLifetimeSegment{
					ID: id, GenerationID: generationID, ProviderObjectID: objectID,
					StartKind: remotehistory.LifetimeSegmentStartBootstrap,
					StartPublicationSequence: 1,
					LastPresentPublicationSequence: 1,
					Status: remotehistory.LifetimeSegmentActive,
				})
				return nil
			},
		})
	if err != nil {
		return nil, fmt.Errorf("derive bootstrap lifetime segments: %w", err)
	}

	err = sqlitex.Execute(conn,
		"SELECT sequence, ordinal, kind, object_id FROM remote_history_publication_changes WHERE generation_id=?1 ORDER BY sequence, ordinal",
		&sqlitex.ExecOptions{
			Args: []any{string(generationID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				sequence := remotehistory.HistoryPublicationSequence(stmt.ColumnInt64(0))
				ordinal := stmt.ColumnInt64(1)
				kind := remotehistory.ChangeKind(stmt.ColumnText(2))
				objectID := corpus.ProviderObjectID(stmt.ColumnText(3))
				index, present := active[objectID]
				switch kind {
				case remotehistory.ChangeUpsert:
					if present {
						value := ordinal
						segments[index].LastPresentPublicationSequence = sequence
						segments[index].LastPresentChangeOrdinal = &value
						return nil
					}
					value := ordinal
					id, err := remotehistory.ProviderLifetimeSegmentID(
						generationID, objectID, remotehistory.LifetimeSegmentStartUpsert, sequence, &value,
					)
					if err != nil {
						return err
					}
					active[objectID] = len(segments)
					segments = append(segments, remotehistory.ProviderObjectLifetimeSegment{
						ID: id, GenerationID: generationID, ProviderObjectID: objectID,
						StartKind: remotehistory.LifetimeSegmentStartUpsert,
						StartPublicationSequence: sequence, StartChangeOrdinal: int64Ptr(value),
						LastPresentPublicationSequence: sequence, LastPresentChangeOrdinal: int64Ptr(value),
						Status: remotehistory.LifetimeSegmentActive,
					})
				case remotehistory.ChangeRemoved:
					if !present {
						return nil
					}
					endSequence := sequence
					endOrdinal := ordinal
					segments[index].Status = remotehistory.LifetimeSegmentClosed
					segments[index].EndPublicationSequence = &endSequence
					segments[index].EndChangeOrdinal = &endOrdinal
					segments[index].ClosureReason = remotehistory.LifetimeSegmentClosedRemovedFromScope
					delete(active, objectID)
				default:
					return remotehistory.ErrInvalidHistoryPublication
				}
				return nil
			},
		})
	if err != nil {
		return nil, fmt.Errorf("derive incremental lifetime segments: %w", err)
	}

	if generation.Status == remotehistory.HistoryGenerationClosed {
		for objectID, index := range active {
			endSequence := generation.CurrentSequence
			segments[index].Status = remotehistory.LifetimeSegmentClosed
			segments[index].EndPublicationSequence = &endSequence
			segments[index].EndChangeOrdinal = nil
			segments[index].ClosureReason = remotehistory.LifetimeSegmentClosedHistoryGeneration
			delete(active, objectID)
		}
	}

	for _, segment := range segments {
		if err := remotehistory.ValidateProviderObjectLifetimeSegment(segment); err != nil {
			return nil, fmt.Errorf("validate derived lifetime segment: %w", err)
		}
	}
	sort.Slice(segments, func(i, j int) bool {
		if segments[i].ProviderObjectID != segments[j].ProviderObjectID {
			return segments[i].ProviderObjectID < segments[j].ProviderObjectID
		}
		if segments[i].StartPublicationSequence != segments[j].StartPublicationSequence {
			return segments[i].StartPublicationSequence < segments[j].StartPublicationSequence
		}
		return ordinalValue(segments[i].StartChangeOrdinal) < ordinalValue(segments[j].StartChangeOrdinal)
	})
	return segments, nil
}

func nullableInt64Column(stmt *sqlite.Stmt, column int) *int64 {
	if stmt.ColumnIsNull(column) {
		return nil
	}
	value := stmt.ColumnInt64(column)
	return &value
}

func int64Ptr(value int64) *int64 {
	copy := value
	return &copy
}

func ordinalValue(value *int64) int64 {
	if value == nil {
		return -1
	}
	return *value
}
