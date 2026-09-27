package sqlitestate

import (
	"context"
	"encoding/json"
	"fmt"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
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

		`
CREATE TABLE provider_object_lifetime_segments (
	lifetime_segment_id TEXT PRIMARY KEY NOT NULL
		CHECK (
			length(lifetime_segment_id) = 69
			AND substr(lifetime_segment_id, 1, 5) = 'hseg_'
			AND substr(lifetime_segment_id, 6) NOT GLOB '*[^0-9a-f]*'
		),
	generation_id TEXT NOT NULL
		REFERENCES remote_history_generations(generation_id) ON DELETE RESTRICT,
	object_id TEXT NOT NULL,
	start_kind TEXT NOT NULL CHECK (start_kind IN ('BOOTSTRAP', 'UPSERT')),
	start_sequence INTEGER NOT NULL CHECK (start_sequence >= 1),
	start_ordinal INTEGER,
	last_present_sequence INTEGER NOT NULL CHECK (last_present_sequence >= 1),
	last_present_ordinal INTEGER,
	status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'CLOSED')),
	end_sequence INTEGER,
	end_ordinal INTEGER,
	closure_reason TEXT,
	CHECK (
		(start_kind = 'BOOTSTRAP' AND start_sequence = 1 AND start_ordinal IS NULL)
		OR
		(start_kind = 'UPSERT' AND start_sequence >= 2 AND start_ordinal >= 0)
	),
	CHECK (
		(last_present_sequence = 1 AND last_present_ordinal IS NULL)
		OR
		(last_present_sequence >= 2 AND last_present_ordinal >= 0)
	),
	CHECK (last_present_sequence >= start_sequence),
	CHECK (
		(status = 'ACTIVE' AND end_sequence IS NULL AND end_ordinal IS NULL AND closure_reason IS NULL)
		OR
		(
			status = 'CLOSED'
			AND end_sequence IS NOT NULL
			AND end_sequence >= start_sequence
			AND (
				(closure_reason = 'REMOVED_FROM_SCOPE' AND end_ordinal >= 0)
				OR
				(closure_reason = 'HISTORY_GENERATION_CLOSED' AND end_ordinal IS NULL)
			)
		)
	)
) STRICT;

CREATE UNIQUE INDEX provider_lifetime_segment_start_identity
	ON provider_object_lifetime_segments (
		generation_id,
		object_id,
		start_kind,
		start_sequence,
		COALESCE(start_ordinal, -1)
	);

CREATE UNIQUE INDEX provider_lifetime_segment_one_active
	ON provider_object_lifetime_segments (generation_id, object_id)
	WHERE status = 'ACTIVE';

CREATE INDEX provider_lifetime_segment_generation
	ON provider_object_lifetime_segments (generation_id, object_id, start_sequence, start_ordinal);

CREATE TRIGGER provider_lifetime_segments_no_delete
BEFORE DELETE ON provider_object_lifetime_segments
BEGIN
	SELECT RAISE(ABORT, 'provider lifetime segments cannot be deleted');
END;

CREATE TRIGGER provider_lifetime_segments_update_guard
BEFORE UPDATE ON provider_object_lifetime_segments
WHEN NOT (
	NEW.lifetime_segment_id = OLD.lifetime_segment_id
	AND NEW.generation_id = OLD.generation_id
	AND NEW.object_id = OLD.object_id
	AND NEW.start_kind = OLD.start_kind
	AND NEW.start_sequence = OLD.start_sequence
	AND NEW.start_ordinal IS OLD.start_ordinal
	AND OLD.status = 'ACTIVE'
	AND (
		(
			NEW.status = 'ACTIVE'
			AND NEW.end_sequence IS NULL
			AND NEW.end_ordinal IS NULL
			AND NEW.closure_reason IS NULL
			AND (
				NEW.last_present_sequence > OLD.last_present_sequence
				OR
				(
					NEW.last_present_sequence = OLD.last_present_sequence
					AND NEW.last_present_ordinal IS NOT NULL
					AND (
						OLD.last_present_ordinal IS NULL
						OR NEW.last_present_ordinal > OLD.last_present_ordinal
					)
				)
			)
		)
		OR
		(
			NEW.status = 'CLOSED'
			AND NEW.last_present_sequence = OLD.last_present_sequence
			AND NEW.last_present_ordinal IS OLD.last_present_ordinal
			AND NEW.end_sequence IS NOT NULL
			AND (
				(
					NEW.closure_reason = 'REMOVED_FROM_SCOPE'
					AND NEW.end_ordinal IS NOT NULL
					AND (
						NEW.end_sequence > OLD.last_present_sequence
						OR
						(
							NEW.end_sequence = OLD.last_present_sequence
							AND OLD.last_present_ordinal IS NOT NULL
							AND NEW.end_ordinal > OLD.last_present_ordinal
						)
					)
				)
				OR
				(
					NEW.closure_reason = 'HISTORY_GENERATION_CLOSED'
					AND NEW.end_ordinal IS NULL
					AND NEW.end_sequence >= OLD.last_present_sequence
				)
			)
		)
	)
)
BEGIN
	SELECT RAISE(ABORT, 'invalid provider lifetime segment mutation');
END;
`,

		`
CREATE TABLE provider_lifetime_artifact_bindings (
	lifetime_segment_id TEXT PRIMARY KEY NOT NULL
		REFERENCES provider_object_lifetime_segments(lifetime_segment_id) ON DELETE RESTRICT,
	artifact_id TEXT NOT NULL
		REFERENCES artifacts(artifact_id) ON DELETE RESTRICT,
	policy_id TEXT NOT NULL,
	source_authority_set_id TEXT NOT NULL
		REFERENCES identity_authority_sets(authority_set_id) ON DELETE RESTRICT,
	accepted_at TEXT NOT NULL
) STRICT;

CREATE INDEX provider_lifetime_artifact_bindings_artifact
	ON provider_lifetime_artifact_bindings (artifact_id);

CREATE TRIGGER remote_history_authority_insert_guard
BEFORE INSERT ON identity_authority_sets
WHEN NEW.policy_id = 'remote-history:lifetime-segment:v1'
	AND NOT EXISTS (
		SELECT 1
		FROM provider_object_lifetime_segments s
		JOIN remote_history_generations g
		  ON g.generation_id = s.generation_id
		JOIN remote_history_membership m
		  ON m.generation_id = s.generation_id
		 AND m.object_id = s.object_id
		WHERE s.lifetime_segment_id = NEW.lifetime_segment_id
		  AND s.generation_id = NEW.generation_id
		  AND s.object_id = NEW.current_object_id
		  AND s.status = 'ACTIVE'
		  AND g.status = 'ACTIVE'
		  AND g.provider_id = NEW.provider_id
		  AND g.identity_domain = NEW.identity_domain
		  AND g.root = NEW.scope_id
	)
BEGIN
	SELECT RAISE(ABORT, 'remote history authority does not match active generation/segment/membership');
END;

CREATE TRIGGER provider_lifetime_artifact_bindings_insert_guard
BEFORE INSERT ON provider_lifetime_artifact_bindings
WHEN NOT EXISTS (
	SELECT 1
	FROM provider_object_lifetime_segments s
	JOIN identity_authority_sets a
	  ON a.authority_set_id = NEW.source_authority_set_id
	WHERE s.lifetime_segment_id = NEW.lifetime_segment_id
	  AND s.status = 'ACTIVE'
	  AND a.policy_id = NEW.policy_id
	  AND a.policy_id = 'remote-history:lifetime-segment:v1'
	  AND a.generation_id = s.generation_id
	  AND a.lifetime_segment_id = s.lifetime_segment_id
	  AND a.current_object_id = s.object_id
	  AND a.sealed_at IS NOT NULL
)
BEGIN
	SELECT RAISE(ABORT, 'lifetime Artifact binding lacks matching sealed authority');
END;

CREATE TRIGGER provider_lifetime_artifact_bindings_no_update
BEFORE UPDATE ON provider_lifetime_artifact_bindings
BEGIN
	SELECT RAISE(ABORT, 'provider lifetime Artifact bindings are immutable');
END;

CREATE TRIGGER provider_lifetime_artifact_bindings_no_delete
BEFORE DELETE ON provider_lifetime_artifact_bindings
BEGIN
	SELECT RAISE(ABORT, 'provider lifetime Artifact bindings are immutable');
END;
`,

		`
ALTER TABLE accepted_continuity_decisions
	ADD COLUMN lifetime_segment_id TEXT
		REFERENCES provider_object_lifetime_segments(lifetime_segment_id) ON DELETE RESTRICT;

ALTER TABLE accepted_artifact_admissions
	ADD COLUMN lifetime_segment_id TEXT
		REFERENCES provider_object_lifetime_segments(lifetime_segment_id) ON DELETE RESTRICT;

CREATE INDEX accepted_continuity_lifetime_segment
	ON accepted_continuity_decisions (lifetime_segment_id);

CREATE INDEX accepted_admission_lifetime_segment
	ON accepted_artifact_admissions (lifetime_segment_id);

CREATE TRIGGER accepted_continuity_lifetime_guard
BEFORE INSERT ON accepted_continuity_decisions
WHEN (
	NEW.policy_id = 'remote-history:lifetime-segment:v1'
	AND (
		NEW.lifetime_segment_id IS NULL
		OR NOT EXISTS (
			SELECT 1
			FROM provider_lifetime_artifact_bindings b
			WHERE b.lifetime_segment_id = NEW.lifetime_segment_id
			  AND b.artifact_id = NEW.artifact_id
			  AND b.policy_id = NEW.policy_id
		)
	)
) OR (
	NEW.policy_id <> 'remote-history:lifetime-segment:v1'
	AND NEW.lifetime_segment_id IS NOT NULL
)
BEGIN
	SELECT RAISE(ABORT, 'accepted continuity lifetime provenance mismatch');
END;

CREATE TRIGGER accepted_admission_lifetime_guard
BEFORE INSERT ON accepted_artifact_admissions
WHEN (
	NEW.policy_id = 'remote-history:lifetime-segment:v1'
	AND (
		NEW.lifetime_segment_id IS NULL
		OR NOT EXISTS (
			SELECT 1
			FROM provider_lifetime_artifact_bindings b
			WHERE b.lifetime_segment_id = NEW.lifetime_segment_id
			  AND b.artifact_id = NEW.artifact_id
			  AND b.policy_id = NEW.policy_id
		)
	)
) OR (
	NEW.policy_id <> 'remote-history:lifetime-segment:v1'
	AND NEW.lifetime_segment_id IS NOT NULL
)
BEGIN
	SELECT RAISE(ABORT, 'accepted admission lifetime provenance mismatch');
END;
`,

		`
CREATE TRIGGER accepted_continuity_decisions_no_update
BEFORE UPDATE ON accepted_continuity_decisions
BEGIN
	SELECT RAISE(ABORT, 'accepted continuity decisions are immutable');
END;

CREATE TRIGGER accepted_continuity_decisions_no_delete
BEFORE DELETE ON accepted_continuity_decisions
BEGIN
	SELECT RAISE(ABORT, 'accepted continuity decisions are immutable');
END;

CREATE TRIGGER accepted_artifact_admissions_no_update
BEFORE UPDATE ON accepted_artifact_admissions
BEGIN
	SELECT RAISE(ABORT, 'accepted Artifact admissions are immutable');
END;

CREATE TRIGGER accepted_artifact_admissions_no_delete
BEFORE DELETE ON accepted_artifact_admissions
BEGIN
	SELECT RAISE(ABORT, 'accepted Artifact admissions are immutable');
END;

CREATE TRIGGER provider_artifact_bindings_remote_history_forbidden
BEFORE INSERT ON provider_artifact_bindings
WHEN NEW.policy_id = 'remote-history:lifetime-segment:v1'
BEGIN
	SELECT RAISE(ABORT, 'RemoteHistory lifetime authority cannot create naked provider bindings');
END;
`,

		`
CREATE TABLE accepted_artifact_admissions_v14 (
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
	lifetime_segment_id TEXT
		REFERENCES provider_object_lifetime_segments(lifetime_segment_id) ON DELETE RESTRICT
) STRICT;

INSERT INTO accepted_artifact_admissions_v14 (
	request_id, observation_id, artifact_id,
	identity_domain, provider_id, native_object_id,
	decision_state, policy_id, resolution_json, decided_at,
	lifetime_segment_id
)
SELECT
	request_id, observation_id, artifact_id,
	identity_domain, provider_id, native_object_id,
	decision_state, policy_id, resolution_json, decided_at,
	lifetime_segment_id
FROM accepted_artifact_admissions;

DROP TABLE accepted_artifact_admissions;
ALTER TABLE accepted_artifact_admissions_v14 RENAME TO accepted_artifact_admissions;

CREATE INDEX accepted_artifact_admissions_artifact
	ON accepted_artifact_admissions (artifact_id);

CREATE INDEX accepted_admission_lifetime_segment
	ON accepted_artifact_admissions (lifetime_segment_id);

CREATE TRIGGER accepted_admission_binding_guard
BEFORE INSERT ON accepted_artifact_admissions
WHEN (
	NEW.policy_id = 'remote-history:lifetime-segment:v1'
	AND (
		NEW.lifetime_segment_id IS NULL
		OR NOT EXISTS (
			SELECT 1
			FROM provider_lifetime_artifact_bindings b
			WHERE b.lifetime_segment_id = NEW.lifetime_segment_id
			  AND b.artifact_id = NEW.artifact_id
			  AND b.policy_id = NEW.policy_id
		)
	)
) OR (
	NEW.policy_id <> 'remote-history:lifetime-segment:v1'
	AND (
		NEW.lifetime_segment_id IS NOT NULL
		OR NOT EXISTS (
			SELECT 1
			FROM provider_artifact_bindings b
			WHERE b.identity_domain = NEW.identity_domain
			  AND b.provider_id = NEW.provider_id
			  AND b.native_object_id = NEW.native_object_id
			  AND b.artifact_id = NEW.artifact_id
			  AND b.policy_id = NEW.policy_id
		)
	)
)
BEGIN
	SELECT RAISE(ABORT, 'accepted admission binding provenance mismatch');
END;

CREATE TRIGGER accepted_artifact_admissions_no_update
BEFORE UPDATE ON accepted_artifact_admissions
BEGIN
	SELECT RAISE(ABORT, 'accepted Artifact admissions are immutable');
END;

CREATE TRIGGER accepted_artifact_admissions_no_delete
BEFORE DELETE ON accepted_artifact_admissions
BEGIN
	SELECT RAISE(ABORT, 'accepted Artifact admissions are immutable');
END;
`,

		`
CREATE TABLE gdrive_topology_evidence (
	generation_id TEXT NOT NULL
		REFERENCES remote_history_generations(generation_id) ON DELETE RESTRICT,
	sequence INTEGER NOT NULL CHECK (sequence >= 1),
	ordinal INTEGER NOT NULL CHECK (ordinal >= -1),
	evidence_kind TEXT NOT NULL CHECK (evidence_kind IN ('BOOTSTRAP','UPSERT','REMOVED')),
	object_id TEXT NOT NULL,
	presence TEXT NOT NULL CHECK (presence IN ('PRESENT','UNAVAILABLE')),
	parent_state TEXT NOT NULL CHECK (parent_state IN ('KNOWN','UNKNOWN','UNAVAILABLE')),
	parent_id TEXT,
	drive_id TEXT NOT NULL,
	PRIMARY KEY (generation_id, sequence, ordinal, object_id),
	FOREIGN KEY (generation_id, sequence)
		REFERENCES remote_history_publications(generation_id, sequence) ON DELETE RESTRICT,
	CHECK (
		(evidence_kind='BOOTSTRAP' AND sequence=1 AND ordinal=-1)
		OR
		(evidence_kind IN ('UPSERT','REMOVED') AND sequence>=2 AND ordinal>=0)
	),
	CHECK (
		(presence='PRESENT' AND parent_state='KNOWN' AND parent_id IS NOT NULL AND parent_id<>'' AND parent_id<>object_id)
		OR
		(presence='PRESENT' AND parent_state='UNKNOWN' AND parent_id IS NULL)
		OR
		(presence='UNAVAILABLE' AND parent_state='UNAVAILABLE' AND parent_id IS NULL)
	)
) STRICT;

CREATE TRIGGER gdrive_topology_evidence_insert_guard
BEFORE INSERT ON gdrive_topology_evidence
WHEN NOT EXISTS (
	SELECT 1 FROM remote_history_generations g
	WHERE g.generation_id=NEW.generation_id
	  AND g.provider_id='google-drive'
) OR NOT (
	(
		NEW.evidence_kind='BOOTSTRAP'
		AND NEW.presence='PRESENT'
		AND EXISTS (
			SELECT 1 FROM remote_history_bootstrap_membership b
			WHERE b.generation_id=NEW.generation_id
			  AND b.object_id=NEW.object_id
		)
	)
	OR
	(
		NEW.evidence_kind='UPSERT'
		AND NEW.presence='PRESENT'
		AND EXISTS (
			SELECT 1 FROM remote_history_publication_changes c
			WHERE c.generation_id=NEW.generation_id
			  AND c.sequence=NEW.sequence
			  AND c.ordinal=NEW.ordinal
			  AND c.object_id=NEW.object_id
			  AND c.kind='UPSERT'
		)
	)
	OR
	(
		NEW.evidence_kind='REMOVED'
		AND NEW.presence='UNAVAILABLE'
		AND EXISTS (
			SELECT 1 FROM remote_history_publication_changes c
			WHERE c.generation_id=NEW.generation_id
			  AND c.sequence=NEW.sequence
			  AND c.ordinal=NEW.ordinal
			  AND c.object_id=NEW.object_id
			  AND c.kind='REMOVED'
		)
	)
)
BEGIN
	SELECT RAISE(ABORT, 'Google Drive topology evidence lacks matching RemoteHistory evidence');
END;

CREATE TRIGGER gdrive_topology_evidence_no_update
BEFORE UPDATE ON gdrive_topology_evidence
BEGIN
	SELECT RAISE(ABORT, 'Google Drive topology evidence is immutable');
END;

CREATE TRIGGER gdrive_topology_evidence_no_delete
BEFORE DELETE ON gdrive_topology_evidence
BEGIN
	SELECT RAISE(ABORT, 'Google Drive topology evidence is immutable');
END;

CREATE TABLE gdrive_topology_nodes (
	generation_id TEXT NOT NULL
		REFERENCES remote_history_generations(generation_id) ON DELETE RESTRICT,
	object_id TEXT NOT NULL,
	presence TEXT NOT NULL CHECK (presence IN ('PRESENT','UNAVAILABLE')),
	parent_state TEXT NOT NULL CHECK (parent_state IN ('KNOWN','UNKNOWN','UNAVAILABLE')),
	parent_id TEXT,
	drive_id TEXT NOT NULL,
	last_sequence INTEGER NOT NULL CHECK (last_sequence >= 1),
	last_ordinal INTEGER NOT NULL CHECK (last_ordinal >= -1),
	PRIMARY KEY (generation_id, object_id),
	FOREIGN KEY (generation_id, last_sequence)
		REFERENCES remote_history_publications(generation_id, sequence) ON DELETE RESTRICT,
	CHECK (
		(last_sequence=1 AND last_ordinal=-1)
		OR
		(last_sequence>=2 AND last_ordinal>=0)
	),
	CHECK (
		(presence='PRESENT' AND parent_state='KNOWN' AND parent_id IS NOT NULL AND parent_id<>'' AND parent_id<>object_id)
		OR
		(presence='PRESENT' AND parent_state='UNKNOWN' AND parent_id IS NULL)
		OR
		(presence='UNAVAILABLE' AND parent_state='UNAVAILABLE' AND parent_id IS NULL)
	)
) STRICT;

CREATE TRIGGER gdrive_topology_nodes_insert_guard
BEFORE INSERT ON gdrive_topology_nodes
WHEN NOT EXISTS (
	SELECT 1 FROM gdrive_topology_evidence e
	WHERE e.generation_id=NEW.generation_id
	  AND e.object_id=NEW.object_id
	  AND e.sequence=NEW.last_sequence
	  AND e.ordinal=NEW.last_ordinal
	  AND e.presence=NEW.presence
	  AND e.parent_state=NEW.parent_state
	  AND e.parent_id IS NEW.parent_id
	  AND e.drive_id=NEW.drive_id
)
BEGIN
	SELECT RAISE(ABORT, 'Google Drive topology node lacks matching evidence');
END;

CREATE TRIGGER gdrive_topology_nodes_update_guard
BEFORE UPDATE ON gdrive_topology_nodes
WHEN NEW.generation_id<>OLD.generation_id
	OR NEW.object_id<>OLD.object_id
	OR NOT EXISTS (
		SELECT 1 FROM gdrive_topology_evidence e
		WHERE e.generation_id=NEW.generation_id
		  AND e.object_id=NEW.object_id
		  AND e.sequence=NEW.last_sequence
		  AND e.ordinal=NEW.last_ordinal
		  AND e.presence=NEW.presence
		  AND e.parent_state=NEW.parent_state
		  AND e.parent_id IS NEW.parent_id
		  AND e.drive_id=NEW.drive_id
	)
BEGIN
	SELECT RAISE(ABORT, 'Google Drive topology node mutation lacks matching evidence');
END;

CREATE TABLE gdrive_topology_watermarks (
	generation_id TEXT PRIMARY KEY NOT NULL
		REFERENCES remote_history_generations(generation_id) ON DELETE RESTRICT,
	publication_sequence INTEGER NOT NULL CHECK (publication_sequence >= 1),
	FOREIGN KEY (generation_id, publication_sequence)
		REFERENCES remote_history_publications(generation_id, sequence) ON DELETE RESTRICT
) STRICT;

CREATE TRIGGER gdrive_topology_watermark_insert_guard
BEFORE INSERT ON gdrive_topology_watermarks
WHEN NOT EXISTS (
	SELECT 1 FROM remote_history_generations g
	WHERE g.generation_id=NEW.generation_id
	  AND g.provider_id='google-drive'
	  AND g.current_sequence>=NEW.publication_sequence
) OR EXISTS (
	SELECT 1 FROM remote_history_bootstrap_membership b
	WHERE b.generation_id=NEW.generation_id
	  AND NOT EXISTS (
		SELECT 1 FROM gdrive_topology_evidence e
		WHERE e.generation_id=b.generation_id
		  AND e.sequence=1
		  AND e.ordinal=-1
		  AND e.object_id=b.object_id
		  AND e.evidence_kind='BOOTSTRAP'
	)
) OR EXISTS (
	SELECT 1 FROM remote_history_publication_changes c
	WHERE c.generation_id=NEW.generation_id
	  AND c.sequence<=NEW.publication_sequence
	  AND NOT EXISTS (
		SELECT 1 FROM gdrive_topology_evidence e
		WHERE e.generation_id=c.generation_id
		  AND e.sequence=c.sequence
		  AND e.ordinal=c.ordinal
		  AND e.object_id=c.object_id
		  AND (
			(e.evidence_kind='UPSERT' AND c.kind='UPSERT')
			OR
			(e.evidence_kind='REMOVED' AND c.kind='REMOVED')
		  )
	)
) OR EXISTS (
	SELECT 1 FROM gdrive_topology_evidence e
	WHERE e.generation_id=NEW.generation_id
	  AND e.sequence<=NEW.publication_sequence
	  AND NOT EXISTS (
		SELECT 1 FROM gdrive_topology_evidence newer
		WHERE newer.generation_id=e.generation_id
		  AND newer.object_id=e.object_id
		  AND newer.sequence<=NEW.publication_sequence
		  AND (
			newer.sequence>e.sequence
			OR (newer.sequence=e.sequence AND newer.ordinal>e.ordinal)
		  )
	  )
	  AND NOT EXISTS (
		SELECT 1 FROM gdrive_topology_nodes n
		WHERE n.generation_id=e.generation_id
		  AND n.object_id=e.object_id
		  AND n.last_sequence=e.sequence
		  AND n.last_ordinal=e.ordinal
		  AND n.presence=e.presence
		  AND n.parent_state=e.parent_state
		  AND n.parent_id IS e.parent_id
		  AND n.drive_id=e.drive_id
	  )
) OR EXISTS (
	SELECT 1 FROM gdrive_topology_nodes n
	WHERE n.generation_id=NEW.generation_id
	  AND n.last_sequence>NEW.publication_sequence
)
BEGIN
	SELECT RAISE(ABORT, 'Google Drive topology watermark does not match complete current projection');
END;

CREATE TRIGGER gdrive_topology_watermark_update_guard
BEFORE UPDATE ON gdrive_topology_watermarks
WHEN NEW.generation_id<>OLD.generation_id
	OR NEW.publication_sequence<=OLD.publication_sequence
BEGIN
	SELECT RAISE(ABORT, 'Google Drive topology watermark must advance monotonically');
END;

CREATE TRIGGER gdrive_topology_watermark_update_coverage_guard
BEFORE UPDATE ON gdrive_topology_watermarks
WHEN EXISTS (
	SELECT 1 FROM remote_history_bootstrap_membership b
	WHERE b.generation_id=NEW.generation_id
	  AND NOT EXISTS (
		SELECT 1 FROM gdrive_topology_evidence e
		WHERE e.generation_id=b.generation_id
		  AND e.sequence=1 AND e.ordinal=-1
		  AND e.object_id=b.object_id
		  AND e.evidence_kind='BOOTSTRAP'
	)
) OR EXISTS (
	SELECT 1 FROM remote_history_publication_changes c
	WHERE c.generation_id=NEW.generation_id
	  AND c.sequence<=NEW.publication_sequence
	  AND NOT EXISTS (
		SELECT 1 FROM gdrive_topology_evidence e
		WHERE e.generation_id=c.generation_id
		  AND e.sequence=c.sequence
		  AND e.ordinal=c.ordinal
		  AND e.object_id=c.object_id
		  AND (
			(e.evidence_kind='UPSERT' AND c.kind='UPSERT')
			OR
			(e.evidence_kind='REMOVED' AND c.kind='REMOVED')
		  )
	)
) OR EXISTS (
	SELECT 1 FROM gdrive_topology_evidence e
	WHERE e.generation_id=NEW.generation_id
	  AND e.sequence<=NEW.publication_sequence
	  AND NOT EXISTS (
		SELECT 1 FROM gdrive_topology_evidence newer
		WHERE newer.generation_id=e.generation_id
		  AND newer.object_id=e.object_id
		  AND newer.sequence<=NEW.publication_sequence
		  AND (
			newer.sequence>e.sequence
			OR (newer.sequence=e.sequence AND newer.ordinal>e.ordinal)
		  )
	  )
	  AND NOT EXISTS (
		SELECT 1 FROM gdrive_topology_nodes n
		WHERE n.generation_id=e.generation_id
		  AND n.object_id=e.object_id
		  AND n.last_sequence=e.sequence
		  AND n.last_ordinal=e.ordinal
		  AND n.presence=e.presence
		  AND n.parent_state=e.parent_state
		  AND n.parent_id IS e.parent_id
		  AND n.drive_id=e.drive_id
	  )
) OR EXISTS (
	SELECT 1 FROM gdrive_topology_nodes n
	WHERE n.generation_id=NEW.generation_id
	  AND n.last_sequence>NEW.publication_sequence
)
BEGIN
	SELECT RAISE(ABORT, 'Google Drive topology watermark update does not match complete projection');
END;

CREATE TRIGGER gdrive_topology_nodes_delete_guard
BEFORE DELETE ON gdrive_topology_nodes
WHEN EXISTS (
	SELECT 1 FROM gdrive_topology_watermarks w
	WHERE w.generation_id=OLD.generation_id
)
BEGIN
	SELECT RAISE(ABORT, 'remove Google Drive topology watermark before rebuilding projection');
END;

CREATE TABLE gdrive_managed_root_bindings (
	generation_id TEXT NOT NULL
		REFERENCES remote_history_generations(generation_id) ON DELETE RESTRICT,
	managed_root_object_id TEXT NOT NULL,
	bound_sequence INTEGER NOT NULL CHECK (bound_sequence >= 1),
	created_at TEXT NOT NULL,
	PRIMARY KEY (generation_id, managed_root_object_id),
	FOREIGN KEY (generation_id, bound_sequence)
		REFERENCES remote_history_publications(generation_id, sequence) ON DELETE RESTRICT
) STRICT;

CREATE TRIGGER gdrive_managed_root_binding_insert_guard
BEFORE INSERT ON gdrive_managed_root_bindings
WHEN NOT EXISTS (
	SELECT 1 FROM remote_history_generations g
	WHERE g.generation_id=NEW.generation_id
	  AND g.provider_id='google-drive'
	  AND g.current_sequence=NEW.bound_sequence
	  AND (
		NEW.managed_root_object_id=g.root
		OR EXISTS (
			SELECT 1 FROM gdrive_topology_nodes n
			JOIN gdrive_topology_watermarks w
			  ON w.generation_id=n.generation_id
			WHERE n.generation_id=g.generation_id
			  AND n.object_id=NEW.managed_root_object_id
			  AND n.presence='PRESENT'
			  AND w.publication_sequence=NEW.bound_sequence
			  AND n.last_sequence<=w.publication_sequence
		)
	  )
)
BEGIN
	SELECT RAISE(ABORT, 'Google Drive managed root binding is not current in history universe');
END;

CREATE TRIGGER gdrive_managed_root_bindings_no_update
BEFORE UPDATE ON gdrive_managed_root_bindings
BEGIN
	SELECT RAISE(ABORT, 'Google Drive managed root bindings are immutable');
END;

CREATE TRIGGER gdrive_managed_root_bindings_no_delete
BEFORE DELETE ON gdrive_managed_root_bindings
BEGIN
	SELECT RAISE(ABORT, 'Google Drive managed root bindings are immutable');
END;
`,

		`
CREATE TRIGGER gdrive_topology_nodes_insert_requires_unwatermarked
BEFORE INSERT ON gdrive_topology_nodes
WHEN EXISTS (
	SELECT 1 FROM gdrive_topology_watermarks w
	WHERE w.generation_id=NEW.generation_id
)
BEGIN
	SELECT RAISE(ABORT, 'remove Google Drive topology watermark before mutating projection');
END;

CREATE TRIGGER gdrive_topology_nodes_update_requires_unwatermarked
BEFORE UPDATE ON gdrive_topology_nodes
WHEN EXISTS (
	SELECT 1 FROM gdrive_topology_watermarks w
	WHERE w.generation_id=NEW.generation_id
)
BEGIN
	SELECT RAISE(ABORT, 'remove Google Drive topology watermark before mutating projection');
END;
`,

		`
CREATE TABLE remote_scan_sources (
	scan_id TEXT PRIMARY KEY NOT NULL
		REFERENCES scan_sessions(scan_id) ON DELETE RESTRICT,
	generation_id TEXT NOT NULL,
	publication_sequence INTEGER NOT NULL CHECK (publication_sequence >= 1),
	source_scope_id TEXT NOT NULL CHECK (source_scope_id <> ''),
	materialization_policy_id TEXT NOT NULL CHECK (materialization_policy_id <> ''),
	snapshot_fingerprint_version TEXT NOT NULL CHECK (snapshot_fingerprint_version <> ''),
	snapshot_fingerprint_sha256 TEXT NOT NULL
		CHECK (
			length(snapshot_fingerprint_sha256) = 64
			AND snapshot_fingerprint_sha256 NOT GLOB '*[^0-9a-f]*'
		),
	FOREIGN KEY (generation_id, publication_sequence)
		REFERENCES remote_history_publications(generation_id, sequence) ON DELETE RESTRICT
) STRICT;

CREATE INDEX remote_scan_sources_replay
	ON remote_scan_sources (
		generation_id,
		publication_sequence,
		source_scope_id,
		materialization_policy_id,
		snapshot_fingerprint_version,
		snapshot_fingerprint_sha256
	);

CREATE TRIGGER remote_scan_sources_insert_guard
BEFORE INSERT ON remote_scan_sources
WHEN NOT EXISTS (
	SELECT 1
	FROM scan_sessions s
	JOIN remote_history_generations g
	  ON g.generation_id=NEW.generation_id
	WHERE s.scan_id=NEW.scan_id
	  AND s.status='OPEN'
	  AND s.provider_id=g.provider_id
	  AND g.status='ACTIVE'
	  AND g.current_sequence=NEW.publication_sequence
)
BEGIN
	SELECT RAISE(ABORT, 'remote scan source does not match OPEN scan/current history publication');
END;

CREATE TRIGGER remote_scan_sources_no_update
BEFORE UPDATE ON remote_scan_sources
BEGIN
	SELECT RAISE(ABORT, 'remote scan source provenance is immutable');
END;

CREATE TRIGGER remote_scan_sources_no_delete
BEFORE DELETE ON remote_scan_sources
BEGIN
	SELECT RAISE(ABORT, 'remote scan source provenance is immutable');
END;
`,

		`
CREATE TRIGGER remote_scan_session_update_guard
BEFORE UPDATE ON scan_sessions
WHEN EXISTS (
	SELECT 1
	FROM remote_scan_sources r
	WHERE r.scan_id=OLD.scan_id
)
AND NOT (
	NEW.scan_id=OLD.scan_id
	AND NEW.provider_id=OLD.provider_id
	AND NEW.root=OLD.root
	AND NEW.started_at=OLD.started_at
	AND OLD.status='OPEN'
	AND OLD.finished_at IS NULL
	AND NEW.status IN ('COMPLETE','ABORTED')
	AND NEW.finished_at IS NOT NULL
)
BEGIN
	SELECT RAISE(ABORT, 'source-bound remote scan session is immutable outside terminal transition');
END;

CREATE TRIGGER remote_scan_session_complete_source_guard
BEFORE UPDATE ON scan_sessions
WHEN EXISTS (
	SELECT 1
	FROM remote_scan_sources r
	WHERE r.scan_id=OLD.scan_id
)
AND OLD.status='OPEN'
AND NEW.status='COMPLETE'
AND NOT EXISTS (
	SELECT 1
	FROM remote_scan_sources r
	JOIN remote_history_generations g
	  ON g.generation_id=r.generation_id
	WHERE r.scan_id=OLD.scan_id
	  AND g.provider_id=OLD.provider_id
	  AND g.status='ACTIVE'
	  AND g.current_sequence=r.publication_sequence
)
BEGIN
	SELECT RAISE(ABORT, 'source-bound remote scan publication is no longer current');
END;
`,

		`
CREATE TRIGGER remote_scan_source_fingerprint_consistency_guard
BEFORE INSERT ON remote_scan_sources
WHEN EXISTS (
	SELECT 1
	FROM remote_scan_sources existing_source
	JOIN scan_sessions existing_scan
	  ON existing_scan.scan_id=existing_source.scan_id
	JOIN scan_sessions incoming_scan
	  ON incoming_scan.scan_id=NEW.scan_id
	WHERE existing_scan.root=incoming_scan.root
	  AND existing_source.generation_id=NEW.generation_id
	  AND existing_source.publication_sequence=NEW.publication_sequence
	  AND existing_source.source_scope_id=NEW.source_scope_id
	  AND existing_source.materialization_policy_id=NEW.materialization_policy_id
	  AND (
		existing_source.snapshot_fingerprint_version<>NEW.snapshot_fingerprint_version
		OR existing_source.snapshot_fingerprint_sha256<>NEW.snapshot_fingerprint_sha256
	  )
)
BEGIN
	SELECT RAISE(ABORT, 'remote scan source fingerprint conflicts with existing source boundary');
END;
`,

		`
CREATE TRIGGER provider_object_occurrences_no_update
BEFORE UPDATE ON provider_object_occurrences
BEGIN
	SELECT RAISE(ABORT, 'provider object occurrences are immutable');
END;

CREATE TRIGGER provider_object_occurrences_no_delete
BEFORE DELETE ON provider_object_occurrences
BEGIN
	SELECT RAISE(ABORT, 'provider object occurrences are immutable');
END;

CREATE TRIGGER observations_no_update
BEFORE UPDATE ON observations
BEGIN
	SELECT RAISE(ABORT, 'observations are immutable');
END;

CREATE TRIGGER observations_no_delete
BEFORE DELETE ON observations
BEGIN
	SELECT RAISE(ABORT, 'observations are immutable');
END;

CREATE TRIGGER locators_no_update
BEFORE UPDATE ON locators
BEGIN
	SELECT RAISE(ABORT, 'locators are immutable');
END;

CREATE TRIGGER locators_no_delete
BEFORE DELETE ON locators
BEGIN
	SELECT RAISE(ABORT, 'locators are immutable');
END;
`,

		`
CREATE TRIGGER observations_scan_insert_requires_open
BEFORE INSERT ON observations
WHEN NEW.scan_id IS NOT NULL
AND NOT EXISTS (
	SELECT 1 FROM scan_sessions s
	WHERE s.scan_id=NEW.scan_id
	  AND s.status='OPEN'
)
BEGIN
	SELECT RAISE(ABORT, 'scan-bound observations require an OPEN scan');
END;

CREATE TRIGGER locators_scan_insert_requires_open
BEFORE INSERT ON locators
WHEN EXISTS (
	SELECT 1
	FROM observations o
	JOIN scan_sessions s ON s.scan_id=o.scan_id
	WHERE o.observation_id=NEW.observation_id
	  AND s.status<>'OPEN'
)
BEGIN
	SELECT RAISE(ABORT, 'scan-bound locators require an OPEN scan');
END;

CREATE TRIGGER remote_managed_root_generic_complete_guard
BEFORE UPDATE ON scan_sessions
WHEN OLD.status='OPEN'
AND NEW.status='COMPLETE'
AND NOT EXISTS (
	SELECT 1 FROM remote_scan_sources current_source
	WHERE current_source.scan_id=OLD.scan_id
)
AND EXISTS (
	SELECT 1
	FROM remote_scan_sources prior_source
	JOIN scan_sessions prior_scan ON prior_scan.scan_id=prior_source.scan_id
	WHERE prior_scan.provider_id=OLD.provider_id
	  AND prior_scan.root=OLD.root
)
BEGIN
	SELECT RAISE(ABORT, 'remote-managed root requires source-bound completion');
END;

CREATE TRIGGER remote_scan_source_complete_replay_guard
BEFORE INSERT ON remote_scan_sources
WHEN EXISTS (
	SELECT 1
	FROM remote_scan_sources existing_source
	JOIN scan_sessions existing_scan ON existing_scan.scan_id=existing_source.scan_id
	JOIN scan_sessions incoming_scan ON incoming_scan.scan_id=NEW.scan_id
	WHERE existing_scan.provider_id=incoming_scan.provider_id
	  AND existing_scan.root=incoming_scan.root
	  AND existing_scan.status='COMPLETE'
	  AND existing_source.generation_id=NEW.generation_id
	  AND existing_source.publication_sequence=NEW.publication_sequence
	  AND existing_source.source_scope_id=NEW.source_scope_id
	  AND existing_source.materialization_policy_id=NEW.materialization_policy_id
	  AND existing_source.snapshot_fingerprint_version=NEW.snapshot_fingerprint_version
	  AND existing_source.snapshot_fingerprint_sha256=NEW.snapshot_fingerprint_sha256
)
BEGIN
	SELECT RAISE(ABORT, 'completed remote scan source must be replayed, not duplicated');
END;
`,

		`
CREATE TRIGGER scan_sessions_insert_requires_open
BEFORE INSERT ON scan_sessions
WHEN NOT (
	NEW.status='OPEN'
	AND NEW.finished_at IS NULL
	AND NEW.provider_id<>''
	AND NEW.root<>''
	AND julianday(NEW.started_at) IS NOT NULL
)
BEGIN
	SELECT RAISE(ABORT, 'scan sessions must be created OPEN with valid immutable scope/start');
END;

CREATE TRIGGER scan_sessions_lifecycle_update_guard
BEFORE UPDATE ON scan_sessions
WHEN NOT (
	NEW.scan_id=OLD.scan_id
	AND NEW.provider_id=OLD.provider_id
	AND NEW.root=OLD.root
	AND NEW.started_at=OLD.started_at
	AND OLD.status='OPEN'
	AND OLD.finished_at IS NULL
	AND NEW.status IN ('COMPLETE','ABORTED')
	AND NEW.finished_at IS NOT NULL
	AND julianday(OLD.started_at) IS NOT NULL
	AND julianday(NEW.finished_at) IS NOT NULL
	AND julianday(NEW.finished_at) >= julianday(OLD.started_at)
)
BEGIN
	SELECT RAISE(ABORT, 'invalid scan session lifecycle mutation');
END;

CREATE TRIGGER scan_sessions_no_delete
BEFORE DELETE ON scan_sessions
BEGIN
	SELECT RAISE(ABORT, 'scan sessions are durable authority and cannot be deleted');
END;
`,

		`
CREATE UNIQUE INDEX observations_occurrence_one_to_one
	ON observations (occurrence_id);

CREATE TRIGGER provider_object_occurrences_insert_structure_guard
BEFORE INSERT ON provider_object_occurrences
WHEN NEW.provider_id=''
	OR (
		NEW.identity_state='OBSERVED'
		AND (NEW.native_object_id IS NULL OR NEW.native_object_id='')
	)
BEGIN
	SELECT RAISE(ABORT, 'invalid provider object occurrence structure');
END;

CREATE TRIGGER observations_insert_structure_guard
BEFORE INSERT ON observations
WHEN NEW.mode>4294967295
	OR julianday(NEW.observed_at) IS NULL
	OR julianday(NEW.modified_at) IS NULL
	OR NOT EXISTS (
		SELECT 1
		FROM provider_object_occurrences p
		LEFT JOIN scan_sessions s ON s.scan_id=NEW.scan_id
		WHERE p.occurrence_id=NEW.occurrence_id
		  AND p.provider_id<>''
		  AND (
			NEW.scan_id IS NULL
			OR (
				s.scan_id=NEW.scan_id
				AND s.status='OPEN'
				AND s.provider_id=p.provider_id
			)
		  )
	)
BEGIN
	SELECT RAISE(ABORT, 'observation does not match durable occurrence/scan scope');
END;

CREATE TRIGGER observations_scan_observed_object_unique_guard
BEFORE INSERT ON observations
WHEN NEW.scan_id IS NOT NULL
AND EXISTS (
	SELECT 1
	FROM provider_object_occurrences incoming
	JOIN observations existing_observation
	  ON existing_observation.scan_id=NEW.scan_id
	JOIN provider_object_occurrences existing
	  ON existing.occurrence_id=existing_observation.occurrence_id
	WHERE incoming.occurrence_id=NEW.occurrence_id
	  AND incoming.identity_state='OBSERVED'
	  AND existing.identity_state='OBSERVED'
	  AND existing.provider_id=incoming.provider_id
	  AND existing.native_object_id=incoming.native_object_id
)
BEGIN
	SELECT RAISE(ABORT, 'scan already contains an observation for this provider object');
END;

CREATE TRIGGER locators_insert_structure_guard
BEFORE INSERT ON locators
WHEN NEW.provider_id=''
	OR NEW.root=''
	OR NEW.path=''
	OR NOT EXISTS (
		SELECT 1
		FROM observations o
		JOIN provider_object_occurrences p
		  ON p.occurrence_id=o.occurrence_id
		LEFT JOIN scan_sessions s
		  ON s.scan_id=o.scan_id
		WHERE o.observation_id=NEW.observation_id
		  AND p.provider_id=NEW.provider_id
		  AND (
			o.scan_id IS NULL
			OR (
				s.scan_id=o.scan_id
				AND s.status='OPEN'
				AND s.provider_id=NEW.provider_id
				AND s.root=NEW.root
			)
		  )
	)
BEGIN
	SELECT RAISE(ABORT, 'locator does not match observation/provider/scan scope');
END;

CREATE TRIGGER locators_scan_path_unique_guard
BEFORE INSERT ON locators
WHEN EXISTS (
	SELECT 1
	FROM observations incoming_observation
	JOIN observations existing_observation
	  ON existing_observation.scan_id=incoming_observation.scan_id
	 AND existing_observation.observation_id<>incoming_observation.observation_id
	JOIN locators existing_locator
	  ON existing_locator.observation_id=existing_observation.observation_id
	WHERE incoming_observation.observation_id=NEW.observation_id
	  AND incoming_observation.scan_id IS NOT NULL
	  AND existing_locator.provider_id=NEW.provider_id
	  AND existing_locator.root=NEW.root
	  AND existing_locator.path=NEW.path
)
BEGIN
	SELECT RAISE(ABORT, 'scan locator is already owned by another observation');
END;

CREATE TRIGGER scan_sessions_complete_observation_coverage_guard
BEFORE UPDATE ON scan_sessions
WHEN OLD.status='OPEN'
AND NEW.status='COMPLETE'
AND EXISTS (
	SELECT 1
	FROM observations o
	WHERE o.scan_id=OLD.scan_id
	  AND NOT EXISTS (
		SELECT 1 FROM locators l
		WHERE l.observation_id=o.observation_id
	  )
)
BEGIN
	SELECT RAISE(ABORT, 'COMPLETE scan contains an observation without a locator');
END;
`,

		`
CREATE TRIGGER remote_scan_session_complete_application_guard
BEFORE UPDATE ON scan_sessions
WHEN OLD.status='OPEN'
AND NEW.status='COMPLETE'
AND EXISTS (
	SELECT 1 FROM remote_scan_sources r
	WHERE r.scan_id=OLD.scan_id
)
AND keelaryn_remote_completion_authorized(OLD.scan_id)<>1
BEGIN
	SELECT RAISE(ABORT, 'source-bound remote scan completion requires validated application authorization');
END;
`,

		`
CREATE TABLE keelaryn_v25_time_validation (
	ok INTEGER NOT NULL CHECK (ok=1)
) STRICT;

INSERT INTO keelaryn_v25_time_validation (ok)
SELECT CASE
	WHEN EXISTS (
		SELECT 1
		FROM scan_sessions
		WHERE keelaryn_is_canonical_utc_rfc3339nano(started_at)<>1
		   OR (finished_at IS NOT NULL AND keelaryn_is_canonical_utc_rfc3339nano(finished_at)<>1)
	)
	OR EXISTS (
		SELECT 1
		FROM observations
		WHERE keelaryn_is_canonical_utc_rfc3339nano(observed_at)<>1
		   OR keelaryn_is_canonical_utc_rfc3339nano(modified_at)<>1
	)
	THEN 0
	ELSE 1
END;

DROP TABLE keelaryn_v25_time_validation;

CREATE TRIGGER scan_sessions_insert_canonical_time_guard
BEFORE INSERT ON scan_sessions
WHEN keelaryn_is_canonical_utc_rfc3339nano(NEW.started_at)<>1
	OR (
		NEW.finished_at IS NOT NULL
		AND keelaryn_is_canonical_utc_rfc3339nano(NEW.finished_at)<>1
	)
BEGIN
	SELECT RAISE(ABORT, 'scan session timestamps must be canonical UTC RFC3339Nano');
END;

CREATE TRIGGER scan_sessions_update_canonical_time_guard
BEFORE UPDATE ON scan_sessions
WHEN keelaryn_is_canonical_utc_rfc3339nano(NEW.started_at)<>1
	OR (
		NEW.finished_at IS NOT NULL
		AND keelaryn_is_canonical_utc_rfc3339nano(NEW.finished_at)<>1
	)
BEGIN
	SELECT RAISE(ABORT, 'scan session timestamps must be canonical UTC RFC3339Nano');
END;

CREATE TRIGGER observations_insert_canonical_time_guard
BEFORE INSERT ON observations
WHEN keelaryn_is_canonical_utc_rfc3339nano(NEW.observed_at)<>1
	OR keelaryn_is_canonical_utc_rfc3339nano(NEW.modified_at)<>1
BEGIN
	SELECT RAISE(ABORT, 'observation timestamps must be canonical UTC RFC3339Nano');
END;
`,

		`
CREATE TABLE keelaryn_v26_remote_history_time_validation (
	ok INTEGER NOT NULL CHECK (ok=1)
) STRICT;

INSERT INTO keelaryn_v26_remote_history_time_validation (ok)
SELECT CASE
	WHEN EXISTS (
		SELECT 1
		FROM remote_history_publications p
		WHERE keelaryn_is_canonical_utc_rfc3339nano(p.committed_at)<>1
	)
	OR EXISTS (
		SELECT 1
		FROM remote_history_publications p
		JOIN remote_history_generations g ON g.generation_id=p.generation_id
		WHERE p.kind='BOOTSTRAP'
		  AND (
			keelaryn_is_canonical_utc_rfc3339nano(g.created_at)<>1
			OR p.committed_at<>g.created_at
		  )
	)
	OR EXISTS (
		SELECT 1
		FROM remote_history_publications p
		LEFT JOIN remote_history_publications previous
		  ON previous.generation_id=p.generation_id
		 AND previous.sequence=p.sequence-1
		WHERE p.kind='INCREMENTAL'
		  AND (
			previous.sequence IS NULL
			OR NOT (
				p.committed_at=previous.committed_at
				OR keelaryn_utc_rfc3339nano_after(p.committed_at, previous.committed_at)=1
			)
		  )
	)
	OR EXISTS (
		SELECT 1
		FROM remote_scan_sources r
		JOIN scan_sessions s ON s.scan_id=r.scan_id
		JOIN remote_history_publications p
		  ON p.generation_id=r.generation_id
		 AND p.sequence=r.publication_sequence
		WHERE NOT (
			s.started_at=p.committed_at
			OR keelaryn_utc_rfc3339nano_after(s.started_at, p.committed_at)=1
		)
	)
	THEN 0
	ELSE 1
END;

DROP TABLE keelaryn_v26_remote_history_time_validation;

CREATE TRIGGER remote_history_publication_time_insert_guard
BEFORE INSERT ON remote_history_publications
WHEN keelaryn_is_canonical_utc_rfc3339nano(NEW.committed_at)<>1
	OR (
		NEW.kind='BOOTSTRAP'
		AND NOT EXISTS (
			SELECT 1
			FROM remote_history_generations g
			WHERE g.generation_id=NEW.generation_id
			  AND keelaryn_is_canonical_utc_rfc3339nano(g.created_at)=1
			  AND NEW.committed_at=g.created_at
		)
	)
	OR (
		NEW.kind='INCREMENTAL'
		AND NOT EXISTS (
			SELECT 1
			FROM remote_history_publications previous
			WHERE previous.generation_id=NEW.generation_id
			  AND previous.sequence=NEW.sequence-1
			  AND (
				NEW.committed_at=previous.committed_at
				OR keelaryn_utc_rfc3339nano_after(NEW.committed_at, previous.committed_at)=1
			  )
		)
	)
BEGIN
	SELECT RAISE(ABORT, 'remote history publication time is noncanonical or regresses');
END;

CREATE TRIGGER remote_scan_source_causal_time_insert_guard
BEFORE INSERT ON remote_scan_sources
WHEN NOT EXISTS (
	SELECT 1
	FROM scan_sessions s
	JOIN remote_history_publications p
	  ON p.generation_id=NEW.generation_id
	 AND p.sequence=NEW.publication_sequence
	WHERE s.scan_id=NEW.scan_id
	  AND (
		s.started_at=p.committed_at
		OR keelaryn_utc_rfc3339nano_after(s.started_at, p.committed_at)=1
	  )
)
BEGIN
	SELECT RAISE(ABORT, 'remote scan cannot start before its source publication');
END;
`,

		`
CREATE TRIGGER source_bound_assigned_observation_application_guard
BEFORE INSERT ON observations
WHEN NEW.scan_id IS NOT NULL
AND NEW.assignment_state='ASSIGNED'
AND EXISTS (
	SELECT 1 FROM remote_scan_sources r
	WHERE r.scan_id=NEW.scan_id
)
AND keelaryn_source_identity_mutation_authorized(NEW.scan_id)<>1
BEGIN
	SELECT RAISE(ABORT, 'source-bound assigned Observation requires validated identity mutation authorization');
END;

CREATE TRIGGER source_bound_continuity_application_guard
BEFORE INSERT ON accepted_continuity_decisions
WHEN EXISTS (
	SELECT 1
	FROM observations o
	JOIN remote_scan_sources r ON r.scan_id=o.scan_id
	WHERE o.observation_id=NEW.observation_id
)
AND keelaryn_source_identity_mutation_authorized(COALESCE((
	SELECT o.scan_id FROM observations o
	WHERE o.observation_id=NEW.observation_id
), ''))<>1
BEGIN
	SELECT RAISE(ABORT, 'source-bound continuity decision requires validated identity mutation authorization');
END;

CREATE TRIGGER source_bound_admission_application_guard
BEFORE INSERT ON accepted_artifact_admissions
WHEN EXISTS (
	SELECT 1
	FROM observations o
	JOIN remote_scan_sources r ON r.scan_id=o.scan_id
	WHERE o.observation_id=NEW.observation_id
)
AND keelaryn_source_identity_mutation_authorized(COALESCE((
	SELECT o.scan_id FROM observations o
	WHERE o.observation_id=NEW.observation_id
), ''))<>1
BEGIN
	SELECT RAISE(ABORT, 'source-bound admission requires validated identity mutation authorization');
END;

CREATE TRIGGER source_bound_identity_mutation_receipt_application_guard
BEFORE INSERT ON identity_mutation_requests
WHEN EXISTS (
	SELECT 1
	FROM observations o
	JOIN remote_scan_sources r ON r.scan_id=o.scan_id
	WHERE o.observation_id=NEW.observation_id
)
AND keelaryn_source_identity_mutation_authorized(COALESCE((
	SELECT o.scan_id FROM observations o
	WHERE o.observation_id=NEW.observation_id
), ''))<>1
BEGIN
	SELECT RAISE(ABORT, 'source-bound identity mutation receipt requires validated identity mutation authorization');
END;

CREATE TRIGGER provider_lifetime_binding_application_guard
BEFORE INSERT ON provider_lifetime_artifact_bindings
WHEN keelaryn_remote_history_binding_authorized(
	NEW.lifetime_segment_id,
	NEW.source_authority_set_id
)<>1
BEGIN
	SELECT RAISE(ABORT, 'RemoteHistory lifetime binding requires validated identity mutation authorization');
END;
`,

		`
CREATE TABLE keelaryn_v28_identity_causal_time_validation (
	ok INTEGER NOT NULL CHECK (ok=1)
) STRICT;

INSERT INTO keelaryn_v28_identity_causal_time_validation (ok)
SELECT CASE
	WHEN EXISTS (
		SELECT 1
		FROM identity_authority_sets a
		WHERE a.policy_id='remote-history:lifetime-segment:v1'
		  AND (
			keelaryn_is_canonical_utc_rfc3339nano(a.created_at)<>1
			OR NOT EXISTS (
				SELECT 1
				FROM remote_history_publications p
				WHERE p.generation_id=a.generation_id
				  AND keelaryn_remote_authority_publication_ref(
					a.source_refs_json,
					a.generation_id,
					CAST(p.sequence AS TEXT)
				  )=1
				  AND (
					a.created_at=p.committed_at
					OR keelaryn_utc_rfc3339nano_after(a.created_at,p.committed_at)=1
				  )
			)
		  )
	)
	OR EXISTS (
		SELECT 1
		FROM observations o
		JOIN remote_scan_sources r ON r.scan_id=o.scan_id
		JOIN scan_sessions s ON s.scan_id=o.scan_id
		WHERE o.assignment_state='ASSIGNED'
		  AND o.observed_at<>s.started_at
	)
	OR EXISTS (
		SELECT 1
		FROM accepted_continuity_decisions d
		JOIN observations o ON o.observation_id=d.observation_id
		JOIN remote_scan_sources r ON r.scan_id=o.scan_id
		JOIN scan_sessions s ON s.scan_id=o.scan_id
		WHERE keelaryn_is_canonical_utc_rfc3339nano(d.decided_at)<>1
		   OR NOT (
			d.decided_at=s.started_at
			OR keelaryn_utc_rfc3339nano_after(d.decided_at,s.started_at)=1
		   )
	)
	OR EXISTS (
		SELECT 1
		FROM accepted_artifact_admissions d
		JOIN observations o ON o.observation_id=d.observation_id
		JOIN remote_scan_sources r ON r.scan_id=o.scan_id
		JOIN scan_sessions s ON s.scan_id=o.scan_id
		WHERE keelaryn_is_canonical_utc_rfc3339nano(d.decided_at)<>1
		   OR NOT (
			d.decided_at=s.started_at
			OR keelaryn_utc_rfc3339nano_after(d.decided_at,s.started_at)=1
		   )
	)
	OR EXISTS (
		SELECT 1
		FROM identity_mutation_requests m
		JOIN observations o ON o.observation_id=m.observation_id
		JOIN remote_scan_sources r ON r.scan_id=o.scan_id
		JOIN scan_sessions s ON s.scan_id=o.scan_id
		JOIN identity_authority_sets a ON a.authority_set_id=m.authority_set_id
		WHERE keelaryn_is_canonical_utc_rfc3339nano(m.accepted_at)<>1
		   OR NOT (
			m.accepted_at=s.started_at
			OR keelaryn_utc_rfc3339nano_after(m.accepted_at,s.started_at)=1
		   )
		   OR NOT (
			m.accepted_at=a.created_at
			OR keelaryn_utc_rfc3339nano_after(m.accepted_at,a.created_at)=1
		   )
	)
	OR EXISTS (
		SELECT 1
		FROM provider_lifetime_artifact_bindings b
		JOIN identity_authority_sets a ON a.authority_set_id=b.source_authority_set_id
		WHERE keelaryn_is_canonical_utc_rfc3339nano(b.accepted_at)<>1
		   OR NOT (
			b.accepted_at=a.created_at
			OR keelaryn_utc_rfc3339nano_after(b.accepted_at,a.created_at)=1
		   )
	)
	THEN 0
	ELSE 1
END;

DROP TABLE keelaryn_v28_identity_causal_time_validation;

CREATE TRIGGER remote_history_authority_causal_time_insert_guard
BEFORE INSERT ON identity_authority_sets
WHEN NEW.policy_id='remote-history:lifetime-segment:v1'
AND (
	keelaryn_is_canonical_utc_rfc3339nano(NEW.created_at)<>1
	OR NOT EXISTS (
		SELECT 1
		FROM remote_history_generations g
		JOIN remote_history_publications p
		  ON p.generation_id=g.generation_id
		 AND p.sequence=g.current_sequence
		WHERE g.generation_id=NEW.generation_id
		  AND g.status='ACTIVE'
		  AND keelaryn_remote_authority_publication_ref(
			NEW.source_refs_json,
			NEW.generation_id,
			CAST(p.sequence AS TEXT)
		  )=1
		  AND (
			NEW.created_at=p.committed_at
			OR keelaryn_utc_rfc3339nano_after(NEW.created_at,p.committed_at)=1
		  )
	)
)
BEGIN
	SELECT RAISE(ABORT, 'RemoteHistory identity authority time is noncausal');
END;

CREATE TRIGGER source_bound_assigned_observation_time_guard
BEFORE INSERT ON observations
WHEN NEW.scan_id IS NOT NULL
AND NEW.assignment_state='ASSIGNED'
AND EXISTS (
	SELECT 1 FROM remote_scan_sources r
	WHERE r.scan_id=NEW.scan_id
)
AND NOT EXISTS (
	SELECT 1 FROM scan_sessions s
	WHERE s.scan_id=NEW.scan_id
	  AND NEW.observed_at=s.started_at
)
BEGIN
	SELECT RAISE(ABORT, 'source-bound assigned Observation time must equal scan boundary');
END;

CREATE TRIGGER source_bound_continuity_causal_time_guard
BEFORE INSERT ON accepted_continuity_decisions
WHEN EXISTS (
	SELECT 1
	FROM observations o
	JOIN remote_scan_sources r ON r.scan_id=o.scan_id
	WHERE o.observation_id=NEW.observation_id
)
AND NOT EXISTS (
	SELECT 1
	FROM observations o
	JOIN scan_sessions s ON s.scan_id=o.scan_id
	WHERE o.observation_id=NEW.observation_id
	  AND keelaryn_is_canonical_utc_rfc3339nano(NEW.decided_at)=1
	  AND (
		NEW.decided_at=s.started_at
		OR keelaryn_utc_rfc3339nano_after(NEW.decided_at,s.started_at)=1
	  )
)
BEGIN
	SELECT RAISE(ABORT, 'source-bound continuity decision time is noncausal');
END;

CREATE TRIGGER source_bound_admission_causal_time_guard
BEFORE INSERT ON accepted_artifact_admissions
WHEN EXISTS (
	SELECT 1
	FROM observations o
	JOIN remote_scan_sources r ON r.scan_id=o.scan_id
	WHERE o.observation_id=NEW.observation_id
)
AND NOT EXISTS (
	SELECT 1
	FROM observations o
	JOIN scan_sessions s ON s.scan_id=o.scan_id
	WHERE o.observation_id=NEW.observation_id
	  AND keelaryn_is_canonical_utc_rfc3339nano(NEW.decided_at)=1
	  AND (
		NEW.decided_at=s.started_at
		OR keelaryn_utc_rfc3339nano_after(NEW.decided_at,s.started_at)=1
	  )
)
BEGIN
	SELECT RAISE(ABORT, 'source-bound admission decision time is noncausal');
END;

CREATE TRIGGER source_bound_identity_mutation_receipt_causal_time_guard
BEFORE INSERT ON identity_mutation_requests
WHEN EXISTS (
	SELECT 1
	FROM observations o
	JOIN remote_scan_sources r ON r.scan_id=o.scan_id
	WHERE o.observation_id=NEW.observation_id
)
AND NOT EXISTS (
	SELECT 1
	FROM observations o
	JOIN scan_sessions s ON s.scan_id=o.scan_id
	JOIN identity_authority_sets a ON a.authority_set_id=NEW.authority_set_id
	WHERE o.observation_id=NEW.observation_id
	  AND keelaryn_is_canonical_utc_rfc3339nano(NEW.accepted_at)=1
	  AND (
		NEW.accepted_at=s.started_at
		OR keelaryn_utc_rfc3339nano_after(NEW.accepted_at,s.started_at)=1
	  )
	  AND (
		NEW.accepted_at=a.created_at
		OR keelaryn_utc_rfc3339nano_after(NEW.accepted_at,a.created_at)=1
	  )
)
BEGIN
	SELECT RAISE(ABORT, 'source-bound identity mutation receipt time is noncausal');
END;

CREATE TRIGGER provider_lifetime_binding_causal_time_guard
BEFORE INSERT ON provider_lifetime_artifact_bindings
WHEN NOT EXISTS (
	SELECT 1
	FROM identity_authority_sets a
	WHERE a.authority_set_id=NEW.source_authority_set_id
	  AND keelaryn_is_canonical_utc_rfc3339nano(NEW.accepted_at)=1
	  AND (
		NEW.accepted_at=a.created_at
		OR keelaryn_utc_rfc3339nano_after(NEW.accepted_at,a.created_at)=1
	  )
)
BEGIN
	SELECT RAISE(ABORT, 'RemoteHistory lifetime binding time is noncausal');
END;
`,

		`
CREATE TABLE keelaryn_v29_remote_identity_causal_validation (
	ok INTEGER NOT NULL CHECK (ok=1)
) STRICT;

INSERT INTO keelaryn_v29_remote_identity_causal_validation (ok)
SELECT CASE
	WHEN EXISTS (
		SELECT 1
		FROM identity_mutation_requests m
		JOIN identity_authority_sets a
		  ON a.authority_set_id=m.authority_set_id
		JOIN observations o
		  ON o.observation_id=m.observation_id
		JOIN scan_sessions s
		  ON s.scan_id=o.scan_id
		WHERE a.policy_id='remote-history:lifetime-segment:v1'
		  AND (
			keelaryn_is_canonical_utc_rfc3339nano(m.accepted_at)<>1
			OR NOT (
				m.accepted_at=s.started_at
				OR keelaryn_utc_rfc3339nano_after(m.accepted_at,s.started_at)=1
			)
			OR NOT (
				m.accepted_at=a.created_at
				OR keelaryn_utc_rfc3339nano_after(m.accepted_at,a.created_at)=1
			)
			OR (
				m.decision_kind='CONTINUITY'
				AND NOT EXISTS (
					SELECT 1
					FROM accepted_continuity_decisions d
					WHERE d.decision_id=m.decision_id
					  AND d.observation_id=m.observation_id
					  AND d.artifact_id=m.artifact_id
					  AND d.policy_id='remote-history:lifetime-segment:v1'
					  AND d.decided_at=m.accepted_at
				)
			)
			OR (
				m.decision_kind='ADMISSION'
				AND NOT EXISTS (
					SELECT 1
					FROM accepted_artifact_admissions d
					WHERE d.request_id=m.decision_id
					  AND d.observation_id=m.observation_id
					  AND d.artifact_id=m.artifact_id
					  AND d.policy_id='remote-history:lifetime-segment:v1'
					  AND d.decided_at=m.accepted_at
				)
			)
		  )
	)
	THEN 0
	ELSE 1
END;

DROP TABLE keelaryn_v29_remote_identity_causal_validation;

CREATE TRIGGER remote_history_continuity_application_causal_guard
BEFORE INSERT ON accepted_continuity_decisions
WHEN NEW.policy_id='remote-history:lifetime-segment:v1'
AND (
	keelaryn_identity_mutation_authorized(COALESCE((
		SELECT o.scan_id
		FROM observations o
		WHERE o.observation_id=NEW.observation_id
	), ''))<>1
	OR NOT EXISTS (
		SELECT 1
		FROM observations o
		JOIN scan_sessions s ON s.scan_id=o.scan_id
		WHERE o.observation_id=NEW.observation_id
		  AND keelaryn_is_canonical_utc_rfc3339nano(NEW.decided_at)=1
		  AND (
			NEW.decided_at=s.started_at
			OR keelaryn_utc_rfc3339nano_after(NEW.decided_at,s.started_at)=1
		  )
	)
)
BEGIN
	SELECT RAISE(ABORT, 'RemoteHistory continuity decision lacks validated causal identity mutation authority');
END;

CREATE TRIGGER remote_history_admission_application_causal_guard
BEFORE INSERT ON accepted_artifact_admissions
WHEN NEW.policy_id='remote-history:lifetime-segment:v1'
AND (
	keelaryn_identity_mutation_authorized(COALESCE((
		SELECT o.scan_id
		FROM observations o
		WHERE o.observation_id=NEW.observation_id
	), ''))<>1
	OR NOT EXISTS (
		SELECT 1
		FROM observations o
		JOIN scan_sessions s ON s.scan_id=o.scan_id
		WHERE o.observation_id=NEW.observation_id
		  AND keelaryn_is_canonical_utc_rfc3339nano(NEW.decided_at)=1
		  AND (
			NEW.decided_at=s.started_at
			OR keelaryn_utc_rfc3339nano_after(NEW.decided_at,s.started_at)=1
		  )
	)
)
BEGIN
	SELECT RAISE(ABORT, 'RemoteHistory admission decision lacks validated causal identity mutation authority');
END;

CREATE TRIGGER remote_history_identity_mutation_receipt_application_causal_guard
BEFORE INSERT ON identity_mutation_requests
WHEN EXISTS (
	SELECT 1
	FROM identity_authority_sets a
	WHERE a.authority_set_id=NEW.authority_set_id
	  AND a.policy_id='remote-history:lifetime-segment:v1'
)
AND (
	keelaryn_identity_mutation_authorized(COALESCE((
		SELECT o.scan_id
		FROM observations o
		WHERE o.observation_id=NEW.observation_id
	), ''))<>1
	OR NOT EXISTS (
		SELECT 1
		FROM observations o
		JOIN scan_sessions s ON s.scan_id=o.scan_id
		JOIN identity_authority_sets a ON a.authority_set_id=NEW.authority_set_id
		WHERE o.observation_id=NEW.observation_id
		  AND keelaryn_is_canonical_utc_rfc3339nano(NEW.accepted_at)=1
		  AND (
			NEW.accepted_at=s.started_at
			OR keelaryn_utc_rfc3339nano_after(NEW.accepted_at,s.started_at)=1
		  )
		  AND (
			NEW.accepted_at=a.created_at
			OR keelaryn_utc_rfc3339nano_after(NEW.accepted_at,a.created_at)=1
		  )
		  AND (
			(
				NEW.decision_kind='CONTINUITY'
				AND EXISTS (
					SELECT 1
					FROM accepted_continuity_decisions d
					WHERE d.decision_id=NEW.decision_id
					  AND d.observation_id=NEW.observation_id
					  AND d.artifact_id=NEW.artifact_id
					  AND d.policy_id='remote-history:lifetime-segment:v1'
					  AND d.decided_at=NEW.accepted_at
				)
			)
			OR
			(
				NEW.decision_kind='ADMISSION'
				AND EXISTS (
					SELECT 1
					FROM accepted_artifact_admissions d
					WHERE d.request_id=NEW.decision_id
					  AND d.observation_id=NEW.observation_id
					  AND d.artifact_id=NEW.artifact_id
					  AND d.policy_id='remote-history:lifetime-segment:v1'
					  AND d.decided_at=NEW.accepted_at
				)
			)
		  )
	)
)
BEGIN
	SELECT RAISE(ABORT, 'RemoteHistory identity mutation receipt lacks validated causal authority');
END;
`,

		`
CREATE TABLE keelaryn_v30_remote_identity_existing_state_validation (
	ok INTEGER NOT NULL CHECK (ok=1)
) STRICT;

INSERT INTO keelaryn_v30_remote_identity_existing_state_validation (ok)
SELECT CASE
	WHEN EXISTS (
		SELECT 1
		FROM identity_mutation_requests m
		JOIN identity_authority_sets a
		  ON a.authority_set_id=m.authority_set_id
		JOIN observations o
		  ON o.observation_id=m.observation_id
		LEFT JOIN scan_sessions s
		  ON s.scan_id=o.scan_id
		WHERE a.policy_id='remote-history:lifetime-segment:v1'
		  AND (
			o.scan_id IS NULL
			OR s.scan_id IS NULL
			OR keelaryn_is_canonical_utc_rfc3339nano(m.accepted_at)<>1
			OR NOT (
				m.accepted_at=s.started_at
				OR keelaryn_utc_rfc3339nano_after(m.accepted_at,s.started_at)=1
			)
			OR NOT (
				m.accepted_at=a.created_at
				OR keelaryn_utc_rfc3339nano_after(m.accepted_at,a.created_at)=1
			)
			OR (
				m.decision_kind='CONTINUITY'
				AND NOT EXISTS (
					SELECT 1
					FROM accepted_continuity_decisions d
					WHERE d.decision_id=m.decision_id
					  AND d.observation_id=m.observation_id
					  AND d.artifact_id=m.artifact_id
					  AND d.policy_id='remote-history:lifetime-segment:v1'
					  AND d.decided_at=m.accepted_at
				)
			)
			OR (
				m.decision_kind='ADMISSION'
				AND NOT EXISTS (
					SELECT 1
					FROM accepted_artifact_admissions d
					WHERE d.request_id=m.decision_id
					  AND d.observation_id=m.observation_id
					  AND d.artifact_id=m.artifact_id
					  AND d.policy_id='remote-history:lifetime-segment:v1'
					  AND d.decided_at=m.accepted_at
				)
			)
		  )
	)
	THEN 0
	ELSE 1
END;

DROP TABLE keelaryn_v30_remote_identity_existing_state_validation;
`,

		`
CREATE TABLE keelaryn_v31_remote_identity_reverse_provenance_validation (
	ok INTEGER NOT NULL CHECK (ok=1)
) STRICT;

INSERT INTO keelaryn_v31_remote_identity_reverse_provenance_validation (ok)
SELECT CASE
	WHEN EXISTS (
		SELECT 1
		FROM accepted_continuity_decisions d
		JOIN observations o ON o.observation_id=d.observation_id
		JOIN provider_object_occurrences p ON p.occurrence_id=o.occurrence_id
		WHERE d.policy_id='remote-history:lifetime-segment:v1'
		  AND NOT EXISTS (
			SELECT 1
			FROM identity_mutation_requests m
			JOIN identity_authority_sets a ON a.authority_set_id=m.authority_set_id
			WHERE m.operation_kind='SAME'
			  AND m.decision_kind='CONTINUITY'
			  AND m.decision_id=d.decision_id
			  AND m.observation_id=d.observation_id
			  AND m.artifact_id=d.artifact_id
			  AND m.accepted_at=d.decided_at
			  AND a.policy_id=d.policy_id
			  AND a.lifetime_segment_id=d.lifetime_segment_id
			  AND a.provider_id=p.provider_id
			  AND a.current_object_id=p.native_object_id
		  )
	)
	OR EXISTS (
		SELECT 1
		FROM accepted_artifact_admissions d
		WHERE d.policy_id='remote-history:lifetime-segment:v1'
		  AND NOT EXISTS (
			SELECT 1
			FROM identity_mutation_requests m
			JOIN identity_authority_sets a ON a.authority_set_id=m.authority_set_id
			JOIN provider_lifetime_artifact_bindings b
			  ON b.lifetime_segment_id=d.lifetime_segment_id
			WHERE m.request_id=d.request_id
			  AND m.operation_kind='NEW'
			  AND m.decision_kind='ADMISSION'
			  AND m.decision_id=d.request_id
			  AND m.observation_id=d.observation_id
			  AND m.artifact_id=d.artifact_id
			  AND m.accepted_at=d.decided_at
			  AND a.policy_id=d.policy_id
			  AND a.identity_domain=d.identity_domain
			  AND a.provider_id=d.provider_id
			  AND a.current_object_id=d.native_object_id
			  AND a.lifetime_segment_id=d.lifetime_segment_id
			  AND b.artifact_id=d.artifact_id
			  AND b.policy_id=d.policy_id
			  AND b.source_authority_set_id=m.authority_set_id
			  AND b.accepted_at=d.decided_at
		  )
	)
	OR EXISTS (
		SELECT 1
		FROM provider_lifetime_artifact_bindings b
		WHERE b.policy_id='remote-history:lifetime-segment:v1'
		  AND NOT EXISTS (
			SELECT 1
			FROM accepted_artifact_admissions d
			JOIN identity_mutation_requests m
			  ON m.request_id=d.request_id
			 AND m.operation_kind='NEW'
			 AND m.decision_kind='ADMISSION'
			 AND m.decision_id=d.request_id
			 AND m.observation_id=d.observation_id
			 AND m.artifact_id=d.artifact_id
			JOIN identity_authority_sets a
			  ON a.authority_set_id=m.authority_set_id
			WHERE d.policy_id=b.policy_id
			  AND d.lifetime_segment_id=b.lifetime_segment_id
			  AND d.artifact_id=b.artifact_id
			  AND d.decided_at=b.accepted_at
			  AND m.authority_set_id=b.source_authority_set_id
			  AND m.accepted_at=b.accepted_at
			  AND a.policy_id=b.policy_id
			  AND a.lifetime_segment_id=b.lifetime_segment_id
			  AND a.authority_set_id=b.source_authority_set_id
		  )
	)
	THEN 0
	ELSE 1
END;

DROP TABLE keelaryn_v31_remote_identity_reverse_provenance_validation;
`,

		`
CREATE UNIQUE INDEX accepted_admission_remote_lifetime_unique
	ON accepted_artifact_admissions (lifetime_segment_id)
	WHERE lifetime_segment_id IS NOT NULL;
`,

		`
CREATE TRIGGER artifacts_no_update
BEFORE UPDATE ON artifacts
BEGIN
	SELECT RAISE(ABORT, 'Artifacts are immutable');
END;

CREATE TRIGGER artifacts_no_delete
BEFORE DELETE ON artifacts
BEGIN
	SELECT RAISE(ABORT, 'Artifacts are immutable');
END;

CREATE TRIGGER revisions_no_update
BEFORE UPDATE ON revisions
BEGIN
	SELECT RAISE(ABORT, 'Revisions are immutable');
END;

CREATE TRIGGER revisions_no_delete
BEFORE DELETE ON revisions
BEGIN
	SELECT RAISE(ABORT, 'Revisions are immutable');
END;

CREATE TRIGGER provider_artifact_bindings_no_update
BEFORE UPDATE ON provider_artifact_bindings
BEGIN
	SELECT RAISE(ABORT, 'provider Artifact bindings are immutable');
END;

CREATE TRIGGER provider_artifact_bindings_no_delete
BEFORE DELETE ON provider_artifact_bindings
BEGIN
	SELECT RAISE(ABORT, 'provider Artifact bindings are immutable');
END;
`,

		`
CREATE TABLE keelaryn_v34_gdrive_topology_watermark_validation (
	ok INTEGER NOT NULL CHECK (ok=1)
) STRICT;

INSERT INTO keelaryn_v34_gdrive_topology_watermark_validation (ok)
SELECT CASE
	WHEN EXISTS (
		SELECT 1
		FROM remote_history_generations g
		WHERE g.provider_id='google-drive'
		  AND NOT EXISTS (
			SELECT 1
			FROM gdrive_topology_watermarks w
			WHERE w.generation_id=g.generation_id
			  AND w.publication_sequence=g.current_sequence
		  )
	)
	THEN 0
	ELSE 1
END;

DROP TABLE keelaryn_v34_gdrive_topology_watermark_validation;

CREATE TRIGGER gdrive_topology_watermark_delete_application_guard
BEFORE DELETE ON gdrive_topology_watermarks
WHEN keelaryn_gdrive_topology_watermark_delete_authorized(
	OLD.generation_id,
	CAST(OLD.publication_sequence AS TEXT)
)<>1
BEGIN
	SELECT RAISE(ABORT, 'Google Drive topology watermark removal requires validated application authority');
END;

CREATE TRIGGER gdrive_topology_watermarks_no_update_v34
BEFORE UPDATE ON gdrive_topology_watermarks
BEGIN
	SELECT RAISE(ABORT, 'Google Drive topology watermark updates are forbidden; rebuild through controlled delete/project/insert');
END;
`,

		`
CREATE TABLE keelaryn_v35_core_identity_insert_validation (
	ok INTEGER NOT NULL CHECK (ok=1)
) STRICT;

INSERT INTO keelaryn_v35_core_identity_insert_validation (ok)
SELECT CASE
	WHEN EXISTS (
		SELECT 1
		FROM revisions r
		WHERE r.sequence <> (
			SELECT COUNT(*)
			FROM revisions p
			WHERE p.artifact_id=r.artifact_id
			  AND p.sequence<=r.sequence
		)
	)
	THEN 0
	ELSE 1
END;

DROP TABLE keelaryn_v35_core_identity_insert_validation;

CREATE TRIGGER artifacts_insert_application_guard
BEFORE INSERT ON artifacts
WHEN keelaryn_artifact_insert_authorized(NEW.artifact_id)<>1
BEGIN
	SELECT RAISE(ABORT, 'Artifact creation requires validated application authority');
END;

CREATE TRIGGER revisions_insert_application_guard
BEFORE INSERT ON revisions
WHEN keelaryn_revision_insert_authorized(
	NEW.revision_id,
	NEW.artifact_id,
	CAST(NEW.sequence AS TEXT),
	NEW.content_algorithm,
	NEW.content_digest,
	CAST(NEW.content_size AS TEXT)
)<>1
BEGIN
	SELECT RAISE(ABORT, 'Revision creation requires validated application authority');
END;

CREATE TRIGGER provider_artifact_bindings_insert_application_guard
BEFORE INSERT ON provider_artifact_bindings
WHEN keelaryn_provider_artifact_binding_insert_authorized(
	NEW.identity_domain,
	NEW.provider_id,
	NEW.native_object_id,
	NEW.artifact_id,
	NEW.policy_id,
	NEW.accepted_at
)<>1
BEGIN
	SELECT RAISE(ABORT, 'provider Artifact binding creation requires validated application authority');
END;
`,

		`
CREATE TABLE keelaryn_v36_identity_authority_creation_validation (
	ok INTEGER NOT NULL CHECK (ok=1)
) STRICT;

INSERT INTO keelaryn_v36_identity_authority_creation_validation (ok)
SELECT CASE
	WHEN EXISTS (
		SELECT 1
		FROM identity_authority_sets a
		WHERE a.sealed_at IS NULL
		   OR a.sealed_at<>a.created_at
	)
	THEN 0
	ELSE 1
END;

DROP TABLE keelaryn_v36_identity_authority_creation_validation;

CREATE TRIGGER identity_authority_sets_insert_application_guard_v36
BEFORE INSERT ON identity_authority_sets
WHEN keelaryn_identity_authority_set_insert_authorized(
	NEW.authority_set_id,
	NEW.policy_id,
	NEW.provider_id,
	NEW.identity_domain,
	NEW.scope_id,
	NEW.current_object_id,
	NEW.universe_coverage,
	COALESCE(NEW.generation_id,''),
	COALESCE(NEW.lifetime_segment_id,''),
	NEW.source_refs_json,
	NEW.created_at,
	COALESCE(NEW.sealed_at,'')
)<>1
BEGIN
	SELECT RAISE(ABORT, 'identity authority set creation requires validated application authority');
END;

CREATE TRIGGER identity_authority_candidates_insert_application_guard_v36
BEFORE INSERT ON identity_authority_candidates
WHEN keelaryn_identity_authority_candidate_insert_authorized(
	NEW.authority_set_id,
	NEW.artifact_id,
	NEW.direction,
	NEW.source_ref
)<>1
BEGIN
	SELECT RAISE(ABORT, 'identity authority candidate creation requires validated application authority');
END;

CREATE TRIGGER identity_authority_sets_seal_application_guard_v36
BEFORE UPDATE ON identity_authority_sets
WHEN OLD.sealed_at IS NULL
AND NEW.sealed_at IS NOT NULL
AND keelaryn_identity_authority_seal_authorized(
	NEW.authority_set_id,
	NEW.sealed_at
)<>1
BEGIN
	SELECT RAISE(ABORT, 'identity authority sealing requires validated application authority');
END;
`,

		`
CREATE TABLE keelaryn_v37_identity_authority_structural_validation (
	ok INTEGER NOT NULL CHECK (ok=1)
) STRICT;

INSERT INTO keelaryn_v37_identity_authority_structural_validation (ok)
SELECT CASE
	WHEN EXISTS (
		SELECT 1
		FROM identity_authority_sets a
		WHERE a.sealed_at IS NULL
		   OR a.sealed_at<>a.created_at
		   OR keelaryn_identity_authority_set_structurally_valid(
				a.authority_set_id,
				a.policy_id,
				a.provider_id,
				a.identity_domain,
				a.scope_id,
				a.current_object_id,
				a.universe_coverage,
				COALESCE(a.generation_id,''),
				COALESCE(a.lifetime_segment_id,''),
				a.source_refs_json,
				a.created_at
		   )<>1
	)
	OR EXISTS (
		SELECT 1
		FROM identity_authority_candidates c
		WHERE keelaryn_identity_authority_candidate_structurally_valid(
			c.artifact_id,
			c.direction,
			c.source_ref
		)<>1
	)
	THEN 0
	ELSE 1
END;

DROP TABLE keelaryn_v37_identity_authority_structural_validation;
`,

	},
}

// Store owns durable, non-rebuildable Keelaryn identity state.
//
// The path is runtime-local control state. This package does not know or store
// corpus file bytes, Locators, extracted text, previews, embeddings, or search
// indexes.
const (
	remoteCompletionAuthorizationFunction = "keelaryn_remote_completion_authorized"
	canonicalUTCRFC3339NanoFunction       = "keelaryn_is_canonical_utc_rfc3339nano"
	utcRFC3339NanoAfterFunction                  = "keelaryn_utc_rfc3339nano_after"
	sourceIdentityMutationAuthorizationFunction  = "keelaryn_source_identity_mutation_authorized"
	identityMutationAuthorizationFunction        = "keelaryn_identity_mutation_authorized"
	remoteHistoryBindingAuthorizationFunction    = "keelaryn_remote_history_binding_authorized"
	remoteAuthorityPublicationRefFunction        = "keelaryn_remote_authority_publication_ref"
	gdriveTopologyWatermarkDeleteAuthorizationFunction = "keelaryn_gdrive_topology_watermark_delete_authorized"
	artifactInsertAuthorizationFunction = "keelaryn_artifact_insert_authorized"
	revisionInsertAuthorizationFunction = "keelaryn_revision_insert_authorized"
	providerArtifactBindingInsertAuthorizationFunction = "keelaryn_provider_artifact_binding_insert_authorized"
	identityAuthoritySetInsertAuthorizationFunction = "keelaryn_identity_authority_set_insert_authorized"
	identityAuthorityCandidateInsertAuthorizationFunction = "keelaryn_identity_authority_candidate_insert_authorized"
	identityAuthoritySealAuthorizationFunction = "keelaryn_identity_authority_seal_authorized"
	identityAuthoritySetStructuralValidationFunction = "keelaryn_identity_authority_set_structurally_valid"
	identityAuthorityCandidateStructuralValidationFunction = "keelaryn_identity_authority_candidate_structurally_valid"
)

type remoteCompletionAuthorization struct {
	scanID corpus.ScanSessionID
}

type identityMutationAuthorization struct {
	scanID            corpus.ScanSessionID
	lifetimeSegmentID remotehistory.ProviderObjectLifetimeSegmentID
	authoritySetID    corpus.IdentityAuthoritySetID
}

type gdriveTopologyWatermarkDeleteAuthorization struct {
	generationID        remotehistory.HistoryGenerationID
	publicationSequence remotehistory.HistoryPublicationSequence
}

type coreIdentityInsertAuthorization struct {
	kind             string
	artifactID       corpus.ArtifactID
	revisionID       corpus.RevisionID
	revisionSequence uint64
	algorithm        string
	digest           string
	contentSize      int64
	identityDomain   string
	providerID       corpus.ProviderID
	providerObjectID corpus.ProviderObjectID
	policyID         string
	acceptedAt       string
}

type identityAuthorityWriteAuthorization struct {
	kind              string
	authoritySetID    corpus.IdentityAuthoritySetID
	policyID          string
	providerID        corpus.ProviderID
	identityDomain    string
	scopeID           string
	currentObjectID   corpus.ProviderObjectID
	universeCoverage  corpus.CandidateUniverseCoverage
	generationID      string
	lifetimeSegmentID string
	sourceRefsJSON    string
	createdAt         string
	sealedAt          string
	candidateArtifactID corpus.ArtifactID
	candidateDirection  corpus.ContinuityDirection
	candidateSourceRef  string
}

type Store struct {
	pool                                      *sqlitemigration.Pool
	path                                      string
	remoteCompletionAuthorizations            sync.Map
	identityMutationAuthorizations            sync.Map
	gdriveTopologyWatermarkDeleteAuthorizations sync.Map
	coreIdentityInsertAuthorizations              sync.Map
	identityAuthorityWriteAuthorizations           sync.Map
}

func (s *Store) prepareConn(conn *sqlite.Conn) error {
	if err := sqlitex.ExecuteTransient(conn, "PRAGMA foreign_keys = ON", nil); err != nil {
		return err
	}
	auth := &remoteCompletionAuthorization{}
	if err := conn.CreateFunction(remoteCompletionAuthorizationFunction, &sqlite.FunctionImpl{
		NArgs:         1,
		Deterministic: false,
		AllowIndirect: true,
		Scalar: func(_ sqlite.Context, args []sqlite.Value) (sqlite.Value, error) {
			if auth.scanID != "" && string(auth.scanID) == args[0].Text() {
				return sqlite.IntegerValue(1), nil
			}
			return sqlite.IntegerValue(0), nil
		},
	}); err != nil {
		return fmt.Errorf("register remote completion authorization function: %w", err)
	}
	if err := conn.CreateFunction(canonicalUTCRFC3339NanoFunction, &sqlite.FunctionImpl{
		NArgs:         1,
		Deterministic: true,
		AllowIndirect: true,
		Scalar: func(_ sqlite.Context, args []sqlite.Value) (sqlite.Value, error) {
			raw := args[0].Text()
			parsed, err := time.Parse(time.RFC3339Nano, raw)
			if err != nil || raw != parsed.UTC().Format(time.RFC3339Nano) {
				return sqlite.IntegerValue(0), nil
			}
			return sqlite.IntegerValue(1), nil
		},
	}); err != nil {
		return fmt.Errorf("register canonical timestamp function: %w", err)
	}
	if err := conn.CreateFunction(utcRFC3339NanoAfterFunction, &sqlite.FunctionImpl{
		NArgs:         2,
		Deterministic: true,
		AllowIndirect: true,
		Scalar: func(_ sqlite.Context, args []sqlite.Value) (sqlite.Value, error) {
			leftRaw, rightRaw := args[0].Text(), args[1].Text()
			left, leftErr := time.Parse(time.RFC3339Nano, leftRaw)
			right, rightErr := time.Parse(time.RFC3339Nano, rightRaw)
			if leftErr != nil || rightErr != nil ||
				leftRaw != left.UTC().Format(time.RFC3339Nano) ||
				rightRaw != right.UTC().Format(time.RFC3339Nano) {
				return sqlite.IntegerValue(0), nil
			}
			if left.After(right) {
				return sqlite.IntegerValue(1), nil
			}
			return sqlite.IntegerValue(0), nil
		},
	}); err != nil {
		return fmt.Errorf("register timestamp ordering function: %w", err)
	}
	if err := conn.CreateFunction(remoteAuthorityPublicationRefFunction, &sqlite.FunctionImpl{
		NArgs:         3,
		Deterministic: true,
		AllowIndirect: true,
		Scalar: func(_ sqlite.Context, args []sqlite.Value) (sqlite.Value, error) {
			var refs []string
			if err := json.Unmarshal([]byte(args[0].Text()), &refs); err != nil {
				return sqlite.IntegerValue(0), nil
			}
			want := "history-publication:" + args[1].Text() + ":" + args[2].Text()
			publicationRefs := 0
			matched := false
			for _, ref := range refs {
				if strings.HasPrefix(ref, "history-publication:") {
					publicationRefs++
					if ref == want {
						matched = true
					}
				}
			}
			if publicationRefs == 1 && matched {
				return sqlite.IntegerValue(1), nil
			}
			return sqlite.IntegerValue(0), nil
		},
	}); err != nil {
		return fmt.Errorf("register RemoteHistory authority publication-ref function: %w", err)
	}
	s.remoteCompletionAuthorizations.Store(conn, auth)

	identityAuth := &identityMutationAuthorization{}
	if err := conn.CreateFunction(sourceIdentityMutationAuthorizationFunction, &sqlite.FunctionImpl{
		NArgs:         1,
		Deterministic: false,
		AllowIndirect: true,
		Scalar: func(_ sqlite.Context, args []sqlite.Value) (sqlite.Value, error) {
			if identityAuth.scanID != "" && string(identityAuth.scanID) == args[0].Text() {
				return sqlite.IntegerValue(1), nil
			}
			return sqlite.IntegerValue(0), nil
		},
	}); err != nil {
		return fmt.Errorf("register source identity mutation authorization function: %w", err)
	}
	if err := conn.CreateFunction(identityMutationAuthorizationFunction, &sqlite.FunctionImpl{
		NArgs:         1,
		Deterministic: false,
		AllowIndirect: true,
		Scalar: func(_ sqlite.Context, args []sqlite.Value) (sqlite.Value, error) {
			if identityAuth.scanID != "" && string(identityAuth.scanID) == args[0].Text() {
				return sqlite.IntegerValue(1), nil
			}
			return sqlite.IntegerValue(0), nil
		},
	}); err != nil {
		return fmt.Errorf("register identity mutation authorization function: %w", err)
	}
	if err := conn.CreateFunction(remoteHistoryBindingAuthorizationFunction, &sqlite.FunctionImpl{
		NArgs:         2,
		Deterministic: false,
		AllowIndirect: true,
		Scalar: func(_ sqlite.Context, args []sqlite.Value) (sqlite.Value, error) {
			if identityAuth.lifetimeSegmentID != "" &&
				identityAuth.authoritySetID != "" &&
				string(identityAuth.lifetimeSegmentID) == args[0].Text() &&
				string(identityAuth.authoritySetID) == args[1].Text() {
				return sqlite.IntegerValue(1), nil
			}
			return sqlite.IntegerValue(0), nil
		},
	}); err != nil {
		return fmt.Errorf("register RemoteHistory binding authorization function: %w", err)
	}
	s.identityMutationAuthorizations.Store(conn, identityAuth)

	topologyAuth := &gdriveTopologyWatermarkDeleteAuthorization{}
	if err := conn.CreateFunction(gdriveTopologyWatermarkDeleteAuthorizationFunction, &sqlite.FunctionImpl{
		NArgs:         2,
		Deterministic: false,
		AllowIndirect: true,
		Scalar: func(_ sqlite.Context, args []sqlite.Value) (sqlite.Value, error) {
			if topologyAuth.generationID != "" &&
				topologyAuth.publicationSequence != 0 &&
				string(topologyAuth.generationID) == args[0].Text() &&
				fmt.Sprint(topologyAuth.publicationSequence) == args[1].Text() {
				return sqlite.IntegerValue(1), nil
			}
			return sqlite.IntegerValue(0), nil
		},
	}); err != nil {
		return fmt.Errorf("register Google Drive topology watermark delete authorization function: %w", err)
	}
	s.gdriveTopologyWatermarkDeleteAuthorizations.Store(conn, topologyAuth)

	coreAuth := &coreIdentityInsertAuthorization{}
	if err := conn.CreateFunction(artifactInsertAuthorizationFunction, &sqlite.FunctionImpl{
		NArgs: 1, Deterministic: false, AllowIndirect: true,
		Scalar: func(_ sqlite.Context, args []sqlite.Value) (sqlite.Value, error) {
			if coreAuth.kind == "ARTIFACT" && coreAuth.artifactID != "" &&
				string(coreAuth.artifactID) == args[0].Text() {
				return sqlite.IntegerValue(1), nil
			}
			return sqlite.IntegerValue(0), nil
		},
	}); err != nil {
		return fmt.Errorf("register Artifact insert authorization function: %w", err)
	}
	if err := conn.CreateFunction(revisionInsertAuthorizationFunction, &sqlite.FunctionImpl{
		NArgs: 6, Deterministic: false, AllowIndirect: true,
		Scalar: func(_ sqlite.Context, args []sqlite.Value) (sqlite.Value, error) {
			if coreAuth.kind == "REVISION" && coreAuth.revisionID != "" && coreAuth.artifactID != "" &&
				string(coreAuth.revisionID) == args[0].Text() &&
				string(coreAuth.artifactID) == args[1].Text() &&
				fmt.Sprint(coreAuth.revisionSequence) == args[2].Text() &&
				coreAuth.algorithm == args[3].Text() &&
				coreAuth.digest == args[4].Text() &&
				fmt.Sprint(coreAuth.contentSize) == args[5].Text() {
				return sqlite.IntegerValue(1), nil
			}
			return sqlite.IntegerValue(0), nil
		},
	}); err != nil {
		return fmt.Errorf("register Revision insert authorization function: %w", err)
	}
	if err := conn.CreateFunction(providerArtifactBindingInsertAuthorizationFunction, &sqlite.FunctionImpl{
		NArgs: 6, Deterministic: false, AllowIndirect: true,
		Scalar: func(_ sqlite.Context, args []sqlite.Value) (sqlite.Value, error) {
			if coreAuth.kind == "PROVIDER_BINDING" && coreAuth.identityDomain != "" &&
				coreAuth.providerID != "" && coreAuth.providerObjectID != "" &&
				coreAuth.artifactID != "" && coreAuth.policyID != "" && coreAuth.acceptedAt != "" &&
				coreAuth.identityDomain == args[0].Text() &&
				string(coreAuth.providerID) == args[1].Text() &&
				string(coreAuth.providerObjectID) == args[2].Text() &&
				string(coreAuth.artifactID) == args[3].Text() &&
				coreAuth.policyID == args[4].Text() &&
				coreAuth.acceptedAt == args[5].Text() {
				return sqlite.IntegerValue(1), nil
			}
			return sqlite.IntegerValue(0), nil
		},
	}); err != nil {
		return fmt.Errorf("register provider Artifact binding insert authorization function: %w", err)
	}
	s.coreIdentityInsertAuthorizations.Store(conn, coreAuth)

	authorityWriteAuth := &identityAuthorityWriteAuthorization{}
	if err := conn.CreateFunction(identityAuthoritySetInsertAuthorizationFunction, &sqlite.FunctionImpl{
		NArgs: 12, Deterministic: false, AllowIndirect: true,
		Scalar: func(_ sqlite.Context, args []sqlite.Value) (sqlite.Value, error) {
			if authorityWriteAuth.kind == "SET" &&
				string(authorityWriteAuth.authoritySetID) == args[0].Text() &&
				authorityWriteAuth.policyID == args[1].Text() &&
				string(authorityWriteAuth.providerID) == args[2].Text() &&
				authorityWriteAuth.identityDomain == args[3].Text() &&
				authorityWriteAuth.scopeID == args[4].Text() &&
				string(authorityWriteAuth.currentObjectID) == args[5].Text() &&
				string(authorityWriteAuth.universeCoverage) == args[6].Text() &&
				authorityWriteAuth.generationID == args[7].Text() &&
				authorityWriteAuth.lifetimeSegmentID == args[8].Text() &&
				authorityWriteAuth.sourceRefsJSON == args[9].Text() &&
				authorityWriteAuth.createdAt == args[10].Text() &&
				authorityWriteAuth.sealedAt == args[11].Text() {
				return sqlite.IntegerValue(1), nil
			}
			return sqlite.IntegerValue(0), nil
		},
	}); err != nil {
		return fmt.Errorf("register identity authority set insert authorization function: %w", err)
	}
	if err := conn.CreateFunction(identityAuthorityCandidateInsertAuthorizationFunction, &sqlite.FunctionImpl{
		NArgs: 4, Deterministic: false, AllowIndirect: true,
		Scalar: func(_ sqlite.Context, args []sqlite.Value) (sqlite.Value, error) {
			if authorityWriteAuth.kind == "CANDIDATE" &&
				string(authorityWriteAuth.authoritySetID) == args[0].Text() &&
				string(authorityWriteAuth.candidateArtifactID) == args[1].Text() &&
				string(authorityWriteAuth.candidateDirection) == args[2].Text() &&
				authorityWriteAuth.candidateSourceRef == args[3].Text() {
				return sqlite.IntegerValue(1), nil
			}
			return sqlite.IntegerValue(0), nil
		},
	}); err != nil {
		return fmt.Errorf("register identity authority candidate insert authorization function: %w", err)
	}
	if err := conn.CreateFunction(identityAuthoritySealAuthorizationFunction, &sqlite.FunctionImpl{
		NArgs: 2, Deterministic: false, AllowIndirect: true,
		Scalar: func(_ sqlite.Context, args []sqlite.Value) (sqlite.Value, error) {
			if authorityWriteAuth.kind == "SEAL" &&
				string(authorityWriteAuth.authoritySetID) == args[0].Text() &&
				authorityWriteAuth.sealedAt == args[1].Text() {
				return sqlite.IntegerValue(1), nil
			}
			return sqlite.IntegerValue(0), nil
		},
	}); err != nil {
		return fmt.Errorf("register identity authority seal authorization function: %w", err)
	}
	s.identityAuthorityWriteAuthorizations.Store(conn, authorityWriteAuth)

	if err := conn.CreateFunction(identityAuthoritySetStructuralValidationFunction, &sqlite.FunctionImpl{
		NArgs: 11, Deterministic: true, AllowIndirect: true,
		Scalar: func(_ sqlite.Context, args []sqlite.Value) (sqlite.Value, error) {
			var refs []string
			if err := json.Unmarshal([]byte(args[9].Text()), &refs); err != nil {
				return sqlite.IntegerValue(0), nil
			}
			createdAt, err := time.Parse(time.RFC3339Nano, args[10].Text())
			if err != nil {
				return sqlite.IntegerValue(0), nil
			}
			set := corpus.IdentityAuthoritySet{
				ID:                corpus.IdentityAuthoritySetID(args[0].Text()),
				PolicyID:          args[1].Text(),
				ProviderID:        corpus.ProviderID(args[2].Text()),
				IdentityDomain:    args[3].Text(),
				ScopeID:           args[4].Text(),
				CurrentObjectID:   corpus.ProviderObjectID(args[5].Text()),
				UniverseCoverage:  corpus.CandidateUniverseCoverage(args[6].Text()),
				GenerationID:      args[7].Text(),
				LifetimeSegmentID: args[8].Text(),
				SourceRefs:        refs,
				CreatedAt:         createdAt,
			}
			if err := corpus.ValidateIdentityAuthoritySet(set); err != nil {
				return sqlite.IntegerValue(0), nil
			}
			return sqlite.IntegerValue(1), nil
		},
	}); err != nil {
		return fmt.Errorf("register identity authority structural validation function: %w", err)
	}
	if err := conn.CreateFunction(identityAuthorityCandidateStructuralValidationFunction, &sqlite.FunctionImpl{
		NArgs: 3, Deterministic: true, AllowIndirect: true,
		Scalar: func(_ sqlite.Context, args []sqlite.Value) (sqlite.Value, error) {
			set := corpus.IdentityAuthoritySet{
				ID:               "structural-validation",
				PolicyID:         "structural-validation",
				ProviderID:       "structural-validation",
				IdentityDomain:   "structural-validation",
				ScopeID:          "structural-validation",
				CurrentObjectID:  "structural-validation",
				UniverseCoverage: corpus.CandidateUniverseUnknown,
				SourceRefs:       []string{"structural-validation"},
				Candidates: []corpus.IdentityAuthorityCandidate{{
					ArtifactID: corpus.ArtifactID(args[0].Text()),
					Direction:  corpus.ContinuityDirection(args[1].Text()),
					SourceRef:  args[2].Text(),
				}},
				CreatedAt: time.Unix(1, 0).UTC(),
			}
			if err := corpus.ValidateIdentityAuthoritySet(set); err != nil {
				return sqlite.IntegerValue(0), nil
			}
			return sqlite.IntegerValue(1), nil
		},
	}); err != nil {
		return fmt.Errorf("register identity authority candidate structural validation function: %w", err)
	}
	return nil
}

func (s *Store) authorizeIdentityAuthorityWriteConn(
	conn *sqlite.Conn,
	auth identityAuthorityWriteAuthorization,
) (func(), error) {
	if auth.kind == "" || auth.authoritySetID == "" {
		return nil, fmt.Errorf("identity authority write authorization target is incomplete")
	}
	value, ok := s.identityAuthorityWriteAuthorizations.Load(conn)
	if !ok {
		return nil, fmt.Errorf("identity authority write authorization state missing for connection")
	}
	state, ok := value.(*identityAuthorityWriteAuthorization)
	if !ok || state == nil {
		return nil, fmt.Errorf("identity authority write authorization state invalid")
	}
	if state.kind != "" {
		return nil, fmt.Errorf("identity authority write authorization already active")
	}
	*state = auth
	return func() { *state = identityAuthorityWriteAuthorization{} }, nil
}

func (s *Store) authorizeCoreIdentityInsertConn(
	conn *sqlite.Conn,
	auth coreIdentityInsertAuthorization,
) (func(), error) {
	if auth.kind == "" {
		return nil, fmt.Errorf("core identity insert authorization kind is empty")
	}
	value, ok := s.coreIdentityInsertAuthorizations.Load(conn)
	if !ok {
		return nil, fmt.Errorf("core identity insert authorization state missing for connection")
	}
	state, ok := value.(*coreIdentityInsertAuthorization)
	if !ok || state == nil {
		return nil, fmt.Errorf("core identity insert authorization state invalid")
	}
	if state.kind != "" {
		return nil, fmt.Errorf("core identity insert authorization already active")
	}
	*state = auth
	return func() { *state = coreIdentityInsertAuthorization{} }, nil
}

func (s *Store) insertArtifactConn(conn *sqlite.Conn, artifactID corpus.ArtifactID) error {
	if artifactID == "" {
		return fmt.Errorf("empty Artifact ID")
	}
	release, err := s.authorizeCoreIdentityInsertConn(conn, coreIdentityInsertAuthorization{
		kind: "ARTIFACT", artifactID: artifactID,
	})
	if err != nil {
		return err
	}
	defer release()
	if err := sqlitex.Execute(conn,
		"INSERT INTO artifacts (artifact_id) VALUES (?1)",
		&sqlitex.ExecOptions{Args: []any{string(artifactID)}}); err != nil {
		return fmt.Errorf("insert Artifact: %w", err)
	}
	return nil
}

func (s *Store) insertRevisionRecordConn(conn *sqlite.Conn, record corpus.RevisionRecord) error {
	if record.Revision.ID == "" || record.Revision.ArtifactID == "" || record.Sequence == 0 {
		return fmt.Errorf("invalid Revision identity")
	}
	if err := corpus.ValidateContentEvidence(record.Evidence); err != nil {
		return err
	}
	release, err := s.authorizeCoreIdentityInsertConn(conn, coreIdentityInsertAuthorization{
		kind: "REVISION", artifactID: record.Revision.ArtifactID, revisionID: record.Revision.ID,
		revisionSequence: record.Sequence, algorithm: record.Evidence.Algorithm,
		digest: record.Evidence.Digest, contentSize: record.Evidence.Size,
	})
	if err != nil {
		return err
	}
	defer release()
	if err := sqlitex.Execute(conn,
		"INSERT INTO revisions (revision_id, artifact_id, sequence, content_algorithm, content_digest, content_size) VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
		&sqlitex.ExecOptions{Args: []any{
			string(record.Revision.ID), string(record.Revision.ArtifactID), int64(record.Sequence),
			record.Evidence.Algorithm, record.Evidence.Digest, record.Evidence.Size,
		}}); err != nil {
		return fmt.Errorf("insert Revision: %w", err)
	}
	return nil
}

func (s *Store) insertProviderArtifactBindingConn(conn *sqlite.Conn, binding corpus.ProviderArtifactBinding) error {
	if binding.IdentityDomain == "" || binding.ProviderID == "" || binding.ProviderObjectID == "" ||
		binding.ArtifactID == "" || binding.PolicyID == "" || binding.AcceptedAt.IsZero() {
		return fmt.Errorf("invalid provider Artifact binding")
	}
	acceptedAt := binding.AcceptedAt.UTC().Format(time.RFC3339Nano)
	release, err := s.authorizeCoreIdentityInsertConn(conn, coreIdentityInsertAuthorization{
		kind: "PROVIDER_BINDING", identityDomain: binding.IdentityDomain,
		providerID: binding.ProviderID, providerObjectID: binding.ProviderObjectID,
		artifactID: binding.ArtifactID, policyID: binding.PolicyID, acceptedAt: acceptedAt,
	})
	if err != nil {
		return err
	}
	defer release()
	if err := sqlitex.Execute(conn,
		"INSERT INTO provider_artifact_bindings (identity_domain, provider_id, native_object_id, artifact_id, policy_id, accepted_at) VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
		&sqlitex.ExecOptions{Args: []any{
			binding.IdentityDomain, string(binding.ProviderID), string(binding.ProviderObjectID),
			string(binding.ArtifactID), binding.PolicyID, acceptedAt,
		}}); err != nil {
		return fmt.Errorf("insert provider Artifact binding: %w", err)
	}
	return nil
}

func (s *Store) authorizeGoogleTopologyWatermarkDeleteConn(
	conn *sqlite.Conn,
	generationID remotehistory.HistoryGenerationID,
	publicationSequence remotehistory.HistoryPublicationSequence,
) (func(), error) {
	if generationID == "" || publicationSequence == 0 {
		return nil, fmt.Errorf("invalid Google Drive topology watermark delete authorization target")
	}
	value, ok := s.gdriveTopologyWatermarkDeleteAuthorizations.Load(conn)
	if !ok {
		return nil, fmt.Errorf("Google Drive topology watermark delete authorization state missing for connection")
	}
	auth, ok := value.(*gdriveTopologyWatermarkDeleteAuthorization)
	if !ok || auth == nil {
		return nil, fmt.Errorf("Google Drive topology watermark delete authorization state invalid")
	}
	if auth.generationID != "" || auth.publicationSequence != 0 {
		return nil, fmt.Errorf("Google Drive topology watermark delete authorization already active")
	}
	auth.generationID = generationID
	auth.publicationSequence = publicationSequence
	return func() {
		auth.generationID = ""
		auth.publicationSequence = 0
	}, nil
}

func (s *Store) authorizeIdentityMutationConn(
	conn *sqlite.Conn,
	scanID corpus.ScanSessionID,
	lifetimeSegmentID remotehistory.ProviderObjectLifetimeSegmentID,
	authoritySetID corpus.IdentityAuthoritySetID,
) (func(), error) {
	value, ok := s.identityMutationAuthorizations.Load(conn)
	if !ok {
		return nil, fmt.Errorf("identity mutation authorization state missing for connection")
	}
	auth, ok := value.(*identityMutationAuthorization)
	if !ok || auth == nil {
		return nil, fmt.Errorf("identity mutation authorization state invalid")
	}
	if auth.scanID != "" || auth.lifetimeSegmentID != "" || auth.authoritySetID != "" {
		return nil, fmt.Errorf("identity mutation authorization already active")
	}
	if lifetimeSegmentID == "" && authoritySetID != "" ||
		lifetimeSegmentID != "" && authoritySetID == "" {
		return nil, fmt.Errorf("identity mutation binding authorization must include both segment and authority")
	}
	if scanID == "" && lifetimeSegmentID == "" {
		return nil, fmt.Errorf("identity mutation authorization has no protected target")
	}
	auth.scanID = scanID
	auth.lifetimeSegmentID = lifetimeSegmentID
	auth.authoritySetID = authoritySetID
	return func() {
		auth.scanID = ""
		auth.lifetimeSegmentID = ""
		auth.authoritySetID = ""
	}, nil
}

func (s *Store) authorizeRemoteCompletionConn(
	conn *sqlite.Conn,
	scanID corpus.ScanSessionID,
) (func(), error) {
	value, ok := s.remoteCompletionAuthorizations.Load(conn)
	if !ok {
		return nil, fmt.Errorf("remote completion authorization state missing for connection")
	}
	auth, ok := value.(*remoteCompletionAuthorization)
	if !ok || auth == nil {
		return nil, fmt.Errorf("remote completion authorization state invalid")
	}
	if auth.scanID != "" {
		return nil, fmt.Errorf("remote completion authorization already active for %s", auth.scanID)
	}
	auth.scanID = scanID
	return func() {
		auth.scanID = ""
	}, nil
}

func Open(ctx context.Context, path string) (*Store, error) {
	absPath, err := filepath.Abs(path)
	if err != nil {
		return nil, fmt.Errorf("resolve state database path: %w", err)
	}

	store := &Store{path: absPath}
	pool := sqlitemigration.NewPool(absPath, schema, sqlitemigration.Options{
		Flags:       sqlite.OpenReadWrite | sqlite.OpenCreate,
		PoolSize:    1,
		PrepareConn: store.prepareConn,
	})
	store.pool = pool

	conn, err := pool.Get(ctx)
	if err != nil {
		_ = pool.Close()
		return nil, fmt.Errorf("open Keelaryn state store: %w", err)
	}
	pool.Put(conn)

	return store, nil
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
	if err := s.insertArtifactConn(conn, artifact.ID); err != nil {
		return corpus.Artifact{}, err
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

	return s.observeRevisionConn(conn, artifactID, evidence)
}

func (s *Store) observeRevisionConn(conn *sqlite.Conn, artifactID corpus.ArtifactID, evidence corpus.ContentEvidence) (corpus.RevisionObservation, error) {
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

	if err := s.insertRevisionRecordConn(conn, record); err != nil {
		return corpus.RevisionObservation{}, err
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
