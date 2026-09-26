package gdrive

import (
	"context"
	"fmt"
	"sort"
	"strings"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
)

func (a *Adapter) BootstrapWithTopology(ctx context.Context, scope remotehistory.Scope) (BootstrapBundle, error) {
	if !a.matches(scope) {
		return BootstrapBundle{History: bootstrapFailure(scope.StreamID, remotehistory.BootstrapScopeMismatch)}, nil
	}

	fence, err := a.client.StartPageToken(ctx, a.config)
	if err != nil {
		history, mappedErr := a.bootstrapClientFailure(scope.StreamID, err)
		return BootstrapBundle{History: history}, mappedErr
	}
	if strings.TrimSpace(fence) == "" {
		return BootstrapBundle{}, fmt.Errorf("%w: empty start page token", ErrInvalidClientResponse)
	}

	files, err := a.enumerateFiles(ctx)
	if err != nil {
		history, mappedErr := a.bootstrapClientFailure(scope.StreamID, err)
		return BootstrapBundle{History: history}, mappedErr
	}
	objects := a.initialObjects(files)
	topology, err := topologyForObjects(files, objects)
	if err != nil {
		return BootstrapBundle{}, err
	}

	cursor, err := a.catchUpWithTopology(ctx, fence, objects, topology)
	if err != nil {
		history, mappedErr := a.bootstrapClientFailure(scope.StreamID, err)
		return BootstrapBundle{History: history}, mappedErr
	}

	history := remotehistory.BootstrapResult{
		StreamID: scope.StreamID,
		Status:   remotehistory.BootstrapComplete,
		Objects:  sortedObjects(objects),
		Cursor:   remotehistory.HistoryCursor(cursor),
		Coverage: corpus.ProviderHistoryContinuous,
	}
	if err := remotehistory.ValidateBootstrap(scope, history); err != nil {
		return BootstrapBundle{}, err
	}
	out := BootstrapBundle{
		History:  history,
		Topology: sortedTopologyStates(topology),
	}
	if err := validateBootstrapBundle(out); err != nil {
		return BootstrapBundle{}, err
	}
	return out, nil
}

func (a *Adapter) ReadChangesWithTopology(
	ctx context.Context,
	scope remotehistory.Scope,
	committed remotehistory.HistoryCursor,
	continuation remotehistory.ContinuationToken,
) (ChangePageBundle, error) {
	if !a.matches(scope) {
		return ChangePageBundle{
			History: remotehistory.ChangePage{
				StreamID: scope.StreamID,
				Status:   remotehistory.PageScopeMismatch,
			},
		}, nil
	}
	if committed == "" {
		return ChangePageBundle{}, remotehistory.ErrInvalidScope
	}

	token := string(committed)
	if continuation != "" {
		token = string(continuation)
	}
	page, err := a.client.ListChanges(ctx, a.config, token)
	if err != nil {
		if status, ok := pageStatusForClientError(err); ok {
			return ChangePageBundle{
				History: remotehistory.ChangePage{StreamID: scope.StreamID, Status: status},
			}, nil
		}
		return ChangePageBundle{}, err
	}

	changes, topology, err := a.convertChangesWithTopology(page.Changes)
	if err != nil {
		return ChangePageBundle{}, err
	}
	hasNext := strings.TrimSpace(page.NextPageToken) != ""
	hasTerminal := strings.TrimSpace(page.NewStartPageToken) != ""
	if hasNext == hasTerminal {
		return ChangePageBundle{}, fmt.Errorf("%w: expected exactly one next or terminal token", ErrInvalidClientResponse)
	}

	history := remotehistory.ChangePage{
		StreamID: scope.StreamID,
		Changes:  changes,
	}
	if hasNext {
		history.Status = remotehistory.PageMore
		history.Continuation = remotehistory.ContinuationToken(page.NextPageToken)
	} else {
		history.Status = remotehistory.PageTerminal
		history.NextCursor = remotehistory.HistoryCursor(page.NewStartPageToken)
	}
	out := ChangePageBundle{History: history, Topology: topology}
	if err := validateChangePageBundle(out); err != nil {
		return ChangePageBundle{}, err
	}
	return out, nil
}

func ConsumeChangesWithTopology(
	ctx context.Context,
	adapter *Adapter,
	scope remotehistory.Scope,
	committed remotehistory.HistoryCursor,
) (ChangeCycleBundle, error) {
	if adapter == nil || committed == "" {
		return ChangeCycleBundle{}, remotehistory.ErrInvalidScope
	}
	cycle := remotehistory.ChangeCycle{
		StreamID:       scope.StreamID,
		Status:         remotehistory.CycleInterrupted,
		PreviousCursor: committed,
		NextCursor:     committed,
		Coverage:       corpus.ProviderHistoryUnknown,
	}
	var topology []TopologyState
	var continuation remotehistory.ContinuationToken

	for {
		if err := ctx.Err(); err != nil {
			return ChangeCycleBundle{History: cycle}, err
		}
		page, err := adapter.ReadChangesWithTopology(ctx, scope, committed, continuation)
		if err != nil {
			return ChangeCycleBundle{History: cycle}, err
		}
		if len(page.History.Changes) != len(page.Topology) {
			return ChangeCycleBundle{History: cycle}, fmt.Errorf("%w: topology/change alignment", ErrInvalidTopologyState)
		}
		cycle.Changes = append(cycle.Changes, page.History.Changes...)
		topology = append(topology, page.Topology...)

		switch page.History.Status {
		case remotehistory.PageMore:
			continuation = page.History.Continuation
		case remotehistory.PageTerminal:
			cycle.Status = remotehistory.CycleComplete
			cycle.NextCursor = page.History.NextCursor
			cycle.Coverage = corpus.ProviderHistoryContinuous
			return ChangeCycleBundle{History: cycle, Topology: topology}, nil
		case remotehistory.PageGap:
			cycle.Status = remotehistory.CycleGap
		case remotehistory.PageInvalidCursor:
			cycle.Status = remotehistory.CycleInvalidCursor
		case remotehistory.PageScopeMismatch:
			cycle.Status = remotehistory.CycleScopeMismatch
		case remotehistory.PageInsufficientHistory:
			cycle.Status = remotehistory.CycleInsufficientHistory
		default:
			return ChangeCycleBundle{History: cycle}, remotehistory.ErrInvalidHistoryPage
		}
		cycle.Changes = nil
		return ChangeCycleBundle{History: cycle}, nil
	}
}

func (a *Adapter) catchUpWithTopology(
	ctx context.Context,
	fence string,
	objects map[corpus.ProviderObjectID]remotehistory.RemoteObjectState,
	topology map[corpus.ProviderObjectID]TopologyState,
) (string, error) {
	seen := map[string]struct{}{fence: {}}
	token := fence
	for {
		page, err := a.client.ListChanges(ctx, a.config, token)
		if err != nil {
			return "", err
		}
		changes, topologyChanges, err := a.convertChangesWithTopology(page.Changes)
		if err != nil {
			return "", err
		}
		for i, change := range changes {
			switch change.Kind {
			case remotehistory.ChangeUpsert:
				objects[change.ObjectID] = *change.State
				topology[change.ObjectID] = topologyChanges[i]
			case remotehistory.ChangeRemoved:
				delete(objects, change.ObjectID)
				delete(topology, change.ObjectID)
			default:
				return "", remotehistory.ErrInvalidHistoryPage
			}
		}

		next := strings.TrimSpace(page.NextPageToken)
		terminal := strings.TrimSpace(page.NewStartPageToken)
		if next != "" && terminal != "" || next == "" && terminal == "" {
			return "", fmt.Errorf("%w: expected exactly one next or terminal token", ErrInvalidClientResponse)
		}
		if terminal != "" {
			return terminal, nil
		}
		if _, duplicate := seen[next]; duplicate {
			return "", fmt.Errorf("%w: repeated change page token", ErrInvalidClientResponse)
		}
		seen[next] = struct{}{}
		token = next
	}
}

func (a *Adapter) convertChangesWithTopology(records []ChangeRecord) ([]remotehistory.RemoteChange, []TopologyState, error) {
	changes := make([]remotehistory.RemoteChange, 0, len(records))
	topology := make([]TopologyState, 0, len(records))
	for _, record := range records {
		if record.ChangeType != "" && record.ChangeType != "file" {
			continue
		}
		id := strings.TrimSpace(record.FileID)
		if id == "" && record.File != nil {
			id = strings.TrimSpace(record.File.ID)
		}
		if id == "" {
			return nil, nil, fmt.Errorf("%w: file change without file ID", ErrInvalidClientResponse)
		}
		objectID := corpus.ProviderObjectID(id)

		if record.Removed {
			changes = append(changes, remotehistory.RemoteChange{Kind: remotehistory.ChangeRemoved, ObjectID: objectID})
			topology = append(topology, unavailableTopologyState(objectID))
			continue
		}
		if record.File == nil || strings.TrimSpace(record.File.ID) != id {
			return nil, nil, fmt.Errorf("%w: current file state missing or ID mismatch", ErrInvalidClientResponse)
		}
		if record.File.Trashed || !a.fileBelongsToStream(*record.File) {
			changes = append(changes, remotehistory.RemoteChange{Kind: remotehistory.ChangeRemoved, ObjectID: objectID})
			topology = append(topology, unavailableTopologyState(objectID))
			continue
		}

		historyState := a.objectState(id)
		topologyState, err := topologyStateFromFile(*record.File)
		if err != nil {
			return nil, nil, err
		}
		changes = append(changes, remotehistory.RemoteChange{
			Kind:     remotehistory.ChangeUpsert,
			ObjectID: objectID,
			State:    &historyState,
		})
		topology = append(topology, topologyState)
	}
	return changes, topology, nil
}

func topologyForObjects(
	files []FileRecord,
	objects map[corpus.ProviderObjectID]remotehistory.RemoteObjectState,
) (map[corpus.ProviderObjectID]TopologyState, error) {
	out := make(map[corpus.ProviderObjectID]TopologyState, len(objects))
	for _, file := range files {
		objectID := corpus.ProviderObjectID(strings.TrimSpace(file.ID))
		if _, ok := objects[objectID]; !ok {
			continue
		}
		state, err := topologyStateFromFile(file)
		if err != nil {
			return nil, err
		}
		out[objectID] = state
	}
	if len(out) != len(objects) {
		return nil, fmt.Errorf("%w: bootstrap topology missing current object", ErrInvalidTopologyState)
	}
	return out, nil
}

func topologyStateFromFile(file FileRecord) (TopologyState, error) {
	objectID := corpus.ProviderObjectID(strings.TrimSpace(file.ID))
	if objectID == "" {
		return TopologyState{}, ErrInvalidTopologyState
	}
	state := TopologyState{
		ObjectID: objectID,
		Presence: TopologyPresent,
		DriveID:  strings.TrimSpace(file.DriveID),
	}
	switch len(file.Parents) {
	case 0:
		state.ParentKnowledge = ParentUnknown
	case 1:
		state.ParentKnowledge = ParentKnown
		state.ParentObjectID = corpus.ProviderObjectID(strings.TrimSpace(file.Parents[0]))
	default:
		return TopologyState{}, fmt.Errorf("%w: object %s has %d parents", ErrInvalidTopologyState, objectID, len(file.Parents))
	}
	if err := ValidateTopologyState(state); err != nil {
		return TopologyState{}, err
	}
	return state, nil
}

func unavailableTopologyState(objectID corpus.ProviderObjectID) TopologyState {
	return TopologyState{
		ObjectID:        objectID,
		Presence:        TopologyUnavailable,
		ParentKnowledge: ParentUnavailable,
	}
}

func sortedTopologyStates(states map[corpus.ProviderObjectID]TopologyState) []TopologyState {
	ids := make([]string, 0, len(states))
	for id := range states {
		ids = append(ids, string(id))
	}
	sort.Strings(ids)
	out := make([]TopologyState, 0, len(ids))
	for _, id := range ids {
		out = append(out, states[corpus.ProviderObjectID(id)])
	}
	return out
}

func validateBootstrapBundle(bundle BootstrapBundle) error {
	if bundle.History.Status != remotehistory.BootstrapComplete {
		if len(bundle.Topology) != 0 {
			return ErrInvalidTopologyState
		}
		return nil
	}
	if len(bundle.History.Objects) != len(bundle.Topology) {
		return ErrInvalidTopologyState
	}
	for i := range bundle.History.Objects {
		if bundle.History.Objects[i].ObjectID != bundle.Topology[i].ObjectID {
			return ErrInvalidTopologyState
		}
		if err := ValidateTopologyState(bundle.Topology[i]); err != nil {
			return err
		}
	}
	return nil
}

func validateChangePageBundle(bundle ChangePageBundle) error {
	if len(bundle.History.Changes) != len(bundle.Topology) {
		return ErrInvalidTopologyState
	}
	for i, change := range bundle.History.Changes {
		state := bundle.Topology[i]
		if change.ObjectID != state.ObjectID {
			return ErrInvalidTopologyState
		}
		switch change.Kind {
		case remotehistory.ChangeUpsert:
			if state.Presence != TopologyPresent {
				return ErrInvalidTopologyState
			}
		case remotehistory.ChangeRemoved:
			if state.Presence != TopologyUnavailable {
				return ErrInvalidTopologyState
			}
		default:
			return ErrInvalidTopologyState
		}
		if err := ValidateTopologyState(state); err != nil {
			return err
		}
	}
	return nil
}
