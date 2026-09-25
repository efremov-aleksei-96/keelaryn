package sqlitestate

import (
	"encoding/json"
	"fmt"
	"sort"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

func identityAuthoritySetConn(conn *sqlite.Conn, id corpus.IdentityAuthoritySetID) (corpus.IdentityAuthoritySet, error) {
	var set corpus.IdentityAuthoritySet
	var sourceRefsJSON, createdText, sealedText string
	var found bool
	err := sqlitex.Execute(conn,
		"SELECT policy_id, provider_id, identity_domain, scope_id, current_object_id, universe_coverage, COALESCE(generation_id, ''), COALESCE(lifetime_segment_id, ''), source_refs_json, created_at, COALESCE(sealed_at, '') FROM identity_authority_sets WHERE authority_set_id = ?1",
		&sqlitex.ExecOptions{
			Args: []any{string(id)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				found = true
				set.ID = id
				set.PolicyID = stmt.ColumnText(0)
				set.ProviderID = corpus.ProviderID(stmt.ColumnText(1))
				set.IdentityDomain = stmt.ColumnText(2)
				set.ScopeID = stmt.ColumnText(3)
				set.CurrentObjectID = corpus.ProviderObjectID(stmt.ColumnText(4))
				set.UniverseCoverage = corpus.CandidateUniverseCoverage(stmt.ColumnText(5))
				set.GenerationID = stmt.ColumnText(6)
				set.LifetimeSegmentID = stmt.ColumnText(7)
				sourceRefsJSON = stmt.ColumnText(8)
				createdText = stmt.ColumnText(9)
				sealedText = stmt.ColumnText(10)
				return nil
			},
		})
	if err != nil {
		return corpus.IdentityAuthoritySet{}, fmt.Errorf("query identity authority set: %w", err)
	}
	if !found {
		return corpus.IdentityAuthoritySet{}, fmt.Errorf("%w: %s", ErrIdentityAuthoritySetNotFound, id)
	}
	if sealedText == "" {
		return corpus.IdentityAuthoritySet{}, fmt.Errorf("%w: authority set %s is not sealed", ErrInvalidIdentityAuthoritySet, id)
	}
	if err := json.Unmarshal([]byte(sourceRefsJSON), &set.SourceRefs); err != nil {
		return corpus.IdentityAuthoritySet{}, fmt.Errorf("decode identity authority source refs: %w", err)
	}
	set.CreatedAt, err = time.Parse(time.RFC3339Nano, createdText)
	if err != nil {
		return corpus.IdentityAuthoritySet{}, fmt.Errorf("parse identity authority timestamp: %w", err)
	}
	err = sqlitex.Execute(conn,
		"SELECT artifact_id, direction, source_ref FROM identity_authority_candidates WHERE authority_set_id = ?1 ORDER BY artifact_id, direction, source_ref",
		&sqlitex.ExecOptions{
			Args: []any{string(id)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				set.Candidates = append(set.Candidates, corpus.IdentityAuthorityCandidate{
					ArtifactID: corpus.ArtifactID(stmt.ColumnText(0)),
					Direction:  corpus.ContinuityDirection(stmt.ColumnText(1)),
					SourceRef:  stmt.ColumnText(2),
				})
				return nil
			},
		})
	if err != nil {
		return corpus.IdentityAuthoritySet{}, fmt.Errorf("query identity authority candidates: %w", err)
	}
	if err := corpus.ValidateIdentityAuthoritySet(set); err != nil {
		return corpus.IdentityAuthoritySet{}, fmt.Errorf("%w: %v", ErrInvalidIdentityAuthoritySet, err)
	}
	return set, nil
}

// No exported generic writer exists. Later source-specific qualified producers
// will call this internal helper. Tests use it for deterministic authority.
func insertIdentityAuthoritySetConn(conn *sqlite.Conn, set corpus.IdentityAuthoritySet) error {
	if err := corpus.ValidateIdentityAuthoritySet(set); err != nil {
		return fmt.Errorf("%w: %v", ErrInvalidIdentityAuthoritySet, err)
	}
	sourceRefs := append([]string(nil), set.SourceRefs...)
	sort.Strings(sourceRefs)
	sourceRefsJSON, err := json.Marshal(sourceRefs)
	if err != nil {
		return fmt.Errorf("marshal identity authority source refs: %w", err)
	}
	for _, candidate := range set.Candidates {
		exists, err := artifactExists(conn, candidate.ArtifactID)
		if err != nil {
			return err
		}
		if !exists {
			return fmt.Errorf("%w: candidate %s", corpus.ErrArtifactNotFound, candidate.ArtifactID)
		}
	}
	var generation any
	var segment any
	if set.GenerationID != "" {
		generation = set.GenerationID
	}
	if set.LifetimeSegmentID != "" {
		segment = set.LifetimeSegmentID
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO identity_authority_sets (authority_set_id, policy_id, provider_id, identity_domain, scope_id, current_object_id, universe_coverage, generation_id, lifetime_segment_id, source_refs_json, created_at) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)",
		&sqlitex.ExecOptions{Args: []any{
			string(set.ID), set.PolicyID, string(set.ProviderID), set.IdentityDomain,
			set.ScopeID, string(set.CurrentObjectID), string(set.UniverseCoverage),
			generation, segment, string(sourceRefsJSON), set.CreatedAt.UTC().Format(time.RFC3339Nano),
		}}); err != nil {
		return fmt.Errorf("insert identity authority set: %w", err)
	}
	candidates := append([]corpus.IdentityAuthorityCandidate(nil), set.Candidates...)
	sort.Slice(candidates, func(i, j int) bool {
		if candidates[i].ArtifactID != candidates[j].ArtifactID {
			return candidates[i].ArtifactID < candidates[j].ArtifactID
		}
		if candidates[i].Direction != candidates[j].Direction {
			return candidates[i].Direction < candidates[j].Direction
		}
		return candidates[i].SourceRef < candidates[j].SourceRef
	})
	for _, candidate := range candidates {
		if err := sqlitex.Execute(conn,
			"INSERT INTO identity_authority_candidates (authority_set_id, artifact_id, direction, source_ref) VALUES (?1, ?2, ?3, ?4)",
			&sqlitex.ExecOptions{Args: []any{
				string(set.ID), string(candidate.ArtifactID), string(candidate.Direction), candidate.SourceRef,
			}}); err != nil {
			return fmt.Errorf("insert identity authority candidate: %w", err)
		}
	}
	if err := sqlitex.Execute(conn,
		"UPDATE identity_authority_sets SET sealed_at = ?1 WHERE authority_set_id = ?2 AND sealed_at IS NULL",
		&sqlitex.ExecOptions{Args: []any{
			set.CreatedAt.UTC().Format(time.RFC3339Nano), string(set.ID),
		}}); err != nil {
		return fmt.Errorf("seal identity authority set: %w", err)
	}
	if conn.Changes() != 1 {
		return fmt.Errorf("%w: authority set %s was not sealed exactly once", ErrInvalidIdentityAuthoritySet, set.ID)
	}
	return nil
}

func candidateResolutionFromAuthority(set corpus.IdentityAuthoritySet) (corpus.CandidateSetResolution, error) {
	inputs := make([]corpus.ArtifactCandidateInput, 0, len(set.Candidates))
	for _, candidate := range set.Candidates {
		inputs = append(inputs, corpus.ArtifactCandidateInput{
			ArtifactID: candidate.ArtifactID,
			Evidence: []corpus.DecisionEvidence{{
				Source:    "authority-set:" + string(set.ID) + ":" + candidate.SourceRef,
				Direction: candidate.Direction,
				Strength:  corpus.EvidenceConclusive,
			}},
		})
	}
	return corpus.ResolveCandidateSet(inputs)
}

func occurrenceResolutionFromAuthority(set corpus.IdentityAuthoritySet) (corpus.OccurrenceIdentityResolution, error) {
	candidates, err := candidateResolutionFromAuthority(set)
	if err != nil {
		return corpus.OccurrenceIdentityResolution{}, err
	}
	refs := append([]string(nil), set.SourceRefs...)
	refs = append(refs, "authority-set:"+string(set.ID))
	proof := corpus.CandidateUniverseProof{
		PolicyID:        set.PolicyID,
		ProviderID:      set.ProviderID,
		IdentityDomain:  set.IdentityDomain,
		ScopeID:         set.ScopeID,
		CurrentObjectID: set.CurrentObjectID,
		Coverage:        set.UniverseCoverage,
		EvidenceRefs:    refs,
	}
	return corpus.ResolveOccurrenceIdentity(candidates, &proof)
}
