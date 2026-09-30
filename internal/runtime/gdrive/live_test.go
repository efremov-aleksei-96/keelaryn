package gdrive

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	providergdrive "github.com/efremov-aleksei-96/keelaryn/internal/remotehistory/gdrive"
	driveapi "google.golang.org/api/drive/v3"
)

func TestInspectAccessTokenKeepsSecretOutOfURL(t *testing.T) {
	const token = "query-log-secret"
	var gotMethod, gotQuery, gotBody string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotMethod = r.Method
		gotQuery = r.URL.RawQuery
		body, err := io.ReadAll(r.Body)
		if err != nil {
			t.Fatal(err)
		}
		gotBody = string(body)
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"scope":"openid https://www.googleapis.com/auth/drive.metadata.readonly"}`)
	}))
	defer server.Close()

	authorization, err := inspectAccessToken(context.Background(), server.Client(), server.URL, token)
	if err != nil {
		t.Fatal(err)
	}
	if gotMethod != http.MethodPost {
		t.Fatalf("method=%s", gotMethod)
	}
	if gotQuery != "" || strings.Contains(server.URL+gotQuery, token) {
		t.Fatalf("access token entered request URL: query=%q", gotQuery)
	}
	values, err := url.ParseQuery(gotBody)
	if err != nil {
		t.Fatal(err)
	}
	if values.Get("access_token") != token {
		t.Fatalf("form=%q", gotBody)
	}
	if len(authorization.Scopes) != 2 || authorization.Scopes[1] != RequiredScope {
		t.Fatalf("authorization=%#v", authorization)
	}
}

func TestBootstrapReadOnlyUsesMetadataOnlyTokenAndProtectedState(t *testing.T) {
	const token = "keelaryn-secret-token-never-persist"
	base := time.Date(2026, 9, 30, 16, 0, 0, 0, time.UTC)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch {
		case r.URL.Path == "/about":
			_, _ = io.WriteString(w, `{"user":{"permissionId":"permission-user-123"}}`)
		case r.URL.Path == "/files/root":
			_, _ = io.WriteString(w, `{"id":"root-id"}`)
		case r.URL.Path == "/changes/startPageToken":
			_, _ = io.WriteString(w, `{"startPageToken":"fence-1"}`)
		case r.URL.Path == "/files":
			_, _ = io.WriteString(w, `{"files":[{"id":"blob","parents":["root-id"],"mimeType":"application/octet-stream","size":"3","modifiedTime":"2026-09-30T16:00:00Z"}]}`)
		case r.URL.Path == "/changes":
			_, _ = io.WriteString(w, `{"newStartPageToken":"cursor-1","changes":[]}`)
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()

	control := filepath.Join(t.TempDir(), "control")
	deps := dependencies{
		inspectToken: func(context.Context, string) (tokenAuthorization, error) {
			return tokenAuthorization{Scopes: []string{RequiredScope}}, nil
		},
		newDriveService: func(context.Context, string) (*driveapi.Service, error) {
			service, err := driveapi.New(server.Client())
			if err != nil {
				return nil, err
			}
			service.BasePath = server.URL + "/"
			return service, nil
		},
	}

	first, err := bootstrapReadOnly(context.Background(), Options{
		ControlDir: control, AccessToken: token, ObservedAt: base,
	}, deps)
	if err != nil {
		t.Fatal(err)
	}
	if first.ProviderID != "google-drive" ||
		first.IdentityDomain != "google-drive:user:permission-user-123" ||
		first.CanonicalRootID != "root-id" ||
		first.RequiredScope != RequiredScope ||
		first.PublicationSequence != 1 ||
		first.ScanID == "" ||
		first.ScanReplayed ||
		first.MetadataCount != 1 {
		t.Fatalf("first=%#v", first)
	}

	replay, err := bootstrapReadOnly(context.Background(), Options{
		ControlDir: control, AccessToken: token, ObservedAt: base.Add(time.Minute),
	}, deps)
	if err != nil {
		t.Fatal(err)
	}
	if !replay.ScanReplayed || replay.ScanID != first.ScanID || replay.GenerationID != first.GenerationID {
		t.Fatalf("replay=%#v first=%#v", replay, first)
	}

	entries, err := os.ReadDir(control)
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) == 0 {
		t.Fatal("protected control state was not created")
	}
	for _, entry := range entries {
		data, readErr := os.ReadFile(filepath.Join(control, entry.Name()))
		if readErr != nil {
			t.Fatal(readErr)
		}
		if strings.Contains(string(data), token) {
			t.Fatalf("access token persisted in control file %s", entry.Name())
		}
	}
}

func TestBootstrapReadOnlyRejectsBroaderDriveScopeBeforeMutation(t *testing.T) {
	control := filepath.Join(t.TempDir(), "control")
	called := false
	_, err := bootstrapReadOnly(context.Background(), Options{
		ControlDir:  control,
		AccessToken: "secret",
		ObservedAt:  time.Date(2026, 9, 30, 16, 0, 0, 0, time.UTC),
	}, dependencies{
		inspectToken: func(context.Context, string) (tokenAuthorization, error) {
			return tokenAuthorization{Scopes: []string{RequiredScope, driveapi.DriveReadonlyScope}}, nil
		},
		newDriveService: func(context.Context, string) (*driveapi.Service, error) {
			called = true
			return nil, errors.New("must not be called")
		},
	})
	if !errors.Is(err, ErrTokenScopeRejected) {
		t.Fatalf("error=%v want ErrTokenScopeRejected", err)
	}
	if called {
		t.Fatal("Drive service constructed after broader scope rejection")
	}
	if _, statErr := os.Stat(control); !errors.Is(statErr, os.ErrNotExist) {
		t.Fatalf("control state mutated before token scope validation: %v", statErr)
	}
}

func TestBootstrapReadOnlyRejectsMissingDrivePermissionIdentityBeforeMutation(t *testing.T) {
	control := filepath.Join(t.TempDir(), "control")
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if r.URL.Path == "/about" {
			_, _ = io.WriteString(w, `{"user":{}}`)
			return
		}
		http.NotFound(w, r)
	}))
	defer server.Close()

	_, err := bootstrapReadOnly(context.Background(), Options{
		ControlDir:  control,
		AccessToken: "secret",
		ObservedAt:  time.Date(2026, 9, 30, 16, 0, 0, 0, time.UTC),
	}, dependencies{
		inspectToken: func(context.Context, string) (tokenAuthorization, error) {
			return tokenAuthorization{Scopes: []string{RequiredScope}}, nil
		},
		newDriveService: func(context.Context, string) (*driveapi.Service, error) {
			service, serviceErr := driveapi.New(server.Client())
			if serviceErr != nil {
				return nil, serviceErr
			}
			service.BasePath = server.URL + "/"
			return service, nil
		},
	})
	if !errors.Is(err, providergdrive.ErrInvalidClientResponse) {
		t.Fatalf("error=%v want ErrInvalidClientResponse", err)
	}
	if _, statErr := os.Stat(control); !errors.Is(statErr, os.ErrNotExist) {
		t.Fatalf("control state mutated before provider identity validation: %v", statErr)
	}
}

func TestValidateTokenAuthorizationRejectsAuxiliaryScopes(t *testing.T) {
	err := validateTokenAuthorization(tokenAuthorization{
		Scopes: []string{RequiredScope, "openid"},
	})
	if !errors.Is(err, ErrTokenScopeRejected) {
		t.Fatalf("error=%v want ErrTokenScopeRejected", err)
	}
}
