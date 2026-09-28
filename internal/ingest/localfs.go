package ingest

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/provider/localfs"
)

var (
	ErrInvalidLocalFSIngest   = errors.New("invalid local filesystem ingest")
	ErrLocalFSSnapshotChanged = errors.New("local filesystem snapshot changed before durable commit")
)

const localFSSnapshotFingerprintVersion = "localfs-snapshot:v1"

// ScanStore is the minimal durable-state contract required by local ingestion.
// The whole provider snapshot is committed atomically. finalValidate executes
// inside the same durable transaction immediately before COMPLETE.
type ScanStore interface {
	CommitLocalSnapshot(
		context.Context,
		corpus.ProviderID,
		string,
		time.Time,
		string,
		string,
		[]corpus.ObservationRecordInput,
		func(context.Context) error,
	) (corpus.ScanSession, error)
}

// LocalFS snapshots one local corpus root read-only, persists the whole
// snapshot as unresolved evidence, and publishes it only by completing the
// scan after every Observation has been durably recorded.
//
// Discovery happens before StartScan. A persistence failure after StartScan
// triggers a best-effort ABORT so the previous COMPLETE scan remains current.
func LocalFS(ctx context.Context, store ScanStore, provider *localfs.Provider, root string, observedAt time.Time) (corpus.ScanSession, error) {
	if store == nil || provider == nil || root == "" || observedAt.IsZero() {
		return corpus.ScanSession{}, ErrInvalidLocalFSIngest
	}
	observedAt = observedAt.UTC()

	initial, err := provider.Snapshot(ctx, root)
	if err != nil {
		return corpus.ScanSession{}, fmt.Errorf("snapshot local corpus: %w", err)
	}
	inputs, err := snapshotInputs(initial, observedAt)
	if err != nil {
		return corpus.ScanSession{}, err
	}
	fingerprint, err := localSnapshotFingerprint("SCAN", initial.ProviderID(), initial.Root(), observedAt, inputs)
	if err != nil {
		return corpus.ScanSession{}, err
	}

	return store.CommitLocalSnapshot(
		ctx,
		initial.ProviderID(),
		initial.Root(),
		observedAt,
		localFSSnapshotFingerprintVersion,
		fingerprint,
		inputs,
		func(validateCtx context.Context) error {
			finalSnapshot, err := provider.Snapshot(validateCtx, root)
			if err != nil {
				return fmt.Errorf("%w: final snapshot: %v", ErrLocalFSSnapshotChanged, err)
			}
			finalInputs, err := snapshotInputs(finalSnapshot, observedAt)
			if err != nil {
				return err
			}
			finalFingerprint, err := localSnapshotFingerprint("SCAN", finalSnapshot.ProviderID(), finalSnapshot.Root(), observedAt, finalInputs)
			if err != nil {
				return err
			}
			if finalFingerprint != fingerprint {
				return ErrLocalFSSnapshotChanged
			}
			return nil
		},
	)
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


// BootstrapStore commits the entire first-observation adoption batch atomically.
type BootstrapStore interface {
	CommitBootstrapLocalSnapshot(
		context.Context,
		corpus.ProviderID,
		string,
		time.Time,
		string,
		string,
		[]corpus.BootstrapObservationInput,
		func(context.Context) error,
	) (corpus.ScanSession, error)
}

// BootstrapLocalFS is the explicit first-observation path.
//
// It is intentionally separate from LocalFS: later scans must not silently
// reuse or mint identity merely because path/hash/native identity looks
// familiar. The store atomically refuses bootstrap when observation history
// already exists for the provider/root.
func BootstrapLocalFS(ctx context.Context, store BootstrapStore, provider *localfs.Provider, root string, observedAt time.Time) (corpus.ScanSession, error) {
	if store == nil || provider == nil || root == "" || observedAt.IsZero() {
		return corpus.ScanSession{}, ErrInvalidLocalFSIngest
	}
	observedAt = observedAt.UTC()

	initial, err := provider.Snapshot(ctx, root)
	if err != nil {
		return corpus.ScanSession{}, fmt.Errorf("snapshot local corpus: %w", err)
	}
	occurrences, err := bootstrapOccurrences(ctx, initial, observedAt)
	if err != nil {
		return corpus.ScanSession{}, err
	}
	fingerprint, err := localSnapshotFingerprint("BOOTSTRAP", initial.ProviderID(), initial.Root(), observedAt, occurrences)
	if err != nil {
		return corpus.ScanSession{}, err
	}

	return store.CommitBootstrapLocalSnapshot(
		ctx,
		initial.ProviderID(),
		initial.Root(),
		observedAt,
		localFSSnapshotFingerprintVersion,
		fingerprint,
		occurrences,
		func(validateCtx context.Context) error {
			finalSnapshot, err := provider.Snapshot(validateCtx, root)
			if err != nil {
				return fmt.Errorf("%w: final bootstrap snapshot: %v", ErrLocalFSSnapshotChanged, err)
			}
			finalOccurrences, err := bootstrapOccurrences(validateCtx, finalSnapshot, observedAt)
			if err != nil {
				return fmt.Errorf("%w: final bootstrap evidence: %v", ErrLocalFSSnapshotChanged, err)
			}
			finalFingerprint, err := localSnapshotFingerprint("BOOTSTRAP", finalSnapshot.ProviderID(), finalSnapshot.Root(), observedAt, finalOccurrences)
			if err != nil {
				return err
			}
			if finalFingerprint != fingerprint {
				return ErrLocalFSSnapshotChanged
			}
			return nil
		},
	)
}

func bootstrapOccurrences(ctx context.Context, snapshot *localfs.Snapshot, observedAt time.Time) ([]corpus.BootstrapObservationInput, error) {
	observations := snapshot.Observations()
	byPath := make(map[string]corpus.Observation, len(observations))
	for _, observation := range observations {
		byPath[observation.Locator.Path] = observation
	}

	out := make([]corpus.BootstrapObservationInput, 0, len(observations))
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
		out = append(out, corpus.BootstrapObservationInput{Observation: input, Evidence: &evidence})
	}

	for _, observation := range observations {
		if observation.Kind == corpus.EntryRegularFile {
			continue
		}
		out = append(out, corpus.BootstrapObservationInput{
			Observation: inputFromObservation(observation, []corpus.Locator{observation.Locator}, observedAt),
		})
	}

	sort.Slice(out, func(i, j int) bool {
		return out[i].Observation.Locators[0].Path < out[j].Observation.Locators[0].Path
	})
	return out, nil
}

func localSnapshotFingerprint(mode string, providerID corpus.ProviderID, root string, observedAt time.Time, payload any) (string, error) {
	encoded, err := json.Marshal(struct {
		Version    string            `json:"version"`
		Mode       string            `json:"mode"`
		ProviderID corpus.ProviderID `json:"provider_id"`
		Root       string            `json:"root"`
		ObservedAt time.Time         `json:"observed_at"`
		Payload    any               `json:"payload"`
	}{
		Version: localFSSnapshotFingerprintVersion,
		Mode: mode,
		ProviderID: providerID,
		Root: root,
		ObservedAt: observedAt.UTC(),
		Payload: payload,
	})
	if err != nil {
		return "", fmt.Errorf("encode local snapshot fingerprint: %w", err)
	}
	sum := sha256.Sum256(encoded)
	return hex.EncodeToString(sum[:]), nil
}
