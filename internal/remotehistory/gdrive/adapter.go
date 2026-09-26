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
	ResolveMyDriveRoot(context.Context, Config) (string, error)
	StartPageToken(context.Context, Config) (string, error)
	ListFiles(context.Context, Config, string) (FilePage, error)
	ListChanges(context.Context, Config, string) (ChangePage, error)
}

var (
	ErrInvalidConfig             = errors.New("invalid Google Drive history config")
	ErrNonCanonicalHistoryRoot   = errors.New("non-canonical Google Drive history root")
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
	if client == nil {
		return nil, ErrInvalidConfig
	}
	if err := validateConfig(config); err != nil {
		return nil, err
	}
	return &Adapter{client: client, config: config}, nil
}

func validateConfigBase(config Config) error {
	if strings.TrimSpace(config.IdentityDomain) == "" ||
		strings.TrimSpace(string(config.StreamID)) == "" {
		return ErrInvalidConfig
	}
	switch config.Kind {
	case StreamMyDrive:
		if strings.TrimSpace(config.DriveID) != "" {
			return ErrInvalidConfig
		}
	case StreamSharedDrive:
		if strings.TrimSpace(config.DriveID) == "" {
			return ErrInvalidConfig
		}
	default:
		return ErrInvalidConfig
	}
	return nil
}

func validateConfig(config Config) error {
	if err := validateConfigBase(config); err != nil {
		return err
	}
	root := strings.TrimSpace(config.Root)
	if root == "" {
		return ErrInvalidConfig
	}
	switch config.Kind {
	case StreamMyDrive:
		if root == "root" {
			return ErrNonCanonicalHistoryRoot
		}
	case StreamSharedDrive:
		if root != strings.TrimSpace(config.DriveID) {
			return ErrInvalidConfig
		}
	default:
		return ErrInvalidConfig
	}
	return nil
}

// CanonicalizeConfig resolves provider API aliases into durable history-universe
// identity before Adapter construction. The Google Drive "root" alias is API
// syntax, while parent metadata contains the actual root file ID.
func CanonicalizeConfig(ctx context.Context, client Client, config Config) (Config, error) {
	if client == nil {
		return Config{}, ErrInvalidConfig
	}
	if err := validateConfigBase(config); err != nil {
		return Config{}, err
	}

	switch config.Kind {
	case StreamMyDrive:
		canonicalRoot, err := client.ResolveMyDriveRoot(ctx, config)
		if err != nil {
			return Config{}, err
		}
		canonicalRoot = strings.TrimSpace(canonicalRoot)
		if canonicalRoot == "" || canonicalRoot == "root" {
			return Config{}, fmt.Errorf("%w: My Drive root resolver returned %q", ErrInvalidClientResponse, canonicalRoot)
		}
		supplied := strings.TrimSpace(config.Root)
		if supplied != "" && supplied != "root" && supplied != canonicalRoot {
			return Config{}, fmt.Errorf("%w: supplied My Drive root %q != canonical %q", ErrInvalidConfig, supplied, canonicalRoot)
		}
		config.Root = canonicalRoot

	case StreamSharedDrive:
		driveID := strings.TrimSpace(config.DriveID)
		supplied := strings.TrimSpace(config.Root)
		if supplied != "" && supplied != driveID {
			return Config{}, fmt.Errorf("%w: shared-drive root %q != drive ID %q", ErrInvalidConfig, supplied, driveID)
		}
		config.Root = driveID

	default:
		return Config{}, ErrInvalidConfig
	}

	if err := validateConfig(config); err != nil {
		return Config{}, err
	}
	return config, nil
}

func (a *Adapter) Bootstrap(ctx context.Context, scope remotehistory.Scope) (remotehistory.BootstrapResult, error) {
	bundle, err := a.BootstrapWithTopology(ctx, scope)
	return bundle.History, err
}

func (a *Adapter) ReadChanges(
	ctx context.Context,
	scope remotehistory.Scope,
	committed remotehistory.HistoryCursor,
	continuation remotehistory.ContinuationToken,
) (remotehistory.ChangePage, error) {
	bundle, err := a.ReadChangesWithTopology(ctx, scope, committed, continuation)
	return bundle.History, err
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
