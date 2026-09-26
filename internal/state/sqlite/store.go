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
		`
CREATE TABLE scan_sessions (
	scan_id TEXT PRIMARY KEY NOT NULL,
	provider_id TEXT NOT NULL,
	root TEXT NOT NULL,
	status TEXT NOT NULL CHECK (status IN ('OPEN', 'COMPLETE', 'ABORTED')),
	started_at TEXT NOT NULL,
	finished_at TEXT,
	CHECK (
		(status = 'OPEN' AND finished_at IS NULL)
		OR
		(status IN ('COMPLETE', 'ABORTED') AND finished_at IS NOT NULL)
	)
) STRICT;

CREATE UNIQUE INDEX scan_sessions_one_open
	ON scan_sessions (provider_id, root)
	WHERE status = 'OPEN';

CREATE INDEX scan_sessions_authority
	ON scan_sessions (provider_id, root, status, finished_at);

ALTER TABLE observations
	ADD COLUMN scan_id TEXT REFERENCES scan_sessions(scan_id) ON DELETE RESTRICT;

CREATE INDEX observations_scan
	ON observations (scan_id);
`,
		`
CREATE TABLE accepted_continuity_decisions (
	decision_id TEXT PRIMARY KEY NOT NULL,
	observation_id TEXT NOT NULL UNIQUE
		REFERENCES observations(observation_id) ON DELETE RESTRICT,
	artifact_id TEXT NOT NULL
		REFERENCES artifacts(artifact_id) ON DELETE RESTRICT,
	decision_state TEXT NOT NULL
		CHECK (decision_state = 'RESOLVED_SAME'),
	policy_id TEXT NOT NULL,
	resolution_json TEXT NOT NULL,
	decided_at TEXT NOT NULL
) STRICT;

CREATE INDEX accepted_continuity_artifact
	ON accepted_continuity_decisions (artifact_id);
`,
		`
CREATE TABLE provider_artifact_bindings (
	identity_domain TEXT NOT NULL,
	provider_id TEXT NOT NULL,
	native_object_id TEXT NOT NULL,
	artifact_id TEXT NOT NULL
		REFERENCES artifacts(artifact_id) ON DELETE RESTRICT,
	policy_id TEXT NOT NULL,
	accepted_at TEXT NOT NULL,
	PRIMARY KEY (identity_domain, provider_id, native_object_id)
) STRICT;

CREATE INDEX provider_artifact_bindings_artifact
	ON provider_artifact_bindings (artifact_id);

CREATE TABLE accepted_artifact_admissions (
	request_id TEXT PRIMARY KEY NOT NULL,
	observation_id TEXT NOT NULL UNIQUE
		REFERENCES observations(observation_id) ON DELETE RESTRICT,
	artifact_id TEXT NOT NULL
		REFERENCES artifacts(artifact_id) ON DELETE RESTRICT,
	identity_domain TEXT NOT NULL,
	provider_id TEXT NOT NULL,
	native_object_id TEXT NOT NULL,
	decision_state TEXT NOT NULL
		CHECK (decision_state = 'RESOLVED_NEW'),
	policy_id TEXT NOT NULL,
	resolution_json TEXT NOT NULL,
	decided_at TEXT NOT NULL,
	FOREIGN KEY (identity_domain, provider_id, native_object_id)
		REFERENCES provider_artifact_bindings(identity_domain, provider_id, native_object_id)
		ON DELETE RESTRICT
) STRICT;

CREATE INDEX accepted_artifact_admissions_artifact
	ON accepted_artifact_admissions (artifact_id);
`,
		`
CREATE TABLE identity_authority_sets (
	authority_set_id TEXT PRIMARY KEY NOT NULL,
	policy_id TEXT NOT NULL,
	provider_id TEXT NOT NULL,
	identity_domain TEXT NOT NULL,
	scope_id TEXT NOT NULL,
	current_object_id TEXT NOT NULL,
	universe_coverage TEXT NOT NULL
		CHECK (universe_coverage IN ('UNKNOWN', 'COMPLETE')),
	generation_id TEXT,
	lifetime_segment_id TEXT,
	source_refs_json TEXT NOT NULL,
	created_at TEXT NOT NULL
) STRICT;

CREATE TABLE identity_authority_candidates (
	authority_set_id TEXT NOT NULL
		REFERENCES identity_authority_sets(authority_set_id) ON DELETE RESTRICT,
	artifact_id TEXT NOT NULL
		REFERENCES artifacts(artifact_id) ON DELETE RESTRICT,
	direction TEXT NOT NULL
		CHECK (direction IN ('SUPPORTS_SAME', 'SUPPORTS_DISTINCT')),
	source_ref TEXT NOT NULL,
	PRIMARY KEY (authority_set_id, artifact_id, direction, source_ref)
) STRICT;

CREATE TABLE identity_mutation_requests (
	request_id TEXT PRIMARY KEY NOT NULL,
	operation_kind TEXT NOT NULL
		CHECK (operation_kind IN ('SAME', 'NEW')),
	fingerprint_version TEXT NOT NULL,
	fingerprint_sha256 TEXT NOT NULL,
	authority_set_id TEXT NOT NULL
		REFERENCES identity_authority_sets(authority_set_id) ON DELETE RESTRICT,
	observation_id TEXT NOT NULL UNIQUE
		REFERENCES observations(observation_id) ON DELETE RESTRICT,
	artifact_id TEXT NOT NULL
		REFERENCES artifacts(artifact_id) ON DELETE RESTRICT,
	revision_id TEXT,
	revision_created INTEGER NOT NULL
		CHECK (revision_created IN (0, 1)),
	decision_kind TEXT NOT NULL
		CHECK (decision_kind IN ('CONTINUITY', 'ADMISSION')),
	decision_id TEXT NOT NULL,
	accepted_at TEXT NOT NULL,
	FOREIGN KEY (revision_id, artifact_id)
		REFERENCES revisions(revision_id, artifact_id) ON DELETE RESTRICT,
	UNIQUE (decision_kind, decision_id)
) STRICT;

CREATE INDEX identity_mutation_artifact
	ON identity_mutation_requests (artifact_id);
CREATE INDEX identity_mutation_authority
	ON identity_mutation_requests (authority_set_id);
`,
		`
ALTER TABLE identity_authority_sets
	ADD COLUMN sealed_at TEXT;

UPDATE identity_authority_sets
	SET sealed_at = created_at
	WHERE sealed_at IS NULL;

CREATE TRIGGER identity_authority_sets_no_delete
BEFORE DELETE ON identity_authority_sets
BEGIN
	SELECT RAISE(ABORT, 'identity authority sets are immutable');
END;

CREATE TRIGGER identity_authority_sets_update_guard
BEFORE UPDATE ON identity_authority_sets
WHEN NOT (
	OLD.sealed_at IS NULL
	AND NEW.sealed_at IS NOT NULL
	AND NEW.authority_set_id = OLD.authority_set_id
	AND NEW.policy_id = OLD.policy_id
	AND NEW.provider_id = OLD.provider_id
	AND NEW.identity_domain = OLD.identity_domain
	AND NEW.scope_id = OLD.scope_id
	AND NEW.current_object_id = OLD.current_object_id
	AND NEW.universe_coverage = OLD.universe_coverage
	AND NEW.generation_id IS OLD.generation_id
	AND NEW.lifetime_segment_id IS OLD.lifetime_segment_id
	AND NEW.source_refs_json = OLD.source_refs_json
	AND NEW.created_at = OLD.created_at
)
BEGIN
	SELECT RAISE(ABORT, 'identity authority sets are immutable after creation');
END;

CREATE TRIGGER identity_authority_candidates_no_update
BEFORE UPDATE ON identity_authority_candidates
BEGIN
	SELECT RAISE(ABORT, 'identity authority candidates are immutable');
END;

CREATE TRIGGER identity_authority_candidates_no_delete
BEFORE DELETE ON identity_authority_candidates
BEGIN
	SELECT RAISE(ABORT, 'identity authority candidates are immutable');
END;

CREATE TRIGGER identity_authority_candidates_no_insert_after_seal
BEFORE INSERT ON identity_authority_candidates
WHEN COALESCE((
	SELECT sealed_at FROM identity_authority_sets
	WHERE authority_set_id = NEW.authority_set_id
), '') <> ''
BEGIN
	SELECT RAISE(ABORT, 'identity authority set is sealed');
END;

CREATE TRIGGER identity_mutation_requests_no_update
BEFORE UPDATE ON identity_mutation_requests
BEGIN
	SELECT RAISE(ABORT, 'identity mutation receipts are immutable');
END;

CREATE TRIGGER identity_mutation_requests_no_delete
BEFORE DELETE ON identity_mutation_requests
BEGIN
	SELECT RAISE(ABORT, 'identity mutation receipts are immutable');
END;
`,
		`
CREATE TABLE remote_history_generations (
	generation_id TEXT PRIMARY KEY NOT NULL,
	provider_id TEXT NOT NULL,
	identity_domain TEXT NOT NULL,
	stream_id TEXT NOT NULL,
	root TEXT NOT NULL,
	scope_policy_fingerprint TEXT NOT NULL,
	status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'CLOSED')),
	created_at TEXT NOT NULL,
	closed_at TEXT,
	closure_reason TEXT,
	current_sequence INTEGER NOT NULL CHECK (current_sequence >= 1),
	committed_cursor TEXT NOT NULL,
	CHECK (
		(status = 'ACTIVE' AND closed_at IS NULL AND closure_reason IS NULL)
		OR
		(status = 'CLOSED' AND closed_at IS NOT NULL AND closure_reason IN ('GAP', 'INVALID_CURSOR', 'SCOPE_MISMATCH', 'INSUFFICIENT_HISTORY'))
	)
) STRICT;

CREATE UNIQUE INDEX remote_history_one_active_scope
	ON remote_history_generations (provider_id, identity_domain, stream_id, root)
	WHERE status = 'ACTIVE';

CREATE TABLE remote_history_publications (
	generation_id TEXT NOT NULL
		REFERENCES remote_history_generations(generation_id) ON DELETE RESTRICT,
	sequence INTEGER NOT NULL CHECK (sequence >= 1),
	kind TEXT NOT NULL CHECK (kind IN ('BOOTSTRAP', 'INCREMENTAL')),
	previous_cursor TEXT NOT NULL,
	committed_cursor TEXT NOT NULL,
	committed_at TEXT NOT NULL,
	fingerprint_version TEXT NOT NULL,
	fingerprint_sha256 TEXT NOT NULL,
	PRIMARY KEY (generation_id, sequence),
	CHECK (
		(kind = 'BOOTSTRAP' AND sequence = 1 AND previous_cursor = '')
		OR
		(kind = 'INCREMENTAL' AND sequence >= 2 AND previous_cursor <> '')
	)
) STRICT;

CREATE TABLE remote_history_bootstrap_membership (
	generation_id TEXT NOT NULL
		REFERENCES remote_history_generations(generation_id) ON DELETE RESTRICT,
	object_id TEXT NOT NULL,
	locators_json TEXT NOT NULL,
	PRIMARY KEY (generation_id, object_id)
) STRICT;

CREATE TRIGGER remote_history_bootstrap_requires_publication
BEFORE INSERT ON remote_history_bootstrap_membership
WHEN NOT EXISTS (
	SELECT 1 FROM remote_history_publications
	WHERE generation_id = NEW.generation_id
	  AND sequence = 1
	  AND kind = 'BOOTSTRAP'
)
BEGIN
	SELECT RAISE(ABORT, 'bootstrap membership requires bootstrap publication');
END;

CREATE TABLE remote_history_publication_changes (
	generation_id TEXT NOT NULL,
	sequence INTEGER NOT NULL,
	ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
	kind TEXT NOT NULL CHECK (kind IN ('UPSERT', 'REMOVED')),
	object_id TEXT NOT NULL,
	state_json TEXT,
	PRIMARY KEY (generation_id, sequence, ordinal),
	FOREIGN KEY (generation_id, sequence)
		REFERENCES remote_history_publications(generation_id, sequence) ON DELETE RESTRICT,
	CHECK (
		(kind = 'UPSERT' AND state_json IS NOT NULL)
		OR
		(kind = 'REMOVED' AND state_json IS NULL)
	)
) STRICT;

CREATE TABLE remote_history_membership (
	generation_id TEXT NOT NULL
		REFERENCES remote_history_generations(generation_id) ON DELETE RESTRICT,
	object_id TEXT NOT NULL,
	locators_json TEXT NOT NULL,
	last_sequence INTEGER NOT NULL CHECK (last_sequence >= 1),
	PRIMARY KEY (generation_id, object_id),
	FOREIGN KEY (generation_id, last_sequence)
		REFERENCES remote_history_publications(generation_id, sequence) ON DELETE RESTRICT
) STRICT;

CREATE TRIGGER remote_history_generations_no_delete
BEFORE DELETE ON remote_history_generations
BEGIN
	SELECT RAISE(ABORT, 'remote history generations cannot be deleted');
END;

CREATE TRIGGER remote_history_generations_update_guard
BEFORE UPDATE ON remote_history_generations
WHEN NOT (
	NEW.generation_id = OLD.generation_id
	AND NEW.provider_id = OLD.provider_id
	AND NEW.identity_domain = OLD.identity_domain
	AND NEW.stream_id = OLD.stream_id
	AND NEW.root = OLD.root
	AND NEW.scope_policy_fingerprint = OLD.scope_policy_fingerprint
	AND NEW.created_at = OLD.created_at
	AND (
		(
			OLD.status = 'ACTIVE'
			AND NEW.status = 'ACTIVE'
			AND NEW.closed_at IS NULL
			AND NEW.closure_reason IS NULL
			AND NEW.current_sequence = OLD.current_sequence + 1
			AND NEW.committed_cursor <> ''
		)
		OR
		(
			OLD.status = 'ACTIVE'
			AND NEW.status = 'CLOSED'
			AND NEW.closed_at IS NOT NULL
			AND NEW.closure_reason IN ('GAP', 'INVALID_CURSOR', 'SCOPE_MISMATCH', 'INSUFFICIENT_HISTORY')
			AND NEW.current_sequence = OLD.current_sequence
			AND NEW.committed_cursor = OLD.committed_cursor
		)
	)
)
BEGIN
	SELECT RAISE(ABORT, 'invalid remote history generation mutation');
END;

CREATE TRIGGER remote_history_publications_no_update
BEFORE UPDATE ON remote_history_publications
BEGIN
	SELECT RAISE(ABORT, 'remote history publications are immutable');
END;

CREATE TRIGGER remote_history_publications_no_delete
BEFORE DELETE ON remote_history_publications
BEGIN
	SELECT RAISE(ABORT, 'remote history publications are immutable');
END;

CREATE TRIGGER remote_history_bootstrap_membership_no_update
BEFORE UPDATE ON remote_history_bootstrap_membership
BEGIN
	SELECT RAISE(ABORT, 'remote history bootstrap evidence is immutable');
END;

CREATE TRIGGER remote_history_bootstrap_membership_no_delete
BEFORE DELETE ON remote_history_bootstrap_membership
BEGIN
	SELECT RAISE(ABORT, 'remote history bootstrap evidence is immutable');
END;

CREATE TRIGGER remote_history_publication_changes_no_update
BEFORE UPDATE ON remote_history_publication_changes
BEGIN
	SELECT RAISE(ABORT, 'remote history publication changes are immutable');
END;

CREATE TRIGGER remote_history_publication_changes_no_delete
BEFORE DELETE ON remote_history_publication_changes
BEGIN
	SELECT RAISE(ABORT, 'remote history publication changes are immutable');
END;
`,

		`
DROP TRIGGER remote_history_generations_update_guard;

CREATE TRIGGER remote_history_publications_insert_guard
BEFORE INSERT ON remote_history_publications
WHEN NOT (
	NEW.fingerprint_version = 'remote-history-publication:v1'
	AND length(NEW.fingerprint_sha256) = 64
	AND NEW.fingerprint_sha256 NOT GLOB '*[^0-9a-f]*'
	AND (
		(
			NEW.kind = 'BOOTSTRAP'
			AND NEW.sequence = 1
			AND NEW.previous_cursor = ''
			AND NEW.committed_cursor <> ''
			AND EXISTS (
				SELECT 1
				FROM remote_history_generations g
				WHERE g.generation_id = NEW.generation_id
				  AND g.status = 'ACTIVE'
				  AND g.current_sequence = 1
				  AND g.committed_cursor = NEW.committed_cursor
			)
			AND NOT EXISTS (
				SELECT 1
				FROM remote_history_publications p
				WHERE p.generation_id = NEW.generation_id
			)
		)
		OR
		(
			NEW.kind = 'INCREMENTAL'
			AND NEW.sequence >= 2
			AND NEW.previous_cursor <> ''
			AND NEW.committed_cursor <> ''
			AND EXISTS (
				SELECT 1
				FROM remote_history_generations g
				WHERE g.generation_id = NEW.generation_id
				  AND g.status = 'ACTIVE'
				  AND g.current_sequence = NEW.sequence - 1
				  AND g.committed_cursor = NEW.previous_cursor
			)
		)
	)
)
BEGIN
	SELECT RAISE(ABORT, 'remote history publication does not match generation prestate');
END;

CREATE TRIGGER remote_history_publication_changes_insert_guard
BEFORE INSERT ON remote_history_publication_changes
WHEN NOT EXISTS (
	SELECT 1
	FROM remote_history_publications p
	WHERE p.generation_id = NEW.generation_id
	  AND p.sequence = NEW.sequence
	  AND p.kind = 'INCREMENTAL'
)
BEGIN
	SELECT RAISE(ABORT, 'remote history changes require incremental publication');
END;

CREATE TRIGGER remote_history_membership_insert_guard
BEFORE INSERT ON remote_history_membership
WHEN NOT (
	(
		NEW.last_sequence = 1
		AND EXISTS (
			SELECT 1
			FROM remote_history_generations g
			JOIN remote_history_bootstrap_membership b
			  ON b.generation_id = g.generation_id
			 AND b.object_id = NEW.object_id
			WHERE g.generation_id = NEW.generation_id
			  AND g.status = 'ACTIVE'
			  AND g.current_sequence = 1
			  AND b.locators_json = NEW.locators_json
		)
	)
	OR
	(
		EXISTS (
			SELECT 1
			FROM remote_history_generations g
			WHERE g.generation_id = NEW.generation_id
			  AND g.status = 'ACTIVE'
			  AND NEW.last_sequence = g.current_sequence + 1
		)
		AND EXISTS (
			SELECT 1
			FROM remote_history_publication_changes c
			WHERE c.generation_id = NEW.generation_id
			  AND c.sequence = NEW.last_sequence
			  AND c.object_id = NEW.object_id
			  AND c.kind = 'UPSERT'
			  AND json_extract(c.state_json, '$.locators') = json(NEW.locators_json)
		)
	)
)
BEGIN
	SELECT RAISE(ABORT, 'remote history membership insert lacks matching immutable evidence');
END;

CREATE TRIGGER remote_history_membership_update_guard
BEFORE UPDATE ON remote_history_membership
WHEN NOT (
	NEW.generation_id = OLD.generation_id
	AND NEW.object_id = OLD.object_id
	AND EXISTS (
		SELECT 1
		FROM remote_history_generations g
		WHERE g.generation_id = NEW.generation_id
		  AND g.status = 'ACTIVE'
		  AND NEW.last_sequence = g.current_sequence + 1
	)
	AND EXISTS (
		SELECT 1
		FROM remote_history_publication_changes c
		WHERE c.generation_id = NEW.generation_id
		  AND c.sequence = NEW.last_sequence
		  AND c.object_id = NEW.object_id
		  AND c.kind = 'UPSERT'
		  AND json_extract(c.state_json, '$.locators') = json(NEW.locators_json)
	)
)
BEGIN
	SELECT RAISE(ABORT, 'remote history membership update lacks matching immutable evidence');
END;

CREATE TRIGGER remote_history_membership_delete_guard
BEFORE DELETE ON remote_history_membership
WHEN NOT EXISTS (
	SELECT 1
	FROM remote_history_generations g
	JOIN remote_history_publication_changes c
	  ON c.generation_id = g.generation_id
	 AND c.sequence = g.current_sequence + 1
	 AND c.object_id = OLD.object_id
	 AND c.kind = 'REMOVED'
	WHERE g.generation_id = OLD.generation_id
	  AND g.status = 'ACTIVE'
)
BEGIN
	SELECT RAISE(ABORT, 'remote history membership delete lacks matching immutable evidence');
END;

CREATE TRIGGER remote_history_generations_update_guard
BEFORE UPDATE ON remote_history_generations
WHEN NOT (
	NEW.generation_id = OLD.generation_id
	AND NEW.provider_id = OLD.provider_id
	AND NEW.identity_domain = OLD.identity_domain
	AND NEW.stream_id = OLD.stream_id
	AND NEW.root = OLD.root
	AND NEW.scope_policy_fingerprint = OLD.scope_policy_fingerprint
	AND NEW.created_at = OLD.created_at
	AND (
		(
			OLD.status = 'ACTIVE'
			AND NEW.status = 'ACTIVE'
			AND NEW.closed_at IS NULL
			AND NEW.closure_reason IS NULL
			AND NEW.current_sequence = OLD.current_sequence + 1
			AND NEW.committed_cursor <> ''
			AND EXISTS (
				SELECT 1
				FROM remote_history_publications p
				WHERE p.generation_id = NEW.generation_id
				  AND p.sequence = NEW.current_sequence
				  AND p.kind = 'INCREMENTAL'
				  AND p.previous_cursor = OLD.committed_cursor
				  AND p.committed_cursor = NEW.committed_cursor
			)
			AND NOT EXISTS (
				SELECT 1
				FROM remote_history_publication_changes c
				WHERE c.generation_id = NEW.generation_id
				  AND c.sequence = NEW.current_sequence
				  AND c.ordinal = (
					SELECT MAX(c2.ordinal)
					FROM remote_history_publication_changes c2
					WHERE c2.generation_id = c.generation_id
					  AND c2.sequence = c.sequence
					  AND c2.object_id = c.object_id
				  )
				  AND (
					(
						c.kind = 'REMOVED'
						AND EXISTS (
							SELECT 1
							FROM remote_history_membership m
							WHERE m.generation_id = c.generation_id
							  AND m.object_id = c.object_id
						)
					)
					OR
					(
						c.kind = 'UPSERT'
						AND NOT EXISTS (
							SELECT 1
							FROM remote_history_membership m
							WHERE m.generation_id = c.generation_id
							  AND m.object_id = c.object_id
							  AND m.last_sequence = c.sequence
							  AND json(m.locators_json) = json_extract(c.state_json, '$.locators')
						)
					)
				  )
			)
		)
		OR
		(
			OLD.status = 'ACTIVE'
			AND NEW.status = 'CLOSED'
			AND NEW.closed_at IS NOT NULL
			AND NEW.closure_reason IN ('GAP', 'INVALID_CURSOR', 'SCOPE_MISMATCH', 'INSUFFICIENT_HISTORY')
			AND NEW.current_sequence = OLD.current_sequence
			AND NEW.committed_cursor = OLD.committed_cursor
		)
	)
)
BEGIN
	SELECT RAISE(ABORT, 'invalid remote history generation mutation');
END;
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

	return observeRevisionConn(conn, artifactID, evidence)
}

func observeRevisionConn(conn *sqlite.Conn, artifactID corpus.ArtifactID, evidence corpus.ContentEvidence) (corpus.RevisionObservation, error) {
	if err := corpus.ValidateContentEvidence(evidence); err != nil {
		return corpus.RevisionObservation{}, err
	}

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
