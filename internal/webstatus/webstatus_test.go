package webstatus

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/doctor"
	localruntime "github.com/efremov-aleksei-96/keelaryn/internal/runtime/local"
)

func TestHandlerServesReadOnlyDoctorStatus(t *testing.T) {
	root, control := bootstrapStatusFixture(t)
	_ = root
	statePath := filepath.Join(control, "state.db")
	searchPath := filepath.Join(control, "search.db")
	stateBefore, err := os.ReadFile(statePath)
	if err != nil {
		t.Fatal(err)
	}
	searchBefore, err := os.ReadFile(searchPath)
	if err != nil {
		t.Fatal(err)
	}

	h, err := NewHandler(control)
	if err != nil {
		t.Fatal(err)
	}

	apiRequest := httptest.NewRequest(http.MethodGet, "http://127.0.0.1/api/status", nil)
	apiRequest.Host = "127.0.0.1"
	apiResponse := httptest.NewRecorder()
	h.ServeHTTP(apiResponse, apiRequest)
	if apiResponse.Code != http.StatusOK {
		t.Fatalf("api status=%d body=%s", apiResponse.Code, apiResponse.Body.String())
	}
	var report doctor.Report
	if err := json.Unmarshal(apiResponse.Body.Bytes(), &report); err != nil {
		t.Fatal(err)
	}
	if !report.Passed() || len(report.Checks) != 4 {
		t.Fatalf("report=%#v", report)
	}
	if apiResponse.Header().Get("Access-Control-Allow-Origin") != "" {
		t.Fatal("status API unexpectedly enabled CORS")
	}
	if apiResponse.Header().Get("Content-Security-Policy") == "" ||
		apiResponse.Header().Get("Cache-Control") != "no-store" {
		t.Fatalf("security headers=%v", apiResponse.Header())
	}

	pageRequest := httptest.NewRequest(http.MethodGet, "http://127.0.0.1/", nil)
	pageRequest.Host = "127.0.0.1"
	pageResponse := httptest.NewRecorder()
	h.ServeHTTP(pageResponse, pageRequest)
	if pageResponse.Code != http.StatusOK {
		t.Fatalf("page status=%d body=%s", pageResponse.Code, pageResponse.Body.String())
	}
	if body := pageResponse.Body.String(); !strings.Contains(body, "Keelaryn status") || !strings.Contains(body, "PASS") {
		t.Fatalf("unexpected page body: %s", body)
	}

	stateAfter, err := os.ReadFile(statePath)
	if err != nil {
		t.Fatal(err)
	}
	searchAfter, err := os.ReadFile(searchPath)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(stateBefore, stateAfter) || !bytes.Equal(searchBefore, searchAfter) {
		t.Fatal("web status mutated protected databases")
	}
}

func TestHandlerRejectsNonLocalHostAndMutationMethods(t *testing.T) {
	_, control := bootstrapStatusFixture(t)
	h, err := NewHandler(control)
	if err != nil {
		t.Fatal(err)
	}

	foreign := httptest.NewRequest(http.MethodGet, "http://example.test/api/status", nil)
	foreign.Host = "example.test"
	foreignResponse := httptest.NewRecorder()
	h.ServeHTTP(foreignResponse, foreign)
	if foreignResponse.Code != http.StatusForbidden {
		t.Fatalf("foreign Host status=%d want %d", foreignResponse.Code, http.StatusForbidden)
	}

	crossSite := httptest.NewRequest(http.MethodGet, "http://127.0.0.1/api/status", nil)
	crossSite.Host = "127.0.0.1"
	crossSite.Header.Set("Sec-Fetch-Site", "cross-site")
	crossSiteResponse := httptest.NewRecorder()
	h.ServeHTTP(crossSiteResponse, crossSite)
	if crossSiteResponse.Code != http.StatusForbidden {
		t.Fatalf("cross-site request status=%d want %d", crossSiteResponse.Code, http.StatusForbidden)
	}
	if vary := crossSiteResponse.Header().Get("Vary"); !strings.Contains(vary, "Sec-Fetch-Site") {
		t.Fatalf("cross-site response missing Vary: %q", vary)
	}

	post := httptest.NewRequest(http.MethodPost, "http://127.0.0.1/api/status", strings.NewReader("{}"))
	post.Host = "127.0.0.1"
	postResponse := httptest.NewRecorder()
	h.ServeHTTP(postResponse, post)
	if postResponse.Code != http.StatusMethodNotAllowed || postResponse.Header().Get("Allow") != "GET, HEAD" {
		t.Fatalf("POST status=%d headers=%v", postResponse.Code, postResponse.Header())
	}
}

func TestNewHandlerMissingControlDoesNotCreate(t *testing.T) {
	control := filepath.Join(t.TempDir(), "missing")
	if _, err := NewHandler(control); err == nil {
		t.Fatal("missing control directory unexpectedly accepted")
	}
	if _, err := os.Stat(control); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("missing control directory was created: %v", err)
	}
}

func TestValidateLoopbackListenAddress(t *testing.T) {
	for _, address := range []string{"127.0.0.1:0", "127.0.0.1:8080", "[::1]:0"} {
		if err := validateLoopbackListenAddress(address); err != nil {
			t.Fatalf("address %q rejected: %v", address, err)
		}
	}
	for _, address := range []string{"0.0.0.0:0", ":0", "192.168.1.5:8080", "localhost:8080", "bad"} {
		if err := validateLoopbackListenAddress(address); err == nil {
			t.Fatalf("address %q unexpectedly accepted", address)
		}
	}
}

func TestRunAnnouncesLoopbackAndStopsOnCancellation(t *testing.T) {
	_, control := bootstrapStatusFixture(t)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	announce := &channelWriter{ch: make(chan string, 1)}
	done := make(chan error, 1)
	go func() {
		done <- Run(ctx, Options{ControlDir: control, Listen: DefaultListenAddress}, announce)
	}()

	select {
	case address := <-announce.ch:
		if !strings.HasPrefix(address, "http://127.0.0.1:") || !strings.HasSuffix(address, "/\n") {
			t.Fatalf("announcement=%q", address)
		}
		cancel()
	case <-time.After(10 * time.Second):
		t.Fatal("web status listener did not announce")
	}

	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("Run after cancellation: %v", err)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("web status listener did not stop after cancellation")
	}
}

type channelWriter struct {
	ch chan string
}

func (w *channelWriter) Write(p []byte) (int, error) {
	w.ch <- string(p)
	return len(p), nil
}

func bootstrapStatusFixture(t *testing.T) (root, control string) {
	t.Helper()
	root = t.TempDir()
	control = filepath.Join(t.TempDir(), "control")
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte("web status fixture"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := localruntime.BootstrapProtectedIndex(context.Background(), localruntime.ProtectedIndexOptions{
		Root: root, ControlDir: control, ObservedAt: time.Now().UTC(), MaxBytes: 4096,
	}); err != nil {
		t.Fatal(err)
	}
	return root, control
}
