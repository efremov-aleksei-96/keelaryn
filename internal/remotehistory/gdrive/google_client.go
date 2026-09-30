package gdrive

import (
	"context"
	"errors"
	"fmt"
	"strings"

	drive "google.golang.org/api/drive/v3"
)

var ErrNilDriveService = errors.New("nil Google Drive service")

// GoogleClient is the thin official google.golang.org/api/drive/v3 binding.
// Authentication/service construction stays outside this package so the
// RemoteHistory adapter remains testable without OAuth or live corpus access.
type GoogleClient struct {
	service *drive.Service
}

func NewGoogleClient(service *drive.Service) (*GoogleClient, error) {
	if service == nil {
		return nil, ErrNilDriveService
	}
	return &GoogleClient{service: service}, nil
}

func (c *GoogleClient) ResolveMyDriveRoot(ctx context.Context, config Config) (string, error) {
	if config.Kind != StreamMyDrive {
		return "", ErrInvalidConfig
	}
	result, err := c.service.Files.Get("root").
		Context(ctx).
		Fields("id").
		Do()
	if err != nil {
		return "", err
	}
	if result == nil {
		return "", fmt.Errorf("%w: nil My Drive root response", ErrInvalidClientResponse)
	}
	rootID := strings.TrimSpace(result.Id)
	if rootID == "" || rootID == "root" {
		return "", fmt.Errorf("%w: invalid canonical My Drive root ID %q", ErrInvalidClientResponse, rootID)
	}
	return rootID, nil
}

func (c *GoogleClient) StartPageToken(ctx context.Context, config Config) (string, error) {
	call := c.service.Changes.GetStartPageToken().
		Context(ctx).
		Fields("startPageToken")
	if config.Kind == StreamSharedDrive {
		call = call.DriveId(config.DriveID).SupportsAllDrives(true)
	}
	result, err := call.Do()
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(result.StartPageToken), nil
}

func (c *GoogleClient) ListFiles(ctx context.Context, config Config, pageToken string) (FilePage, error) {
	call := c.service.Files.List().
		Context(ctx).
		Spaces("drive").
		Fields("nextPageToken,files(id,parents,driveId,trashed,shortcutDetails(targetId),mimeType,size,modifiedTime)")

	switch config.Kind {
	case StreamSharedDrive:
		call = call.
			Corpora("drive").
			DriveId(config.DriveID).
			IncludeItemsFromAllDrives(true).
			SupportsAllDrives(true)
	case StreamMyDrive:
		call = call.
			Corpora("user").
			IncludeItemsFromAllDrives(false)
	}
	if pageToken != "" {
		call = call.PageToken(pageToken)
	}

	result, err := call.Do()
	if err != nil {
		return FilePage{}, err
	}
	page := FilePage{NextPageToken: result.NextPageToken}
	page.Files = make([]FileRecord, 0, len(result.Files))
	for _, file := range result.Files {
		if file == nil {
			continue
		}
		page.Files = append(page.Files, fileRecordFromGoogle(file))
	}
	return page, nil
}

func (c *GoogleClient) ListChanges(ctx context.Context, config Config, pageToken string) (ChangePage, error) {
	call := c.service.Changes.List(pageToken).
		Context(ctx).
		IncludeRemoved(true).
		Spaces("drive").
		Fields("nextPageToken,newStartPageToken,changes(changeType,fileId,removed,file(id,parents,driveId,trashed,shortcutDetails(targetId),mimeType,size,modifiedTime))")

	switch config.Kind {
	case StreamSharedDrive:
		call = call.
			DriveId(config.DriveID).
			IncludeItemsFromAllDrives(true).
			SupportsAllDrives(true)
	case StreamMyDrive:
		call = call.
			RestrictToMyDrive(true).
			IncludeItemsFromAllDrives(false)
	}

	result, err := call.Do()
	if err != nil {
		return ChangePage{}, err
	}
	page := ChangePage{
		NextPageToken:     result.NextPageToken,
		NewStartPageToken: result.NewStartPageToken,
	}
	page.Changes = make([]ChangeRecord, 0, len(result.Changes))
	for _, change := range result.Changes {
		if change == nil {
			continue
		}
		record := ChangeRecord{
			ChangeType: change.ChangeType,
			FileID:     change.FileId,
			Removed:    change.Removed,
		}
		if change.File != nil {
			file := fileRecordFromGoogle(change.File)
			record.File = &file
		}
		page.Changes = append(page.Changes, record)
	}
	return page, nil
}

func fileRecordFromGoogle(file *drive.File) FileRecord {
	record := FileRecord{
		ID:           file.Id,
		Parents:      append([]string(nil), file.Parents...),
		DriveID:      file.DriveId,
		Trashed:      file.Trashed,
		MimeType:     file.MimeType,
		Size:         file.Size,
		SizeKnown:    googleFileSizeKnown(file),
		ModifiedTime: file.ModifiedTime,
	}
	if file.ShortcutDetails != nil {
		record.ShortcutTargetID = file.ShortcutDetails.TargetId
	}
	return record
}

func googleFileSizeKnown(file *drive.File) bool {
	if file == nil {
		return false
	}
	mime := strings.TrimSpace(file.MimeType)
	switch mime {
	case googleFolderMIMEType, googleShortcutMIMEType, googleDriveSDKMIMEType:
		return false
	}
	if file.Size != 0 {
		return true
	}
	if mime == "" {
		return false
	}
	// The generated Drive client represents size as an int64, so a missing
	// provider field and an explicit zero decode to the same Go value. A blob
	// MIME type is sufficient provider evidence that size is defined; for
	// Google-native types with a zero value we remain conservative and leave
	// availability unknown rather than fabricate a fact.
	return !strings.HasPrefix(mime, "application/vnd.google-apps.")
}
