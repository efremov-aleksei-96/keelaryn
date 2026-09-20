# Operation Runtime v1

## Purpose

Operation Runtime is the durable execution/status boundary for long-running Keelaryn administrative work. It exists so production work does not depend on a ChatGPT stream, browser tab, PowerShell window or SSH connection remaining alive.

This runtime is infrastructure for future remote-autonomous development and production control. It is not itself permission to perform a production mutation.

## Core properties

Every operation receives one opaque 32-hex operation ID and a private owner-controlled directory:

```text
/var/lib/keelaryn/operations/<operation-id>/
    state.json
    progress.jsonl
    handoff.json
    result.json      # only after terminal completion
```

The runtime root and operation directories are mode `0700`; durable JSON/JSONL files are mode `0600`.

`LATEST` is a private file containing only the latest operation ID. Symlinks are not accepted as durable authority.

All runtime status is sanitized. The schema deliberately permits tokens, counters, source commit identity and timestamps but no free-form exception text, OAuth material, Drive IDs or arbitrary filesystem paths.

## Execution state

```text
CREATED -> RUNNING -> SUCCEEDED
                  -> FAILED
                  -> RECOVERY_REQUIRED
```

`RECOVERY_REQUIRED` is terminal for the operation runner. Recovery is a separate read-only reconciliation step; the original mutation is never blindly retried.

A running operation whose durable heartbeat becomes older than its configured timeout is reported as `STALLED` without rewriting durable state. If the operation had crossed the mutation commit boundary, the only recommended next action is `READ_ONLY_RECONCILE`.

## Mutation boundaries

Mutation-capable operations advance only one boundary at a time:

```text
MUTATION_NOT_STARTED
    -> PRECOMMIT_VERIFIED
    -> COMMITTING
    -> COMMITTED
    -> POSTCOMMIT_VERIFYING
    -> VERIFIED
```

A transition may stay at the current boundary or advance by exactly one boundary. Skipping or moving backwards fails closed.

Failure or loss of process certainty from `COMMITTING`, `COMMITTED` or `POSTCOMMIT_VERIFYING` requires reconciliation. A successful mutation operation must either remain a proven no-op at `MUTATION_NOT_STARTED` or reach `VERIFIED`.

## Progress and heartbeat

Operation Runtime composes the existing sanitized `GateProgressJournal`.

The journal is append-only and emits heartbeat records while work is running. `keelaryn-operation status` combines durable state with the newest progress timestamp, while `keelaryn-operation watch` provides a stable UI for observing progress without controlling the worker process.

The viewer is deliberately separate from the worker. Closing the viewer must not terminate the operation.

## Durable handoff

Every durable state write refreshes `handoff.json`. The handoff contains only:

- operation ID;
- operation token;
- exact source commit;
- execution state;
- mutation boundary;
- phase;
- next permitted action.

This is the machine-readable continuation primitive. Repository-level handoffs may summarize it, but chat memory is never authoritative.

## Detached execution and remote-control roadmap

v1 establishes the durable local runtime, status/watch surface, heartbeat integration and recovery semantics.

The next layer is the VPS Operation Agent:

1. run workers detached under systemd;
2. poll an authenticated GitHub operation-request channel using an outbound VPS connection;
3. accept only strict-schema allowlisted operations from exact qualified source;
4. never execute arbitrary shell supplied by GitHub;
5. publish sanitized durable results for remote inspection;
6. require explicit human approval only for policy-classified production boundaries.

A self-hosted GitHub Actions runner or unrestricted remote root shell is not the target architecture.

## Security boundary

Operation Runtime does not replace release-switch, Hub-cutover, mutation-gate or migration transaction authorities. Those remain the canonical commit/rollback mechanisms for their domains.

The runtime records execution and recovery state around those authorities. A runtime PASS cannot convert an unqualified candidate into a qualified release, authorize a production cutover, or weaken an existing fail-closed transaction rule.


## Local allowlisted dispatcher

The v1 dispatcher is `keelaryn_core.operation_agent`. It is intentionally transport-independent.

A request is canonical JSON with only a request ID, operation token, exact source commit, profile token, mutation capability, bounded timeout and approval policy. There is no shell command, argv list, arbitrary path or free-form payload field.

The request ID is also the Operation Runtime operation ID. Re-delivery of the same request therefore resolves to the existing durable operation instead of executing it again.

The initial allowlist contains only `RUNTIME_SELFTEST`. Production mutations are deliberately impossible until an explicit handler and approval verifier are qualified.

The systemd agent service is detached from SSH/chat, has no network access, no Linux capabilities, and may write only the private operation/control roots. A future network transport must be a separate less-privileged component that can deliver strict request files but cannot execute arbitrary commands or gain the dispatcher privileges.
