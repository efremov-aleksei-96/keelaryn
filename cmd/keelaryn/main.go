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
	"github.com/efremov-aleksei-96/keelaryn/internal/provider/localfs"
	localruntime "github.com/efremov-aleksei-96/keelaryn/internal/runtime/local"
)

func main() {
	if err := run(os.Args[1:], os.Stdout, os.Stderr); err != nil {
		fmt.Fprintln(os.Stderr, "keelaryn:", err)
		os.Exit(1)
	}
}

func run(args []string, stdout, stderr io.Writer) error {
	if len(args) == 0 {
		return errors.New("usage: keelaryn <scan|bootstrap-index|search> [options]")
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
		stateDB := flags.String("state-db", "", "runtime-local Keelaryn state database path outside the corpus")
		searchDB := flags.String("search-db", "", "runtime-local derived search database path outside the corpus")
		maxBytes := flags.Int64("max-bytes", 4*1024*1024, "maximum bytes read from one supported text file")
		if err := flags.Parse(args[1:]); err != nil {
			return err
		}
		if *root == "" || *stateDB == "" || *searchDB == "" {
			return errors.New("bootstrap-index requires --root, --state-db and --search-db")
		}
		result, err := localruntime.BootstrapIndex(context.Background(), localruntime.IndexOptions{
			Root: *root, StateDB: *stateDB, SearchDB: *searchDB,
			ObservedAt: time.Now().UTC(), MaxBytes: *maxBytes,
		})
		if err != nil {
			return err
		}
		return encodeJSON(stdout, result)

	case "search":
		flags := flag.NewFlagSet("search", flag.ContinueOnError)
		flags.SetOutput(stderr)
		searchDB := flags.String("search-db", "", "runtime-local derived search database path")
		query := flags.String("query", "", "literal all-terms search query")
		limit := flags.Int("limit", 20, "maximum search hits (1-100)")
		if err := flags.Parse(args[1:]); err != nil {
			return err
		}
		if *searchDB == "" || *query == "" {
			return errors.New("search requires --search-db and --query")
		}
		hits, err := localruntime.Query(context.Background(), *searchDB, *query, *limit)
		if err != nil {
			return err
		}
		return encodeJSON(stdout, hits)

	default:
		return fmt.Errorf("unknown command %q", args[0])
	}
}

func encodeJSON(writer io.Writer, value any) error {
	encoder := json.NewEncoder(writer)
	encoder.SetIndent("", "  ")
	return encoder.Encode(value)
}
