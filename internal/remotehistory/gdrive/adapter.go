package gdrive

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"sort"
	"strings"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
)

const ProviderID corpus.ProviderID = "google-drive"

type StreamKind string

const (
	StreamMyDrive     StreamKind = "MY_DRIVE"
	StreamSharedDrive StreamKind = "SHARED_DRIVE"
)

type Config struct {
	IdentityDomain string
	StreamID       remotehistory.HistoryStreamID
	Root           string
	Kind           StreamKind
	DriveID        string
}

func (c Config) Scope() remotehistory.Scope {
	return remotehistory.Scope{
		ProviderID:     ProviderID,
		IdentityDomain: c.IdentityDomain,
		StreamID:       c.StreamID,
		Root:           c.Root,
	}
}

type FileRecord struct {
	ID               string
	Parents          []string
	DriveID          string
	Trashed          bool
	ShortcutTargetID string
}

type FilePage struct {
	Files         []FileRecord
	NextPageToken string
}

type ChangeRecord struct {
	ChangeType string
	FileID     string
	Removed    bool
	File       *FileRecord
}

type ChangePage struct {
	Changes           []ChangeRecord
	NextPageToken     string
	NewStartPageToken string
}

type Client interface {
	StartPageToken(context.Context, Config) (string, error)
	ListFiles(context.Context, Config, string) (FilePage, error)
	ListChanges(context.Context, Config, string) (ChangePage, error)
}

var (
	ErrInvalidConfig             = errors.New("invalid Google Drive history config")
	ErrInvalidClientResponse     = errors.New("invalid Google Drive history client response")
	ErrClientHistoryGap          = errors.New("Google Drive history gap")
	ErrClientInvalidCursor       = errors.New("Google Drive invalid history cursor")
	ErrClientScopeMismatch       = errors.New("Google Drive history scope mismatch")
	ErrClientInsufficientHistory = errors.New("Google Drive insufficient history guarantee")
)

type Adapter struct {
	client Client
	config Config
}

func New(client Client, config Config) (*Adapter, error) {
	if client == nil || validateConfig(config) != nil {
		return nil, ErrInvalidConfig
	}
	return &Adapter{client: client, config: config}, nil
}

func validateConfig(config Config) error {
	if strings.TrimSpace(config.IdentityDomain) == "" ||
		strings.TrimSpace(string(config.StreamID)) == "" ||
		strings.TrimSpace(config.Root) == "" {
		return ErrInvalidConfig
	}
	switch config.Kind {
	case StreamMyDrive:
		if strings.TrimSpace(config.DriveID) != "" {
			return ErrInvalidConfig
		}
	case StreamSharedDrive:
		if strings.TrimSpace(config.DriveID) == "" || config.Root != config.DriveID {
			return ErrInvalidConfig
		}
	default:
		return ErrInvalidConfig
	}
	return nil
}

func (a *Adapter) Bootstrap(ctx context.Context, scope remotehistory.Scope) (remotehistory.BootstrapResult, error) {
	if !a.matches(scope) {
		return bootstrapFailure(scope.StreamID, remotehistory.BootstrapScopeMismatch), nil
	}

	fence, err := a.client.StartPageToken(ctx, a.config)
	if err != nil {
		return a.bootstrapClientFailure(scope.StreamID, err)
	}
	if strings.TrimSpace(fence) == "" {
		return remotehistory.BootstrapResult{}, fmt.Errorf("%w: empty start page token", ErrInvalidClientResponse)
	}

	files, err := a.enumerateFiles(ctx)
	if err != nil {
		return a.bootstrapClientFailure(scope.StreamID, err)
	}
	objects := a.initialObjects(files)

	cursor, err := a.catchUp(ctx, fence, objects)
	if err != nil {
		return a.bootstrapClientFailure(scope.StreamID, err)
	}

	result := remotehistory.BootstrapResult{
		StreamID: scope.StreamID,
		Status:   remotehistory.BootstrapComplete,
		Objects:  sortedObjects(objects),
		Cursor:   remotehistory.HistoryCursor(cursor),
		Coverage: corpus.ProviderHistoryContinuous,
	}
	if err := remotehistory.ValidateBootstrap(scope, result); err != nil {
		return remotehistory.BootstrapResult{}, err
	}
	return result, nil
}

func (a *Adapter) ReadChanges(ctx context.Context, scope remotehistory.Scope, committed remotehistory.HistoryCursor, continuation remotehistory.ContinuationToken) (remotehistory.ChangePage, error) {
	if !a.matches(scope) {
		return remotehistory.ChangePage{StreamID: scope.StreamID, Status: remotehistory.PageScopeMismatch}, nil
	}
	if committed == "" {
		return remotehistory.ChangePage{}, remotehistory.ErrInvalidScope
	}

	token := string(committed)
	if continuation != "" {
		token = string(continuation)
	}
	page, err := a.client.ListChanges(ctx, a.config, token)
	if err != nil {
		if status, ok := pageStatusForClientError(err); ok {
			return remotehistory.ChangePage{StreamID: scope.StreamID, Status: status}, nil
		}
		return remotehistory.ChangePage{}, err
	}
	changes, err := a.convertChanges(page.Changes)
	if err != nil {
		return remotehistory.ChangePage{}, err
	}

	hasNext := strings.TrimSpace(page.NextPageToken) != ""
	hasTerminal := strings.TrimSpace(page.NewStartPageToken) != ""
	if hasNext == hasTerminal {
		return remotehistory.ChangePage{}, fmt.Errorf("%w: expected exactly one next or terminal token", ErrInvalidClientResponse)
	}
	if hasNext {
		return remotehistory.ChangePage{
			StreamID:     scope.StreamID,
			Status:       remotehistory.PageMore,
			Changes:      changes,
			Continuation: remotehistory.ContinuationToken(page.NextPageToken),
		}, nil
	}
	return remotehistory.ChangePage{
		StreamID:   scope.StreamID,
		Status:     remotehistory.PageTerminal,
		Changes:    changes,
		NextCursor: remotehistory.HistoryCursor(page.NewStartPageToken),
	}, nil
}

func (a *Adapter) matches(scope remotehistory.Scope) bool {
	return scope == a.config.Scope()
}

func (a *Adapter) enumerateFiles(ctx context.Context) ([]FileRecord, error) {
	var files []FileRecord
	seen := map[string]struct{}{"": {}}
	pageToken := ""
	for {
		page, err := a.client.ListFiles(ctx, a.config, pageToken)
		if err != nil {
			return nil, err
		}
		files = append(files, page.Files...)
		next := strings.TrimSpace(page.NextPageToken)
		if next == "" {
			return files, nil
		}
		if _, duplicate := seen[next]; duplicate {
			return nil, fmt.Errorf("%w: repeated file page token", ErrInvalidClientResponse)
		}
		seen[next] = struct{}{}
		pageToken = next
	}
}

func (a *Adapter) initialObjects(files []FileRecord) map[corpus.ProviderObjectID]remotehistory.RemoteObjectState {
	inScope := make(map[string]bool)
	if a.config.Kind == StreamSharedDrive {
		for _, file := range files {
			if !file.Trashed && file.DriveID == a.config.DriveID && file.ID != "" && file.ID != a.config.Root {
				inScope[file.ID] = true
			}
		}
	} else {
		reachable := map[string]bool{a.config.Root: true}
		changed := true
		for changed {
			changed = false
			for _, file := range files {
				if file.ID == "" || file.Trashed || file.DriveID != "" || reachable[file.ID] {
					continue
				}
				for _, parent := range file.Parents {
					if reachable[parent] {
						reachable[file.ID] = true
						changed = true
						break
					}
				}
			}
		}
		for id := range reachable {
			if id != a.config.Root {
				inScope[id] = true
			}
		}
	}

	objects := make(map[corpus.ProviderObjectID]remotehistory.RemoteObjectState, len(inScope))
	for _, file := range files {
		if inScope[file.ID] {
			state := a.objectState(file.ID)
			objects[state.ObjectID] = state
		}
	}
	return objects
}

func (a *Adapter) catchUp(ctx context.Context, fence string, objects map[corpus.ProviderObjectID]remotehistory.RemoteObjectState) (string, error) {
	seen := map[string]struct{}{fence: {}}
	token := fence
	for {
		page, err := a.client.ListChanges(ctx, a.config, token)
		if err != nil {
			return "", err
		}
		changes, err := a.convertChanges(page.Changes)
		if err != nil {
			return "", err
		}
		for _, change := range changes {
			switch change.Kind {
			case remotehistory.ChangeUpsert:
				objects[change.ObjectID] = *change.State
			case remotehistory.ChangeRemoved:
				delete(objects, change.ObjectID)
			}
		}

		next := strings.TrimSpace(page.NextPageToken)
		terminal := strings.TrimSpace(page.NewStartPageToken)
		if next != "" && terminal != "" || next == "" && terminal == "" {
			return "", fmt.Errorf("%w: expected exactly one next or terminal token", ErrInvalidClientResponse)
		}
		if terminal != "" {
			return terminal, nil
		}
		if _, duplicate := seen[next]; duplicate {
			return "", fmt.Errorf("%w: repeated change page token", ErrInvalidClientResponse)
		}
		seen[next] = struct{}{}
		token = next
	}
}

func (a *Adapter) convertChanges(records []ChangeRecord) ([]remotehistory.RemoteChange, error) {
	changes := make([]remotehistory.RemoteChange, 0, len(records))
	for _, record := range records {
		if record.ChangeType != "" && record.ChangeType != "file" {
			continue
		}
		id := strings.TrimSpace(record.FileID)
		if id == "" && record.File != nil {
			id = strings.TrimSpace(record.File.ID)
		}
		if id == "" {
			return nil, fmt.Errorf("%w: file change without file ID", ErrInvalidClientResponse)
		}
		objectID := corpus.ProviderObjectID(id)
		if record.Removed {
			changes = append(changes, remotehistory.RemoteChange{Kind: remotehistory.ChangeRemoved, ObjectID: objectID})
			continue
		}
		if record.File == nil || record.File.ID != id {
			return nil, fmt.Errorf("%w: current file state missing or ID mismatch", ErrInvalidClientResponse)
		}
		if record.File.Trashed || !a.fileBelongsToStream(*record.File) {
			changes = append(changes, remotehistory.RemoteChange{Kind: remotehistory.ChangeRemoved, ObjectID: objectID})
			continue
		}
		state := a.objectState(id)
		changes = append(changes, remotehistory.RemoteChange{Kind: remotehistory.ChangeUpsert, ObjectID: objectID, State: &state})
	}
	return changes, nil
}

func (a *Adapter) fileBelongsToStream(file FileRecord) bool {
	if a.config.Kind == StreamSharedDrive {
		return file.DriveID == a.config.DriveID
	}
	// The concrete MY_DRIVE client must issue changes.list with
	// restrictToMyDrive=true. A non-empty DriveID is therefore outside this stream.
	return file.DriveID == ""
}

func (a *Adapter) objectState(id string) remotehistory.RemoteObjectState {
	objectID := corpus.ProviderObjectID(id)
	return remotehistory.RemoteObjectState{
		ObjectID: objectID,
		Locators: []corpus.Locator{{
			ProviderID: ProviderID,
			Root:       a.config.Root,
			Path:       "file-id/" + url.PathEscape(id),
		}},
	}
}

func (a *Adapter) bootstrapClientFailure(streamID remotehistory.HistoryStreamID, err error) (remotehistory.BootstrapResult, error) {
	switch {
	case errors.Is(err, ErrClientHistoryGap), errors.Is(err, ErrClientInvalidCursor):
		return bootstrapFailure(streamID, remotehistory.BootstrapGap), nil
	case errors.Is(err, ErrClientScopeMismatch):
		return bootstrapFailure(streamID, remotehistory.BootstrapScopeMismatch), nil
	case errors.Is(err, ErrClientInsufficientHistory):
		return bootstrapFailure(streamID, remotehistory.BootstrapInsufficientHistory), nil
	default:
		return remotehistory.BootstrapResult{}, err
	}
}

func bootstrapFailure(streamID remotehistory.HistoryStreamID, status remotehistory.BootstrapStatus) remotehistory.BootstrapResult {
	return remotehistory.BootstrapResult{
		StreamID: streamID,
		Status:   status,
		Coverage: corpus.ProviderHistoryUnknown,
	}
}

func pageStatusForClientError(err error) (remotehistory.PageStatus, bool) {
	switch {
	case errors.Is(err, ErrClientHistoryGap):
		return remotehistory.PageGap, true
	case errors.Is(err, ErrClientInvalidCursor):
		return remotehistory.PageInvalidCursor, true
	case errors.Is(err, ErrClientScopeMismatch):
		return remotehistory.PageScopeMismatch, true
	case errors.Is(err, ErrClientInsufficientHistory):
		return remotehistory.PageInsufficientHistory, true
	default:
		return "", false
	}
}

func sortedObjects(objects map[corpus.ProviderObjectID]remotehistory.RemoteObjectState) []remotehistory.RemoteObjectState {
	ids := make([]string, 0, len(objects))
	for id := range objects {
		ids = append(ids, string(id))
	}
	sort.Strings(ids)
	out := make([]remotehistory.RemoteObjectState, 0, len(ids))
	for _, id := range ids {
		out = append(out, objects[corpus.ProviderObjectID(id)])
	}
	return out
}
