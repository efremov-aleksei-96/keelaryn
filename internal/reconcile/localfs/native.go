package localfs

import (
	"errors"
	"fmt"
	"sort"
	"strings"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	providerlocalfs "github.com/efremov-aleksei-96/keelaryn/internal/provider/localfs"
)

var ErrInvalidNativeSnapshotBinding = errors.New("invalid native snapshot binding")

// EnrichNativeCandidates adds in-process local filesystem continuity evidence
// while both the previous and current Snapshots coexist.
//
// Native identity is never persisted and every emitted signal is SUPPORTING.
// A native mismatch emits no elimination evidence.
func EnrichNativeCandidates(
	previous *providerlocalfs.Snapshot,
	current *providerlocalfs.Snapshot,
	previousInventory []corpus.InventoryEntry,
	base []corpus.OccurrenceCandidateSet,
) ([]corpus.OccurrenceCandidateSet, error) {
	if previous == nil || current == nil {
		return nil, ErrInvalidNativeSnapshotBinding
	}
	if previous.ProviderID() == "" ||
		previous.ProviderID() != current.ProviderID() ||
		previous.Root() == "" ||
		previous.Root() != current.Root() {
		return nil, fmt.Errorf("%w: snapshot scope mismatch", ErrInvalidNativeSnapshotBinding)
	}
	if err := validatePreviousBinding(previous, previousInventory); err != nil {
		return nil, err
	}
	if err := validateCurrentSets(current, base); err != nil {
		return nil, err
	}

	previousArtifactsByPath := make(map[string][]corpus.ArtifactID)
	for _, entry := range previousInventory {
		if entry.AssignmentState != corpus.AssignmentAssigned || entry.ArtifactID == "" {
			continue
		}
		previousArtifactsByPath[entry.Locator.Path] = append(previousArtifactsByPath[entry.Locator.Path], entry.ArtifactID)
	}

	previousGroups := previous.ObjectGroups()
	currentGroups := current.ObjectGroups()

	out := make([]corpus.OccurrenceCandidateSet, len(base))
	for i := range base {
		out[i] = cloneSet(base[i])
		if out[i].Kind != corpus.EntryRegularFile {
			continue
		}

		currentGroup, ok := groupForLocators(currentGroups, out[i].Locators)
		if !ok {
			return nil, fmt.Errorf("%w: current group not found for %s", ErrInvalidNativeSnapshotBinding, locatorKey(out[i].Locators))
		}

		inputs := cloneInputs(out[i].Inputs)
		for _, previousGroup := range previousGroups {
			evidence, err := providerlocalfs.CompareObjectGroups(previous, previousGroup, current, currentGroup)
			if err != nil {
				return nil, fmt.Errorf("compare native groups: %w", err)
			}
			if evidence.Kind != corpus.ContinuityNativeIdentityMatch {
				continue
			}

			artifactIDs := artifactsForGroup(previousGroup, previousArtifactsByPath)
			for _, artifactID := range artifactIDs {
				inputs = addEvidence(inputs, artifactID, (corpus.ReconciliationSignal{
					Kind: corpus.SignalProviderContinuityMatch,
					Source: "localfs:os.SameFile:" +
						previousGroup.Locators[0].Path + "->" + currentGroup.Locators[0].Path,
				}).DecisionEvidence())
			}
		}

		resolution, err := corpus.ResolveCandidateSet(inputs)
		if err != nil {
			return nil, err
		}
		out[i].Inputs = inputs
		out[i].Resolution = resolution
	}
	return out, nil
}

func validatePreviousBinding(snapshot *providerlocalfs.Snapshot, inventory []corpus.InventoryEntry) error {
	observations := snapshot.Observations()
	if len(inventory) != len(observations) {
		return fmt.Errorf("%w: previous inventory rows=%d snapshot locators=%d", ErrInvalidNativeSnapshotBinding, len(inventory), len(observations))
	}

	byPath := make(map[string]corpus.Observation, len(observations))
	for _, observation := range observations {
		if _, exists := byPath[observation.Locator.Path]; exists {
			return fmt.Errorf("%w: duplicate snapshot locator %q", ErrInvalidNativeSnapshotBinding, observation.Locator.Path)
		}
		byPath[observation.Locator.Path] = observation
	}

	seen := make(map[string]struct{}, len(inventory))
	for _, entry := range inventory {
		if entry.Locator.ProviderID != snapshot.ProviderID() || entry.Locator.Root != snapshot.Root() {
			return fmt.Errorf("%w: previous inventory scope %#v", ErrInvalidNativeSnapshotBinding, entry.Locator)
		}
		if _, exists := seen[entry.Locator.Path]; exists {
			return fmt.Errorf("%w: duplicate inventory locator %q", ErrInvalidNativeSnapshotBinding, entry.Locator.Path)
		}
		seen[entry.Locator.Path] = struct{}{}

		observation, ok := byPath[entry.Locator.Path]
		if !ok ||
			observation.Kind != entry.Kind ||
			observation.Size != entry.Size ||
			!observation.ModifiedAt.Equal(entry.ModifiedAt) {
			return fmt.Errorf("%w: previous inventory does not match Snapshot at %q", ErrInvalidNativeSnapshotBinding, entry.Locator.Path)
		}
	}
	return nil
}

func validateCurrentSets(snapshot *providerlocalfs.Snapshot, sets []corpus.OccurrenceCandidateSet) error {
	expected := currentOccurrenceDescriptors(snapshot)
	if len(expected) != len(sets) {
		return fmt.Errorf("%w: current sets=%d expected occurrences=%d", ErrInvalidNativeSnapshotBinding, len(sets), len(expected))
	}
	for i := range expected {
		if expected[i].kind != sets[i].Kind || expected[i].key != locatorKey(sets[i].Locators) {
			return fmt.Errorf("%w: current set %d does not match Snapshot", ErrInvalidNativeSnapshotBinding, i)
		}
	}
	return nil
}

type occurrenceDescriptor struct {
	key  string
	kind corpus.EntryKind
}

func currentOccurrenceDescriptors(snapshot *providerlocalfs.Snapshot) []occurrenceDescriptor {
	var out []occurrenceDescriptor
	for _, group := range snapshot.ObjectGroups() {
		if len(group.Locators) > 0 {
			out = append(out, occurrenceDescriptor{
				key:  locatorKey(group.Locators),
				kind: corpus.EntryRegularFile,
			})
		}
	}
	for _, observation := range snapshot.Observations() {
		if observation.Kind != corpus.EntryRegularFile {
			out = append(out, occurrenceDescriptor{
				key:  locatorKey([]corpus.Locator{observation.Locator}),
				kind: observation.Kind,
			})
		}
	}
	sort.Slice(out, func(i, j int) bool {
		return strings.Compare(out[i].key, out[j].key) < 0
	})
	return out
}

func groupForLocators(groups []providerlocalfs.ObjectGroup, locators []corpus.Locator) (providerlocalfs.ObjectGroup, bool) {
	for _, group := range groups {
		if sameLocators(group.Locators, locators) {
			return group, true
		}
	}
	return providerlocalfs.ObjectGroup{}, false
}

func artifactsForGroup(group providerlocalfs.ObjectGroup, byPath map[string][]corpus.ArtifactID) []corpus.ArtifactID {
	seen := make(map[corpus.ArtifactID]struct{})
	for _, locator := range group.Locators {
		for _, artifactID := range byPath[locator.Path] {
			seen[artifactID] = struct{}{}
		}
	}
	out := make([]corpus.ArtifactID, 0, len(seen))
	for artifactID := range seen {
		out = append(out, artifactID)
	}
	sort.Slice(out, func(i, j int) bool { return out[i] < out[j] })
	return out
}

func addEvidence(inputs []corpus.ArtifactCandidateInput, artifactID corpus.ArtifactID, evidence corpus.DecisionEvidence) []corpus.ArtifactCandidateInput {
	for i := range inputs {
		if inputs[i].ArtifactID == artifactID {
			inputs[i].Evidence = append(inputs[i].Evidence, evidence)
			return inputs
		}
	}
	inputs = append(inputs, corpus.ArtifactCandidateInput{
		ArtifactID: artifactID,
		Evidence:   []corpus.DecisionEvidence{evidence},
	})
	sort.Slice(inputs, func(i, j int) bool { return inputs[i].ArtifactID < inputs[j].ArtifactID })
	return inputs
}

func locatorKey(locators []corpus.Locator) string {
	parts := make([]string, len(locators))
	for i, locator := range locators {
		parts[i] = string(locator.ProviderID) + "\x00" + locator.Root + "\x00" + locator.Path
	}
	return strings.Join(parts, "\x01")
}
