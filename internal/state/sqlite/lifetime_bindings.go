package sqlitestate

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

const remoteHistoryLifetimeAuthorityPolicyV1 = "remote-history:lifetime-segment:v1"

var (
	ErrProviderLifetimeArtifactBindingNotFound = errors.New("provider lifetime Artifact binding not found")
	ErrProviderLifetimeArtifactBindingConflict = errors.New("provider lifetime Artifact binding conflict")
)

type ProviderLifetimeArtifactBinding struct {
	LifetimeSegmentID remotehistory.ProviderObjectLifetimeSegmentID
	ArtifactID        corpus.ArtifactID
	PolicyID          string
	AuthoritySetID    corpus.IdentityAuthoritySetID
	AcceptedAt        time.Time
}

func (s *Store) ProviderLifetimeArtifactBinding(
	ctx context.Context,
	segmentID remotehistory.ProviderObjectLifetimeSegmentID,
) (ProviderLifetimeArtifactBinding, error) {
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return ProviderLifetimeArtifactBinding{}, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)
	found, binding, err := providerLifetimeArtifactBindingConn(conn, segmentID)
	if err != nil {
		return ProviderLifetimeArtifactBinding{}, err
	}
	if !found {
		return ProviderLifetimeArtifactBinding{}, fmt.Errorf("%w: %s", ErrProviderLifetimeArtifactBindingNotFound, segmentID)
	}
	return binding, nil
}

func providerLifetimeArtifactBindingConn(
	conn *sqlite.Conn,
	segmentID remotehistory.ProviderObjectLifetimeSegmentID,
) (bool, ProviderLifetimeArtifactBinding, error) {
	var binding ProviderLifetimeArtifactBinding
	var acceptedText string
	var found bool
	if err := sqlitex.Execute(conn,
		"SELECT artifact_id, policy_id, source_authority_set_id, accepted_at FROM provider_lifetime_artifact_bindings WHERE lifetime_segment_id=?1",
		&sqlitex.ExecOptions{
			Args: []any{string(segmentID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				found = true
				binding.LifetimeSegmentID = segmentID
				binding.ArtifactID = corpus.ArtifactID(stmt.ColumnText(0))
				binding.PolicyID = stmt.ColumnText(1)
				binding.AuthoritySetID = corpus.IdentityAuthoritySetID(stmt.ColumnText(2))
				acceptedText = stmt.ColumnText(3)
				return nil
			},
		}); err != nil {
		return false, ProviderLifetimeArtifactBinding{}, fmt.Errorf("query provider lifetime Artifact binding: %w", err)
	}
	if !found {
		return false, ProviderLifetimeArtifactBinding{}, nil
	}
	var err error
	binding.AcceptedAt, err = time.Parse(time.RFC3339Nano, acceptedText)
	if err != nil {
		return false, ProviderLifetimeArtifactBinding{}, fmt.Errorf("parse provider lifetime Artifact binding time: %w", err)
	}
	return true, binding, nil
}

func insertProviderLifetimeArtifactBindingConn(
	conn *sqlite.Conn,
	binding ProviderLifetimeArtifactBinding,
) (ProviderLifetimeArtifactBinding, bool, error) {
	if binding.LifetimeSegmentID == "" ||
		binding.ArtifactID == "" ||
		binding.PolicyID != remoteHistoryLifetimeAuthorityPolicyV1 ||
		binding.AuthoritySetID == "" ||
		binding.AcceptedAt.IsZero() {
		return ProviderLifetimeArtifactBinding{}, false, ErrProviderLifetimeArtifactBindingConflict
	}
	if found, existing, err := providerLifetimeArtifactBindingConn(conn, binding.LifetimeSegmentID); err != nil {
		return ProviderLifetimeArtifactBinding{}, false, err
	} else if found {
		if existing.ArtifactID != binding.ArtifactID {
			return ProviderLifetimeArtifactBinding{}, false, fmt.Errorf(
				"%w: segment=%s existing=%s requested=%s",
				ErrProviderLifetimeArtifactBindingConflict,
				binding.LifetimeSegmentID,
				existing.ArtifactID,
				binding.ArtifactID,
			)
		}
		return existing, false, nil
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO provider_lifetime_artifact_bindings (lifetime_segment_id, artifact_id, policy_id, source_authority_set_id, accepted_at) VALUES (?1, ?2, ?3, ?4, ?5)",
		&sqlitex.ExecOptions{Args: []any{
			string(binding.LifetimeSegmentID),
			string(binding.ArtifactID),
			binding.PolicyID,
			string(binding.AuthoritySetID),
			binding.AcceptedAt.UTC().Format(time.RFC3339Nano),
		}}); err != nil {
		return ProviderLifetimeArtifactBinding{}, false, fmt.Errorf("insert provider lifetime Artifact binding: %w", err)
	}
	binding.AcceptedAt = binding.AcceptedAt.UTC()
	return binding, true, nil
}

type historicalLifetimeBinding struct {
	SegmentID remotehistory.ProviderObjectLifetimeSegmentID
	ArtifactID corpus.ArtifactID
}

func historicalLifetimeBindingsForObjectConn(
	conn *sqlite.Conn,
	generation remotehistory.HistoryGeneration,
	currentSegmentID remotehistory.ProviderObjectLifetimeSegmentID,
	objectID corpus.ProviderObjectID,
) ([]historicalLifetimeBinding, error) {
	var out []historicalLifetimeBinding
	query := "SELECT b.lifetime_segment_id, b.artifact_id " +
		"FROM provider_lifetime_artifact_bindings b " +
		"JOIN provider_object_lifetime_segments s ON s.lifetime_segment_id = b.lifetime_segment_id " +
		"JOIN remote_history_generations g ON g.generation_id = s.generation_id " +
		"WHERE g.provider_id = ?1 AND g.identity_domain = ?2 AND s.object_id = ?3 AND b.lifetime_segment_id <> ?4 " +
		"ORDER BY b.lifetime_segment_id, b.artifact_id"
	if err := sqlitex.Execute(conn, query,
		&sqlitex.ExecOptions{
			Args: []any{
				string(generation.Scope.ProviderID),
				generation.Scope.IdentityDomain,
				string(objectID),
				string(currentSegmentID),
			},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				out = append(out, historicalLifetimeBinding{
					SegmentID: remotehistory.ProviderObjectLifetimeSegmentID(stmt.ColumnText(0)),
					ArtifactID: corpus.ArtifactID(stmt.ColumnText(1)),
				})
				return nil
			},
		}); err != nil {
		return nil, fmt.Errorf("query historical lifetime bindings: %w", err)
	}
	return out, nil
}
