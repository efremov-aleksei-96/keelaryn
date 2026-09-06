# Keelaryn Manager user interface

`KEELARYN.cmd` is the canonical Manager entrypoint. Generic DISTRIBUTION also includes `keelaryn/Keelaryn.cmd`, which delegates to it by relative path.

The frontend is `product/tools/KeelarynMenu.ps1`. It uses direct .NET console I/O with Windows PowerShell 5.1-safe fallbacks.

## Visible action-result contract

Interactive actions preserve meaningful backend stdout/stderr, but their final human-facing status is semantic rather than a raw process exit code:

- `COMPLETED`
- `NO CHANGES REQUIRED`
- `CANCELLED. No changes made.`
- `FAILED`

Raw exit codes remain machine-readable and are retained in detailed logs/contracts.

Navigation-only actions return to the menu immediately. Actions whose output must be read use `[Enter] Back`; navigation does not use an unconditional `Press Enter to continue...` pause.

## Picker and child-process boundary

GUI selection and GUI cancellation are distinct from GUI unavailability:

- successful GUI selection continues;
- GUI Cancel cancels immediately;
- manual path input is offered only if the GUI picker cannot be created or shown.

The frontend owns overwrite, binding and migration confirmations. A child whose output is redirected/captured must not block on `Read-Host` or another hidden prompt. The test-archive backend therefore supports `-PlanOnly` and `-NonInteractive`; the frontend plans the destination, asks once when replacement is needed, and only then executes the child.

The same archive validation/unpack contract is reused by Manager UI, Full Gate and the external/manual gate workflow.

Direct frontend automation is deterministic and never waits on a hidden confirmation prompt. Existing test workspaces require an explicit `-Replace`; direct migration or binding commits require `-ConfirmChanges`; direct Genesis requires a validated `-Path <config.json>` plus `-ConfirmChanges`. The ordinary `Action=Menu` path remains interactive and owns the same commit confirmations before invoking runtime children non-interactively.

## Menu hierarchy

### Everyday

Open Hub, Doctor, install an update package, install pending updates, Installation info.

### Maintenance

Repair Hub CURRENT, check/apply migrations, bind an existing Hub, open update inbox and logs. Ordinary update actions are not duplicated here.

Zero pending migrations are a no-op and require no confirmation. When an applicable migration exists, the frontend shows the plan before commit. Binding shows both current and proposed Hub paths before confirmation.

### Development

Validation: Run Full Gate, run a test package.

Build: AI_CONTEXT, release, distribution.

Hub candidate transport: export and restore CANDIDATE transport.

Results: test workspace, test results and releases.

`Run Full Gate...` unpacks the selected `manager-<version>.zip` through the canonical archive tool into `tests/work`, then invokes that archive's canonical PowerShell Full Gate runner directly and non-interactively. It passes the current Keelaryn layout as the read-only production root. Destructive development targets remain under `tests`.

### Advanced

Genesis, compatibility/legacy migration, root-launcher repair and compatibility commands. Historical migration primitives remain available only inside the deeper legacy-tools screen.

## Status and Installation info

The main header is intentionally compact: Manager version, Hub version plus human revision time, health and pending updates.

Installation info carries the detailed Manager/Hub paths, artifact ID, UTC revision metadata, legacy numeric sequence, binding source, Doctor metadata, pending package counts and instance identity.

## Hub revision presentation

`revision_time_utc` is the preferred immutable human-facing revision identity for new Hub revisions. For old artifacts that lack it, Manager uses the artifact's immutable `created` timestamp as a compatibility fallback.

`data_revision` remains the internal monotonic compatibility/order sequence; the UI may expose it as a legacy/internal sequence where diagnostic context is useful.

## Validation

`RenderMain` validates non-interactive rendering. Frontend SelfTest validates the output/orchestration source contract. Windows Full Gate covers real menu paths, picker/archive replacement behavior, hidden-prompt prevention, semantic result states, migration no-op behavior, binding preview and the first-class Full Gate delegation path. Doctor remains authoritative for installation health.
