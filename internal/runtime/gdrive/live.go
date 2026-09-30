package gdrive

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/controlstorage"
	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/ingest"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	providergdrive "github.com/efremov-aleksei-96/keelaryn/internal/remotehistory/gdrive"
	sqlitestate "github.com/efremov-aleksei-96/keelaryn/internal/state/sqlite"
	"golang.org/x/oauth2"
	driveapi "google.golang.org/api/drive/v3"
	"google.golang.org/api/option"
)

const (
	RequiredScope     = driveapi.DriveMetadataReadonlyScope
	tokenInfoEndpoint = "https://oauth2.googleapis.com/tokeninfo"
)

var (
	ErrInvalidOptions     = errors.New("invalid Google Drive live runtime options")
	ErrAccessTokenMissing = errors.New("Google Drive access token is missing")
	ErrTokenScopeRejected = errors.New("Google Drive access token scope is not metadata-read-only")
)

type Options struct {
	ControlDir  string
	AccessToken string
	ObservedAt  time.Time
}

type Result struct {
	ProviderID          corpus.ProviderID                        `json:"provider_id"`
	IdentityDomain      string                                   `json:"identity_domain"`
	StreamID            remotehistory.HistoryStreamID            `json:"stream_id"`
	CanonicalRootID     corpus.ProviderObjectID                  `json:"canonical_root_id"`
	RequiredScope       string                                   `json:"required_scope"`
	CoordinatorStatus   remotehistory.CoordinatorStatus          `json:"coordinator_status"`
	GenerationID        remotehistory.HistoryGenerationID        `json:"generation_id"`
	PublicationSequence remotehistory.HistoryPublicationSequence `json:"publication_sequence"`
	ScanID              corpus.ScanSessionID                     `json:"scan_id"`
	ScanReplayed        bool                                     `json:"scan_replayed"`
	MetadataCount       int                                      `json:"metadata_count"`
}

type tokenAuthorization struct {
	Scopes []string
}

type dependencies struct {
	inspectToken    func(context.Context, string) (tokenAuthorization, error)
	newDriveService func(context.Context, string) (*driveapi.Service, error)
}

func BootstrapReadOnly(ctx context.Context, options Options) (Result, error) {
	return bootstrapReadOnly(ctx, options, defaultDependencies())
}

func bootstrapReadOnly(ctx context.Context, options Options, deps dependencies) (Result, error) {
	controlDir := strings.TrimSpace(options.ControlDir)
	token := strings.TrimSpace(options.AccessToken)
	if controlDir == "" || options.ObservedAt.IsZero() || deps.inspectToken == nil || deps.newDriveService == nil {
		return Result{}, ErrInvalidOptions
	}
	if token == "" {
		return Result{}, ErrAccessTokenMissing
	}

	authorization, err := deps.inspectToken(ctx, token)
	if err != nil {
		return Result{}, fmt.Errorf("inspect Google Drive access token: %w", err)
	}
	if err := validateTokenAuthorization(authorization); err != nil {
		return Result{}, err
	}

	service, err := deps.newDriveService(ctx, token)
	if err != nil {
		return Result{}, fmt.Errorf("construct Google Drive service: %w", err)
	}

	about, err := service.About.Get().Context(ctx).Fields("user(permissionId)").Do()
	if err != nil {
		return Result{}, fmt.Errorf("resolve authenticated Google Drive user: %w", err)
	}
	if about == nil || about.User == nil || strings.TrimSpace(about.User.PermissionId) == "" {
		return Result{}, fmt.Errorf("%w: authenticated Drive user has no permission ID", providergdrive.ErrInvalidClientResponse)
	}
	identityDomain := "google-drive:user:" + strings.TrimSpace(about.User.PermissionId)

	client, err := providergdrive.NewGoogleClient(service)
	if err != nil {
		return Result{}, err
	}
	config := providergdrive.Config{
		IdentityDomain: identityDomain,
		StreamID:       remotehistory.HistoryStreamID(identityDomain + ":my-drive:changes"),
		Root:           "root",
		Kind:           providergdrive.StreamMyDrive,
	}
	config, err = providergdrive.CanonicalizeConfig(ctx, client, config)
	if err != nil {
		return Result{}, fmt.Errorf("canonicalize Google Drive scope: %w", err)
	}
	adapter, err := providergdrive.New(client, config)
	if err != nil {
		return Result{}, err
	}
	fingerprint, err := providergdrive.ScopePolicyFingerprint(config)
	if err != nil {
		return Result{}, err
	}

	// Provider/auth validation above is read-only. Creating the protected
	// control directory is the first durable mutation boundary.
	layout, err := controlstorage.Prepare(controlDir)
	if err != nil {
		return Result{}, err
	}
	store, err := sqlitestate.Open(ctx, layout.StateDB)
	if err != nil {
		verifyErr := controlstorage.Verify(layout.Dir)
		if verifyErr != nil {
			return Result{}, errors.Join(err, verifyErr)
		}
		return Result{}, err
	}

	live, operationErr := ingest.BootstrapGoogleDriveLiveMetadata(
		ctx,
		store,
		adapter,
		config.Scope(),
		fingerprint,
		corpus.ProviderObjectID(config.Root),
		options.ObservedAt.UTC(),
	)
	closeErr := store.Close()
	verifyErr := controlstorage.Verify(layout.Dir)
	if operationErr != nil || closeErr != nil || verifyErr != nil {
		return Result{}, errors.Join(operationErr, closeErr, verifyErr)
	}

	return Result{
		ProviderID:          providergdrive.ProviderID,
		IdentityDomain:      identityDomain,
		StreamID:            config.StreamID,
		CanonicalRootID:     corpus.ProviderObjectID(config.Root),
		RequiredScope:       RequiredScope,
		CoordinatorStatus:   live.Coordinator.Status,
		GenerationID:        live.Generation.ID,
		PublicationSequence: live.Generation.CurrentSequence,
		ScanID:              live.Scan.ID,
		ScanReplayed:        live.ScanReplayed,
		MetadataCount:       live.MetadataCount,
	}, nil
}

func defaultDependencies() dependencies {
	return dependencies{
		inspectToken: func(ctx context.Context, token string) (tokenAuthorization, error) {
			return inspectAccessToken(ctx, http.DefaultClient, tokenInfoEndpoint, token)
		},
		newDriveService: func(ctx context.Context, token string) (*driveapi.Service, error) {
			source := oauth2.StaticTokenSource(&oauth2.Token{
				AccessToken: token,
				TokenType:   "Bearer",
			})
			return driveapi.NewService(ctx, option.WithTokenSource(source))
		},
	}
}

func inspectAccessToken(
	ctx context.Context,
	client *http.Client,
	endpoint string,
	token string,
) (tokenAuthorization, error) {
	if client == nil || strings.TrimSpace(endpoint) == "" || strings.TrimSpace(token) == "" {
		return tokenAuthorization{}, ErrInvalidOptions
	}
	form := url.Values{"access_token": {token}}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, strings.NewReader(form.Encode()))
	if err != nil {
		return tokenAuthorization{}, err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	resp, err := client.Do(req)
	if err != nil {
		return tokenAuthorization{}, err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return tokenAuthorization{}, fmt.Errorf("Google tokeninfo status %s", resp.Status)
	}
	var payload struct {
		Scope string `json:"scope"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&payload); err != nil {
		return tokenAuthorization{}, err
	}
	return tokenAuthorization{Scopes: strings.Fields(payload.Scope)}, nil
}

func validateTokenAuthorization(authorization tokenAuthorization) error {
	if len(authorization.Scopes) != 1 || strings.TrimSpace(authorization.Scopes[0]) != RequiredScope {
		return fmt.Errorf("%w: granted scopes=%v", ErrTokenScopeRejected, authorization.Scopes)
	}
	return nil
}
