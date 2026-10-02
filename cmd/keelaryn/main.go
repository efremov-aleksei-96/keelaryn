package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/doctor"
	"github.com/efremov-aleksei-96/keelaryn/internal/mcpaccess"
	"github.com/efremov-aleksei-96/keelaryn/internal/provider/localfs"
	gdriveruntime "github.com/efremov-aleksei-96/keelaryn/internal/runtime/gdrive"
	localruntime "github.com/efremov-aleksei-96/keelaryn/internal/runtime/local"
	"github.com/efremov-aleksei-96/keelaryn/internal/selftest"
	"github.com/efremov-aleksei-96/keelaryn/internal/webstatus"
)

var (
	bootstrapGoogleDriveReadOnly = gdriveruntime.BootstrapReadOnly
	runMCPStdio                 = mcpaccess.RunStdio
	runWebStatus                = webstatus.Run
)

func main() {
	if err := run(os.Args[1:], os.Stdout, os.Stderr); err != nil {
		if errors.Is(err, doctor.ErrFailed) || errors.Is(err, selftest.ErrFailed) {
			os.Exit(1)
		}
		fmt.Fprintln(os.Stderr, "keelaryn:", err)
		os.Exit(1)
	}
}

func run(args []string, stdout, stderr io.Writer) error {
	if len(args) == 0 {
		return errors.New("usage: keelaryn <scan|bootstrap-index|search|context-bundle|mcp-stdio|web-status|google-drive-bootstrap|doctor|self-test> [options]")
	}

	switch args[0] {
	case "scan":
		flags := flag.NewFlagSet("scan", flag.ContinueOnError)
		flags.SetOutput(stderr)
		root := flags.String("root", "", "existing local corpus directory")
		if err := flags.Parse(args[1:]); err != nil {
			return err
		}
		if *root == "" {
			return errors.New("scan requires --root")
		}
		discoverer := localfs.New(corpus.ProviderID("localfs"))
		observations, err := discoverer.Discover(context.Background(), *root)
		if err != nil {
			return err
		}
		return encodeJSON(stdout, observations)

	case "bootstrap-index":
		flags := flag.NewFlagSet("bootstrap-index", flag.ContinueOnError)
		flags.SetOutput(stderr)
		root := flags.String("root", "", "existing local corpus directory")
		controlDir := flags.String("control-dir", "", "dedicated protected Keelaryn control directory outside the corpus")
		maxBytes := flags.Int64("max-bytes", 4*1024*1024, "maximum bytes read from one supported text file")
		if err := flags.Parse(args[1:]); err != nil {
			return err
		}
		if *root == "" || *controlDir == "" {
			return errors.New("bootstrap-index requires --root and --control-dir")
		}
		result, err := localruntime.BootstrapProtectedIndex(context.Background(), localruntime.ProtectedIndexOptions{
			Root: *root, ControlDir: *controlDir,
			ObservedAt: time.Now().UTC(), MaxBytes: *maxBytes,
		})
		if err != nil {
			return err
		}
		return encodeJSON(stdout, result)

	case "search":
		flags := flag.NewFlagSet("search", flag.ContinueOnError)
		flags.SetOutput(stderr)
		controlDir := flags.String("control-dir", "", "existing protected Keelaryn control directory")
		query := flags.String("query", "", "literal all-terms search query")
		limit := flags.Int("limit", 20, "maximum search hits (1-100)")
		if err := flags.Parse(args[1:]); err != nil {
			return err
		}
		if *controlDir == "" || *query == "" {
			return errors.New("search requires --control-dir and --query")
		}
		hits, err := localruntime.QueryProtected(context.Background(), *controlDir, *query, *limit)
		if err != nil {
			return err
		}
		return encodeJSON(stdout, hits)

	case "context-bundle":
		flags := flag.NewFlagSet("context-bundle", flag.ContinueOnError)
		flags.SetOutput(stderr)
		root := flags.String("root", "", "existing local corpus directory")
		controlDir := flags.String("control-dir", "", "existing protected Keelaryn control directory")
		query := flags.String("query", "", "literal all-terms search query")
		reason := flags.String("reason", "", "explicit task reason for selected context")
		limit := flags.Int("limit", 20, "maximum search hits (1-100)")
		maxBytes := flags.Int64("max-bytes", 4*1024*1024, "maximum bytes read from one selected text file")
		if err := flags.Parse(args[1:]); err != nil {
			return err
		}
		if *root == "" || *controlDir == "" || *query == "" || *reason == "" {
			return errors.New("context-bundle requires --root, --control-dir, --query and --reason")
		}
		bundle, err := localruntime.BuildProtectedContext(context.Background(), localruntime.ProtectedContextOptions{
			Root: *root, ControlDir: *controlDir,
			Query: *query, Reason: *reason, Limit: *limit, MaxBytes: *maxBytes,
		})
		if err != nil {
			return err
		}
		return encodeJSON(stdout, bundle)

	case "mcp-stdio":
		flags := flag.NewFlagSet("mcp-stdio", flag.ContinueOnError)
		flags.SetOutput(stderr)
		root := flags.String("root", "", "existing local corpus directory fixed for this MCP server")
		controlDir := flags.String("control-dir", "", "existing protected Keelaryn control directory fixed for this MCP server")
		if err := flags.Parse(args[1:]); err != nil {
			return err
		}
		if flags.NArg() != 0 {
			return errors.New("mcp-stdio accepts no positional arguments")
		}
		if *root == "" || *controlDir == "" {
			return errors.New("mcp-stdio requires --root and --control-dir")
		}
		return runMCPStdio(context.Background(), mcpaccess.Options{
			Root: *root, ControlDir: *controlDir,
		})

	case "web-status":
		flags := flag.NewFlagSet("web-status", flag.ContinueOnError)
		flags.SetOutput(stderr)
		controlDir := flags.String("control-dir", "", "existing protected Keelaryn control directory")
		listen := flags.String("listen", webstatus.DefaultListenAddress, "literal loopback listen address")
		if err := flags.Parse(args[1:]); err != nil {
			return err
		}
		if flags.NArg() != 0 {
			return errors.New("web-status accepts no positional arguments")
		}
		if *controlDir == "" {
			return errors.New("web-status requires --control-dir")
		}
		ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
		defer stop()
		return runWebStatus(ctx, webstatus.Options{
			ControlDir: *controlDir,
			Listen:     *listen,
		}, stdout)

	case "google-drive-bootstrap":
		flags := flag.NewFlagSet("google-drive-bootstrap", flag.ContinueOnError)
		flags.SetOutput(stderr)
		controlDir := flags.String("control-dir", "", "dedicated protected Keelaryn control directory")
		accessTokenEnv := flags.String("access-token-env", "KEELARYN_GOOGLE_DRIVE_ACCESS_TOKEN", "environment variable containing a temporary Google OAuth access token")
		if err := flags.Parse(args[1:]); err != nil {
			return err
		}
		if flags.NArg() != 0 {
			return errors.New("google-drive-bootstrap accepts no positional arguments")
		}
		if *controlDir == "" {
			return errors.New("google-drive-bootstrap requires --control-dir")
		}
		envName := strings.TrimSpace(*accessTokenEnv)
		if envName == "" {
			return errors.New("google-drive-bootstrap requires non-empty --access-token-env")
		}
		accessToken := strings.TrimSpace(os.Getenv(envName))
		if accessToken == "" {
			return fmt.Errorf("google-drive-bootstrap requires a non-empty access token in environment variable %s", envName)
		}
		result, err := bootstrapGoogleDriveReadOnly(context.Background(), gdriveruntime.Options{
			ControlDir:  *controlDir,
			AccessToken: accessToken,
			ObservedAt:  time.Now().UTC(),
		})
		if err != nil {
			return err
		}
		return encodeJSON(stdout, result)

	case "doctor":
		flags := flag.NewFlagSet("doctor", flag.ContinueOnError)
		flags.SetOutput(stderr)
		controlDir := flags.String("control-dir", "", "existing protected Keelaryn control directory")
		if err := flags.Parse(args[1:]); err != nil {
			return err
		}
		if *controlDir == "" {
			return errors.New("doctor requires --control-dir")
		}
		report := doctor.Run(context.Background(), *controlDir)
		if err := encodeJSON(stdout, report); err != nil {
			return err
		}
		if !report.Passed() {
			return doctor.ErrFailed
		}
		return nil

	case "self-test":
		flags := flag.NewFlagSet("self-test", flag.ContinueOnError)
		flags.SetOutput(stderr)
		if err := flags.Parse(args[1:]); err != nil {
			return err
		}
		if flags.NArg() != 0 {
			return errors.New("self-test accepts no arguments")
		}
		report := selftest.Run(context.Background())
		if err := encodeJSON(stdout, report); err != nil {
			return err
		}
		if !report.Passed() {
			return selftest.ErrFailed
		}
		return nil

	default:
		return fmt.Errorf("unknown command %q", args[0])
	}
}

func encodeJSON(writer io.Writer, value any) error {
	encoder := json.NewEncoder(writer)
	encoder.SetIndent("", "  ")
	return encoder.Encode(value)
}
