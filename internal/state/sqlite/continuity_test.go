package sqlitestate_test

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	sqlitestate "github.com/efremov-aleksei-96/keelaryn/internal/state/sqlite"
)

func TestAcceptResolvedSameUnchangedContentReusesRevision(t *testing.T) {
	ctx := context.Background()
	store := openStore(t)
	artifact, err := store.AdoptArtifact(ctx)
	if err != nil {
		t.Fatal(err)
	}
	first, err := store.ObserveRevision(ctx, artifact.ID, evidence("same", 4))
	if err != nil {
		t.Fatal(err)
	}

	at := time.Date(2026, 9, 25, 21, 0, 0, 0, time.UTC)
	scan, err := store.StartScan(ctx, "localfs", "/corpus", at)
	if err != nil {
		t.Fatal(err)
	}
	input := unresolvedScanObservation("file.txt", at)
	resolution := resolvedSame(t, artifact.ID)

	got, err := store.AcceptResolvedObservationInScan(
		ctx, scan.ID, input, resolution, ptrEvidence(evidence("same", 4)), at,
		corpus.ContinuityPolicyCandidateSetV1,
	)
	if err != nil {
		t.Fatal(err)
	}
	if got.Observation.ArtifactID != artifact.ID ||
		got.Observation.RevisionID != first.Current.Revision.ID ||
		got.Observation.AssignmentState != corpus.AssignmentAssigned {
		t.Fatalf("accepted observation=%#v", got.Observation)
	}
	if got.Revision == nil || got.Revision.Created || got.Revision.Current.Revision.ID != first.Current.Revision.ID {
		t.Fatalf("unchanged content revision=%#v", got.Revision)
	}
	if got.Decision.ArtifactID != artifact.ID ||
		got.Decision.State != corpus.CandidateSetResolvedSame ||
		got.Decision.PolicyID != corpus.ContinuityPolicyCandidateSetV1 {
		t.Fatalf("decision=%#v", got.Decision)
	}

	stored, err := store.AcceptedContinuity(ctx, got.Observation.ID)
	if err != nil {
		t.Fatal(err)
	}
	if stored.ID != got.Decision.ID ||
		stored.ArtifactID != artifact.ID ||
		stored.Resolution.SelectedArtifactID != artifact.ID {
		t.Fatalf("stored decision=%#v", stored)
	}
}

func TestAcceptResolvedSameChangedContentCreatesNextRevision(t *testing.T) {
	ctx := context.Background()
	store := openStore(t)
	artifact, err := store.AdoptArtifact(ctx)
	if err != nil {
		t.Fatal(err)
	}
	first, err := store.ObserveRevision(ctx, artifact.ID, evidence("old!", 4))
	if err != nil {
		t.Fatal(err)
	}

	at := time.Date(2026, 9, 25, 21, 1, 0, 0, time.UTC)
	scan, err := store.StartScan(ctx, "localfs", "/corpus", at)
	if err != nil {
		t.Fatal(err)
	}
	got, err := store.AcceptResolvedObservationInScan(
		ctx,
		scan.ID,
		unresolvedScanObservation("file.txt", at),
		resolvedSame(t, artifact.ID),
		ptrEvidence(evidence("new!", 4)),
		at,
		corpus.ContinuityPolicyCandidateSetV1,
	)
	if err != nil {
		t.Fatal(err)
	}
	if got.Revision == nil || !got.Revision.Created || got.Revision.Current.Sequence != 2 {
		t.Fatalf("changed content revision=%#v", got.Revision)
	}
	if got.Revision.Current.Revision.ArtifactID != artifact.ID ||
		got.Revision.Current.Revision.ID == first.Current.Revision.ID ||
		got.Observation.ArtifactID != artifact.ID ||
		got.Observation.RevisionID != got.Revision.Current.Revision.ID {
		t.Fatalf("continuity/revision mismatch: %#v", got)
	}
	history, err := store.RevisionHistory(ctx, artifact.ID)
	if err != nil {
		t.Fatal(err)
	}
	if len(history) != 2 {
		t.Fatalf("history=%#v", history)
	}
}

func TestAcceptAmbiguousFailsWithoutDurableMutation(t *testing.T) {
	ctx := context.Background()
	store := openStore(t)
	artifact, err := store.AdoptArtifact(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.ObserveRevision(ctx, artifact.ID, evidence("same", 4)); err != nil {
		t.Fatal(err)
	}
	beforeObs := tableCount(t, store.Path(), "observations")
	beforeDecisions := tableCount(t, store.Path(), "accepted_continuity_decisions")

	at := time.Date(2026, 9, 25, 21, 2, 0, 0, time.UTC)
	scan, err := store.StartScan(ctx, "localfs", "/corpus", at)
	if err != nil {
		t.Fatal(err)
	}
	ambiguous, err := corpus.ResolveCandidateSet([]corpus.ArtifactCandidateInput{{
		ArtifactID: artifact.ID,
		Evidence: []corpus.DecisionEvidence{{
			Source: "supporting-only",
			Direction: corpus.DirectionSupportsSame,
			Strength: corpus.EvidenceSupporting,
		}},
	}})
	if err != nil {
		t.Fatal(err)
	}

	_, err = store.AcceptResolvedObservationInScan(
		ctx, scan.ID, unresolvedScanObservation("file.txt", at), ambiguous,
		ptrEvidence(evidence("same", 4)), at, corpus.ContinuityPolicyCandidateSetV1,
	)
	if !errors.Is(err, sqlitestate.ErrInvalidContinuityAcceptance) {
		t.Fatalf("error=%v, want ErrInvalidContinuityAcceptance", err)
	}
	if got := tableCount(t, store.Path(), "observations"); got != beforeObs {
		t.Fatalf("ambiguous acceptance wrote observation: before=%d after=%d", beforeObs, got)
	}
	if got := tableCount(t, store.Path(), "accepted_continuity_decisions"); got != beforeDecisions {
		t.Fatalf("ambiguous acceptance wrote decision: before=%d after=%d", beforeDecisions, got)
	}
	history, err := store.RevisionHistory(ctx, artifact.ID)
	if err != nil {
		t.Fatal(err)
	}
	if len(history) != 1 {
		t.Fatalf("ambiguous acceptance mutated revision history: %#v", history)
	}
}

func TestAcceptResolvedMissingArtifactRollsBack(t *testing.T) {
	ctx := context.Background()
	store := openStore(t)
	at := time.Date(2026, 9, 25, 21, 3, 0, 0, time.UTC)
	scan, err := store.StartScan(ctx, "localfs", "/corpus", at)
	if err != nil {
		t.Fatal(err)
	}
	beforeObs := tableCount(t, store.Path(), "observations")

	_, err = store.AcceptResolvedObservationInScan(
		ctx,
		scan.ID,
		unresolvedScanObservation("file.txt", at),
		resolvedSame(t, "art_missing"),
		ptrEvidence(evidence("same", 4)),
		at,
		corpus.ContinuityPolicyCandidateSetV1,
	)
	if !errors.Is(err, corpus.ErrArtifactNotFound) {
		t.Fatalf("error=%v, want ErrArtifactNotFound", err)
	}
	if got := tableCount(t, store.Path(), "observations"); got != beforeObs {
		t.Fatalf("missing Artifact wrote observation: before=%d after=%d", beforeObs, got)
	}
}

func TestAcceptResolvedAlgorithmMismatchRollsBack(t *testing.T) {
	ctx := context.Background()
	store := openStore(t)
	artifact, err := store.AdoptArtifact(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.ObserveRevision(ctx, artifact.ID, evidence("same", 4)); err != nil {
		t.Fatal(err)
	}
	beforeObs := tableCount(t, store.Path(), "observations")
	beforeDecisions := tableCount(t, store.Path(), "accepted_continuity_decisions")

	at := time.Date(2026, 9, 25, 21, 4, 0, 0, time.UTC)
	scan, err := store.StartScan(ctx, "localfs", "/corpus", at)
	if err != nil {
		t.Fatal(err)
	}
	_, err = store.AcceptResolvedObservationInScan(
		ctx,
		scan.ID,
		unresolvedScanObservation("file.txt", at),
		resolvedSame(t, artifact.ID),
		&corpus.ContentEvidence{Algorithm: "blake3", Digest: "same", Size: 4},
		at,
		corpus.ContinuityPolicyCandidateSetV1,
	)
	if !errors.Is(err, corpus.ErrContentEvidenceNotComparable) {
		t.Fatalf("error=%v, want ErrContentEvidenceNotComparable", err)
	}
	if got := tableCount(t, store.Path(), "observations"); got != beforeObs {
		t.Fatalf("algorithm mismatch wrote observation: before=%d after=%d", beforeObs, got)
	}
	if got := tableCount(t, store.Path(), "accepted_continuity_decisions"); got != beforeDecisions {
		t.Fatalf("algorithm mismatch wrote decision: before=%d after=%d", beforeDecisions, got)
	}
	history, err := store.RevisionHistory(ctx, artifact.ID)
	if err != nil {
		t.Fatal(err)
	}
	if len(history) != 1 {
		t.Fatalf("algorithm mismatch mutated revision history: %#v", history)
	}
}

func TestAcceptResolvedScopeMismatchRollsBack(t *testing.T) {
	ctx := context.Background()
	store := openStore(t)
	artifact, err := store.AdoptArtifact(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.ObserveRevision(ctx, artifact.ID, evidence("same", 4)); err != nil {
		t.Fatal(err)
	}
	at := time.Date(2026, 9, 25, 21, 5, 0, 0, time.UTC)
	scan, err := store.StartScan(ctx, "localfs", "/corpus", at)
	if err != nil {
		t.Fatal(err)
	}
	input := unresolvedScanObservation("file.txt", at)
	input.Locators[0].Root = "/other"

	beforeObs := tableCount(t, store.Path(), "observations")
	_, err = store.AcceptResolvedObservationInScan(
		ctx, scan.ID, input, resolvedSame(t, artifact.ID),
		ptrEvidence(evidence("same", 4)), at, corpus.ContinuityPolicyCandidateSetV1,
	)
	if !errors.Is(err, sqlitestate.ErrScanScopeMismatch) {
		t.Fatalf("error=%v, want ErrScanScopeMismatch", err)
	}
	if got := tableCount(t, store.Path(), "observations"); got != beforeObs {
		t.Fatalf("scope mismatch wrote observation: before=%d after=%d", beforeObs, got)
	}
}

func TestAcceptedContinuitySurvivesReopen(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "state.db")
	store, err := sqlitestate.Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	artifact, err := store.AdoptArtifact(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.ObserveRevision(ctx, artifact.ID, evidence("same", 4)); err != nil {
		t.Fatal(err)
	}
	at := time.Date(2026, 9, 25, 21, 6, 0, 0, time.UTC)
	scan, err := store.StartScan(ctx, "localfs", "/corpus", at)
	if err != nil {
		t.Fatal(err)
	}
	accepted, err := store.AcceptResolvedObservationInScan(
		ctx, scan.ID, unresolvedScanObservation("file.txt", at), resolvedSame(t, artifact.ID),
		ptrEvidence(evidence("same", 4)), at, corpus.ContinuityPolicyCandidateSetV1,
	)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.CompleteScan(ctx, scan.ID, at); err != nil {
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
	record, err := store.AcceptedContinuity(ctx, accepted.Observation.ID)
	if err != nil {
		t.Fatal(err)
	}
	if record.ID != accepted.Decision.ID ||
		record.ArtifactID != artifact.ID ||
		record.Resolution.SelectedArtifactID != artifact.ID ||
		record.PolicyID != corpus.ContinuityPolicyCandidateSetV1 {
		t.Fatalf("reopened decision=%#v", record)
	}
	inventory, err := store.Inventory(ctx, "localfs", "/corpus")
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory) != 1 || inventory[0].ArtifactID != artifact.ID {
		t.Fatalf("reopened inventory=%#v", inventory)
	}
}

func resolvedSame(t *testing.T, artifactID corpus.ArtifactID) corpus.CandidateSetResolution {
	t.Helper()
	resolution, err := corpus.ResolveCandidateSet([]corpus.ArtifactCandidateInput{{
		ArtifactID: artifactID,
		Evidence: []corpus.DecisionEvidence{{
			Source: "trusted:test-conclusive",
			Direction: corpus.DirectionSupportsSame,
			Strength: corpus.EvidenceConclusive,
		}},
	}})
	if err != nil {
		t.Fatal(err)
	}
	return resolution
}

func ptrEvidence(value corpus.ContentEvidence) *corpus.ContentEvidence {
	return &value
}
