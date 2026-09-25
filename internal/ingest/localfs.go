package ingest

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/provider/localfs"
)

var ErrInvalidLocalFSIngest = errors.New("invalid local filesystem ingest")

// ScanStore is the minimal durable-state contract required by ingestion.
// It deliberately does not expose SQLite.
type ScanStore interface {
	StartScan(context.Context, corpus.ProviderID, string, time.Time) (corpus.ScanSession, error)
	RecordObservationInScan(context.Context, corpus.ScanSessionID, corpus.ObservationRecordInput) (corpus.ObservationRecord, error)
	CompleteScan(context.Context, corpus.ScanSessionID, time.Time) error
	AbortScan(context.Context, corpus.ScanSessionID, time.Time) error
}

// LocalFS snapshots one local corpus root read-only, persists the whole
// snapshot as unresolved evidence, and publishes it only by completing the
// scan after every Observation has been durably recorded.
//
// Discovery happens before StartScan. A persistence failure after StartScan
// triggers a best-effort ABORT so the previous COMPLETE scan remains current.
func LocalFS(ctx context.Context, store ScanStore, provider *localfs.Provider, root string, observedAt time.Time) (scan corpus.ScanSession, err error) {
	if store == nil || provider == nil || root == "" || observedAt.IsZero() {
		return corpus.ScanSession{}, ErrInvalidLocalFSIngest
	}

	snapshot, err := provider.Snapshot(ctx, root)
	if err != nil {
		return corpus.ScanSession{}, fmt.Errorf("snapshot local corpus: %w", err)
	}
	inputs, err := snapshotInputs(snapshot, observedAt.UTC())
	if err != nil {
		return corpus.ScanSession{}, err
	}

	scan, err = store.StartScan(ctx, snapshot.ProviderID(), snapshot.Root(), observedAt.UTC())
	if err != nil {
		return corpus.ScanSession{}, fmt.Errorf("start durable scan: %w", err)
	}

	finalized := false
	defer func() {
		if err == nil || finalized {
			return
		}
		if abortErr := store.AbortScan(context.Background(), scan.ID, observedAt.UTC()); abortErr != nil {
			err = errors.Join(err, fmt.Errorf("abort failed scan %s: %w", scan.ID, abortErr))
		}
	}()

	for _, input := range inputs {
		if _, err = store.RecordObservationInScan(ctx, scan.ID, input); err != nil {
			return scan, fmt.Errorf("persist snapshot observation: %w", err)
		}
	}

	if err = store.CompleteScan(ctx, scan.ID, observedAt.UTC()); err != nil {
		return scan, fmt.Errorf("complete durable scan: %w", err)
	}
	finalized = true
	scan.Status = corpus.ScanComplete
	scan.FinishedAt = observedAt.UTC()
	return scan, nil
}

func snapshotInputs(snapshot *localfs.Snapshot, observedAt time.Time) ([]corpus.ObservationRecordInput, error) {
	observations := snapshot.Observations()
	byPath := make(map[string]corpus.Observation, len(observations))
	for _, observation := range observations {
		byPath[observation.Locator.Path] = observation
	}

	inputs := make([]corpus.ObservationRecordInput, 0, len(observations))

	for _, group := range snapshot.ObjectGroups() {
		if len(group.Locators) == 0 {
			continue
		}
		representative, ok := byPath[group.Locators[0].Path]
		if !ok {
			return nil, fmt.Errorf("snapshot group representative %q missing from observations", group.Locators[0].Path)
		}
		inputs = append(inputs, inputFromObservation(representative, group.Locators, observedAt))
	}

	for _, observation := range observations {
		if observation.Kind == corpus.EntryRegularFile {
			continue
		}
		inputs = append(inputs, inputFromObservation(
			observation,
			[]corpus.Locator{observation.Locator},
			observedAt,
		))
	}

	sort.Slice(inputs, func(i, j int) bool {
		return inputs[i].Locators[0].Path < inputs[j].Locators[0].Path
	})
	return inputs, nil
}

func inputFromObservation(observation corpus.Observation, locators []corpus.Locator, observedAt time.Time) corpus.ObservationRecordInput {
	copiedLocators := make([]corpus.Locator, len(locators))
	copy(copiedLocators, locators)
	return corpus.ObservationRecordInput{
		ProviderObject: corpus.ProviderObject{
			ProviderID:    observation.ProviderObject.ProviderID,
			IdentityState: corpus.ObjectIdentityUnresolved,
		},
		Locators:        copiedLocators,
		AssignmentState: corpus.AssignmentUnresolved,
		ObservedAt:      observedAt,
		Kind:            observation.Kind,
		Size:            observation.Size,
		Mode:            observation.Mode,
		ModifiedAt:      observation.ModifiedAt,
	}
}


// BootstrapStore extends ScanStore with the two atomic operations required for
// safe first-observation identity adoption.
type BootstrapStore interface {
	ScanStore
	StartBootstrapScan(context.Context, corpus.ProviderID, string, time.Time) (corpus.ScanSession, error)
	AdoptObservationInScan(context.Context, corpus.ScanSessionID, corpus.ObservationRecordInput, *corpus.ContentEvidence) (corpus.ObservationRecord, error)
}

// BootstrapLocalFS is the explicit first-observation path.
//
// It is intentionally separate from LocalFS: later scans must not silently
// reuse or mint identity merely because path/hash/native identity looks
// familiar. The store atomically refuses bootstrap when observation history
// already exists for the provider/root.
func BootstrapLocalFS(ctx context.Context, store BootstrapStore, provider *localfs.Provider, root string, observedAt time.Time) (scan corpus.ScanSession, err error) {
	if store == nil || provider == nil || root == "" || observedAt.IsZero() {
		return corpus.ScanSession{}, ErrInvalidLocalFSIngest
	}

	snapshot, err := provider.Snapshot(ctx, root)
	if err != nil {
		return corpus.ScanSession{}, fmt.Errorf("snapshot local corpus: %w", err)
	}
	occurrences, err := bootstrapOccurrences(ctx, snapshot, observedAt.UTC())
	if err != nil {
		return corpus.ScanSession{}, err
	}

	scan, err = store.StartBootstrapScan(ctx, snapshot.ProviderID(), snapshot.Root(), observedAt.UTC())
	if err != nil {
		return corpus.ScanSession{}, fmt.Errorf("start bootstrap scan: %w", err)
	}

	finalized := false
	defer func() {
		if err == nil || finalized {
			return
		}
		if abortErr := store.AbortScan(context.Background(), scan.ID, observedAt.UTC()); abortErr != nil {
			err = errors.Join(err, fmt.Errorf("abort failed bootstrap scan %s: %w", scan.ID, abortErr))
		}
	}()

	for _, occurrence := range occurrences {
		if _, err = store.AdoptObservationInScan(ctx, scan.ID, occurrence.input, occurrence.evidence); err != nil {
			return scan, fmt.Errorf("adopt bootstrap occurrence: %w", err)
		}
	}

	if err = store.CompleteScan(ctx, scan.ID, observedAt.UTC()); err != nil {
		return scan, fmt.Errorf("complete bootstrap scan: %w", err)
	}
	finalized = true
	scan.Status = corpus.ScanComplete
	scan.FinishedAt = observedAt.UTC()
	return scan, nil
}

type bootstrapOccurrence struct {
	input    corpus.ObservationRecordInput
	evidence *corpus.ContentEvidence
}

func bootstrapOccurrences(ctx context.Context, snapshot *localfs.Snapshot, observedAt time.Time) ([]bootstrapOccurrence, error) {
	observations := snapshot.Observations()
	byPath := make(map[string]corpus.Observation, len(observations))
	for _, observation := range observations {
		byPath[observation.Locator.Path] = observation
	}

	out := make([]bootstrapOccurrence, 0, len(observations))
	for _, group := range snapshot.ObjectGroups() {
		if len(group.Locators) == 0 {
			continue
		}
		sample, err := snapshot.SampleObjectGroupContent(ctx, group)
		if err != nil {
			return nil, fmt.Errorf("sample regular occurrence %q: %w", group.Locators[0].Path, err)
		}
		input := inputFromObservation(sample.Observation, group.Locators, observedAt)
		evidence := sample.Evidence
		out = append(out, bootstrapOccurrence{input: input, evidence: &evidence})
	}

	for _, observation := range observations {
		if observation.Kind == corpus.EntryRegularFile {
			continue
		}
		out = append(out, bootstrapOccurrence{
			input: inputFromObservation(observation, []corpus.Locator{observation.Locator}, observedAt),
		})
	}

	sort.Slice(out, func(i, j int) bool {
		return out[i].input.Locators[0].Path < out[j].input.Locators[0].Path
	})
	return out, nil
}
