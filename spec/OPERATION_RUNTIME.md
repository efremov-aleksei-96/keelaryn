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

## Terminal crash recovery

`result.json` is immutable terminal authority. It is published as a complete
no-overwrite private file before the mutable state/handoff view is advanced to terminal.
If the worker dies after result publication but before the state/handoff update,
`recover_terminal` validates exact operation/source/mutation identity and reconstructs
the terminal state without invoking the operation handler again. A terminal state with
no result authority, conflicting result/state identities, or a conflicting requested
finish fails closed.

New immutable runtime authority files are staged privately and become visible at their
final path only after their complete bytes are fsynced; a crash cannot expose a partially
written `result.json` as valid terminal authority. If a crash happens even earlier,
after the operation directory is created but before `state.json` becomes visible, the
agent may reclaim that directory only when it contains no authority and only the exact
runtime-generated `.state.json.new-<pid>-<32-lowercase-hex>` staging filename form.
Prefix lookalikes or any other material make initialization recovery fail closed.

## Progress and heartbeat

Operation Runtime composes the existing sanitized `GateProgressJournal`.

The journal is append-only and emits heartbeat records while work is running. Appends retry short writes and fsync their bytes. A crash-torn final fragment without a newline is ignored by status recovery, while a newline-terminated invalid record remains a fail-closed integrity error. `keelaryn-operation status` combines durable state with the newest complete progress timestamp, while `keelaryn-operation watch` provides a stable UI for observing progress without controlling the worker process.

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

The request ID is also the Operation Runtime operation ID. Re-delivery of the same exact request therefore resolves to the existing durable operation instead of executing it again. Reuse of an already-processed request ID with different canonical request bytes is quarantined as a conflicting replay rather than entering an agent restart loop.

The initial allowlist contains only `RUNTIME_SELFTEST`. Production mutations are deliberately impossible until an explicit handler and approval verifier are qualified.

The systemd agent service is detached from SSH/chat, has no network access, no Linux capabilities, and may write only the private operation/control roots. A future network transport must be a separate less-privileged component that can deliver strict request files but cannot execute arbitrary commands or gain the dispatcher privileges.


## GitHub Issues transport

The first remote transport uses one dedicated GitHub issue as a narrow queue/status channel. It is deliberately not a repository-content writer and not a self-hosted Actions runner.

The VPS transport runs separately from the privileged agent as the unprivileged `keelaryn` account. It can reach GitHub over HTTPS but is sandboxed away from `/etc/keelaryn`, the private Operation Runtime authority, migration state, mutation gate and Hub credentials. It writes only `/var/lib/keelaryn-operation-transport`.

Requests are accepted only from an explicit GitHub actor allowlist, require exact `KEELARYN_OPERATION_REQUEST_V1` framing and strict operation-request JSON, and remain bound to the exact materialized source commit. There is no shell command, argv list, arbitrary path or free-form executable payload.

The GitHub credential is a dedicated fine-grained token limited to repository metadata read and Issues read/write. It must not receive Contents, Actions, Administration, Secrets or repository-management write permission. The expected GitHub status-publisher actor is configured separately from the request-actor allowlist and every remotely recovered/created/updated status comment must match that exact publisher identity.

The transport status channel is non-authoritative. The network-isolated privileged agent writes only sanitized relay snapshots to the transport outbox. Remote status recovery accepts only canonical relay payloads from the exact configured status-publisher actor and exact source commit; an arbitrary public issue commenter cannot be adopted as the transport's publication identity. GitHub status comments can be lost or delayed without changing private Operation Runtime, Hub selector, release-switch or mutation-gate authority.

Request archive publication and inbox deletion are directory-fsynced on POSIX so a crash does not silently lose the handoff boundary. Requests are archived exactly once by the agent. Invalid or conflicting replay requests are quarantined as rejected rather than causing a restart/retry loop. Re-delivery of the same exact request ID resolves to the existing durable operation and cannot repeat an already-created mutation. If the agent restarts with an existing nonterminal operation, it never re-executes the handler: the operation is terminalized as `INTERRUPTED`; a commit-ambiguous mutation boundary becomes `RECOVERY_REQUIRED` and requires read-only reconciliation.

A GitHub status comment is observability evidence, never permission to repeat a mutation. Ambiguous mutation boundaries continue to require `READ_ONLY_RECONCILE`.


## Sidecar control-plane release identity

The operation control plane must not be coupled to `/opt/keelaryn/current`. A production Hub cutover may already have a durable transaction bound to the exact current release, so changing the production selector merely to add remote-control infrastructure would violate transaction identity.

Operation-control services therefore run from the independent selector:

`/opt/keelaryn/control-current -> releases/<exact-qualified-source-commit>`

The initial bootstrap validates the exact deterministic release payload, requires the control selector, operation units and GitHub credential destination to be absent, installs them transactionally, starts both services, verifies them active, and proves the production `/opt/keelaryn/current` symlink did not change. Failure removes only objects created by that bootstrap attempt and leaves the production selector untouched.

The bootstrap token is entered interactively through `getpass`; it is never accepted as a command-line argument, printed, written to the bootstrap receipt or sent through GitHub. The installed environment file is mode 0600 inside the dedicated root-owned mode-0700 directory `/etc/keelaryn/operation-control/`; bootstrap does not require the shared `/etc/keelaryn` parent itself to be mode 0700.

Initial bootstrap is intentionally install-only. Replacing an existing control-plane selector, unit set or GitHub credential requires a separately qualified update transaction rather than silently reusing bootstrap semantics.

### Bootstrap transaction and degraded transport behavior

Operation-control bootstrap preflight is strictly read-only: absent private control
directories remain absent. Directory creation belongs to the install transaction and is
tracked for rollback. Service activation is considered attempted before invoking
`systemctl enable --now`, because systemd may partially activate a unit before returning
failure. Rollback disables every attempted unit through the same checked systemctl
boundary, proves both operation-control units inactive, removes every transaction-created
file/selector and empty private directory, reloads systemd, and proves production
`/opt/keelaryn/current` unchanged. Bootstrap starts by publishing an atomic private transaction-directory marker whose name binds the exact source/payload/configuration identity, a SHA-256 of the credential bytes, and whether the private directories pre-existed; the marker contains no token. Initial final-path file creation remains direct exclusive/no-overwrite with no hidden token-bearing staging file. If the process is killed after that marker but before the receipt, an exact retry may adopt or repair only marker-owned regular files with stable owner/mode/path identity, and only while no operation-control unit is active; any active transaction requires every credential/unit/selector byte to already be exact. A torn receipt is recoverable, while an exact completed receipt replay is read-only. Rollback is bound to open Linux ownership pins plus stable object identity (device, inode and file type), refuses to delete a replacement pathname, and retains the transaction marker whenever complete rollback cannot be proven. If a newly-created private
directory cannot be ownership-pinned, cleanup fails closed and leaves the ambiguous
path for read-only reconciliation rather than deleting an unproven object. Any incomplete rollback is a distinct fail-closed error and must be reconciled before retry. Systemd active-state probes accept only the explicit active/inactive-or-unknown return classes and fail closed on unclassified manager errors.

The root operation agent only `Wants=` the network transport and is ordered after it;
transport failure or network loss must not make the durable agent itself unavailable.
The transport remains the only network-capable component.
