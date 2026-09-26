package gdrive

import (
	"context"
	"fmt"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
)

type TopologyHistoryStore interface {
	remotehistory.HistoryStateReader
	ActiveRemoteHistoryGeneration(context.Context, remotehistory.Scope) (remotehistory.HistoryGeneration, bool, error)
	StartGoogleDriveRemoteHistoryGeneration(
		context.Context,
		remotehistory.Scope,
		remotehistory.ScopePolicyFingerprint,
		BootstrapBundle,
		time.Time,
	) (remotehistory.HistoryGeneration, error)
	PublishGoogleDriveRemoteHistoryCycle(
		context.Context,
		remotehistory.HistoryGenerationID,
		remotehistory.Scope,
		remotehistory.ScopePolicyFingerprint,
		remotehistory.HistoryPublicationSequence,
		remotehistory.HistoryCursor,
		ChangeCycleBundle,
		time.Time,
	) (remotehistory.HistoryGeneration, error)
	CloseRemoteHistoryGeneration(
		context.Context,
		remotehistory.HistoryGenerationID,
		remotehistory.Scope,
		remotehistory.ScopePolicyFingerprint,
		remotehistory.HistoryPublicationSequence,
		remotehistory.HistoryCursor,
		remotehistory.ChangeCycle,
		time.Time,
	) (remotehistory.HistoryGeneration, error)
}

type TopologyCoordinator struct {
	store       TopologyHistoryStore
	adapter     *Adapter
	scope       remotehistory.Scope
	fingerprint remotehistory.ScopePolicyFingerprint
}

func NewTopologyCoordinator(
	store TopologyHistoryStore,
	adapter *Adapter,
	scope remotehistory.Scope,
	fingerprint remotehistory.ScopePolicyFingerprint,
) (*TopologyCoordinator, error) {
	if store == nil || adapter == nil {
		return nil, remotehistory.ErrInvalidCoordinator
	}
	if err := remotehistory.ValidateScope(scope); err != nil {
		return nil, err
	}
	if err := remotehistory.ValidateScopePolicyFingerprint(fingerprint); err != nil {
		return nil, err
	}
	if scope.ProviderID != ProviderID || !adapter.matches(scope) {
		return nil, remotehistory.ErrCoordinatorScopeMismatch
	}
	return &TopologyCoordinator{
		store:       store,
		adapter:     adapter,
		scope:       scope,
		fingerprint: fingerprint,
	}, nil
}

func (c *TopologyCoordinator) Bootstrap(
	ctx context.Context,
	committedAt time.Time,
) (remotehistory.CoordinatorResult, error) {
	if committedAt.IsZero() {
		return remotehistory.CoordinatorResult{}, remotehistory.ErrInvalidCoordinator
	}
	active, found, err := c.store.ActiveRemoteHistoryGeneration(ctx, c.scope)
	if err != nil {
		return remotehistory.CoordinatorResult{}, err
	}
	if found {
		if active.Scope != c.scope {
			return remotehistory.CoordinatorResult{}, remotehistory.ErrCoordinatorScopeMismatch
		}
		if active.ScopePolicyFingerprint != c.fingerprint {
			return remotehistory.CoordinatorResult{}, remotehistory.ErrCoordinatorPolicyMismatch
		}
		return remotehistory.CoordinatorResult{
			Status:     remotehistory.CoordinatorAlreadyActive,
			Generation: active,
		}, nil
	}

	bundle, err := c.adapter.BootstrapWithTopology(ctx, c.scope)
	if err != nil {
		return remotehistory.CoordinatorResult{Status: remotehistory.CoordinatorNoMutation}, err
	}
	if bundle.History.Status != remotehistory.BootstrapComplete {
		return remotehistory.CoordinatorResult{
			Status:          remotehistory.CoordinatorNoMutation,
			BootstrapStatus: bundle.History.Status,
		}, nil
	}

	generation, err := c.store.StartGoogleDriveRemoteHistoryGeneration(
		ctx, c.scope, c.fingerprint, bundle, committedAt,
	)
	if err != nil {
		return remotehistory.CoordinatorResult{Status: remotehistory.CoordinatorNoMutation}, err
	}
	return remotehistory.CoordinatorResult{
		Status:          remotehistory.CoordinatorBootstrapCommitted,
		Generation:      generation,
		BootstrapStatus: bundle.History.Status,
	}, nil
}

func (c *TopologyCoordinator) Advance(
	ctx context.Context,
	expected remotehistory.ExpectedHistoryPrestate,
	committedAt time.Time,
) (remotehistory.CoordinatorResult, error) {
	if committedAt.IsZero() {
		return remotehistory.CoordinatorResult{}, remotehistory.ErrInvalidExpectedHistoryState
	}

	generation, ready, err := remotehistory.ReconcileExpectedHistoryPrestate(
		ctx, c.store, c.scope, c.fingerprint, expected,
	)
	if err != nil {
		return remotehistory.CoordinatorResult{}, err
	}
	if !ready {
		return remotehistory.CoordinatorResult{
			Status:     remotehistory.CoordinatorPrestateChanged,
			Generation: generation,
		}, nil
	}

	bundle, err := ConsumeChangesWithTopology(ctx, c.adapter, c.scope, expected.Cursor)
	if err != nil {
		return remotehistory.CoordinatorResult{
			Status:      remotehistory.CoordinatorNoMutation,
			Generation:  generation,
			CycleStatus: bundle.History.Status,
		}, err
	}

	switch bundle.History.Status {
	case remotehistory.CycleComplete:
		updated, err := c.store.PublishGoogleDriveRemoteHistoryCycle(
			ctx,
			expected.GenerationID,
			c.scope,
			c.fingerprint,
			expected.Sequence,
			expected.Cursor,
			bundle,
			committedAt,
		)
		if err != nil {
			return remotehistory.CoordinatorResult{
				Status:      remotehistory.CoordinatorNoMutation,
				Generation:  generation,
				CycleStatus: bundle.History.Status,
			}, err
		}
		return remotehistory.CoordinatorResult{
			Status:      remotehistory.CoordinatorPublished,
			Generation:  updated,
			CycleStatus: bundle.History.Status,
		}, nil

	case remotehistory.CycleGap,
		remotehistory.CycleInvalidCursor,
		remotehistory.CycleScopeMismatch,
		remotehistory.CycleInsufficientHistory:
		closed, err := c.store.CloseRemoteHistoryGeneration(
			ctx,
			expected.GenerationID,
			c.scope,
			c.fingerprint,
			expected.Sequence,
			expected.Cursor,
			bundle.History,
			committedAt,
		)
		if err != nil {
			return remotehistory.CoordinatorResult{
				Status:      remotehistory.CoordinatorNoMutation,
				Generation:  generation,
				CycleStatus: bundle.History.Status,
			}, err
		}
		return remotehistory.CoordinatorResult{
			Status:      remotehistory.CoordinatorClosed,
			Generation:  closed,
			CycleStatus: bundle.History.Status,
		}, nil

	case remotehistory.CycleInterrupted:
		return remotehistory.CoordinatorResult{
			Status:      remotehistory.CoordinatorNoMutation,
			Generation:  generation,
			CycleStatus: bundle.History.Status,
		}, fmt.Errorf("%w: interrupted cycle returned without provider error", remotehistory.ErrInvalidHistoryPage)

	default:
		return remotehistory.CoordinatorResult{
			Status:      remotehistory.CoordinatorNoMutation,
			Generation:  generation,
			CycleStatus: bundle.History.Status,
		}, fmt.Errorf("%w: cycle status=%q", remotehistory.ErrInvalidHistoryPage, bundle.History.Status)
	}
}
