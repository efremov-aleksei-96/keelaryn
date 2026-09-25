package localfs

import (
	"context"
	"errors"
	"fmt"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	providerlocalfs "github.com/efremov-aleksei-96/keelaryn/internal/provider/localfs"
)

var ErrInvalidContentCandidateSet = errors.New("invalid content candidate set")

// RevisionReader exposes only the durable Revision evidence required for
// explicit candidate enrichment.
type RevisionReader interface {
	RevisionHistory(context.Context, corpus.ArtifactID) ([]corpus.RevisionRecord, error)
}

// ContentEnrichment is the result of explicitly hashing one current regular
// occurrence and comparing it only with already-discovered Artifact
// candidates.
type ContentEnrichment struct {
	Set      corpus.OccurrenceCandidateSet `json:"set"`
	Evidence *corpus.ContentEvidence        `json:"evidence,omitempty"`
}

// EnrichContent performs selective, read-only content enrichment.
//
// No candidates => no file read.
// Non-empty candidates => current content is sampled exactly once through the
// Snapshot's open-handle-anchored group sampler.
// Only equal current Revision evidence adds a SUPPORTING CONTENT_EQUAL signal.
// A mismatch adds no negative signal because content changes are valid within
// one Artifact.
func EnrichContent(ctx context.Context, reader RevisionReader, snapshot *providerlocalfs.Snapshot, set corpus.OccurrenceCandidateSet) (ContentEnrichment, error) {
	if reader == nil || snapshot == nil {
		return ContentEnrichment{}, ErrInvalidContentCandidateSet
	}
	if len(set.Inputs) == 0 {
		return ContentEnrichment{Set: cloneSet(set)}, nil
	}
	if set.Kind != corpus.EntryRegularFile || len(set.Locators) == 0 {
		return ContentEnrichment{}, ErrInvalidContentCandidateSet
	}
	if err := ctx.Err(); err != nil {
		return ContentEnrichment{}, err
	}

	group, ok := findExactGroup(snapshot, set.Locators)
	if !ok {
		return ContentEnrichment{}, fmt.Errorf("%w: candidate locators do not identify one current regular group", ErrInvalidContentCandidateSet)
	}

	sample, err := snapshot.SampleObjectGroupContent(ctx, group)
	if err != nil {
		return ContentEnrichment{}, fmt.Errorf("sample current candidate content: %w", err)
	}
	current := sample.Evidence
	inputs := cloneInputs(set.Inputs)

	for i := range inputs {
		history, err := reader.RevisionHistory(ctx, inputs[i].ArtifactID)
		if err != nil {
			return ContentEnrichment{}, fmt.Errorf("read candidate %s Revision history: %w", inputs[i].ArtifactID, err)
		}
		if len(history) == 0 {
			continue
		}
		latest := history[len(history)-1]
		if latest.Evidence.Algorithm == current.Algorithm &&
			latest.Evidence.Digest == current.Digest &&
			latest.Evidence.Size == current.Size {
			inputs[i].Evidence = append(inputs[i].Evidence, (corpus.ReconciliationSignal{
				Kind:   corpus.SignalContentEqual,
				Source: "localfs:content-equal:" + current.Algorithm,
			}).DecisionEvidence())
		}
	}

	resolution, err := corpus.ResolveCandidateSet(inputs)
	if err != nil {
		return ContentEnrichment{}, err
	}

	enriched := cloneSet(set)
	enriched.Inputs = inputs
	enriched.Resolution = resolution
	return ContentEnrichment{
		Set:      enriched,
		Evidence: &current,
	}, nil
}

func findExactGroup(snapshot *providerlocalfs.Snapshot, locators []corpus.Locator) (providerlocalfs.ObjectGroup, bool) {
	for _, group := range snapshot.ObjectGroups() {
		if sameLocators(group.Locators, locators) {
			return group, true
		}
	}
	return providerlocalfs.ObjectGroup{}, false
}

func sameLocators(a, b []corpus.Locator) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

func cloneInputs(src []corpus.ArtifactCandidateInput) []corpus.ArtifactCandidateInput {
	out := make([]corpus.ArtifactCandidateInput, len(src))
	for i := range src {
		out[i] = corpus.ArtifactCandidateInput{
			ArtifactID: src[i].ArtifactID,
			Evidence:   append([]corpus.DecisionEvidence(nil), src[i].Evidence...),
		}
	}
	return out
}

func cloneSet(src corpus.OccurrenceCandidateSet) corpus.OccurrenceCandidateSet {
	out := src
	out.Locators = append([]corpus.Locator(nil), src.Locators...)
	out.Inputs = cloneInputs(src.Inputs)
	out.Resolution.Candidates = append([]corpus.ArtifactCandidateResolution(nil), src.Resolution.Candidates...)
	for i := range out.Resolution.Candidates {
		out.Resolution.Candidates[i].Decision.Evidence = append(
			[]corpus.DecisionEvidence(nil),
			src.Resolution.Candidates[i].Decision.Evidence...,
		)
	}
	return out
}
