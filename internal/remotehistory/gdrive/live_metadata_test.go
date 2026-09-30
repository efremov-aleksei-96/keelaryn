package gdrive_test

import (
	"context"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory/gdrive"
)

func TestBootstrapWithMetadataUsesSameFenceAndCatchUp(t *testing.T) {
	t1 := time.Date(2026, 9, 30, 10, 0, 0, 0, time.UTC)
	t2 := t1.Add(time.Minute)
	client := &fakeClient{
		startToken: "fence-1",
		filePages: []gdrive.FilePage{{Files: []gdrive.FileRecord{
			{ID: "managed", Parents: []string{"my-drive-root-id"}, MimeType: "application/vnd.google-apps.folder", ModifiedTime: t1.Format(time.RFC3339Nano)},
			{ID: "blob", Parents: []string{"managed"}, MimeType: "application/octet-stream", Size: 1, SizeKnown: true, ModifiedTime: t1.Format(time.RFC3339Nano)},
			{ID: "native", Parents: []string{"managed"}, MimeType: "application/vnd.google-apps.document", Size: 12, SizeKnown: true, ModifiedTime: t1.Format(time.RFC3339Nano)},
			{ID: "shortcut", Parents: []string{"managed"}, MimeType: "application/vnd.google-apps.shortcut", ModifiedTime: t1.Format(time.RFC3339Nano), ShortcutTargetID: "target"},
		}}},
		changePages: map[string]changeResult{
			"fence-1": {page: gdrive.ChangePage{
				Changes: []gdrive.ChangeRecord{{
					ChangeType: "file", FileID: "blob",
					File: &gdrive.FileRecord{ID: "blob", Parents: []string{"managed"}, MimeType: "application/octet-stream", Size: 7, SizeKnown: true, ModifiedTime: t2.Format(time.RFC3339Nano)},
				}},
				NewStartPageToken: "cursor-1",
			}},
		},
	}
	adapter := mustAdapter(t, client, myDriveConfig())
	bundle, err := adapter.BootstrapWithMetadata(context.Background(), myDriveConfig().Scope())
	if err != nil {
		t.Fatal(err)
	}
	if bundle.Bundle.History.Status != remotehistory.BootstrapComplete || bundle.Bundle.History.Cursor != "cursor-1" {
		t.Fatalf("history=%#v", bundle.Bundle.History)
	}
	if got, want := objectIDs(bundle.Bundle.History.Objects), []string{"blob", "managed", "native", "shortcut"}; !equalMetadataStrings(got, want) {
		t.Fatalf("objects=%#v want=%#v", got, want)
	}
	if len(bundle.Metadata) != 4 {
		t.Fatalf("metadata=%#v", bundle.Metadata)
	}
	byID := make(map[corpus.ProviderObjectID]gdrive.MetadataRecord, len(bundle.Metadata))
	for _, record := range bundle.Metadata {
		byID[record.ObjectID] = record
	}
	blob := byID["blob"]
	if blob.Kind != corpus.EntryRegularFile || blob.Size == nil || *blob.Size != 7 || blob.ModifiedAt == nil || !blob.ModifiedAt.Equal(t2) {
		t.Fatalf("blob=%#v", blob)
	}
	managed := byID["managed"]
	if managed.Kind != corpus.EntryOther || managed.Size != nil {
		t.Fatalf("managed=%#v", managed)
	}
	shortcut := byID["shortcut"]
	if shortcut.Kind != corpus.EntryOther || shortcut.Size != nil {
		t.Fatalf("shortcut=%#v", shortcut)
	}
	native := byID["native"]
	if native.Kind != corpus.EntryRegularFile || native.Size == nil || *native.Size != 12 {
		t.Fatalf("native=%#v", native)
	}
	if len(client.changeTokens) != 1 || client.changeTokens[0] != "fence-1" {
		t.Fatalf("change tokens=%#v", client.changeTokens)
	}
}

func equalMetadataStrings(a, b []string) bool {
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
