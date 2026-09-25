package remotehistory

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
)

type HistoryStreamID string
type HistoryCursor string
type ContinuationToken string

type Scope struct {
	ProviderID     corpus.ProviderID `json:"provider_id"`
	IdentityDomain string            `json:"identity_domain"`
	StreamID       HistoryStreamID   `json:"stream_id"`
	Root           string            `json:"root,omitempty"`
}

type RemoteObjectState struct {
	ObjectID corpus.ProviderObjectID `json:"object_id"`
	Locators []corpus.Locator        `json:"locators,omitempty"`
}

type ChangeKind string

const (
	ChangeUpsert  ChangeKind = "UPSERT"
	ChangeRemoved ChangeKind = "REMOVED"
)

type RemoteChange struct {
	Kind     ChangeKind              `json:"kind"`
	ObjectID corpus.ProviderObjectID `json:"object_id"`
	State    *RemoteObjectState       `json:"state,omitempty"`
}

type PageStatus string

const (
	PageMore                PageStatus = "MORE"
	PageTerminal            PageStatus = "TERMINAL"
	PageGap                 PageStatus = "GAP"
	PageInvalidCursor       PageStatus = "INVALID_CURSOR"
	PageScopeMismatch       PageStatus = "SCOPE_MISMATCH"
	PageInsufficientHistory PageStatus = "INSUFFICIENT_HISTORY"
)

type ChangePage struct {
	StreamID     HistoryStreamID   `json:"stream_id"`
	Status       PageStatus        `json:"status"`
	Changes      []RemoteChange    `json:"changes,omitempty"`
	Continuation ContinuationToken `json:"continuation,omitempty"`
	NextCursor   HistoryCursor     `json:"next_cursor,omitempty"`
}

type CycleStatus string

const (
	CycleComplete            CycleStatus = "COMPLETE"
	CycleGap                 CycleStatus = "GAP"
	CycleInvalidCursor       CycleStatus = "INVALID_CURSOR"
	CycleScopeMismatch       CycleStatus = "SCOPE_MISMATCH"
	CycleInsufficientHistory CycleStatus = "INSUFFICIENT_HISTORY"
	CycleInterrupted         CycleStatus = "INTERRUPTED"
)

type ChangeCycle struct {
	StreamID       HistoryStreamID              `json:"stream_id"`
	Status         CycleStatus                  `json:"status"`
	PreviousCursor HistoryCursor                `json:"previous_cursor"`
	NextCursor     HistoryCursor                `json:"next_cursor"`
	Changes        []RemoteChange               `json:"changes,omitempty"`
	Coverage       corpus.ProviderHistoryCoverage `json:"coverage"`
}

type BootstrapStatus string

const (
	BootstrapComplete            BootstrapStatus = "COMPLETE"
	BootstrapGap                 BootstrapStatus = "GAP"
	BootstrapScopeMismatch       BootstrapStatus = "SCOPE_MISMATCH"
	BootstrapInsufficientHistory BootstrapStatus = "INSUFFICIENT_HISTORY"
)

type BootstrapResult struct {
	StreamID HistoryStreamID                `json:"stream_id"`
	Status   BootstrapStatus                `json:"status"`
	Objects  []RemoteObjectState            `json:"objects,omitempty"`
	Cursor   HistoryCursor                  `json:"cursor,omitempty"`
	Coverage corpus.ProviderHistoryCoverage `json:"coverage"`
}

type Adapter interface {
	Bootstrap(context.Context, Scope) (BootstrapResult, error)
	ReadChanges(context.Context, Scope, HistoryCursor, ContinuationToken) (ChangePage, error)
}

var (
	ErrInvalidScope           = errors.New("invalid remote history scope")
	ErrInvalidHistoryPage     = errors.New("invalid remote history page")
	ErrInvalidBootstrapResult = errors.New("invalid remote history bootstrap result")
)

func ValidateScope(scope Scope) error {
	if scope.ProviderID == "" ||
		strings.TrimSpace(scope.IdentityDomain) == "" ||
		strings.TrimSpace(string(scope.StreamID)) == "" {
		return ErrInvalidScope
	}
	return nil
}

func ValidateBootstrap(scope Scope, result BootstrapResult) error {
	if err := ValidateScope(scope); err != nil {
		return err
	}
	if result.StreamID != scope.StreamID {
		return fmt.Errorf("%w: stream mismatch", ErrInvalidBootstrapResult)
	}
	switch result.Status {
	case BootstrapComplete:
		if result.Cursor == "" || result.Coverage != corpus.ProviderHistoryContinuous {
			return fmt.Errorf("%w: COMPLETE requires cursor + CONTINUOUS coverage", ErrInvalidBootstrapResult)
		}
		for _, object := range result.Objects {
			if err := validateObjectState(scope, object); err != nil {
				return err
			}
		}
	case BootstrapGap, BootstrapScopeMismatch, BootstrapInsufficientHistory:
		if result.Cursor != "" || result.Coverage != corpus.ProviderHistoryUnknown {
			return fmt.Errorf("%w: non-complete bootstrap cannot advance cursor/coverage", ErrInvalidBootstrapResult)
		}
	default:
		return fmt.Errorf("%w: status=%q", ErrInvalidBootstrapResult, result.Status)
	}
	return nil
}

func ConsumeChanges(ctx context.Context, adapter Adapter, scope Scope, committed HistoryCursor) (ChangeCycle, error) {
	if adapter == nil || committed == "" {
		return ChangeCycle{}, ErrInvalidScope
	}
	if err := ValidateScope(scope); err != nil {
		return ChangeCycle{}, err
	}

	cycle := ChangeCycle{
		StreamID:       scope.StreamID,
		Status:         CycleInterrupted,
		PreviousCursor: committed,
		NextCursor:     committed,
		Coverage:       corpus.ProviderHistoryUnknown,
	}
	var continuation ContinuationToken

	for {
		if err := ctx.Err(); err != nil {
			return cycle, err
		}
		page, err := adapter.ReadChanges(ctx, scope, committed, continuation)
		if err != nil {
			return cycle, err
		}
		if err := validatePage(scope, page); err != nil {
			return cycle, err
		}
		cycle.Changes = append(cycle.Changes, cloneChanges(page.Changes)...)

		switch page.Status {
		case PageMore:
			continuation = page.Continuation
		case PageTerminal:
			cycle.Status = CycleComplete
			cycle.NextCursor = page.NextCursor
			cycle.Coverage = corpus.ProviderHistoryContinuous
			return cycle, nil
		case PageGap:
			cycle.Status = CycleGap
			cycle.Changes = nil
			return cycle, nil
		case PageInvalidCursor:
			cycle.Status = CycleInvalidCursor
			cycle.Changes = nil
			return cycle, nil
		case PageScopeMismatch:
			cycle.Status = CycleScopeMismatch
			cycle.Changes = nil
			return cycle, nil
		case PageInsufficientHistory:
			cycle.Status = CycleInsufficientHistory
			cycle.Changes = nil
			return cycle, nil
		default:
			return cycle, ErrInvalidHistoryPage
		}
	}
}

func validatePage(scope Scope, page ChangePage) error {
	if page.StreamID != scope.StreamID {
		return fmt.Errorf("%w: stream mismatch", ErrInvalidHistoryPage)
	}
	for _, change := range page.Changes {
		if err := validateChange(scope, change); err != nil {
			return err
		}
	}

	switch page.Status {
	case PageMore:
		if page.Continuation == "" || page.NextCursor != "" {
			return fmt.Errorf("%w: MORE requires continuation only", ErrInvalidHistoryPage)
		}
	case PageTerminal:
		if page.Continuation != "" || page.NextCursor == "" {
			return fmt.Errorf("%w: TERMINAL requires committed next cursor only", ErrInvalidHistoryPage)
		}
	case PageGap, PageInvalidCursor, PageScopeMismatch, PageInsufficientHistory:
		if len(page.Changes) != 0 || page.Continuation != "" || page.NextCursor != "" {
			return fmt.Errorf("%w: failure page cannot carry changes/cursor advancement", ErrInvalidHistoryPage)
		}
	default:
		return fmt.Errorf("%w: status=%q", ErrInvalidHistoryPage, page.Status)
	}
	return nil
}

func validateChange(scope Scope, change RemoteChange) error {
	if change.ObjectID == "" {
		return fmt.Errorf("%w: empty object ID", ErrInvalidHistoryPage)
	}
	switch change.Kind {
	case ChangeUpsert:
		if change.State == nil || change.State.ObjectID != change.ObjectID {
			return fmt.Errorf("%w: invalid UPSERT state", ErrInvalidHistoryPage)
		}
		return validateObjectState(scope, *change.State)
	case ChangeRemoved:
		if change.State != nil {
			return fmt.Errorf("%w: REMOVED must not invent current state", ErrInvalidHistoryPage)
		}
		return nil
	default:
		return fmt.Errorf("%w: change kind=%q", ErrInvalidHistoryPage, change.Kind)
	}
}

func validateObjectState(scope Scope, object RemoteObjectState) error {
	if object.ObjectID == "" {
		return fmt.Errorf("%w: empty object ID", ErrInvalidHistoryPage)
	}
	for _, locator := range object.Locators {
		if locator.ProviderID != scope.ProviderID || strings.TrimSpace(locator.Path) == "" {
			return fmt.Errorf("%w: locator scope mismatch", ErrInvalidHistoryPage)
		}
	}
	return nil
}

func cloneChanges(src []RemoteChange) []RemoteChange {
	out := make([]RemoteChange, len(src))
	for i := range src {
		out[i] = src[i]
		if src[i].State != nil {
			state := *src[i].State
			state.Locators = append([]corpus.Locator(nil), src[i].State.Locators...)
			out[i].State = &state
		}
	}
	return out
}
