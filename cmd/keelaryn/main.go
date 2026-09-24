package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/provider/localfs"
)

func main() {
	if err := run(os.Args[1:], os.Stdout, os.Stderr); err != nil {
		fmt.Fprintln(os.Stderr, "keelaryn:", err)
		os.Exit(1)
	}
}

func run(args []string, stdout, stderr io.Writer) error {
	if len(args) == 0 {
		return errors.New("usage: keelaryn scan --root <directory>")
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

		encoder := json.NewEncoder(stdout)
		encoder.SetIndent("", "  ")
		return encoder.Encode(observations)
	default:
		return fmt.Errorf("unknown command %q", args[0])
	}
}
