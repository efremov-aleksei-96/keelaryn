package sqlitestate_test

import (
	"context"
	"errors"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	sqlitestate "github.com/efremov-aleksei-96/keelaryn/internal/state/sqlite"
)

func TestAcceptResolvedNewCreatesArtifactRevisionObservationProvenanceAndBinding(t *testing.T) {
	ctx := context.Background()
	store := openStore(t)
	at := time.Date(2026, 9, 25, 23, 0, 0, 0, time.UTC)
	scan, err := store.StartScan(ctx, "drive", "drive-root", at)
	if err != nil {
		t.Fatal(err)
	}
	input := observedDriveObservation("obj-new", "file-id/obj-new", at)
	resolution := resolvedNew(t, "obj-new", nil)

	got, err := store.AcceptResolvedNewObservationInScan(
		ctx, "admit-1", scan.ID, input, resolution,
		ptrEvidence(evidence("same", 4)), at, "test:complete:v1",
	)
	if err != nil {
		t.Fatal(err)
	}
	if got.Observation.ArtifactID == "" ||
		got.Observation.AssignmentState != corpus.AssignmentAssigned ||
		got.Revision == nil ||
		!got.Revision.Created ||
		got.Revision.Current.Sequence != 1 ||
		got.Decision.State != corpus.OccurrenceIdentityResolvedNew ||
		got.Binding.ArtifactID != got.Observation.ArtifactID {
		t.Fatalf("acceptance=%#v", got)
	}
	if got.Observation.RevisionID != got.Revision.Current.Revision.ID {
		t.Fatalf("revision binding mismatch: %#v", got)
	}
	stored, err := store.AcceptedAdmission(ctx, "admit-1")
	if err != nil {
		t.Fatal(err)
	}
	if stored.ArtifactID != got.Observation.ArtifactID ||
		stored.ProviderObjectID != "obj-new" ||
		stored.Resolution.State != corpus.OccurrenceIdentityResolvedNew {
		t.Fatalf("stored admission=%#v", stored)
	}
	binding, err := store.ProviderArtifactBinding(ctx, "drive:test-account", "drive", "obj-new")
	if err != nil {
		t.Fatal(err)
	}
	if binding.ArtifactID != got.Observation.ArtifactID {
		t.Fatalf("binding=%#v", binding)
	}
}

func TestAdmissionReplayRequestCannotMintSecondArtifact(t *testing.T) {
	ctx := context.Background()
	store := openStore(t)
	at := time.Date(2026, 9, 25, 23, 1, 0, 0, time.UTC)
	scan, err := store.StartScan(ctx, "drive", "drive-root", at)
	if err != nil {
		t.Fatal(err)
	}
	input := observedDriveObservation("obj-replay", "file-id/obj-replay", at)
	resolution := resolvedNew(t, "obj-replay", nil)
	if _, err := store.AcceptResolvedNewObservationInScan(
		ctx, "admit-replay", scan.ID, input, resolution,
		ptrEvidence(evidence("same", 4)), at, "test:complete:v1",
	); err != nil {
		t.Fatal(err)
	}
	beforeArtifacts := tableCount(t, store.Path(), "artifacts")
	beforeObservations := tableCount(t, store.Path(), "observations")

	_, err = store.AcceptResolvedNewObservationInScan(
		ctx, "admit-replay", scan.ID, input, resolution,
		ptrEvidence(evidence("same", 4)), at, "test:complete:v1",
	)
	if !errors.Is(err, sqlitestate.ErrAdmissionAlreadyAccepted) {
		t.Fatalf("error=%v, want ErrAdmissionAlreadyAccepted", err)
	}
	if got := tableCount(t, store.Path(), "artifacts"); got != beforeArtifacts {
		t.Fatalf("replay minted Artifact: before=%d after=%d", beforeArtifacts, got)
	}
	if got := tableCount(t, store.Path(), "observations"); got != beforeObservations {
		t.Fatalf("replay wrote Observation: before=%d after=%d", beforeObservations, got)
	}
}

func TestDifferentRequestCannotReadmitSameProviderIdentity(t *testing.T) {
	ctx := context.Background()
	store := openStore(t)
	at := time.Date(2026, 9, 25, 23, 2, 0, 0, time.UTC)
	first, err := store.StartScan(ctx, "drive", "drive-root", at)
	if err != nil {
		t.Fatal(err)
	}
	input := observedDriveObservation("obj-bound", "file-id/obj-bound", at)
	resolution := resolvedNew(t, "obj-bound", nil)
	if _, err := store.AcceptResolvedNewObservationInScan(
		ctx, "admit-first", first.ID, input, resolution,
		ptrEvidence(evidence("same", 4)), at, "test:complete:v1",
	); err != nil {
		t.Fatal(err)
	}
	if err := store.CompleteScan(ctx, first.ID, at.Add(time.Minute)); err != nil {
		t.Fatal(err)
	}

	secondAt := at.Add(2 * time.Minute)
	second, err := store.StartScan(ctx, "drive", "drive-root", secondAt)
	if err != nil {
		t.Fatal(err)
	}
	input.ObservedAt = secondAt
	beforeArtifacts := tableCount(t, store.Path(), "artifacts")
	_, err = store.AcceptResolvedNewObservationInScan(
		ctx, "admit-second", second.ID, input, resolution,
		ptrEvidence(evidence("same", 4)), secondAt, "test:complete:v1",
	)
	if !errors.Is(err, sqlitestate.ErrProviderObjectAlreadyBound) {
		t.Fatalf("error=%v, want ErrProviderObjectAlreadyBound", err)
	}
	if got := tableCount(t, store.Path(), "artifacts"); got != beforeArtifacts {
		t.Fatalf("bound identity minted another Artifact: before=%d after=%d", beforeArtifacts, got)
	}
}

func TestResolvedNewRequiresCompleteUniverseAndExactScope(t *testing.T) {
	ctx := context.Background()
	store := openStore(t)
	at := time.Date(2026, 9, 25, 23, 3, 0, 0, time.UTC)
	scan, err := store.StartScan(ctx, "drive", "drive-root", at)
	if err != nil {
		t.Fatal(err)
	}
	input := observedDriveObservation("obj-new", "file-id/obj-new", at)

	candidates, err := corpus.ResolveCandidateSet(nil)
	if err != nil {
		t.Fatal(err)
	}
	unknownProof := fakeCompleteProof("obj-new")
	unknownProof.Coverage = corpus.CandidateUniverseUnknown
	unknownProof.EvidenceRefs = nil
	unresolved, err := corpus.ResolveOccurrenceIdentity(candidates, &unknownProof)
	if err != nil {
		t.Fatal(err)
	}
	if unresolved.State != corpus.OccurrenceIdentityUnresolved {
		t.Fatalf("resolution=%#v", unresolved)
	}
	beforeArtifacts := tableCount(t, store.Path(), "artifacts")
	_, err = store.AcceptResolvedNewObservationInScan(
		ctx, "admit-unknown", scan.ID, input, unresolved,
		ptrEvidence(evidence("same", 4)), at, "test:complete:v1",
	)
	if !errors.Is(err, sqlitestate.ErrInvalidArtifactAdmission) {
		t.Fatalf("error=%v, want ErrInvalidArtifactAdmission", err)
	}
	if got := tableCount(t, store.Path(), "artifacts"); got != beforeArtifacts {
		t.Fatal("unknown completeness mutated artifacts")
	}

	wrongScope := fakeCompleteProof("obj-new")
	wrongScope.ScopeID = "other-root"
	resolution, err := corpus.ResolveOccurrenceIdentity(candidates, &wrongScope)
	if err != nil {
		t.Fatal(err)
	}
	_, err = store.AcceptResolvedNewObservationInScan(
		ctx, "admit-scope", scan.ID, input, resolution,
		ptrEvidence(evidence("same", 4)), at, "test:complete:v1",
	)
	if !errors.Is(err, sqlitestate.ErrScanScopeMismatch) {
		t.Fatalf("error=%v, want ErrScanScopeMismatch", err)
	}
	if got := tableCount(t, store.Path(), "artifacts"); got != beforeArtifacts {
		t.Fatal("scope mismatch mutated artifacts")
	}
}

func TestTrueCopyIdenticalBytesCanBecomeDistinctArtifactWithConclusiveIdentity(t *testing.T) {
	ctx := context.Background()
	store := openStore(t)
	base := time.Date(2026, 9, 25, 23, 4, 0, 0, time.UTC)

	firstScan, err := store.StartScan(ctx, "drive", "drive-root", base)
	if err != nil {
		t.Fatal(err)
	}
	firstInput := observedDriveObservation("obj-original", "file-id/obj-original", base)
	first, err := store.AcceptResolvedNewObservationInScan(
		ctx, "admit-original", firstScan.ID, firstInput, resolvedNew(t, "obj-original", nil),
		ptrEvidence(evidence("identical", 4)), base, "test:complete:v1",
	)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.CompleteScan(ctx, firstScan.ID, base.Add(time.Minute)); err != nil {
		t.Fatal(err)
	}

	copyAt := base.Add(2 * time.Minute)
	copyScan, err := store.StartScan(ctx, "drive", "drive-root", copyAt)
	if err != nil {
		t.Fatal(err)
	}
	distinctCandidates := []corpus.ArtifactCandidateInput{{
		ArtifactID: first.Observation.ArtifactID,
		Evidence: []corpus.DecisionEvidence{{
			Source:    "google-drive:fileId:v1",
			Direction: corpus.DirectionSupportsDistinct,
			Strength:  corpus.EvidenceConclusive,
		}},
	}}
	copyInput := observedDriveObservation("obj-copy", "file-id/obj-copy", copyAt)
	copyAccepted, err := store.AcceptResolvedNewObservationInScan(
		ctx, "admit-copy", copyScan.ID, copyInput, resolvedNew(t, "obj-copy", distinctCandidates),
		ptrEvidence(evidence("identical", 4)), copyAt, "test:complete:v1",
	)
	if err != nil {
		t.Fatal(err)
	}
	if copyAccepted.Observation.ArtifactID == first.Observation.ArtifactID {
		t.Fatal("identical-byte copy reused Artifact identity")
	}
	if copyAccepted.Revision == nil || first.Revision == nil ||
		copyAccepted.Revision.Current.Evidence.Digest != first.Revision.Current.Evidence.Digest {
		t.Fatal("expected identical content evidence across distinct Artifacts")
	}
}

func TestAcceptedAdmissionAndBindingSurviveReopen(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "state.db")
	store, err := sqlitestate.Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	at := time.Date(2026, 9, 25, 23, 5, 0, 0, time.UTC)
	scan, err := store.StartScan(ctx, "drive", "drive-root", at)
	if err != nil {
		t.Fatal(err)
	}
	accepted, err := store.AcceptResolvedNewObservationInScan(
		ctx, "admit-reopen", scan.ID,
		observedDriveObservation("obj-reopen", "file-id/obj-reopen", at),
		resolvedNew(t, "obj-reopen", nil),
		ptrEvidence(evidence("same", 4)), at, "test:complete:v1",
	)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.CompleteScan(ctx, scan.ID, at.Add(time.Minute)); err != nil {
		t.Fatal(err)
	}
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}

	store, err = sqlitestate.Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	record, err := store.AcceptedAdmission(ctx, "admit-reopen")
	if err != nil {
		t.Fatal(err)
	}
	if record.ArtifactID != accepted.Observation.ArtifactID {
		t.Fatalf("record=%#v", record)
	}
	binding, err := store.ProviderArtifactBinding(ctx, "drive:test-account", "drive", "obj-reopen")
	if err != nil {
		t.Fatal(err)
	}
	if binding.ArtifactID != accepted.Observation.ArtifactID {
		t.Fatalf("binding=%#v", binding)
	}
}

func observedDriveObservation(objectID corpus.ProviderObjectID, path string, at time.Time) corpus.ObservationRecordInput {
	return corpus.ObservationRecordInput{
		ProviderObject: corpus.ProviderObject{
			ProviderID:    "drive",
			ID:            objectID,
			IdentityState: corpus.ObjectIdentityObserved,
		},
		Locators: []corpus.Locator{{
			ProviderID: "drive",
			Root:       "drive-root",
			Path:       path,
		}},
		AssignmentState: corpus.AssignmentUnresolved,
		ObservedAt:      at,
		Kind:            corpus.EntryRegularFile,
		Size:            4,
		Mode:            0o600,
		ModifiedAt:      at.Add(-time.Minute),
	}
}

func fakeCompleteProof(objectID corpus.ProviderObjectID) corpus.CandidateUniverseProof {
	return corpus.CandidateUniverseProof{
		PolicyID:        "test:complete:v1",
		ProviderID:      "drive",
		IdentityDomain:  "drive:test-account",
		ScopeID:         "drive-root",
		CurrentObjectID: objectID,
		Coverage:        corpus.CandidateUniverseComplete,
		EvidenceRefs:    []string{"baseline:test", "cursor:test"},
	}
}

func resolvedNew(t *testing.T, objectID corpus.ProviderObjectID, inputs []corpus.ArtifactCandidateInput) corpus.OccurrenceIdentityResolution {
	t.Helper()
	candidates, err := corpus.ResolveCandidateSet(inputs)
	if err != nil {
		t.Fatal(err)
	}
	proof := fakeCompleteProof(objectID)
	resolution, err := corpus.ResolveOccurrenceIdentity(candidates, &proof)
	if err != nil {
		t.Fatal(err)
	}
	if resolution.State != corpus.OccurrenceIdentityResolvedNew {
		t.Fatalf("resolution=%#v, want RESOLVED_NEW", resolution)
	}
	return resolution
}
