package remotehistory

import (
	"context"
	"errors"
	"fmt"
	"time"
)

type CoordinatorStatus string

const (
	CoordinatorBootstrapCommitted CoordinatorStatus = "BOOTSTRAP_COMMITTED"
	CoordinatorAlreadyActive      CoordinatorStatus = "ALREADY_ACTIVE"
	CoordinatorPrestateChanged    CoordinatorStatus = "PRESTATE_CHANGED"
	CoordinatorPublished          CoordinatorStatus = "PUBLISHED"
	CoordinatorClosed             CoordinatorStatus = "CLOSED"
	CoordinatorNoMutation         CoordinatorStatus = "NO_MUTATION"
)

type ExpectedHistoryPrestate struct {
	GenerationID HistoryGenerationID         `json:"generation_id"`
	Sequence     HistoryPublicationSequence `json:"sequence"`
	Cursor       HistoryCursor              `json:"cursor"`
}

type CoordinatorResult struct {
	Status          CoordinatorStatus `json:"status"`
	Generation      HistoryGeneration `json:"generation,omitempty"`
	BootstrapStatus BootstrapStatus   `json:"bootstrap_status,omitempty"`
	CycleStatus     CycleStatus       `json:"cycle_status,omitempty"`
}

type DurableHistoryStore interface {
	ActiveRemoteHistoryGeneration(context.Context, Scope) (HistoryGeneration, bool, error)
	RemoteHistoryGeneration(context.Context, HistoryGenerationID) (HistoryGeneration, error)
	StartRemoteHistoryGeneration(context.Context, Scope, ScopePolicyFingerprint, BootstrapResult, time.Time) (HistoryGeneration, error)
	PublishRemoteHistoryCycle(context.Context, HistoryGenerationID, Scope, ScopePolicyFingerprint, HistoryPublicationSequence, HistoryCursor, ChangeCycle, time.Time) (HistoryGeneration, error)
	CloseRemoteHistoryGeneration(context.Context, HistoryGenerationID, Scope, ScopePolicyFingerprint, HistoryPublicationSequence, HistoryCursor, ChangeCycle, time.Time) (HistoryGeneration, error)
}

var (
	ErrInvalidCoordinator           = errors.New("invalid remote history coordinator")
	ErrCoordinatorScopeMismatch     = errors.New("remote history coordinator scope mismatch")
	ErrCoordinatorPolicyMismatch    = errors.New("remote history coordinator policy mismatch")
	ErrInvalidExpectedHistoryState  = errors.New("invalid expected remote history prestate")
)

type Coordinator struct {
	store       DurableHistoryStore
	adapter     Adapter
	scope       Scope
	fingerprint ScopePolicyFingerprint
}

func NewCoordinator(store DurableHistoryStore, adapter Adapter, scope Scope, fingerprint ScopePolicyFingerprint) (*Coordinator, error) {
	if store == nil || adapter == nil {
		return nil, ErrInvalidCoordinator
	}
	if err := ValidateScope(scope); err != nil {
		return nil, err
	}
	if err := ValidateScopePolicyFingerprint(fingerprint); err != nil {
		return nil, err
	}
	return &Coordinator{
		store:       store,
		adapter:     adapter,
		scope:       scope,
		fingerprint: fingerprint,
	}, nil
}

type HistoryStateReader interface {
	RemoteHistoryGeneration(context.Context, HistoryGenerationID) (HistoryGeneration, error)
}

func ReconcileExpectedHistoryPrestate(
	ctx context.Context,
	store HistoryStateReader,
	scope Scope,
	fingerprint ScopePolicyFingerprint,
	expected ExpectedHistoryPrestate,
) (HistoryGeneration, bool, error) {
	if store == nil ||
		expected.GenerationID == "" ||
		expected.Sequence == 0 ||
		expected.Cursor == "" {
		return HistoryGeneration{}, false, ErrInvalidExpectedHistoryState
	}
	generation, err := store.RemoteHistoryGeneration(ctx, expected.GenerationID)
	if err != nil {
		return HistoryGeneration{}, false, err
	}
	if generation.Scope != scope {
		return HistoryGeneration{}, false, ErrCoordinatorScopeMismatch
	}
	if generation.ScopePolicyFingerprint != fingerprint {
		return HistoryGeneration{}, false, ErrCoordinatorPolicyMismatch
	}
	if generation.Status != HistoryGenerationActive ||
		generation.CurrentSequence != expected.Sequence ||
		generation.CommittedCursor != expected.Cursor {
		return generation, false, nil
	}
	return generation, true, nil
}

// Bootstrap publishes at most one durable write. If an ACTIVE generation
// already exists, it returns that prestate without calling the provider.
func (c *Coordinator) Bootstrap(ctx context.Context, committedAt time.Time) (CoordinatorResult, error) {
	if committedAt.IsZero() {
		return CoordinatorResult{}, ErrInvalidCoordinator
	}
	active, found, err := c.store.ActiveRemoteHistoryGeneration(ctx, c.scope)
	if err != nil {
		return CoordinatorResult{}, err
	}
	if found {
		if active.Scope != c.scope {
			return CoordinatorResult{}, ErrCoordinatorScopeMismatch
		}
		if active.ScopePolicyFingerprint != c.fingerprint {
			return CoordinatorResult{}, ErrCoordinatorPolicyMismatch
		}
		return CoordinatorResult{
			Status:     CoordinatorAlreadyActive,
			Generation: active,
		}, nil
	}

	bootstrap, err := c.adapter.Bootstrap(ctx, c.scope)
	if err != nil {
		return CoordinatorResult{Status: CoordinatorNoMutation}, err
	}
	if err := ValidateBootstrap(c.scope, bootstrap); err != nil {
		return CoordinatorResult{Status: CoordinatorNoMutation}, err
	}
	if bootstrap.Status != BootstrapComplete {
		return CoordinatorResult{
			Status:          CoordinatorNoMutation,
			BootstrapStatus: bootstrap.Status,
		}, nil
	}

	generation, err := c.store.StartRemoteHistoryGeneration(
		ctx, c.scope, c.fingerprint, bootstrap, committedAt,
	)
	if err != nil {
		return CoordinatorResult{Status: CoordinatorNoMutation}, err
	}
	return CoordinatorResult{
		Status:          CoordinatorBootstrapCommitted,
		Generation:      generation,
		BootstrapStatus: bootstrap.Status,
	}, nil
}

// Advance requires an exact caller-captured durable prestate before any
// provider read. A lost previous write response therefore reconciles as
// PRESTATE_CHANGED rather than silently consuming the next provider cycle.
func (c *Coordinator) Advance(ctx context.Context, expected ExpectedHistoryPrestate, committedAt time.Time) (CoordinatorResult, error) {
	if expected.GenerationID == "" || expected.Sequence == 0 || expected.Cursor == "" || committedAt.IsZero() {
		return CoordinatorResult{}, ErrInvalidExpectedHistoryState
	}

	generation, ready, err := ReconcileExpectedHistoryPrestate(
		ctx, c.store, c.scope, c.fingerprint, expected,
	)
	if err != nil {
		return CoordinatorResult{}, err
	}
	if !ready {
		return CoordinatorResult{
			Status:     CoordinatorPrestateChanged,
			Generation: generation,
		}, nil
	}

	cycle, err := ConsumeChanges(ctx, c.adapter, c.scope, expected.Cursor)
	if err != nil {
		return CoordinatorResult{
			Status:     CoordinatorNoMutation,
			Generation: generation,
			CycleStatus: cycle.Status,
		}, err
	}

	switch cycle.Status {
	case CycleComplete:
		updated, err := c.store.PublishRemoteHistoryCycle(
			ctx,
			expected.GenerationID,
			c.scope,
			c.fingerprint,
			expected.Sequence,
			expected.Cursor,
			cycle,
			committedAt,
		)
		if err != nil {
			return CoordinatorResult{Status: CoordinatorNoMutation, Generation: generation, CycleStatus: cycle.Status}, err
		}
		return CoordinatorResult{
			Status:      CoordinatorPublished,
			Generation:  updated,
			CycleStatus: cycle.Status,
		}, nil

	case CycleGap, CycleInvalidCursor, CycleScopeMismatch, CycleInsufficientHistory:
		closed, err := c.store.CloseRemoteHistoryGeneration(
			ctx,
			expected.GenerationID,
			c.scope,
			c.fingerprint,
			expected.Sequence,
			expected.Cursor,
			cycle,
			committedAt,
		)
		if err != nil {
			return CoordinatorResult{Status: CoordinatorNoMutation, Generation: generation, CycleStatus: cycle.Status}, err
		}
		return CoordinatorResult{
			Status:      CoordinatorClosed,
			Generation:  closed,
			CycleStatus: cycle.Status,
		}, nil

	case CycleInterrupted:
		return CoordinatorResult{
			Status:      CoordinatorNoMutation,
			Generation:  generation,
			CycleStatus: cycle.Status,
		}, fmt.Errorf("%w: interrupted cycle returned without provider error", ErrInvalidHistoryPage)

	default:
		return CoordinatorResult{
			Status:      CoordinatorNoMutation,
			Generation:  generation,
			CycleStatus: cycle.Status,
		}, fmt.Errorf("%w: cycle status=%q", ErrInvalidHistoryPage, cycle.Status)
	}
}
