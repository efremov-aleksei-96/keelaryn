package mcpaccess

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	localruntime "github.com/efremov-aleksei-96/keelaryn/internal/runtime/local"
	"github.com/modelcontextprotocol/go-sdk/mcp"
	zsqlite "zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestMinimalMCPAccessSearchAndContextBundle(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	control := filepath.Join(t.TempDir(), "control")
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte("mcp exact provenance searchable"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := localruntime.BootstrapProtectedIndex(ctx, localruntime.ProtectedIndexOptions{
		Root: root, ControlDir: control, ObservedAt: time.Now().UTC(), MaxBytes: 4096,
	}); err != nil {
		t.Fatalf("bootstrap protected index: %v", err)
	}

	server, err := NewServer(Options{Root: root, ControlDir: control})
	if err != nil {
		t.Fatal(err)
	}
	serverTransport, clientTransport := mcp.NewInMemoryTransports()
	serverSession, err := server.Connect(ctx, serverTransport, nil)
	if err != nil {
		t.Fatal(err)
	}
	client := mcp.NewClient(&mcp.Implementation{Name: "keelaryn-test", Version: "p0"}, nil)
	clientSession, err := client.Connect(ctx, clientTransport, nil)
	if err != nil {
		serverSession.Close()
		t.Fatal(err)
	}

	tools, err := clientSession.ListTools(ctx, nil)
	if err != nil {
		clientSession.Close()
		serverSession.Close()
		t.Fatal(err)
	}
	if len(tools.Tools) != 2 {
		t.Fatalf("tools=%d want 2", len(tools.Tools))
	}
	for _, tool := range tools.Tools {
		if tool.Annotations == nil || !tool.Annotations.ReadOnlyHint ||
			tool.Annotations.DestructiveHint == nil || *tool.Annotations.DestructiveHint ||
			tool.Annotations.OpenWorldHint == nil || *tool.Annotations.OpenWorldHint {
			t.Fatalf("tool %q annotations=%#v", tool.Name, tool.Annotations)
		}
		schema, err := json.Marshal(tool.InputSchema)
		if err != nil {
			t.Fatal(err)
		}
		lower := strings.ToLower(string(schema))
		if strings.Contains(lower, "root") || strings.Contains(lower, "control-dir") || strings.Contains(lower, "control_dir") ||
			strings.Contains(lower, "state-db") || strings.Contains(lower, "search-db") ||
			strings.Contains(lower, "\"path\"") {
			t.Fatalf("tool %q exposes filesystem/database authority in input schema: %s", tool.Name, schema)
		}
	}

	searchResult, err := clientSession.CallTool(ctx, &mcp.CallToolParams{
		Name: "keelaryn_search",
		Arguments: map[string]any{"query": "exact searchable"},
	})
	if err != nil {
		t.Fatalf("call search: %v", err)
	}
	if searchResult.IsError {
		t.Fatalf("search returned tool error: %#v", searchResult.Content)
	}
	var searchOut SearchOutput
	decodeStructured(t, searchResult.StructuredContent, &searchOut)
	if len(searchOut.Hits) != 1 || searchOut.Hits[0].ArtifactID == "" || searchOut.Hits[0].RevisionID == "" {
		t.Fatalf("search output=%#v", searchOut)
	}

	contextResult, err := clientSession.CallTool(ctx, &mcp.CallToolParams{
		Name: "keelaryn_context_bundle",
		Arguments: map[string]any{
			"query": "exact searchable",
			"reason": "answer the current task",
			"max_bytes": 4096,
		},
	})
	if err != nil {
		t.Fatalf("call context bundle: %v", err)
	}
	if contextResult.IsError {
		t.Fatalf("context bundle returned tool error: %#v", contextResult.Content)
	}
	var contextOut ContextBundleOutput
	decodeStructured(t, contextResult.StructuredContent, &contextOut)
	if len(contextOut.Bundle.Items) != 1 {
		t.Fatalf("context output=%#v", contextOut)
	}
	item := contextOut.Bundle.Items[0]
	if item.Text != "mcp exact provenance searchable" ||
		item.Reason != "answer the current task" ||
		item.ArtifactID != searchOut.Hits[0].ArtifactID ||
		item.RevisionID != searchOut.Hits[0].RevisionID {
		t.Fatalf("context item=%#v search=%#v", item, searchOut.Hits[0])
	}

	if err := clientSession.Close(); err != nil {
		t.Fatal(err)
	}
	if err := serverSession.Wait(); err != nil {
		t.Fatal(err)
	}
}

func TestMCPAccessRejectsResourceAuthorityExpansion(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	control := filepath.Join(t.TempDir(), "control")
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte("bounded mcp access"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := localruntime.BootstrapProtectedIndex(ctx, localruntime.ProtectedIndexOptions{
		Root: root, ControlDir: control, ObservedAt: time.Now().UTC(), MaxBytes: 4096,
	}); err != nil {
		t.Fatalf("bootstrap protected index: %v", err)
	}

	server, err := NewServer(Options{Root: root, ControlDir: control})
	if err != nil {
		t.Fatal(err)
	}
	serverTransport, clientTransport := mcp.NewInMemoryTransports()
	serverSession, err := server.Connect(ctx, serverTransport, nil)
	if err != nil {
		t.Fatal(err)
	}
	client := mcp.NewClient(&mcp.Implementation{Name: "keelaryn-test", Version: "p0"}, nil)
	clientSession, err := client.Connect(ctx, clientTransport, nil)
	if err != nil {
		serverSession.Close()
		t.Fatal(err)
	}
	defer clientSession.Close()
	defer serverSession.Close()

	searchResult, err := clientSession.CallTool(ctx, &mcp.CallToolParams{
		Name: "keelaryn_search",
		Arguments: map[string]any{"query": "bounded", "limit": maxSearchLimit + 1},
	})
	if err != nil {
		t.Fatalf("oversized search call transport error: %v", err)
	}
	if !searchResult.IsError {
		t.Fatal("MCP search unexpectedly accepted limit above qualified maximum")
	}

	oversizedQueryResult, err := clientSession.CallTool(ctx, &mcp.CallToolParams{
		Name:      "keelaryn_search",
		Arguments: map[string]any{"query": strings.Repeat("q", maxQueryBytes+1)},
	})
	if err != nil {
		t.Fatalf("oversized search query transport error: %v", err)
	}
	if !oversizedQueryResult.IsError {
		t.Fatal("MCP search unexpectedly accepted query above qualified byte maximum")
	}

	oversizedReasonResult, err := clientSession.CallTool(ctx, &mcp.CallToolParams{
		Name: "keelaryn_context_bundle",
		Arguments: map[string]any{
			"query":  "bounded",
			"reason": strings.Repeat("r", maxReasonBytes+1),
		},
	})
	if err != nil {
		t.Fatalf("oversized context reason transport error: %v", err)
	}
	if !oversizedReasonResult.IsError {
		t.Fatal("MCP context unexpectedly accepted reason above qualified byte maximum")
	}

	contextResult, err := clientSession.CallTool(ctx, &mcp.CallToolParams{
		Name: "keelaryn_context_bundle",
		Arguments: map[string]any{
			"query": "bounded",
			"reason": "prove MCP resource bound",
			"max_bytes": maxContextMaxBytes + 1,
		},
	})
	if err != nil {
		t.Fatalf("oversized context call transport error: %v", err)
	}
	if !contextResult.IsError {
		t.Fatal("MCP context unexpectedly accepted max_bytes above qualified maximum")
	}
}

func TestNewServerRequiresFixedOperatorScope(t *testing.T) {
	if _, err := NewServer(Options{}); err == nil {
		t.Fatal("empty MCP scope unexpectedly accepted")
	}
	if _, err := NewServer(Options{Root: t.TempDir()}); err == nil {
		t.Fatal("missing control directory unexpectedly accepted")
	}
}

func TestNewServerRejectsControlDirectoryInsideCorpus(t *testing.T) {
	root := t.TempDir()
	control := filepath.Join(root, "control")
	if err := os.Mkdir(control, 0o700); err != nil {
		t.Fatal(err)
	}
	if _, err := NewServer(Options{Root: root, ControlDir: control}); err == nil {
		t.Fatal("MCP server unexpectedly accepted protected control directory inside corpus")
	}
}

func TestNewServerRejectsIncompleteProtectedControlStore(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	control := filepath.Join(t.TempDir(), "control")
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte("complete MCP control"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := localruntime.BootstrapProtectedIndex(ctx, localruntime.ProtectedIndexOptions{
		Root: root, ControlDir: control, ObservedAt: time.Now().UTC(), MaxBytes: 4096,
	}); err != nil {
		t.Fatalf("bootstrap protected index: %v", err)
	}
	if err := os.Remove(filepath.Join(control, "search.db")); err != nil {
		t.Fatal(err)
	}
	if _, err := NewServer(Options{Root: root, ControlDir: control}); err == nil {
		t.Fatal("MCP server unexpectedly accepted protected control without search database")
	}
}

func TestNewServerRejectsControlStoreForDifferentRoot(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	otherRoot := t.TempDir()
	control := filepath.Join(t.TempDir(), "control")
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte("bound MCP root"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := localruntime.BootstrapProtectedIndex(ctx, localruntime.ProtectedIndexOptions{
		Root: root, ControlDir: control, ObservedAt: time.Now().UTC(), MaxBytes: 4096,
	}); err != nil {
		t.Fatalf("bootstrap protected index: %v", err)
	}
	if _, err := NewServer(Options{Root: otherRoot, ControlDir: control}); err == nil {
		t.Fatal("MCP server unexpectedly accepted control store bound to a different corpus root")
	}
}

func TestNewServerRejectsFTSDrift(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	control := filepath.Join(t.TempDir(), "control")
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte("MCP FTS integrity"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := localruntime.BootstrapProtectedIndex(ctx, localruntime.ProtectedIndexOptions{
		Root: root, ControlDir: control, ObservedAt: time.Now().UTC(), MaxBytes: 4096,
	}); err != nil {
		t.Fatalf("bootstrap protected index: %v", err)
	}

	searchDB := filepath.Join(control, "search.db")
	conn, err := zsqlite.OpenConn(searchDB, zsqlite.OpenReadWrite)
	if err != nil {
		t.Fatal(err)
	}
	var rowID int64
	var textValue string
	if err := sqlitex.Execute(conn,
		"SELECT document_id, text FROM search_documents LIMIT 1",
		&sqlitex.ExecOptions{ResultFunc: func(stmt *zsqlite.Stmt) error {
			rowID = stmt.ColumnInt64(0)
			textValue = stmt.ColumnText(1)
			return nil
		}}); err != nil {
		conn.Close()
		t.Fatal(err)
	}
	if rowID == 0 {
		conn.Close()
		t.Fatal("bootstrap search database contained no document to corrupt")
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO search_documents_fts(search_documents_fts, rowid, text) VALUES('delete', ?1, ?2)",
		&sqlitex.ExecOptions{Args: []any{rowID, textValue}}); err != nil {
		conn.Close()
		t.Fatal(err)
	}
	if err := conn.Close(); err != nil {
		t.Fatal(err)
	}

	if _, err := NewServer(Options{Root: root, ControlDir: control}); err == nil {
		t.Fatal("MCP server unexpectedly advertised search over an FTS-drifted control store")
	}
}

func TestNewServerRejectsSearchCacheFromDifferentState(t *testing.T) {
	ctx := context.Background()
	rootA := t.TempDir()
	rootB := t.TempDir()
	controlA := filepath.Join(t.TempDir(), "control-a")
	controlB := filepath.Join(t.TempDir(), "control-b")
	if err := os.WriteFile(filepath.Join(rootA, "a.txt"), []byte("alpha cache"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(rootB, "b.txt"), []byte("beta cache"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := localruntime.BootstrapProtectedIndex(ctx, localruntime.ProtectedIndexOptions{
		Root: rootA, ControlDir: controlA, ObservedAt: time.Now().UTC(), MaxBytes: 4096,
	}); err != nil {
		t.Fatal(err)
	}
	if _, err := localruntime.BootstrapProtectedIndex(ctx, localruntime.ProtectedIndexOptions{
		Root: rootB, ControlDir: controlB, ObservedAt: time.Now().UTC().Add(time.Second), MaxBytes: 4096,
	}); err != nil {
		t.Fatal(err)
	}
	foreign, err := os.ReadFile(filepath.Join(controlB, "search.db"))
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(controlA, "search.db"), foreign, 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := NewServer(Options{Root: rootA, ControlDir: controlA}); err == nil {
		t.Fatal("MCP server unexpectedly accepted search cache from a different state receipt")
	}
}

func TestMCPServerPinsRelativeStartupPaths(t *testing.T) {
	ctx := context.Background()
	base := t.TempDir()
	root := filepath.Join(base, "root")
	control := filepath.Join(base, "control")
	if err := os.Mkdir(root, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte("pinned relative path"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := localruntime.BootstrapProtectedIndex(ctx, localruntime.ProtectedIndexOptions{
		Root: root, ControlDir: control, ObservedAt: time.Now().UTC(), MaxBytes: 4096,
	}); err != nil {
		t.Fatal(err)
	}

	oldWD, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chdir(base); err != nil {
		t.Fatal(err)
	}
	server, err := NewServer(Options{Root: "root", ControlDir: "control"})
	if err != nil {
		_ = os.Chdir(oldWD)
		t.Fatal(err)
	}
	other := t.TempDir()
	if err := os.Chdir(other); err != nil {
		_ = os.Chdir(oldWD)
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chdir(oldWD) })

	serverTransport, clientTransport := mcp.NewInMemoryTransports()
	serverSession, err := server.Connect(ctx, serverTransport, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer serverSession.Close()
	client := mcp.NewClient(&mcp.Implementation{Name: "keelaryn-path-test", Version: "p0"}, nil)
	clientSession, err := client.Connect(ctx, clientTransport, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer clientSession.Close()
	result, err := clientSession.CallTool(ctx, &mcp.CallToolParams{
		Name: "keelaryn_search",
		Arguments: map[string]any{"query": "pinned"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if result.IsError {
		t.Fatalf("pinned search failed after working-directory change: %#v", result.Content)
	}
}

func TestMCPContextRejectsSearchCacheSwapAfterStartup(t *testing.T) {
	ctx := context.Background()
	rootA := t.TempDir()
	rootB := t.TempDir()
	controlA := filepath.Join(t.TempDir(), "control-a")
	controlB := filepath.Join(t.TempDir(), "control-b")
	if err := os.WriteFile(filepath.Join(rootA, "a.txt"), []byte("original context token"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(rootB, "b.txt"), []byte("foreign context token"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := localruntime.BootstrapProtectedIndex(ctx, localruntime.ProtectedIndexOptions{
		Root: rootA, ControlDir: controlA, ObservedAt: time.Now().UTC(), MaxBytes: 4096,
	}); err != nil {
		t.Fatal(err)
	}
	if _, err := localruntime.BootstrapProtectedIndex(ctx, localruntime.ProtectedIndexOptions{
		Root: rootB, ControlDir: controlB, ObservedAt: time.Now().UTC().Add(time.Second), MaxBytes: 4096,
	}); err != nil {
		t.Fatal(err)
	}

	server, err := NewServer(Options{Root: rootA, ControlDir: controlA})
	if err != nil {
		t.Fatal(err)
	}
	foreign, err := os.ReadFile(filepath.Join(controlB, "search.db"))
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(controlA, "search.db"), foreign, 0o600); err != nil {
		t.Fatal(err)
	}

	serverTransport, clientTransport := mcp.NewInMemoryTransports()
	serverSession, err := server.Connect(ctx, serverTransport, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer serverSession.Close()
	client := mcp.NewClient(&mcp.Implementation{Name: "keelaryn-swap-test", Version: "p0"}, nil)
	clientSession, err := client.Connect(ctx, clientTransport, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer clientSession.Close()

	result, err := clientSession.CallTool(ctx, &mcp.CallToolParams{
		Name: "keelaryn_context_bundle",
		Arguments: map[string]any{"query": "foreign", "reason": "must reject foreign cache"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if !result.IsError {
		t.Fatalf("ContextBundle unexpectedly accepted post-startup foreign search cache: %#v", result.StructuredContent)
	}
}

func TestMCPContextKeepsPinnedPhysicalRootAfterAncestorAliasRetarget(t *testing.T) {
	ctx := context.Background()
	parentA := t.TempDir()
	parentB := t.TempDir()
	rootA := filepath.Join(parentA, "root")
	rootB := filepath.Join(parentB, "root")
	if err := os.Mkdir(rootA, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(rootB, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(rootA, "note.txt"), []byte("pinned physical corpus"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(rootB, "note.txt"), []byte("retargeted foreign corpus"), 0o600); err != nil {
		t.Fatal(err)
	}
	aliasHost := t.TempDir()
	aliasParent := filepath.Join(aliasHost, "parent")
	if err := os.Symlink(parentA, aliasParent); err != nil {
		t.Skipf("symlink unavailable: %v", err)
	}
	authorityRoot := filepath.Join(aliasParent, "root")
	control := filepath.Join(t.TempDir(), "control")
	if _, err := localruntime.BootstrapProtectedIndex(ctx, localruntime.ProtectedIndexOptions{
		Root: authorityRoot, ControlDir: control, ObservedAt: time.Now().UTC(), MaxBytes: 4096,
	}); err != nil {
		t.Fatal(err)
	}
	server, err := NewServer(Options{Root: authorityRoot, ControlDir: control})
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(aliasParent); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(parentB, aliasParent); err != nil {
		t.Fatal(err)
	}

	serverTransport, clientTransport := mcp.NewInMemoryTransports()
	serverSession, err := server.Connect(ctx, serverTransport, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer serverSession.Close()
	client := mcp.NewClient(&mcp.Implementation{Name: "keelaryn-pin-test", Version: "p0"}, nil)
	clientSession, err := client.Connect(ctx, clientTransport, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer clientSession.Close()

	result, err := clientSession.CallTool(ctx, &mcp.CallToolParams{
		Name: "keelaryn_context_bundle",
		Arguments: map[string]any{"query": "pinned physical", "reason": "prove physical root pin", "max_bytes": 4096},
	})
	if err != nil {
		t.Fatal(err)
	}
	if result.IsError {
		t.Fatalf("pinned ContextBundle failed after ancestor alias retarget: %#v", result.Content)
	}
	var out ContextBundleOutput
	decodeStructured(t, result.StructuredContent, &out)
	if len(out.Bundle.Items) != 1 || out.Bundle.Items[0].Text != "pinned physical corpus" {
		t.Fatalf("bundle=%#v", out.Bundle)
	}
}

func decodeStructured(t *testing.T, value any, dst any) {
	t.Helper()
	data, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(data, dst); err != nil {
		t.Fatalf("decode structured content: %v; data=%s", err, data)
	}
}
