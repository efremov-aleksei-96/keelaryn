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
			tool.Annotations.OpenWorldHint == nil || *tool.Annotations.OpenWorldHint {
			t.Fatalf("tool %q annotations=%#v", tool.Name, tool.Annotations)
		}
		schema, err := json.Marshal(tool.InputSchema)
		if err != nil {
			t.Fatal(err)
		}
		lower := strings.ToLower(string(schema))
		if strings.Contains(lower, "root") || strings.Contains(lower, "control-dir") || strings.Contains(lower, "control_dir") ||
			strings.Contains(lower, "state-db") || strings.Contains(lower, "search-db") {
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

func TestNewServerRequiresFixedOperatorScope(t *testing.T) {
	if _, err := NewServer(Options{}); err == nil {
		t.Fatal("empty MCP scope unexpectedly accepted")
	}
	if _, err := NewServer(Options{Root: t.TempDir()}); err == nil {
		t.Fatal("missing control directory unexpectedly accepted")
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
