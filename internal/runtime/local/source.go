package local

import (
	"context"
	"errors"
	"fmt"

	"github.com/efremov-aleksei-96/keelaryn/internal/ingest"
	providerlocalfs "github.com/efremov-aleksei-96/keelaryn/internal/provider/localfs"
	searchsqlite "github.com/efremov-aleksei-96/keelaryn/internal/search/sqlite"
	sqlitestate "github.com/efremov-aleksei-96/keelaryn/internal/state/sqlite"
)

var ErrAcceptedLocalSourceUnsupported = errors.New("accepted local source fingerprint is unsupported")

type acceptedLocalSource struct {
	receipt sqlitestate.LocalIngestCommitReceipt
}

func latestAcceptedLocalSource(
	ctx context.Context,
	state *sqlitestate.Store,
	root string,
) (acceptedLocalSource, bool, error) {
	if state == nil {
		return acceptedLocalSource{}, false, ErrRuntimeStateUnavailable
	}
	receipt, found, err := state.LatestBootstrapLocalIngestCommit(ctx, ProviderID, root)
	if err != nil {
		return acceptedLocalSource{}, false, err
	}
	if !found {
		return acceptedLocalSource{}, false, nil
	}
	if !receipt.Bootstrap || receipt.FingerprintVersion != ingest.LocalFSSnapshotFingerprintVersion {
		return acceptedLocalSource{}, false, fmt.Errorf(
			"%w: bootstrap=%t version=%q",
			ErrAcceptedLocalSourceUnsupported,
			receipt.Bootstrap,
			receipt.FingerprintVersion,
		)
	}
	return acceptedLocalSource{receipt: receipt}, true, nil
}

func (source acceptedLocalSource) boundary() searchsqlite.SourceBoundary {
	scan := source.receipt.Scan
	return searchsqlite.SourceBoundary{
		ProviderID:         scan.ProviderID,
		Root:               scan.Root,
		ScanID:             scan.ID,
		StartedAt:          scan.StartedAt,
		FingerprintVersion: source.receipt.FingerprintVersion,
		FingerprintSHA256:  source.receipt.FingerprintSHA256,
	}
}

func proveAcceptedLocalSource(
	ctx context.Context,
	state *sqlitestate.Store,
	provider *providerlocalfs.Provider,
	source acceptedLocalSource,
) error {
	return proveAcceptedLocalSourceAtRoot(ctx, state, provider, source, source.receipt.Scan.Root)
}

func proveAcceptedLocalSourceAtRoot(
	ctx context.Context,
	state *sqlitestate.Store,
	provider *providerlocalfs.Provider,
	source acceptedLocalSource,
	readRoot string,
) error {
	current, found, err := latestAcceptedLocalSource(ctx, state, source.receipt.Scan.Root)
	if err != nil {
		return err
	}
	if !found || !source.boundary().Equal(current.boundary()) {
		return searchsqlite.ErrSourceBoundaryMismatch
	}
	version, fingerprint, err := ingest.BootstrapLocalFSSnapshotFingerprintAtRoot(
		ctx,
		provider,
		readRoot,
		source.receipt.Scan.Root,
		source.receipt.Scan.StartedAt,
	)
	if err != nil {
		return fmt.Errorf("reconcile accepted local source: %w", err)
	}
	if version != source.receipt.FingerprintVersion || fingerprint != source.receipt.FingerprintSHA256 {
		return fmt.Errorf("%w: accepted local source fingerprint mismatch", ErrCorpusChanged)
	}
	return nil
}
