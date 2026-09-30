package gdrive

import (
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
)

const (
	googleFolderMIMEType   = "application/vnd.google-apps.folder"
	googleShortcutMIMEType = "application/vnd.google-apps.shortcut"
	googleDriveSDKMIMEType = "application/vnd.google-apps.drive-sdk"
)

// MetadataRecord is transient provider evidence captured at the same fenced
// boundary as a RemoteHistory bootstrap. It is not a second durable inventory.
type MetadataRecord struct {
	ObjectID   corpus.ProviderObjectID
	Kind       corpus.EntryKind
	Size       *int64
	ModifiedAt *time.Time
}

type BootstrapMetadataBundle struct {
	Bundle   BootstrapBundle
	Metadata []MetadataRecord
}

func metadataRecordFromFile(file FileRecord) (MetadataRecord, error) {
	objectID := corpus.ProviderObjectID(strings.TrimSpace(file.ID))
	mime := strings.TrimSpace(file.MimeType)
	if objectID == "" || mime == "" {
		return MetadataRecord{}, fmt.Errorf("%w: metadata object=%q mime=%q", ErrInvalidClientResponse, objectID, mime)
	}
	kind := corpus.EntryRegularFile
	switch mime {
	case googleFolderMIMEType, googleShortcutMIMEType, googleDriveSDKMIMEType:
		kind = corpus.EntryOther
	}

	var size *int64
	if file.SizeKnown {
		if file.Size < 0 {
			return MetadataRecord{}, fmt.Errorf("%w: negative size for %s", ErrInvalidClientResponse, objectID)
		}
		value := file.Size
		size = &value
	}

	var modifiedAt *time.Time
	if text := strings.TrimSpace(file.ModifiedTime); text != "" {
		value, err := time.Parse(time.RFC3339Nano, text)
		if err != nil || value.IsZero() {
			return MetadataRecord{}, fmt.Errorf("%w: invalid modifiedTime for %s", ErrInvalidClientResponse, objectID)
		}
		value = value.UTC()
		modifiedAt = &value
	}
	return MetadataRecord{ObjectID: objectID, Kind: kind, Size: size, ModifiedAt: modifiedAt}, nil
}

func metadataForObjects(
	files []FileRecord,
	objects map[corpus.ProviderObjectID]struct{},
) (map[corpus.ProviderObjectID]MetadataRecord, error) {
	out := make(map[corpus.ProviderObjectID]MetadataRecord, len(objects))
	for _, file := range files {
		objectID := corpus.ProviderObjectID(strings.TrimSpace(file.ID))
		if _, ok := objects[objectID]; !ok {
			continue
		}
		metadata, err := metadataRecordFromFile(file)
		if err != nil {
			return nil, err
		}
		out[objectID] = metadata
	}
	if len(out) != len(objects) {
		return nil, fmt.Errorf("%w: bootstrap metadata missing current object", ErrInvalidClientResponse)
	}
	return out, nil
}

func sortedMetadataRecords(records map[corpus.ProviderObjectID]MetadataRecord) []MetadataRecord {
	ids := make([]string, 0, len(records))
	for id := range records {
		ids = append(ids, string(id))
	}
	sort.Strings(ids)
	out := make([]MetadataRecord, 0, len(ids))
	for _, id := range ids {
		out = append(out, cloneMetadataRecord(records[corpus.ProviderObjectID(id)]))
	}
	return out
}

func cloneMetadataRecord(record MetadataRecord) MetadataRecord {
	out := record
	if record.Size != nil {
		value := *record.Size
		out.Size = &value
	}
	if record.ModifiedAt != nil {
		value := record.ModifiedAt.UTC()
		out.ModifiedAt = &value
	}
	return out
}

func validateBootstrapMetadataBundle(bundle BootstrapMetadataBundle) error {
	if err := validateBootstrapBundle(bundle.Bundle); err != nil {
		return err
	}
	if bundle.Bundle.History.Status != remotehistory.BootstrapComplete {
		if len(bundle.Metadata) != 0 {
			return ErrInvalidClientResponse
		}
		return nil
	}
	if len(bundle.Bundle.History.Objects) != len(bundle.Metadata) {
		return fmt.Errorf("%w: metadata/object alignment", ErrInvalidClientResponse)
	}
	for i := range bundle.Metadata {
		if bundle.Bundle.History.Objects[i].ObjectID != bundle.Metadata[i].ObjectID {
			return fmt.Errorf("%w: metadata/object alignment", ErrInvalidClientResponse)
		}
	}
	return nil
}
