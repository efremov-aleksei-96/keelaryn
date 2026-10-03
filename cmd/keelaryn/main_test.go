package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/contextbundle"
	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/doctor"
	"github.com/efremov-aleksei-96/keelaryn/internal/mcpaccess"
	gdriveruntime "github.com/efremov-aleksei-96/keelaryn/internal/runtime/gdrive"
	localruntime "github.com/efremov-aleksei-96/keelaryn/internal/runtime/local"
	"github.com/efremov-aleksei-96/keelaryn/internal/search"
	"github.com/efremov-aleksei-96/keelaryn/internal/selftest"
	"github.com/efremov-aleksei-96/keelaryn/internal/webstatus"
)

func TestScanOutputsObservationsWithoutInventingIdentity(t *testing.T) {
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte("hello"), 0o600); err != nil {
		t.Fatal(err)
	}
	var stdout, stderr bytes.Buffer
	if err := run([]string{"scan", "--root", root}, &stdout, &stderr); err != nil {
		t.Fatalf("run: %v; stderr=%s", err, stderr.String())
	}
	var observations []corpus.Observation
	if err := json.Unmarshal(stdout.Bytes(), &observations); err != nil {
		t.Fatalf("decode output: %v\n%s", err, stdout.String())
	}
	if len(observations) != 1 || observations[0].Locator.Path != "note.txt" {
		t.Fatalf("observations=%#v", observations)
	}
	if observations[0].ProviderObject.ID != "" {
		t.Fatalf("provider identity was invented: %#v", observations[0].ProviderObject)
	}
}

func TestBootstrapIndexAndSearchThroughProtectedExecutableSurface(t *testing.T) {
	root := t.TempDir()
	control := filepath.Join(t.TempDir(), "control")
	if err := os.WriteFile(filepath.Join(root, "note.md"), []byte("Keelaryn runtime composition searchable"), 0o600); err != nil {
		t.Fatal(err)
	}
	var stdout, stderr bytes.Buffer
	if err := run([]string{
		"bootstrap-index", "--root", root, "--control-dir", control, "--max-bytes", "4096",
	}, &stdout, &stderr); err != nil {
		t.Fatalf("bootstrap-index: %v; stderr=%s", err, stderr.String())
	}
	var first localruntime.IndexResult
	if err := json.Unmarshal(stdout.Bytes(), &first); err != nil {
		t.Fatal(err)
	}
	if first.ReusedScan || first.Indexed != 1 {
		t.Fatalf("first=%#v", first)
	}

	stdout.Reset()
	stderr.Reset()
	if err := run([]string{
		"search", "--control-dir", control, "--query", "runtime searchable",
	}, &stdout, &stderr); err != nil {
		t.Fatalf("search: %v; stderr=%s", err, stderr.String())
	}
	var hits []search.Hit
	if err := json.Unmarshal(stdout.Bytes(), &hits); err != nil {
		t.Fatal(err)
	}
	if len(hits) != 1 || hits[0].ArtifactID == "" || hits[0].RevisionID == "" {
		t.Fatalf("hits=%#v", hits)
	}

	stdout.Reset()
	stderr.Reset()
	if err := run([]string{
		"bootstrap-index", "--root", root, "--control-dir", control, "--max-bytes", "4096",
	}, &stdout, &stderr); err != nil {
		t.Fatalf("replay bootstrap-index: %v; stderr=%s", err, stderr.String())
	}
	var replay localruntime.IndexResult
	if err := json.Unmarshal(stdout.Bytes(), &replay); err != nil {
		t.Fatal(err)
	}
	if !replay.ReusedScan || replay.ScanID != first.ScanID || replay.Indexed != 1 {
		t.Fatalf("replay=%#v first=%#v", replay, first)
	}

	entries, err := os.ReadDir(root)
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 1 || entries[0].Name() != "note.md" {
		t.Fatalf("corpus mutated by runtime composition: %#v", entries)
	}
}

func TestContextBundleThroughProtectedExecutableSurface(t *testing.T) {
	root := t.TempDir()
	control := filepath.Join(t.TempDir(), "control")
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte("context runtime searchable"), 0o600); err != nil {
		t.Fatal(err)
	}
	var stdout, stderr bytes.Buffer
	if err := run([]string{
		"bootstrap-index", "--root", root, "--control-dir", control, "--max-bytes", "4096",
	}, &stdout, &stderr); err != nil {
		t.Fatalf("bootstrap-index: %v; stderr=%s", err, stderr.String())
	}
	stdout.Reset()
	stderr.Reset()
	if err := run([]string{
		"context-bundle", "--root", root, "--control-dir", control,
		"--query", "runtime searchable", "--reason", "answer exact task", "--max-bytes", "4096",
	}, &stdout, &stderr); err != nil {
		t.Fatalf("context-bundle: %v; stderr=%s", err, stderr.String())
	}
	var bundle contextbundle.Bundle
	if err := json.Unmarshal(stdout.Bytes(), &bundle); err != nil {
		t.Fatal(err)
	}
	if len(bundle.Items) != 1 ||
		bundle.Items[0].Reason != "answer exact task" ||
		bundle.Items[0].Text != "context runtime searchable" ||
		bundle.Items[0].ArtifactID == "" ||
		bundle.Items[0].RevisionID == "" {
		t.Fatalf("bundle=%#v", bundle)
	}
}

func TestBootstrapIndexRejectsControlDirectoryInsideCorpus(t *testing.T) {
	root := t.TempDir()
	control := filepath.Join(root, "control")
	var stdout, stderr bytes.Buffer
	err := run([]string{
		"bootstrap-index", "--root", root, "--control-dir", control,
	}, &stdout, &stderr)
	if !errors.Is(err, localruntime.ErrRuntimeStateInCorpus) {
		t.Fatalf("error=%v want ErrRuntimeStateInCorpus", err)
	}
	if _, statErr := os.Stat(control); !errors.Is(statErr, os.ErrNotExist) {
		t.Fatalf("control directory created inside corpus: %v", statErr)
	}
}

func TestExecutableRejectsRawDatabasePathBypass(t *testing.T) {
	var stdout, stderr bytes.Buffer
	err := run([]string{
		"search", "--search-db", filepath.Join(t.TempDir(), "search.db"), "--query", "x",
	}, &stdout, &stderr)
	if err == nil {
		t.Fatal("raw --search-db executable bypass unexpectedly accepted")
	}
}

func TestMCPStdioCommandPassesOnlyOperatorScopedPaths(t *testing.T) {
	root := t.TempDir()
	control := filepath.Join(t.TempDir(), "control")

	original := runMCPStdio
	t.Cleanup(func() { runMCPStdio = original })
	called := false
	var captured mcpaccess.Options
	runMCPStdio = func(_ context.Context, options mcpaccess.Options) error {
		called = true
		captured = options
		return nil
	}

	var stdout, stderr bytes.Buffer
	if err := run([]string{
		"mcp-stdio", "--root", root, "--control-dir", control,
	}, &stdout, &stderr); err != nil {
		t.Fatalf("mcp-stdio: %v; stderr=%s", err, stderr.String())
	}
	if !called {
		t.Fatal("MCP stdio runtime was not called")
	}
	if captured.Root != root || captured.ControlDir != control {
		t.Fatalf("captured=%#v", captured)
	}
	if stdout.Len() != 0 || stderr.Len() != 0 {
		t.Fatalf("unexpected command output: stdout=%q stderr=%q", stdout.String(), stderr.String())
	}
}

func TestMCPStdioCommandRequiresOperatorScope(t *testing.T) {
	original := runMCPStdio
	t.Cleanup(func() { runMCPStdio = original })
	called := false
	runMCPStdio = func(context.Context, mcpaccess.Options) error {
		called = true
		return nil
	}

	var stdout, stderr bytes.Buffer
	err := run([]string{"mcp-stdio", "--root", t.TempDir()}, &stdout, &stderr)
	if err == nil {
		t.Fatal("mcp-stdio unexpectedly accepted missing --control-dir")
	}
	if called {
		t.Fatal("MCP runtime called without complete operator scope")
	}
}

func TestGoogleDriveBootstrapReadsTokenFromEnvironmentWithoutEmittingIt(t *testing.T) {
	const token = "cli-secret-token-never-output"
	const envName = "KEELARYN_TEST_GOOGLE_TOKEN"
	t.Setenv(envName, token)
	control := filepath.Join(t.TempDir(), "control")

	original := bootstrapGoogleDriveReadOnly
	t.Cleanup(func() { bootstrapGoogleDriveReadOnly = original })
	var captured gdriveruntime.Options
	bootstrapGoogleDriveReadOnly = func(_ context.Context, options gdriveruntime.Options) (gdriveruntime.Result, error) {
		captured = options
		return gdriveruntime.Result{
			ProviderID:      "google-drive",
			IdentityDomain:  "google-drive:user:test",
			CanonicalRootID: "root-id",
			RequiredScope:   gdriveruntime.RequiredScope,
		}, nil
	}

	var stdout, stderr bytes.Buffer
	if err := run([]string{
		"google-drive-bootstrap",
		"--control-dir", control,
		"--access-token-env", envName,
	}, &stdout, &stderr); err != nil {
		t.Fatalf("run: %v; stderr=%s", err, stderr.String())
	}
	if captured.ControlDir != control || captured.AccessToken != token || captured.ObservedAt.IsZero() {
		t.Fatalf("captured=%#v", captured)
	}
	if strings.Contains(stdout.String(), token) || strings.Contains(stderr.String(), token) {
		t.Fatal("access token leaked through executable output")
	}
	var result gdriveruntime.Result
	if err := json.Unmarshal(stdout.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	if result.RequiredScope != gdriveruntime.RequiredScope {
		t.Fatalf("result=%#v", result)
	}
}

func TestGoogleDriveBootstrapRequiresEnvironmentTokenBeforeRuntime(t *testing.T) {
	const envName = "KEELARYN_TEST_MISSING_GOOGLE_TOKEN"
	t.Setenv(envName, "")
	control := filepath.Join(t.TempDir(), "control")

	original := bootstrapGoogleDriveReadOnly
	t.Cleanup(func() { bootstrapGoogleDriveReadOnly = original })
	called := false
	bootstrapGoogleDriveReadOnly = func(context.Context, gdriveruntime.Options) (gdriveruntime.Result, error) {
		called = true
		return gdriveruntime.Result{}, nil
	}

	var stdout, stderr bytes.Buffer
	err := run([]string{
		"google-drive-bootstrap",
		"--control-dir", control,
		"--access-token-env", envName,
	}, &stdout, &stderr)
	if err == nil {
		t.Fatal("missing environment token unexpectedly accepted")
	}
	if called {
		t.Fatal("runtime called without access token")
	}
	if _, statErr := os.Stat(control); !errors.Is(statErr, os.ErrNotExist) {
		t.Fatalf("control directory created before runtime: %v", statErr)
	}
}

func TestGoogleDriveBootstrapRejectsTokenArgument(t *testing.T) {
	const token = "do-not-put-token-in-argv"
	var stdout, stderr bytes.Buffer
	err := run([]string{
		"google-drive-bootstrap",
		"--control-dir", filepath.Join(t.TempDir(), "control"),
		"--access-token", token,
	}, &stdout, &stderr)
	if err == nil {
		t.Fatal("raw access-token CLI argument unexpectedly accepted")
	}
	if strings.Contains(stderr.String(), token) || strings.Contains(err.Error(), token) {
		t.Fatal("rejected token argument leaked token value")
	}
}

func TestDoctorThroughExecutableSurface(t *testing.T) {
	root := t.TempDir()
	control := filepath.Join(t.TempDir(), "control")
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte("doctor cli searchable"), 0o600); err != nil {
		t.Fatal(err)
	}
	var stdout, stderr bytes.Buffer
	if err := run([]string{
		"bootstrap-index", "--root", root, "--control-dir", control, "--max-bytes", "4096",
	}, &stdout, &stderr); err != nil {
		t.Fatalf("bootstrap-index: %v; stderr=%s", err, stderr.String())
	}
	stdout.Reset()
	stderr.Reset()

	if err := run([]string{"doctor", "--control-dir", control}, &stdout, &stderr); err != nil {
		t.Fatalf("doctor: %v; stderr=%s", err, stderr.String())
	}
	var report doctor.Report
	if err := json.Unmarshal(stdout.Bytes(), &report); err != nil {
		t.Fatalf("decode doctor report: %v\n%s", err, stdout.String())
	}
	if !report.Passed() || len(report.Checks) != 4 {
		t.Fatalf("report=%#v", report)
	}
}

func TestDoctorFailureKeepsFindingsOnStdoutOnly(t *testing.T) {
	control := filepath.Join(t.TempDir(), "missing")
	var stdout, stderr bytes.Buffer

	err := run([]string{"doctor", "--control-dir", control}, &stdout, &stderr)
	if !errors.Is(err, doctor.ErrFailed) {
		t.Fatalf("error=%v want doctor.ErrFailed", err)
	}
	var report doctor.Report
	if decodeErr := json.Unmarshal(stdout.Bytes(), &report); decodeErr != nil {
		t.Fatalf("decode doctor failure report: %v\n%s", decodeErr, stdout.String())
	}
	if report.Passed() {
		t.Fatalf("failure report unexpectedly passed: %#v", report)
	}
	if stderr.Len() != 0 {
		t.Fatalf("doctor failure emitted unstructured stderr: %q", stderr.String())
	}
	if _, statErr := os.Stat(control); !errors.Is(statErr, os.ErrNotExist) {
		t.Fatalf("doctor created missing control directory: %v", statErr)
	}
}

func TestSelfTestThroughExecutableSurface(t *testing.T) {
	var stdout, stderr bytes.Buffer
	if err := run([]string{"self-test"}, &stdout, &stderr); err != nil {
		t.Fatalf("self-test: %v; stderr=%s", err, stderr.String())
	}
	var report selftest.Report
	if err := json.Unmarshal(stdout.Bytes(), &report); err != nil {
		t.Fatalf("decode self-test report: %v\n%s", err, stdout.String())
	}
	if !report.Passed() {
		t.Fatalf("report=%#v", report)
	}
	if report.Proof.ArtifactID == "" || report.Proof.RevisionID == "" ||
		report.Proof.Reason != "prove disposable exact provenance" ||
		!report.Proof.CorpusUnchanged || !report.Proof.Cleaned {
		t.Fatalf("proof=%#v", report.Proof)
	}
	if stderr.Len() != 0 {
		t.Fatalf("self-test emitted stderr on success: %q", stderr.String())
	}
}

func TestSelfTestRejectsUserArguments(t *testing.T) {
	var stdout, stderr bytes.Buffer
	err := run([]string{"self-test", "unexpected"}, &stdout, &stderr)
	if err == nil {
		t.Fatal("self-test unexpectedly accepted a user argument")
	}
	if stdout.Len() != 0 {
		t.Fatalf("self-test emitted a report after invalid arguments: %q", stdout.String())
	}
}

func TestWebStatusCommandUsesLoopbackDefault(t *testing.T) {
	control := filepath.Join(t.TempDir(), "control")

	original := runWebStatus
	t.Cleanup(func() { runWebStatus = original })
	called := false
	var captured webstatus.Options
	runWebStatus = func(ctx context.Context, options webstatus.Options, announce io.Writer) error {
		called = true
		captured = options
		if ctx.Done() == nil {
			t.Fatal("web-status CLI did not supply a signal-cancellable context")
		}
		_, err := io.WriteString(announce, "http://127.0.0.1:43210/\n")
		return err
	}

	var stdout, stderr bytes.Buffer
	if err := run([]string{"web-status", "--control-dir", control}, &stdout, &stderr); err != nil {
		t.Fatalf("web-status: %v; stderr=%s", err, stderr.String())
	}
	if !called {
		t.Fatal("web-status runtime was not called")
	}
	if captured.ControlDir != control || captured.Listen != webstatus.DefaultListenAddress {
		t.Fatalf("captured=%#v", captured)
	}
	if stdout.String() != "http://127.0.0.1:43210/\n" || stderr.Len() != 0 {
		t.Fatalf("unexpected output stdout=%q stderr=%q", stdout.String(), stderr.String())
	}
}

func TestWebStatusCommandRequiresControlAndRejectsPositionalArguments(t *testing.T) {
	original := runWebStatus
	t.Cleanup(func() { runWebStatus = original })
	called := false
	runWebStatus = func(context.Context, webstatus.Options, io.Writer) error {
		called = true
		return nil
	}

	for _, args := range [][]string{
		{"web-status"},
		{"web-status", "--control-dir", filepath.Join(t.TempDir(), "control"), "extra"},
	} {
		var stdout, stderr bytes.Buffer
		if err := run(args, &stdout, &stderr); err == nil {
			t.Fatalf("args=%q unexpectedly accepted", args)
		}
	}
	if called {
		t.Fatal("web-status runtime called for invalid CLI arguments")
	}
}
