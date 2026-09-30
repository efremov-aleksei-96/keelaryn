package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/doctor"
	"github.com/efremov-aleksei-96/keelaryn/internal/provider/localfs"
	localruntime "github.com/efremov-aleksei-96/keelaryn/internal/runtime/local"
)

func main() {
	if err := run(os.Args[1:], os.Stdout, os.Stderr); err != nil {
		if errors.Is(err, doctor.ErrFailed) {
			os.Exit(1)
		}
		fmt.Fprintln(os.Stderr, "keelaryn:", err)
		os.Exit(1)
	}
}

func run(args []string, stdout, stderr io.Writer) error {
	if len(args) == 0 {
		return errors.New("usage: keelaryn <scan|bootstrap-index|search|context-bundle|doctor> [options]")
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

	default:
		return fmt.Errorf("unknown command %q", args[0])
	}
}

func encodeJSON(writer io.Writer, value any) error {
	encoder := json.NewEncoder(writer)
	encoder.SetIndent("", "  ")
	return encoder.Encode(value)
}
