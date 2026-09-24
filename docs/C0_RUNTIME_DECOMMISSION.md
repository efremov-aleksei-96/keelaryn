# C0 Legacy Runtime Decommission Plan

Status: **READY FOR EXECUTION, NOT YET EXECUTED**  
Observed through Gateway on 2026-09-24.

## Current live state

`keelaryn-operation-agent.service`
- active/running;
- enabled;
- PID observed: 1348217;
- purpose: legacy durable operation dispatcher;
- reverse dependents: only `multi-user.target` and `graphical.target`.

`keelaryn-operation-transport.service`
- active/running;
- enabled;
- PID observed: 1348215;
- purpose: legacy GitHub-Issues transport;
- reverse dependents: agent plus `multi-user.target` and `graphical.target`.

`keelaryn-drive.service`
- inactive/dead;
- enabled;
- not part of this decommission transaction.

## Queue/transaction reconcile

The legacy operation root contains exactly three historical operation IDs:

- 50000000000000000000000000000001
- 50000000000000000000000000000002
- 50000000000000000000000000000003

For all three:

- operation = `RUNTIME_SELFTEST`;
- mutation_capable = false;
- mutation_state = `READ_ONLY`;
- execution_state = `SUCCEEDED`;
- phase = `COMPLETE`;
- outcome = `PASS`;
- next_action = `NONE`.

Transport:
- inbox entries = 0;
- outbox entries = 3;
- all outbox records are `TERMINAL`, `terminal=true`, `SUCCEEDED`, `PASS`;
- transport state records a published status comment for all three operation IDs.

Therefore there is no observed in-flight operation or unpublished terminal result.

## Why decommission is safe

Gateway/OpenSSH is now the OperatorChannel used by development. It does not depend on either legacy service.

The old services exist only to implement the superseded path:

```text
GitHub Issue
→ operation-transport
→ operation-agent
→ operation-runtime
```

No active Corpus-first P0 component depends on that path; P0 has not started.

## Exact reversible mutation

One coherent runtime transaction:

```bash
systemctl disable --now   keelaryn-operation-agent.service   keelaryn-operation-transport.service
```

Do **not** delete:

- unit files;
- `/var/lib/keelaryn/operations`;
- `/var/lib/keelaryn-operation-transport`;
- `/var/lib/keelaryn/operation-control`;
- old releases;
- GitHub-operation credential file.

Those remain rollback/provenance until a later cleanup phase.

## Immediate verification

After the mutation require:

- agent ActiveState=inactive;
- agent UnitFileState=disabled;
- transport ActiveState=inactive;
- transport UnitFileState=disabled;
- no matching operation agent/transport process;
- Gateway SSH still works;
- `keelaryn-drive.service` remains unchanged;
- existing operation/transport/control state remains byte-preserved.

## Rollback

If OperatorChannel assumptions prove wrong:

```bash
systemctl enable --now   keelaryn-operation-transport.service   keelaryn-operation-agent.service
```

Then read-only reconcile both units and legacy operation state.

## Later cleanup, separate transaction

Only after a stable observation period:

- remove obsolete GitHub operation credential;
- remove legacy unit files;
- archive or remove old runtime state according to provenance value;
- decide disposition of old `/opt/keelaryn` releases.

None of those actions are part of the first decommission.
