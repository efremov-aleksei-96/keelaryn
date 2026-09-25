package sqlitestate

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/google/uuid"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

var (
	ErrInvalidObservation        = errors.New("invalid observation")
	ErrObservationNotFound       = errors.New("observation not found")
	ErrRevisionArtifactMismatch  = errors.New("revision does not belong to artifact")
)

func (s *Store) RecordObservation(ctx context.Context, input corpus.ObservationRecordInput) (out corpus.ObservationRecord, err error) {
	if err := validateObservationInput(input); err != nil {
		return corpus.ObservationRecord{}, err
	}

	conn, err := s.pool.Get(ctx)
	if err != nil {
		return corpus.ObservationRecord{}, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)

	end, err := sqlitex.ImmediateTransaction(conn)
	if err != nil {
		return corpus.ObservationRecord{}, fmt.Errorf("begin Observation transaction: %w", err)
	}
	defer end(&err)

	return recordObservationConn(conn, "", input)
}

func recordObservationConn(conn *sqlite.Conn, scanID corpus.ScanSessionID, input corpus.ObservationRecordInput) (corpus.ObservationRecord, error) {
	if input.AssignmentState == corpus.AssignmentAssigned {
		exists, err := artifactExists(conn, input.ArtifactID)
		if err != nil {
			return corpus.ObservationRecord{}, err
		}
		if !exists {
			return corpus.ObservationRecord{}, fmt.Errorf("%w: %s", corpus.ErrArtifactNotFound, input.ArtifactID)
		}
		if input.RevisionID != "" {
			matches, err := revisionBelongsToArtifact(conn, input.RevisionID, input.ArtifactID)
			if err != nil {
				return corpus.ObservationRecord{}, err
			}
			if !matches {
				return corpus.ObservationRecord{}, fmt.Errorf("%w: revision=%s artifact=%s", ErrRevisionArtifactMismatch, input.RevisionID, input.ArtifactID)
			}
		}
	}

	occurrenceID := corpus.ProviderObjectOccurrenceID("pobjocc_" + uuid.NewString())
	observationID := corpus.ObservationID("obs_" + uuid.NewString())

	var nativeID any
	if input.ProviderObject.ID != "" {
		nativeID = string(input.ProviderObject.ID)
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO provider_object_occurrences (occurrence_id, provider_id, native_object_id, identity_state) VALUES (?1, ?2, ?3, ?4)",
		&sqlitex.ExecOptions{Args: []any{
			string(occurrenceID),
			string(input.ProviderObject.ProviderID),
			nativeID,
			string(input.ProviderObject.IdentityState),
		}}); err != nil {
		return corpus.ObservationRecord{}, fmt.Errorf("insert ProviderObject occurrence: %w", err)
	}

	var artifactID any
	var revisionID any
	if input.ArtifactID != "" {
		artifactID = string(input.ArtifactID)
	}
	if input.RevisionID != "" {
		revisionID = string(input.RevisionID)
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO observations (observation_id, occurrence_id, artifact_id, revision_id, assignment_state, observed_at, kind, size, mode, modified_at, scan_id) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)",
		&sqlitex.ExecOptions{Args: []any{
			string(observationID),
			string(occurrenceID),
			artifactID,
			revisionID,
			string(input.AssignmentState),
			input.ObservedAt.UTC().Format(time.RFC3339Nano),
			string(input.Kind),
			input.Size,
			int64(input.Mode),
			input.ModifiedAt.UTC().Format(time.RFC3339Nano),
			nullableScanID(scanID),
		}}); err != nil {
		return corpus.ObservationRecord{}, fmt.Errorf("insert Observation: %w", err)
	}

	locators := make([]corpus.LocatorRecord, 0, len(input.Locators))
	for _, locator := range input.Locators {
		locatorID := corpus.LocatorID("loc_" + uuid.NewString())
		if err := sqlitex.Execute(conn,
			"INSERT INTO locators (locator_id, observation_id, provider_id, root, path) VALUES (?1, ?2, ?3, ?4, ?5)",
			&sqlitex.ExecOptions{Args: []any{
				string(locatorID),
				string(observationID),
				string(locator.ProviderID),
				locator.Root,
				locator.Path,
			}}); err != nil {
			return corpus.ObservationRecord{}, fmt.Errorf("insert Locator: %w", err)
		}
		locators = append(locators, corpus.LocatorRecord{
			ID:            locatorID,
			ObservationID: observationID,
			Locator:       locator,
		})
	}

	return corpus.ObservationRecord{
		ID:                         observationID,
		ProviderObjectOccurrenceID: occurrenceID,
		ProviderObject:             input.ProviderObject,
		Locators:                   locators,
		ArtifactID:                 input.ArtifactID,
		RevisionID:                 input.RevisionID,
		AssignmentState:            input.AssignmentState,
		ObservedAt:                 input.ObservedAt.UTC(),
		Kind:                       input.Kind,
		Size:                       input.Size,
		Mode:                       input.Mode,
		ModifiedAt:                 input.ModifiedAt.UTC(),
	}, nil
}

func (s *Store) Observation(ctx context.Context, observationID corpus.ObservationID) (corpus.ObservationRecord, error) {
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return corpus.ObservationRecord{}, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)

	var record corpus.ObservationRecord
	var found bool
	var observedAtText, modifiedAtText string
	err = sqlitex.Execute(conn,
		"SELECT o.occurrence_id, p.provider_id, COALESCE(p.native_object_id, ''), p.identity_state, COALESCE(o.artifact_id, ''), COALESCE(o.revision_id, ''), o.assignment_state, o.observed_at, o.kind, o.size, o.mode, o.modified_at FROM observations o JOIN provider_object_occurrences p ON p.occurrence_id = o.occurrence_id WHERE o.observation_id = ?1",
		&sqlitex.ExecOptions{
			Args: []any{string(observationID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				found = true
				record.ID = observationID
				record.ProviderObjectOccurrenceID = corpus.ProviderObjectOccurrenceID(stmt.ColumnText(0))
				record.ProviderObject = corpus.ProviderObject{
					ProviderID:    corpus.ProviderID(stmt.ColumnText(1)),
					ID:            corpus.ProviderObjectID(stmt.ColumnText(2)),
					IdentityState: corpus.ObjectIdentityState(stmt.ColumnText(3)),
				}
				record.ArtifactID = corpus.ArtifactID(stmt.ColumnText(4))
				record.RevisionID = corpus.RevisionID(stmt.ColumnText(5))
				record.AssignmentState = corpus.AssignmentState(stmt.ColumnText(6))
				observedAtText = stmt.ColumnText(7)
				record.Kind = corpus.EntryKind(stmt.ColumnText(8))
				record.Size = stmt.ColumnInt64(9)
				record.Mode = uint32(stmt.ColumnInt64(10))
				modifiedAtText = stmt.ColumnText(11)
				return nil
			},
		})
	if err != nil {
		return corpus.ObservationRecord{}, fmt.Errorf("query Observation: %w", err)
	}
	if !found {
		return corpus.ObservationRecord{}, fmt.Errorf("%w: %s", ErrObservationNotFound, observationID)
	}

	record.ObservedAt, err = time.Parse(time.RFC3339Nano, observedAtText)
	if err != nil {
		return corpus.ObservationRecord{}, fmt.Errorf("parse Observation time: %w", err)
	}
	record.ModifiedAt, err = time.Parse(time.RFC3339Nano, modifiedAtText)
	if err != nil {
		return corpus.ObservationRecord{}, fmt.Errorf("parse modified time: %w", err)
	}

	err = sqlitex.Execute(conn,
		"SELECT locator_id, provider_id, root, path FROM locators WHERE observation_id = ?1 ORDER BY root, path, locator_id",
		&sqlitex.ExecOptions{
			Args: []any{string(observationID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				record.Locators = append(record.Locators, corpus.LocatorRecord{
					ID:            corpus.LocatorID(stmt.ColumnText(0)),
					ObservationID: observationID,
					Locator: corpus.Locator{
						ProviderID: corpus.ProviderID(stmt.ColumnText(1)),
						Root:       stmt.ColumnText(2),
						Path:       stmt.ColumnText(3),
					},
				})
				return nil
			},
		})
	if err != nil {
		return corpus.ObservationRecord{}, fmt.Errorf("query Locators: %w", err)
	}
	return record, nil
}

func validateObservationInput(input corpus.ObservationRecordInput) error {
	if input.ProviderObject.ProviderID == "" {
		return fmt.Errorf("%w: empty provider ID", ErrInvalidObservation)
	}
	switch input.ProviderObject.IdentityState {
	case corpus.ObjectIdentityUnresolved:
		if input.ProviderObject.ID != "" {
			return fmt.Errorf("%w: unresolved provider object has native ID", ErrInvalidObservation)
		}
	case corpus.ObjectIdentityObserved:
		if input.ProviderObject.ID == "" {
			return fmt.Errorf("%w: observed provider object lacks native ID", ErrInvalidObservation)
		}
	default:
		return fmt.Errorf("%w: invalid provider identity state %q", ErrInvalidObservation, input.ProviderObject.IdentityState)
	}
	if len(input.Locators) == 0 {
		return fmt.Errorf("%w: no locators", ErrInvalidObservation)
	}
	for _, locator := range input.Locators {
		if locator.ProviderID != input.ProviderObject.ProviderID || locator.Root == "" || locator.Path == "" {
			return fmt.Errorf("%w: invalid locator %#v", ErrInvalidObservation, locator)
		}
	}
	switch input.AssignmentState {
	case corpus.AssignmentAssigned:
		if input.ArtifactID == "" {
			return fmt.Errorf("%w: assigned observation has no Artifact", ErrInvalidObservation)
		}
	case corpus.AssignmentUnresolved:
		if input.ArtifactID != "" || input.RevisionID != "" {
			return fmt.Errorf("%w: unresolved observation contains assigned identity", ErrInvalidObservation)
		}
	default:
		return fmt.Errorf("%w: invalid assignment state %q", ErrInvalidObservation, input.AssignmentState)
	}
	if input.RevisionID != "" && input.ArtifactID == "" {
		return fmt.Errorf("%w: Revision without Artifact", ErrInvalidObservation)
	}
	switch input.Kind {
	case corpus.EntryRegularFile, corpus.EntrySymlink, corpus.EntryOther:
	default:
		return fmt.Errorf("%w: invalid entry kind %q", ErrInvalidObservation, input.Kind)
	}
	if input.Size < 0 || input.ObservedAt.IsZero() {
		return fmt.Errorf("%w: invalid size/time", ErrInvalidObservation)
	}
	return nil
}

func revisionBelongsToArtifact(conn *sqlite.Conn, revisionID corpus.RevisionID, artifactID corpus.ArtifactID) (bool, error) {
	var matches bool
	err := sqlitex.Execute(conn,
		"SELECT 1 FROM revisions WHERE revision_id = ?1 AND artifact_id = ?2 LIMIT 1",
		&sqlitex.ExecOptions{
			Args: []any{string(revisionID), string(artifactID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				matches = true
				return nil
			},
		})
	if err != nil {
		return false, fmt.Errorf("query Revision ownership: %w", err)
	}
	return matches, nil
}


func nullableScanID(scanID corpus.ScanSessionID) any {
	if scanID == "" {
		return nil
	}
	return string(scanID)
}
