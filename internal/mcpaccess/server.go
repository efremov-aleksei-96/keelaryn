package mcpaccess

import (
	"context"
	"errors"
	"strings"

	"github.com/efremov-aleksei-96/keelaryn/internal/contextbundle"
	localruntime "github.com/efremov-aleksei-96/keelaryn/internal/runtime/local"
	"github.com/efremov-aleksei-96/keelaryn/internal/search"
	"github.com/modelcontextprotocol/go-sdk/mcp"
)

const (
	serverName             = "keelaryn"
	serverVersion          = "p0"
	defaultSearchLimit     = 20
	maxSearchLimit         = 20
	defaultContextLimit    = 20
	maxContextLimit        = 20
	defaultContextMaxBytes = int64(4 * 1024 * 1024)
	maxContextMaxBytes     = int64(4 * 1024 * 1024)
	maxContextTotalBytes   = int64(4 * 1024 * 1024)
	maxQueryBytes          = 4096
	maxReasonBytes         = 4096
)

var (
	ErrInvalidOptions = errors.New("invalid MCP access options")
	ErrInvalidRequest = errors.New("invalid MCP tool request")
)

// Options fixes the corpus and protected control directory at server startup.
// Tool callers cannot choose filesystem paths.
type Options struct {
	Root       string
	ControlDir string
}

type SearchInput struct {
	Query string `json:"query" jsonschema:"literal all-terms query over the existing Keelaryn search index; maximum 4096 UTF-8 bytes"`
	Limit *int   `json:"limit,omitempty" jsonschema:"optional maximum number of hits; defaults to 20 and must be between 1 and 20"`
}

type SearchOutput struct {
	Hits []search.Hit `json:"hits"`
}

type ContextBundleInput struct {
	Query    string `json:"query" jsonschema:"literal all-terms query used to select exact current revisions; maximum 4096 UTF-8 bytes"`
	Reason   string `json:"reason" jsonschema:"explicit task reason recorded on each selected ContextBundle item; maximum 4096 UTF-8 bytes"`
	Limit    *int   `json:"limit,omitempty" jsonschema:"optional maximum number of selected hits; defaults to 20 and must be between 1 and 20"`
	MaxBytes *int64 `json:"max_bytes,omitempty" jsonschema:"optional maximum bytes read from one selected file; defaults to and cannot exceed 4194304"`
}

type ContextBundleOutput struct {
	Bundle contextbundle.Bundle `json:"bundle"`
}

// NewServer constructs the minimal read-only MCP surface. It intentionally
// exposes no corpus mutation, state mutation, provider write, raw database path,
// filesystem path, HTTP listener, prompt, resource, or sampling surface.
func NewServer(options Options) (*mcp.Server, error) {
	if strings.TrimSpace(options.Root) == "" || strings.TrimSpace(options.ControlDir) == "" {
		return nil, ErrInvalidOptions
	}
	if err := localruntime.ValidateProtectedReadOnlyScope(context.Background(), options.Root, options.ControlDir); err != nil {
		return nil, err
	}

	server := mcp.NewServer(
		&mcp.Implementation{Name: serverName, Version: serverVersion},
		&mcp.ServerOptions{
			Instructions: "Read-only Keelaryn access scoped by the operator at process startup.",
			Capabilities: &mcp.ServerCapabilities{},
		},
	)

	mcp.AddTool(server, &mcp.Tool{
		Name:        "keelaryn_search",
		Description: "Search the existing rebuildable Keelaryn FTS index and return exact Artifact/Revision provenance.",
		Annotations: readOnlyAnnotations("Keelaryn search"),
	}, func(ctx context.Context, _ *mcp.CallToolRequest, input SearchInput) (*mcp.CallToolResult, SearchOutput, error) {
		limit := defaultSearchLimit
		if input.Limit != nil {
			limit = *input.Limit
		}
		if strings.TrimSpace(input.Query) == "" ||
			len(input.Query) > maxQueryBytes ||
			limit < 1 || limit > maxSearchLimit {
			return nil, SearchOutput{}, ErrInvalidRequest
		}
		hits, err := localruntime.QueryProtectedReadOnly(ctx, options.ControlDir, input.Query, limit)
		if err != nil {
			return nil, SearchOutput{}, err
		}
		if hits == nil {
			hits = []search.Hit{}
		}
		return nil, SearchOutput{Hits: hits}, nil
	})

	mcp.AddTool(server, &mcp.Tool{
		Name:        "keelaryn_context_bundle",
		Description: "Build an ephemeral task-specific ContextBundle from exact current search hits with qualified provenance checks.",
		Annotations: readOnlyAnnotations("Keelaryn context bundle"),
	}, func(ctx context.Context, _ *mcp.CallToolRequest, input ContextBundleInput) (*mcp.CallToolResult, ContextBundleOutput, error) {
		limit := defaultContextLimit
		if input.Limit != nil {
			limit = *input.Limit
		}
		maxBytes := defaultContextMaxBytes
		if input.MaxBytes != nil {
			maxBytes = *input.MaxBytes
		}
		if strings.TrimSpace(input.Query) == "" ||
			len(input.Query) > maxQueryBytes ||
			strings.TrimSpace(input.Reason) == "" ||
			len(input.Reason) > maxReasonBytes ||
			limit < 1 || limit > maxContextLimit ||
			maxBytes < 0 || maxBytes > maxContextMaxBytes {
			return nil, ContextBundleOutput{}, ErrInvalidRequest
		}
		bundle, err := localruntime.BuildProtectedContextReadOnly(ctx, localruntime.ProtectedContextOptions{
			Root:          options.Root,
			ControlDir:    options.ControlDir,
			Query:         input.Query,
			Reason:        input.Reason,
			Limit:         limit,
			MaxBytes:      maxBytes,
			MaxTotalBytes: maxContextTotalBytes,
		})
		if err != nil {
			return nil, ContextBundleOutput{}, err
		}
		if bundle.Items == nil {
			bundle.Items = []contextbundle.Item{}
		}
		return nil, ContextBundleOutput{Bundle: bundle}, nil
	})

	return server, nil
}

func RunStdio(ctx context.Context, options Options) error {
	server, err := NewServer(options)
	if err != nil {
		return err
	}
	return server.Run(ctx, &mcp.StdioTransport{})
}

func readOnlyAnnotations(title string) *mcp.ToolAnnotations {
	f := false
	return &mcp.ToolAnnotations{
		Title:           title,
		ReadOnlyHint:    true,
		DestructiveHint: &f,
		OpenWorldHint:   &f,
	}
}
