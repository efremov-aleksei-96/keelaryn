package localfs

import (
	"context"
	"errors"
	"fmt"
	"sort"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	providerlocalfs "github.com/efremov-aleksei-96/keelaryn/internal/provider/localfs"
)

var ErrInvalidCandidateScope = errors.New("invalid localfs candidate scope")

// InventoryReader exposes only the derived latest-COMPLETE inventory needed
// for read-only candidate generation.
type InventoryReader interface {
	Inventory(context.Context, corpus.ProviderID, string) ([]corpus.InventoryEntry, error)
}

// Candidates generates cheap, bounded reconciliation candidates for every
// current occurrence in snapshot.
//
// Base generation uses Locator overlap only. It never hashes content, compares
// cross-time native IDs, persists reconciliation, or mutates Artifact identity.
func Candidates(ctx context.Context, reader InventoryReader, snapshot *providerlocalfs.Snapshot) ([]corpus.OccurrenceCandidateSet, error) {
	if reader == nil || snapshot == nil || snapshot.ProviderID() == "" || snapshot.Root() == "" {
		return nil, ErrInvalidCandidateScope
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}

	previous, err := reader.Inventory(ctx, snapshot.ProviderID(), snapshot.Root())
	if err != nil {
		return nil, fmt.Errorf("read previous COMPLETE inventory: %w", err)
	}

	byPath := make(map[string][]corpus.ArtifactID)
	for _, entry := range previous {
		if entry.AssignmentState != corpus.AssignmentAssigned || entry.ArtifactID == "" {
			continue
		}
		if entry.Locator.ProviderID != snapshot.ProviderID() || entry.Locator.Root != snapshot.Root() {
			return nil, fmt.Errorf("%w: prior locator %#v", ErrInvalidCandidateScope, entry.Locator)
		}
		byPath[entry.Locator.Path] = append(byPath[entry.Locator.Path], entry.ArtifactID)
	}
	for path := range byPath {
		sort.Slice(byPath[path], func(i, j int) bool { return byPath[path][i] < byPath[path][j] })
	}

	observations := snapshot.Observations()
	byCurrentPath := make(map[string]corpus.Observation, len(observations))
	for _, observation := range observations {
		byCurrentPath[observation.Locator.Path] = observation
	}

	var out []corpus.OccurrenceCandidateSet

	for _, group := range snapshot.ObjectGroups() {
		if len(group.Locators) == 0 {
			continue
		}
		representative, ok := byCurrentPath[group.Locators[0].Path]
		if !ok {
			return nil, fmt.Errorf("%w: group representative %q missing", ErrInvalidCandidateScope, group.Locators[0].Path)
		}
		set, err := candidateSetForLocators(group.Locators, representative.Kind, byPath)
		if err != nil {
			return nil, err
		}
		out = append(out, set)
	}

	for _, observation := range observations {
		if observation.Kind == corpus.EntryRegularFile {
			continue
		}
		set, err := candidateSetForLocators([]corpus.Locator{observation.Locator}, observation.Kind, byPath)
		if err != nil {
			return nil, err
		}
		out = append(out, set)
	}

	sort.Slice(out, func(i, j int) bool {
		return out[i].Locators[0].Path < out[j].Locators[0].Path
	})
	return out, nil
}

func candidateSetForLocators(locators []corpus.Locator, kind corpus.EntryKind, byPath map[string][]corpus.ArtifactID) (corpus.OccurrenceCandidateSet, error) {
	artifactPaths := make(map[corpus.ArtifactID][]string)
	for _, locator := range locators {
		for _, artifactID := range byPath[locator.Path] {
			artifactPaths[artifactID] = append(artifactPaths[artifactID], locator.Path)
		}
	}

	ids := make([]corpus.ArtifactID, 0, len(artifactPaths))
	for artifactID := range artifactPaths {
		ids = append(ids, artifactID)
	}
	sort.Slice(ids, func(i, j int) bool { return ids[i] < ids[j] })

	inputs := make([]corpus.ArtifactCandidateInput, 0, len(ids))
	for _, artifactID := range ids {
		paths := artifactPaths[artifactID]
		sort.Strings(paths)
		evidence := make([]corpus.DecisionEvidence, 0, len(paths))
		for _, path := range paths {
			evidence = append(evidence, (corpus.ReconciliationSignal{
				Kind:   corpus.SignalLocatorOverlap,
				Source: "localfs:locator-overlap:" + path,
			}).DecisionEvidence())
		}
		inputs = append(inputs, corpus.ArtifactCandidateInput{
			ArtifactID: artifactID,
			Evidence:   evidence,
		})
	}

	resolution, err := corpus.ResolveCandidateSet(inputs)
	if err != nil {
		return corpus.OccurrenceCandidateSet{}, err
	}
	copiedLocators := append([]corpus.Locator(nil), locators...)
	return corpus.OccurrenceCandidateSet{
		Locators:   copiedLocators,
		Kind:       kind,
		Inputs:     inputs,
		Resolution: resolution,
	}, nil
}
