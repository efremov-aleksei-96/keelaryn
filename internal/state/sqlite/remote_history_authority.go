package sqlitestate

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"reflect"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

var (
	ErrRemoteHistoryIdentityAuthorityUnavailable = errors.New("remote history identity authority unavailable")
	ErrRemoteHistoryIdentityAuthorityCollision   = errors.New("remote history identity authority semantic collision")
)

type remoteHistoryAuthorityFingerprintPayload struct {
	Version             string
	PolicyID            string
	GenerationID        string
	PublicationSequence uint64
	SegmentID           string
	ObjectID            string
	MembershipSequence  uint64
	UniverseCoverage    string
	SourceRefs          []string
	Candidates          []string
}

const remoteHistoryAuthorityFingerprintVersion = "remote-history-authority:v1"

func (s *Store) CreateRemoteHistoryIdentityAuthority(
	ctx context.Context,
	generationID remotehistory.HistoryGenerationID,
	segmentID remotehistory.ProviderObjectLifetimeSegmentID,
	createdAt time.Time,
) (out corpus.IdentityAuthoritySet, err error) {
	if generationID == "" || segmentID == "" || createdAt.IsZero() {
		return corpus.IdentityAuthoritySet{}, ErrRemoteHistoryIdentityAuthorityUnavailable
	}
	conn, err := s.pool.Get(ctx)
	if err != nil {
		return corpus.IdentityAuthoritySet{}, fmt.Errorf("get state connection: %w", err)
	}
	defer s.pool.Put(conn)

	end, err := sqlitex.ImmediateTransaction(conn)
	if err != nil {
		return corpus.IdentityAuthoritySet{}, fmt.Errorf("begin remote history authority transaction: %w", err)
	}
	defer end(&err)

	generation, err := remoteHistoryGenerationConn(conn, generationID)
	if err != nil {
		return corpus.IdentityAuthoritySet{}, err
	}
	if generation.Status != remotehistory.HistoryGenerationActive {
		return corpus.IdentityAuthoritySet{}, fmt.Errorf("%w: generation %s is %s", ErrRemoteHistoryIdentityAuthorityUnavailable, generationID, generation.Status)
	}
	segment, err := lifetimeSegmentByIDConn(conn, segmentID)
	if err != nil {
		return corpus.IdentityAuthoritySet{}, err
	}
	if segment.GenerationID != generationID || segment.Status != remotehistory.LifetimeSegmentActive {
		return corpus.IdentityAuthoritySet{}, fmt.Errorf("%w: segment %s is not active in generation %s", ErrRemoteHistoryIdentityAuthorityUnavailable, segmentID, generationID)
	}
	if err := verifyLifetimeSegmentAgainstHistoryConn(conn, segment); err != nil {
		return corpus.IdentityAuthoritySet{}, err
	}

	membershipSequence, found, err := currentRemoteHistoryMembershipSequenceConn(conn, generationID, segment.ProviderObjectID)
	if err != nil {
		return corpus.IdentityAuthoritySet{}, err
	}
	if !found {
		return corpus.IdentityAuthoritySet{}, fmt.Errorf("%w: object %s is absent from current membership", ErrRemoteHistoryIdentityAuthorityUnavailable, segment.ProviderObjectID)
	}

	sourceRefs := []string{
		"history-generation:" + string(generation.ID),
		"history-publication:" + string(generation.ID) + ":" + strconv.FormatUint(uint64(generation.CurrentSequence), 10),
		"lifetime-segment:" + string(segment.ID),
		"current-membership:" + string(generation.ID) + ":" + string(segment.ProviderObjectID) + ":" + strconv.FormatUint(uint64(membershipSequence), 10),
	}
	set := corpus.IdentityAuthoritySet{
		PolicyID:          remoteHistoryLifetimeAuthorityPolicyV1,
		ProviderID:        generation.Scope.ProviderID,
		IdentityDomain:    generation.Scope.IdentityDomain,
		ScopeID:           generation.Scope.Root,
		CurrentObjectID:   segment.ProviderObjectID,
		UniverseCoverage:  corpus.CandidateUniverseUnknown,
		GenerationID:      string(generation.ID),
		LifetimeSegmentID: string(segment.ID),
		CreatedAt:         createdAt.UTC(),
	}

	if bound, binding, err := providerLifetimeArtifactBindingConn(conn, segment.ID); err != nil {
		return corpus.IdentityAuthoritySet{}, err
	} else if bound {
		sourceRef := "lifetime-binding:" + string(segment.ID) + ":" + string(binding.ArtifactID)
		sourceRefs = append(sourceRefs, sourceRef)
		set.Candidates = []corpus.IdentityAuthorityCandidate{{
			ArtifactID: binding.ArtifactID,
			Direction:  corpus.DirectionSupportsSame,
			SourceRef:  sourceRef,
		}}
	} else {
		historical, err := historicalLifetimeBindingsForObjectConn(conn, generation, segment.ID, segment.ProviderObjectID)
		if err != nil {
			return corpus.IdentityAuthoritySet{}, err
		}
		for _, binding := range historical {
			sourceRefs = append(sourceRefs,
				"prior-lifetime-binding:"+string(binding.SegmentID)+":"+string(binding.ArtifactID))
		}
		if legacy, binding, err := providerArtifactBindingConn(
			conn, generation.Scope.IdentityDomain, generation.Scope.ProviderID, segment.ProviderObjectID,
		); err != nil {
			return corpus.IdentityAuthoritySet{}, err
		} else if legacy {
			sourceRefs = append(sourceRefs, "legacy-provider-binding:"+string(binding.ArtifactID))
		}
		if len(historical) == 0 && !containsRefPrefix(sourceRefs, "legacy-provider-binding:") {
			set.UniverseCoverage = corpus.CandidateUniverseComplete
		}
	}

	sort.Strings(sourceRefs)
	set.SourceRefs = sourceRefs
	authorityID, err := remoteHistoryAuthorityID(generation.CurrentSequence, membershipSequence, set)
	if err != nil {
		return corpus.IdentityAuthoritySet{}, err
	}
	set.ID = authorityID

	var exists bool
	if err := sqlitex.Execute(conn,
		"SELECT 1 FROM identity_authority_sets WHERE authority_set_id=?1 LIMIT 1",
		&sqlitex.ExecOptions{
			Args: []any{string(authorityID)},
			ResultFunc: func(*sqlite.Stmt) error {
				exists = true
				return nil
			},
		}); err != nil {
		return corpus.IdentityAuthoritySet{}, fmt.Errorf("query remote history authority replay: %w", err)
	}
	if exists {
		existing, err := identityAuthoritySetConn(conn, authorityID)
		if err != nil {
			return corpus.IdentityAuthoritySet{}, err
		}
		if !sameIdentityAuthoritySemantics(existing, set) {
			return corpus.IdentityAuthoritySet{}, fmt.Errorf("%w: %s", ErrRemoteHistoryIdentityAuthorityCollision, authorityID)
		}
		return existing, nil
	}
	if err := insertIdentityAuthoritySetConn(conn, set); err != nil {
		return corpus.IdentityAuthoritySet{}, err
	}
	return set, nil
}

func lifetimeSegmentByIDConn(
	conn *sqlite.Conn,
	segmentID remotehistory.ProviderObjectLifetimeSegmentID,
) (remotehistory.ProviderObjectLifetimeSegment, error) {
	var segment remotehistory.ProviderObjectLifetimeSegment
	var found bool
	if err := sqlitex.Execute(conn,
		"SELECT generation_id, object_id, start_kind, start_sequence, start_ordinal, last_present_sequence, last_present_ordinal, status, end_sequence, end_ordinal, COALESCE(closure_reason,'') FROM provider_object_lifetime_segments WHERE lifetime_segment_id=?1",
		&sqlitex.ExecOptions{
			Args: []any{string(segmentID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				found = true
				segment.ID = segmentID
				segment.GenerationID = remotehistory.HistoryGenerationID(stmt.ColumnText(0))
				segment.ProviderObjectID = corpus.ProviderObjectID(stmt.ColumnText(1))
				segment.StartKind = remotehistory.LifetimeSegmentStartKind(stmt.ColumnText(2))
				segment.StartPublicationSequence = remotehistory.HistoryPublicationSequence(stmt.ColumnInt64(3))
				segment.StartChangeOrdinal = nullableInt64Column(stmt, 4)
				segment.LastPresentPublicationSequence = remotehistory.HistoryPublicationSequence(stmt.ColumnInt64(5))
				segment.LastPresentChangeOrdinal = nullableInt64Column(stmt, 6)
				segment.Status = remotehistory.LifetimeSegmentStatus(stmt.ColumnText(7))
				if !stmt.ColumnIsNull(8) {
					value := remotehistory.HistoryPublicationSequence(stmt.ColumnInt64(8))
					segment.EndPublicationSequence = &value
				}
				segment.EndChangeOrdinal = nullableInt64Column(stmt, 9)
				segment.ClosureReason = remotehistory.LifetimeSegmentClosureReason(stmt.ColumnText(10))
				return nil
			},
		}); err != nil {
		return remotehistory.ProviderObjectLifetimeSegment{}, fmt.Errorf("query lifetime segment: %w", err)
	}
	if !found {
		return remotehistory.ProviderObjectLifetimeSegment{}, fmt.Errorf("%w: %s", ErrLifetimeSegmentNotFound, segmentID)
	}
	if err := remotehistory.ValidateProviderObjectLifetimeSegment(segment); err != nil {
		return remotehistory.ProviderObjectLifetimeSegment{}, fmt.Errorf("validate lifetime segment: %w", err)
	}
	return segment, nil
}

func verifyLifetimeSegmentAgainstHistoryConn(
	conn *sqlite.Conn,
	segment remotehistory.ProviderObjectLifetimeSegment,
) error {
	expected, err := deriveLifetimeSegmentsConn(conn, segment.GenerationID)
	if err != nil {
		return err
	}
	for _, candidate := range expected {
		if candidate.ID == segment.ID {
			if !reflect.DeepEqual(candidate, segment) {
				return fmt.Errorf("%w: segment=%s materialized=%#v derived=%#v", ErrLifetimeSegmentProjectionDrift, segment.ID, segment, candidate)
			}
			return nil
		}
	}
	return fmt.Errorf("%w: segment=%s absent from immutable history derivation", ErrLifetimeSegmentProjectionDrift, segment.ID)
}

func currentRemoteHistoryMembershipSequenceConn(
	conn *sqlite.Conn,
	generationID remotehistory.HistoryGenerationID,
	objectID corpus.ProviderObjectID,
) (remotehistory.HistoryPublicationSequence, bool, error) {
	var sequence remotehistory.HistoryPublicationSequence
	var found bool
	if err := sqlitex.Execute(conn,
		"SELECT last_sequence FROM remote_history_membership WHERE generation_id=?1 AND object_id=?2",
		&sqlitex.ExecOptions{
			Args: []any{string(generationID), string(objectID)},
			ResultFunc: func(stmt *sqlite.Stmt) error {
				found = true
				sequence = remotehistory.HistoryPublicationSequence(stmt.ColumnInt64(0))
				return nil
			},
		}); err != nil {
		return 0, false, fmt.Errorf("query current RemoteHistory membership: %w", err)
	}
	return sequence, found, nil
}

func remoteHistoryAuthorityID(
	publicationSequence remotehistory.HistoryPublicationSequence,
	membershipSequence remotehistory.HistoryPublicationSequence,
	set corpus.IdentityAuthoritySet,
) (corpus.IdentityAuthoritySetID, error) {
	candidates := make([]string, 0, len(set.Candidates))
	for _, candidate := range set.Candidates {
		candidates = append(candidates,
			string(candidate.ArtifactID)+"\x00"+string(candidate.Direction)+"\x00"+candidate.SourceRef)
	}
	sort.Strings(candidates)
	refs := append([]string(nil), set.SourceRefs...)
	sort.Strings(refs)
	payload := remoteHistoryAuthorityFingerprintPayload{
		Version:             remoteHistoryAuthorityFingerprintVersion,
		PolicyID:            set.PolicyID,
		GenerationID:        set.GenerationID,
		PublicationSequence: uint64(publicationSequence),
		SegmentID:           set.LifetimeSegmentID,
		ObjectID:            string(set.CurrentObjectID),
		MembershipSequence:  uint64(membershipSequence),
		UniverseCoverage:    string(set.UniverseCoverage),
		SourceRefs:          refs,
		Candidates:          candidates,
	}
	encoded, err := json.Marshal(payload)
	if err != nil {
		return "", fmt.Errorf("encode RemoteHistory authority fingerprint: %w", err)
	}
	sum := sha256.Sum256(encoded)
	return corpus.IdentityAuthoritySetID("authrh_" + hex.EncodeToString(sum[:])), nil
}

func sameIdentityAuthoritySemantics(left, right corpus.IdentityAuthoritySet) bool {
	left.CreatedAt = time.Time{}
	right.CreatedAt = time.Time{}
	left.SourceRefs = append([]string(nil), left.SourceRefs...)
	right.SourceRefs = append([]string(nil), right.SourceRefs...)
	sort.Strings(left.SourceRefs)
	sort.Strings(right.SourceRefs)
	sort.Slice(left.Candidates, func(i, j int) bool {
		if left.Candidates[i].ArtifactID != left.Candidates[j].ArtifactID {
			return left.Candidates[i].ArtifactID < left.Candidates[j].ArtifactID
		}
		if left.Candidates[i].Direction != left.Candidates[j].Direction {
			return left.Candidates[i].Direction < left.Candidates[j].Direction
		}
		return left.Candidates[i].SourceRef < left.Candidates[j].SourceRef
	})
	sort.Slice(right.Candidates, func(i, j int) bool {
		if right.Candidates[i].ArtifactID != right.Candidates[j].ArtifactID {
			return right.Candidates[i].ArtifactID < right.Candidates[j].ArtifactID
		}
		if right.Candidates[i].Direction != right.Candidates[j].Direction {
			return right.Candidates[i].Direction < right.Candidates[j].Direction
		}
		return right.Candidates[i].SourceRef < right.Candidates[j].SourceRef
	})
	return reflect.DeepEqual(left, right)
}

func containsRefPrefix(refs []string, prefix string) bool {
	for _, ref := range refs {
		if strings.HasPrefix(ref, prefix) {
			return true
		}
	}
	return false
}
