package sqlitestate

import (
	"context"
	"fmt"
	"path/filepath"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/google/uuid"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

const applicationID int32 = 0x4b4c5259 // "KLRY"

var schema = sqlitemigration.Schema{
	AppID: applicationID,
	Migrations: []string{
		`
CREATE TABLE artifacts (
	artifact_id TEXT PRIMARY KEY NOT NULL
) STRICT;

CREATE TABLE revisions (
	revision_id TEXT PRIMARY KEY NOT NULL,
	artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id) ON DELETE RESTRICT,
	sequence INTEGER NOT NULL CHECK (sequence >= 1),
	content_algorithm TEXT NOT NULL,
	content_digest TEXT NOT NULL,
	content_size INTEGER NOT NULL CHECK (content_size >= 0),
	UNIQUE (artifact_id, sequence)
) STRICT;

CREATE INDEX revisions_artifact_sequence
	ON revisions (artifact_id, sequence);
`,
		`
CREATE UNIQUE INDEX revisions_identity_artifact
	ON revisions (revision_id, artifact_id);

CREATE TABLE provider_object_occurrences (
	occurrence_id TEXT PRIMARY KEY NOT NULL,
	provider_id TEXT NOT NULL,
	native_object_id TEXT,
	identity_state TEXT NOT NULL
		CHECK (identity_state IN ('UNRESOLVED', 'OBSERVED')),
	CHECK (
		(identity_state = 'UNRESOLVED' AND native_object_id IS NULL)
		OR
		(identity_state = 'OBSERVED' AND native_object_id IS NOT NULL)
	)
) STRICT;

CREATE TABLE observations (
	observation_id TEXT PRIMARY KEY NOT NULL,
	occurrence_id TEXT NOT NULL
		REFERENCES provider_object_occurrences(occurrence_id) ON DELETE RESTRICT,
	artifact_id TEXT REFERENCES artifacts(artifact_id) ON DELETE RESTRICT,
	revision_id TEXT,
	assignment_state TEXT NOT NULL
		CHECK (assignment_state IN ('ASSIGNED', 'UNRESOLVED')),
	observed_at TEXT NOT NULL,
	kind TEXT NOT NULL
		CHECK (kind IN ('REGULAR_FILE', 'SYMLINK', 'OTHER')),
	size INTEGER NOT NULL CHECK (size >= 0),
	mode INTEGER NOT NULL CHECK (mode >= 0),
	modified_at TEXT NOT NULL,
	CHECK (
		(assignment_state = 'ASSIGNED' AND artifact_id IS NOT NULL)
		OR
		(assignment_state = 'UNRESOLVED' AND artifact_id IS NULL AND revision_id IS NULL)
	),
	CHECK (revision_id IS NULL OR artifact_id IS NOT NULL),
	FOREIGN KEY (revision_id, artifact_id)
		REFERENCES revisions(revision_id, artifact_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE locators (
	locator_id TEXT PRIMARY KEY NOT NULL,
	observation_id TEXT NOT NULL
		REFERENCES observations(observation_id) ON DELETE RESTRICT,
	provider_id TEXT NOT NULL,
	root TEXT NOT NULL,
	path TEXT NOT NULL,
	UNIQUE (observation_id, provider_id, root, path)
) STRICT;

CREATE INDEX observations_occurrence
	ON observations (occurrence_id);
CREATE INDEX observations_artifact
	ON observations (artifact_id);
CREATE INDEX locators_observation
	ON locators (observation_id);
`,
	},
}

// Store owns durable, non-rebuildable Keelaryn identity state.
//
// The path is runtime-local control state. This package does not know or store
// corpus file bytes, Locators, extracted text, previews, embeddings, or search
// indexes.
type Store struct {
	pool *sqlitemigration.Pool
	path string
}

func Open(ctx context.Context, path string) (*Store, error) {
	absPath, err := filepath.Abs(path)
	if err != nil {
		return nil, fmt.Errorf("resolve state database path: %w", err)
	}

	pool := sqlitemigration.NewPool(absPath, schema, sqlitemigration.Options{
		Flags:    sqlite.OpenReadWrite | sqlite.OpenCreate,
		PoolSize: 1,
		PrepareConn: func(conn *sqlite.Conn) error {
			return sqlitex.ExecuteTransient(conn, "PRAGMA foreign_keys = ON", nil)
		},
	})

	conn, err := pool.Get(ctx)
	if err != nil {
		_ = pool.Close()
		return nil, fmt.Errorf("open Keelaryn state store: %w", err)
	}
	pool.Put(conn)

	return &Store{pool: pool, path: absPath}, nil
}

func (s *Store) Close() error {
	if s == nil || s.pool == nil {
		return nil
	}
	return s.pool.Close()
}

func (s *Store) Path() string {
	if s == nil {
		return ""
	}
	return s.path
}

func (s *Store) AdoptArtifact(ctx context.Context) (corpus.Artifact, error) {
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return corpus.Artifact{}, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)

	artifact := corpus.Artifact{ID: corpus.ArtifactID("art_" + uuid.NewString())}
	err = sqlitex.Execute(conn,
		"INSERT INTO artifacts (artifact_id) VALUES (?1)",
		&sqlitex.ExecOptions{Args: []any{string(artifact.ID)}})
	if err != nil {
		return corpus.Artifact{}, fmt.Errorf("insert Artifact: %w", err)
	}
	return artifact, nil
}

func (s *Store) ArtifactExists(ctx context.Context, artifactID corpus.ArtifactID) (bool, error) {
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return false, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)
	return artifactExists(conn, artifactID)
}

func artifactExists(conn *sqlite.Conn, artifactID corpus.ArtifactID) (bool, error) {
	var exists bool
	err := sqlitex.Execute(conn,
		"SELECT 1 FROM artifacts WHERE artifact_id = ?1 LIMIT 1",
		&sqlitex.ExecOptions{
			Args: []any{string(artifactID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				exists = true
				return nil
			},
		})
	if err != nil {
		return false, fmt.Errorf("query Artifact: %w", err)
	}
	return exists, nil
}

func (s *Store) ObserveRevision(ctx context.Context, artifactID corpus.ArtifactID, evidence corpus.ContentEvidence) (out corpus.RevisionObservation, err error) {
	if err := corpus.ValidateContentEvidence(evidence); err != nil {
		return corpus.RevisionObservation{}, err
	}

	conn, err := s.pool.Get(ctx)
	if err != nil {
		return corpus.RevisionObservation{}, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)

	end, err := sqlitex.ImmediateTransaction(conn)
	if err != nil {
		return corpus.RevisionObservation{}, fmt.Errorf("begin Revision transaction: %w", err)
	}
	defer end(&err)

	exists, err := artifactExists(conn, artifactID)
	if err != nil {
		return corpus.RevisionObservation{}, err
	}
	if !exists {
		return corpus.RevisionObservation{}, fmt.Errorf("%w: %s", corpus.ErrArtifactNotFound, artifactID)
	}

	current, hasCurrent, err := currentRevision(conn, artifactID)
	if err != nil {
		return corpus.RevisionObservation{}, err
	}
	if hasCurrent {
		if current.Evidence.Algorithm != evidence.Algorithm {
			return corpus.RevisionObservation{}, fmt.Errorf(
				"%w: current=%s observed=%s",
				corpus.ErrContentEvidenceNotComparable,
				current.Evidence.Algorithm,
				evidence.Algorithm,
			)
		}
		if current.Evidence.Digest == evidence.Digest && current.Evidence.Size == evidence.Size {
			return corpus.RevisionObservation{Current: current, Created: false}, nil
		}
	}

	sequence := uint64(1)
	if hasCurrent {
		sequence = current.Sequence + 1
	}
	record := corpus.RevisionRecord{
		Revision: corpus.Revision{
			ID:         corpus.RevisionID("rev_" + uuid.NewString()),
			ArtifactID: artifactID,
		},
		Sequence: sequence,
		Evidence: evidence,
	}

	err = sqlitex.Execute(conn, "INSERT INTO revisions (revision_id, artifact_id, sequence, content_algorithm, content_digest, content_size) VALUES (?1, ?2, ?3, ?4, ?5, ?6)", &sqlitex.ExecOptions{
		Args: []any{
			string(record.Revision.ID),
			string(record.Revision.ArtifactID),
			int64(record.Sequence),
			record.Evidence.Algorithm,
			record.Evidence.Digest,
			record.Evidence.Size,
		},
	})
	if err != nil {
		return corpus.RevisionObservation{}, fmt.Errorf("insert Revision: %w", err)
	}

	return corpus.RevisionObservation{Current: record, Created: true}, nil
}

func currentRevision(conn *sqlite.Conn, artifactID corpus.ArtifactID) (corpus.RevisionRecord, bool, error) {
	var record corpus.RevisionRecord
	var found bool
	err := sqlitex.Execute(conn, "SELECT revision_id, sequence, content_algorithm, content_digest, content_size FROM revisions WHERE artifact_id = ?1 ORDER BY sequence DESC LIMIT 1", &sqlitex.ExecOptions{
		Args: []any{string(artifactID)},
		ResultFunc: func(stmt *sqlite.Stmt) error {
			found = true
			record = corpus.RevisionRecord{
				Revision: corpus.Revision{
					ID:         corpus.RevisionID(stmt.ColumnText(0)),
					ArtifactID: artifactID,
				},
				Sequence: uint64(stmt.ColumnInt64(1)),
				Evidence: corpus.ContentEvidence{
					Algorithm: stmt.ColumnText(2),
					Digest:    stmt.ColumnText(3),
					Size:      stmt.ColumnInt64(4),
				},
			}
			return nil
		},
	})
	if err != nil {
		return corpus.RevisionRecord{}, false, fmt.Errorf("query current Revision: %w", err)
	}
	return record, found, nil
}

func (s *Store) RevisionHistory(ctx context.Context, artifactID corpus.ArtifactID) ([]corpus.RevisionRecord, error) {
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return nil, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)

	var history []corpus.RevisionRecord
	err = sqlitex.Execute(conn, "SELECT revision_id, sequence, content_algorithm, content_digest, content_size FROM revisions WHERE artifact_id = ?1 ORDER BY sequence", &sqlitex.ExecOptions{
		Args: []any{string(artifactID)},
		ResultFunc: func(stmt *sqlite.Stmt) error {
			history = append(history, corpus.RevisionRecord{
				Revision: corpus.Revision{
					ID:         corpus.RevisionID(stmt.ColumnText(0)),
					ArtifactID: artifactID,
				},
				Sequence: uint64(stmt.ColumnInt64(1)),
				Evidence: corpus.ContentEvidence{
					Algorithm: stmt.ColumnText(2),
					Digest:    stmt.ColumnText(3),
					Size:      stmt.ColumnInt64(4),
				},
			})
			return nil
		},
	})
	if err != nil {
		return nil, fmt.Errorf("query Revision history: %w", err)
	}
	return history, nil
}
