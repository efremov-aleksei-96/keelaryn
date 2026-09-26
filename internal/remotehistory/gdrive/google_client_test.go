package gdrive_test

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"net/url"
	"testing"

	drive "google.golang.org/api/drive/v3"

	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory/gdrive"
)

func TestGoogleClientSharedDriveBinding(t *testing.T) {
	var requests []capturedRequest
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests = append(requests, capturedRequest{path: r.URL.Path, query: r.URL.Query()})
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/changes/startPageToken":
			_, _ = w.Write([]byte(`{"startPageToken":"cursor-fence"}`))
		case "/files":
			_, _ = w.Write([]byte(`{"nextPageToken":"files-2","files":[{"id":"shortcut","parents":["drive-1"],"driveId":"drive-1","shortcutDetails":{"targetId":"target"}}]}`))
		case "/changes":
			_, _ = w.Write([]byte(`{"newStartPageToken":"cursor-2","changes":[{"changeType":"file","fileId":"shortcut","removed":false,"file":{"id":"shortcut","parents":["drive-1"],"driveId":"drive-1","shortcutDetails":{"targetId":"target"}}}]}`))
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()

	service := mustTestService(t, server)
	client, err := gdrive.NewGoogleClient(service)
	if err != nil {
		t.Fatal(err)
	}
	config := gdrive.Config{
		IdentityDomain: "google-drive:shared:drive-1",
		StreamID:       "google-drive:shared:drive-1:changes",
		Root:           "drive-1",
		Kind:           gdrive.StreamSharedDrive,
		DriveID:        "drive-1",
	}

	token, err := client.StartPageToken(context.Background(), config)
	if err != nil || token != "cursor-fence" {
		t.Fatalf("token=%q err=%v", token, err)
	}
	files, err := client.ListFiles(context.Background(), config, "")
	if err != nil {
		t.Fatal(err)
	}
	if len(files.Files) != 1 || files.Files[0].ID != "shortcut" || files.Files[0].ShortcutTargetID != "target" || files.NextPageToken != "files-2" {
		t.Fatalf("files=%#v", files)
	}
	changes, err := client.ListChanges(context.Background(), config, "cursor-fence")
	if err != nil {
		t.Fatal(err)
	}
	if len(changes.Changes) != 1 || changes.Changes[0].File == nil || changes.Changes[0].File.ID != "shortcut" || changes.NewStartPageToken != "cursor-2" {
		t.Fatalf("changes=%#v", changes)
	}

	if len(requests) != 3 {
		t.Fatalf("requests=%#v", requests)
	}
	assertQuery(t, requests[0].query, "driveId", "drive-1")
	assertQuery(t, requests[0].query, "supportsAllDrives", "true")
	assertQuery(t, requests[1].query, "corpora", "drive")
	assertQuery(t, requests[1].query, "driveId", "drive-1")
	assertQuery(t, requests[1].query, "includeItemsFromAllDrives", "true")
	assertQuery(t, requests[1].query, "supportsAllDrives", "true")
	assertQuery(t, requests[1].query, "spaces", "drive")
	assertQuery(t, requests[2].query, "driveId", "drive-1")
	assertQuery(t, requests[2].query, "includeItemsFromAllDrives", "true")
	assertQuery(t, requests[2].query, "supportsAllDrives", "true")
	assertQuery(t, requests[2].query, "includeRemoved", "true")
}

func TestGoogleClientMyDriveBinding(t *testing.T) {
	var queries []url.Values
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		queries = append(queries, r.URL.Query())
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/files":
			_ = json.NewEncoder(w).Encode(map[string]any{"files": []any{}})
		case "/changes":
			_ = json.NewEncoder(w).Encode(map[string]any{"newStartPageToken": "cursor-2", "changes": []any{}})
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()

	client, err := gdrive.NewGoogleClient(mustTestService(t, server))
	if err != nil {
		t.Fatal(err)
	}
	config := gdrive.Config{
		IdentityDomain: "google-drive:user:user-1",
		StreamID:       "google-drive:user:user-1:my-drive:changes",
		Root:           "root",
		Kind:           gdrive.StreamMyDrive,
	}
	if _, err := client.ListFiles(context.Background(), config, "files-2"); err != nil {
		t.Fatal(err)
	}
	if _, err := client.ListChanges(context.Background(), config, "cursor-1"); err != nil {
		t.Fatal(err)
	}

	if len(queries) != 2 {
		t.Fatalf("queries=%#v", queries)
	}
	assertQuery(t, queries[0], "corpora", "user")
	assertQuery(t, queries[0], "includeItemsFromAllDrives", "false")
	assertQuery(t, queries[0], "pageToken", "files-2")
	assertQuery(t, queries[0], "spaces", "drive")
	assertQuery(t, queries[1], "restrictToMyDrive", "true")
	assertQuery(t, queries[1], "includeItemsFromAllDrives", "false")
	assertQuery(t, queries[1], "includeRemoved", "true")
	assertQuery(t, queries[1], "spaces", "drive")
}

func TestGoogleClientResolvesCanonicalMyDriveRootID(t *testing.T) {
	var request capturedRequest
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		request = capturedRequest{path: r.URL.Path, query: r.URL.Query()}
		w.Header().Set("Content-Type", "application/json")
		if r.URL.Path != "/files/root" {
			http.NotFound(w, r)
			return
		}
		_, _ = w.Write([]byte(`{"id":"actual-my-drive-root-id"}`))
	}))
	defer server.Close()

	client, err := gdrive.NewGoogleClient(mustTestService(t, server))
	if err != nil {
		t.Fatal(err)
	}
	config := gdrive.Config{
		IdentityDomain: "google-drive:user:user-1",
		StreamID:       "google-drive:user:user-1:my-drive:changes",
		Root:           "root",
		Kind:           gdrive.StreamMyDrive,
	}
	rootID, err := client.ResolveMyDriveRoot(context.Background(), config)
	if err != nil {
		t.Fatal(err)
	}
	if rootID != "actual-my-drive-root-id" {
		t.Fatalf("root=%q", rootID)
	}
	if request.path != "/files/root" {
		t.Fatalf("path=%q", request.path)
	}
	if fields := request.query.Get("fields"); fields != "id" {
		t.Fatalf("fields=%q query=%v", fields, request.query)
	}
}

func TestGoogleClientHTTPFailuresRemainOrdinaryErrors(t *testing.T) {
	for _, status := range []int{
		http.StatusUnauthorized,
		http.StatusForbidden,
		http.StatusNotFound,
		http.StatusTooManyRequests,
		http.StatusInternalServerError,
	} {
		t.Run(http.StatusText(status), func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				http.Error(w, http.StatusText(status), status)
			}))
			defer server.Close()

			client, err := gdrive.NewGoogleClient(mustTestService(t, server))
			if err != nil {
				t.Fatal(err)
			}
			config := gdrive.Config{
				IdentityDomain: "google-drive:user:user-1",
				StreamID:       "google-drive:user:user-1:my-drive:changes",
				Root:           "actual-root-id",
				Kind:           gdrive.StreamMyDrive,
			}
			adapter, err := gdrive.New(client, config)
			if err != nil {
				t.Fatal(err)
			}
			page, err := adapter.ReadChanges(context.Background(), config.Scope(), "cursor-1", "")
			if err == nil {
				t.Fatalf("status=%d unexpectedly returned page=%#v", status, page)
			}
			for _, sentinel := range []error{
				gdrive.ErrClientHistoryGap,
				gdrive.ErrClientInvalidCursor,
				gdrive.ErrClientScopeMismatch,
				gdrive.ErrClientInsufficientHistory,
			} {
				if errors.Is(err, sentinel) {
					t.Fatalf("status=%d incorrectly mapped to history semantic %v: %v", status, sentinel, err)
				}
			}
		})
	}
}

func TestNewGoogleClientRejectsNilService(t *testing.T) {
	if _, err := gdrive.NewGoogleClient(nil); err != gdrive.ErrNilDriveService {
		t.Fatalf("err=%v", err)
	}
}

type capturedRequest struct {
	path  string
	query url.Values
}

func mustTestService(t *testing.T, server *httptest.Server) *drive.Service {
	t.Helper()
	service, err := drive.New(server.Client())
	if err != nil {
		t.Fatal(err)
	}
	service.BasePath = server.URL + "/"
	return service
}

func assertQuery(t *testing.T, query url.Values, key, want string) {
	t.Helper()
	if got := query.Get(key); got != want {
		t.Fatalf("%s=%q want=%q full=%v", key, got, want, query)
	}
}
