package sqlitestate

import (
	"context"
	"errors"
	"fmt"

	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory/gdrive"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

var ErrGoogleDriveTopologyVerification = errors.New("Google Drive topology projection verification failed")

func (s *Store) VerifyGoogleDriveTopologyProjection(
	ctx context.Context,
	generationID remotehistory.HistoryGenerationID,
	expectedSequence remotehistory.HistoryPublicationSequence,
) error {
	if generationID == "" || expectedSequence == 0 {
		return fmt.Errorf("%w: invalid expected generation/sequence", ErrGoogleDriveTopologyVerification)
	}

	conn, err := s.pool.Get(ctx)
	if err != nil {
		return fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)

	generation, err := remoteHistoryGenerationConn(conn, generationID)
	if err != nil {
		return err
	}
	if generation.Scope.ProviderID != gdrive.ProviderID {
		return fmt.Errorf("%w: provider=%s", ErrGoogleDriveTopologyVerification, generation.Scope.ProviderID)
	}
	if generation.CurrentSequence != expectedSequence {
		return fmt.Errorf(
			"%w: generation sequence=%d expected=%d",
			ErrGoogleDriveTopologyVerification,
			generation.CurrentSequence,
			expectedSequence,
		)
	}

	watermark, found, err := googleTopologyWatermarkConn(conn, generationID)
	if err != nil {
		return err
	}
	if !found || watermark != expectedSequence {
		return fmt.Errorf(
			"%w: topology watermark found=%v sequence=%d expected=%d",
			ErrGoogleDriveTopologyVerification,
			found,
			watermark,
			expectedSequence,
		)
	}

	var missingBootstrapEvidence int64
	if err := sqlitex.Execute(conn, `
SELECT COUNT(*)
FROM remote_history_bootstrap_membership b
WHERE b.generation_id=?1
  AND NOT EXISTS (
    SELECT 1
    FROM gdrive_topology_evidence e
    WHERE e.generation_id=b.generation_id
      AND e.sequence=1
      AND e.ordinal=-1
      AND e.object_id=b.object_id
      AND e.evidence_kind='BOOTSTRAP'
  )`,
		&sqlitex.ExecOptions{
			Args: []any{string(generationID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				missingBootstrapEvidence = stmt.ColumnInt64(0)
				return nil
			},
		}); err != nil {
		return fmt.Errorf("verify Google bootstrap topology coverage: %w", err)
	}
	if missingBootstrapEvidence != 0 {
		return fmt.Errorf(
			"%w: missing bootstrap topology evidence=%d",
			ErrGoogleDriveTopologyVerification,
			missingBootstrapEvidence,
		)
	}

	var missingChangeEvidence int64
	if err := sqlitex.Execute(conn, `
SELECT COUNT(*)
FROM remote_history_publication_changes c
WHERE c.generation_id=?1
  AND c.sequence<=?2
  AND NOT EXISTS (
    SELECT 1
    FROM gdrive_topology_evidence e
    WHERE e.generation_id=c.generation_id
      AND e.sequence=c.sequence
      AND e.ordinal=c.ordinal
      AND e.object_id=c.object_id
      AND (
        (c.kind='UPSERT' AND e.evidence_kind='UPSERT')
        OR
        (c.kind='REMOVED' AND e.evidence_kind='REMOVED')
      )
  )`,
		&sqlitex.ExecOptions{
			Args: []any{string(generationID), int64(expectedSequence)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				missingChangeEvidence = stmt.ColumnInt64(0)
				return nil
			},
		}); err != nil {
		return fmt.Errorf("verify Google incremental topology coverage: %w", err)
	}
	if missingChangeEvidence != 0 {
		return fmt.Errorf(
			"%w: missing change topology evidence=%d",
			ErrGoogleDriveTopologyVerification,
			missingChangeEvidence,
		)
	}

	var latestEvidenceMismatch int64
	if err := sqlitex.Execute(conn, `
WITH latest AS (
  SELECT e.*
  FROM gdrive_topology_evidence e
  WHERE e.generation_id=?1
    AND e.sequence<=?2
    AND NOT EXISTS (
      SELECT 1
      FROM gdrive_topology_evidence newer
      WHERE newer.generation_id=e.generation_id
        AND newer.object_id=e.object_id
        AND newer.sequence<=?2
        AND (
          newer.sequence>e.sequence
          OR (newer.sequence=e.sequence AND newer.ordinal>e.ordinal)
        )
    )
)
SELECT COUNT(*)
FROM latest e
LEFT JOIN gdrive_topology_nodes n
  ON n.generation_id=e.generation_id
 AND n.object_id=e.object_id
WHERE n.object_id IS NULL
   OR n.presence<>e.presence
   OR n.parent_state<>e.parent_state
   OR NOT (n.parent_id IS e.parent_id)
   OR n.drive_id<>e.drive_id
   OR n.last_sequence<>e.sequence
   OR n.last_ordinal<>e.ordinal`,
		&sqlitex.ExecOptions{
			Args: []any{string(generationID), int64(expectedSequence)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				latestEvidenceMismatch = stmt.ColumnInt64(0)
				return nil
			},
		}); err != nil {
		return fmt.Errorf("verify Google topology latest evidence projection: %w", err)
	}
	if latestEvidenceMismatch != 0 {
		return fmt.Errorf(
			"%w: latest evidence/node mismatch=%d",
			ErrGoogleDriveTopologyVerification,
			latestEvidenceMismatch,
		)
	}

	var extraOrStaleNodes int64
	if err := sqlitex.Execute(conn, `
SELECT COUNT(*)
FROM gdrive_topology_nodes n
WHERE n.generation_id=?1
  AND (
    n.last_sequence>?2
    OR NOT EXISTS (
      SELECT 1
      FROM gdrive_topology_evidence e
      WHERE e.generation_id=n.generation_id
        AND e.object_id=n.object_id
        AND e.sequence=n.last_sequence
        AND e.ordinal=n.last_ordinal
        AND e.presence=n.presence
        AND e.parent_state=n.parent_state
        AND e.parent_id IS n.parent_id
        AND e.drive_id=n.drive_id
    )
    OR EXISTS (
      SELECT 1
      FROM gdrive_topology_evidence newer
      WHERE newer.generation_id=n.generation_id
        AND newer.object_id=n.object_id
        AND newer.sequence<=?2
        AND (
          newer.sequence>n.last_sequence
          OR (newer.sequence=n.last_sequence AND newer.ordinal>n.last_ordinal)
        )
    )
  )`,
		&sqlitex.ExecOptions{
			Args: []any{string(generationID), int64(expectedSequence)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				extraOrStaleNodes = stmt.ColumnInt64(0)
				return nil
			},
		}); err != nil {
		return fmt.Errorf("verify Google topology node projection: %w", err)
	}
	if extraOrStaleNodes != 0 {
		return fmt.Errorf(
			"%w: stale/extra topology nodes=%d",
			ErrGoogleDriveTopologyVerification,
			extraOrStaleNodes,
		)
	}

	return nil
}
