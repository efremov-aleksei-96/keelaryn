package remotehistory

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
)

const (
	RemoteMetadataSnapshotFingerprintVersion = "keelaryn.remote-metadata-snapshot:v1"
	LightweightAllMaterializationPolicyID    = "LIGHTWEIGHT_ALL:v1"
)

var ErrInvalidRemoteMetadataFingerprint = errors.New("invalid remote metadata fingerprint input")

type RemoteMetadataFingerprintEntry struct {
	ProviderObjectID corpus.ProviderObjectID `json:"provider_object_id"`
	Locators         []corpus.Locator        `json:"locators"`
	Kind             corpus.EntryKind        `json:"kind"`
	Size             int64                   `json:"size"`
	Mode             uint32                  `json:"mode"`
	ModifiedAt       string                  `json:"modified_at"`
}

type RemoteMetadataFingerprintInput struct {
	GenerationID            HistoryGenerationID
	PublicationSequence     HistoryPublicationSequence
	ProviderID              corpus.ProviderID
	ScanRoot                string
	SourceScopeID           string
	MaterializationPolicyID string
	Entries                 []RemoteMetadataFingerprintEntry
}

func FingerprintRemoteMetadataSnapshot(input RemoteMetadataFingerprintInput) (string, error) {
	if input.GenerationID == "" || input.PublicationSequence == 0 || input.ProviderID == "" ||
		strings.TrimSpace(input.ScanRoot) == "" ||
		strings.TrimSpace(input.SourceScopeID) == "" ||
		input.MaterializationPolicyID != LightweightAllMaterializationPolicyID {
		return "", ErrInvalidRemoteMetadataFingerprint
	}

	entries := make([]RemoteMetadataFingerprintEntry, len(input.Entries))
	seenObjects := make(map[corpus.ProviderObjectID]struct{}, len(entries))
	locatorOwners := make(map[corpus.Locator]corpus.ProviderObjectID)
	for i, entry := range input.Entries {
		if entry.ProviderObjectID == "" || entry.Size < 0 || len(entry.Locators) == 0 {
			return "", ErrInvalidRemoteMetadataFingerprint
		}
		if _, duplicate := seenObjects[entry.ProviderObjectID]; duplicate {
			return "", fmt.Errorf("%w: duplicate object %s", ErrInvalidRemoteMetadataFingerprint, entry.ProviderObjectID)
		}
		seenObjects[entry.ProviderObjectID] = struct{}{}
		switch entry.Kind {
		case corpus.EntryRegularFile, corpus.EntrySymlink, corpus.EntryOther:
		default:
			return "", ErrInvalidRemoteMetadataFingerprint
		}
		modifiedAt, err := time.Parse(time.RFC3339Nano, entry.ModifiedAt)
		if err != nil {
			return "", fmt.Errorf("%w: modified_at for %s: %v", ErrInvalidRemoteMetadataFingerprint, entry.ProviderObjectID, err)
		}
		entry.ModifiedAt = modifiedAt.UTC().Format(time.RFC3339Nano)
		entry.Locators = append([]corpus.Locator(nil), entry.Locators...)
		sort.Slice(entry.Locators, func(a, b int) bool {
			if entry.Locators[a].ProviderID != entry.Locators[b].ProviderID {
				return entry.Locators[a].ProviderID < entry.Locators[b].ProviderID
			}
			if entry.Locators[a].Root != entry.Locators[b].Root {
				return entry.Locators[a].Root < entry.Locators[b].Root
			}
			return entry.Locators[a].Path < entry.Locators[b].Path
		})
		for j, locator := range entry.Locators {
			if locator.ProviderID != input.ProviderID || locator.Root != input.ScanRoot || strings.TrimSpace(locator.Path) == "" {
				return "", fmt.Errorf("%w: locator %#v", ErrInvalidRemoteMetadataFingerprint, locator)
			}
			if j > 0 && locator == entry.Locators[j-1] {
				return "", fmt.Errorf("%w: duplicate locator %#v", ErrInvalidRemoteMetadataFingerprint, locator)
			}
			if owner, exists := locatorOwners[locator]; exists && owner != entry.ProviderObjectID {
				return "", fmt.Errorf("%w: locator collision %s/%s", ErrInvalidRemoteMetadataFingerprint, owner, entry.ProviderObjectID)
			}
			locatorOwners[locator] = entry.ProviderObjectID
		}
		entries[i] = entry
	}
	sort.Slice(entries, func(i, j int) bool {
		return entries[i].ProviderObjectID < entries[j].ProviderObjectID
	})

	value := struct {
		Version                 string                           `json:"version"`
		GenerationID            HistoryGenerationID              `json:"generation_id"`
		PublicationSequence     HistoryPublicationSequence       `json:"publication_sequence"`
		ProviderID              corpus.ProviderID                `json:"provider_id"`
		ScanRoot                string                           `json:"scan_root"`
		SourceScopeID           string                           `json:"source_scope_id"`
		MaterializationPolicyID string                           `json:"materialization_policy_id"`
		Entries                 []RemoteMetadataFingerprintEntry `json:"entries"`
	}{
		Version:                 RemoteMetadataSnapshotFingerprintVersion,
		GenerationID:            input.GenerationID,
		PublicationSequence:     input.PublicationSequence,
		ProviderID:              input.ProviderID,
		ScanRoot:                input.ScanRoot,
		SourceScopeID:           input.SourceScopeID,
		MaterializationPolicyID: input.MaterializationPolicyID,
		Entries:                 entries,
	}
	encoded, err := json.Marshal(value)
	if err != nil {
		return "", fmt.Errorf("encode remote metadata snapshot fingerprint: %w", err)
	}
	sum := sha256.Sum256(encoded)
	return hex.EncodeToString(sum[:]), nil
}
