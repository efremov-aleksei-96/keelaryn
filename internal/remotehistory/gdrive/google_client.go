package gdrive

import (
	"context"
	"errors"
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
		Fields("nextPageToken,files(id,parents,driveId,trashed,shortcutDetails(targetId))")

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
		Fields("nextPageToken,newStartPageToken,changes(changeType,fileId,removed,file(id,parents,driveId,trashed,shortcutDetails(targetId)))")

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
		ID:      file.Id,
		Parents: append([]string(nil), file.Parents...),
		DriveID: file.DriveId,
		Trashed: file.Trashed,
	}
	if file.ShortcutDetails != nil {
		record.ShortcutTargetID = file.ShortcutDetails.TargetId
	}
	return record
}
