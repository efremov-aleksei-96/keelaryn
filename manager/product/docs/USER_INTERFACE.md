# Keelaryn Manager user interface

`KEELARYN.cmd` is the canonical Manager entrypoint. Generic DISTRIBUTION also includes `keelaryn/Keelaryn.cmd`, which delegates to it by relative path.

The frontend is `product/tools/KeelarynMenu.ps1`. It uses direct .NET console I/O with Windows PowerShell 5.1-safe fallbacks.

## First-run and recovery startup

On a clean canonical Generic DISTRIBUTION with no Hub, CURRENT baseline, binding or Hub environment override, the interactive frontend opens a first-run screen before the ordinary menu. It offers **Create a new Hub**, **Connect an existing Hub**, **Main menu for now**, or Exit. Creation and binding reuse the existing validated Genesis/binding paths; successful setup immediately runs Doctor and then offers Open Hub.

The startup classifier is fail-safe. If no valid Hub is available but the canonical `hub` path, a CURRENT baseline, binding state or Hub environment override already exists, Manager does not assume a fresh installation and does not overwrite anything. It presents recovery actions (Doctor, bind existing Hub, or main menu). This also prevents a public source checkout containing the repository-only `hub/README.md` boundary marker from being mistaken for an empty runtime installation.

The first-run screen is not persisted as a bypass flag. Choosing **Main menu for now** affects only that invocation; a still-unconfigured clean installation is offered setup again on the next launch.
Frontend operational paths are refreshed after each Manager child action, so a fresh state-layout initialization or new binding is visible immediately within the same interactive session.

## Visible action-result contract

Interactive actions preserve meaningful backend stdout/stderr, but their final human-facing status is semantic rather than a raw process exit code:

- `COMPLETED`
- `COMPLETED WITH WARNINGS`
- `NO CHANGES REQUIRED`
- `CANCELLED. No changes made.`
- `FAILED`

Doctor exit code 2 means the diagnostic completed and reported warnings that require attention. In the interactive frontend this is rendered as `COMPLETED WITH WARNINGS`, not as a failed Doctor run. Other actions keep their existing semantic result mapping; this Doctor-specific presentation does not convert arbitrary exit code 2/3 results into success.

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

Repair Hub CURRENT, check/apply migrations, bind an existing Hub, open update inbox/logs, show a storage report, clean disposable test work and compact completed qualification evidence. Ordinary update actions are not duplicated here.

Zero pending migrations are a no-op and require no confirmation. When an applicable migration exists, the frontend shows the plan before commit. Binding shows both current and proposed Hub paths before confirmation. Storage/destructive maintenance actions are dry-run first. Qualification compaction verifies the frozen archive before expanded evidence cleanup and never targets Manager rollback history.

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

<!-- multi-hub-ui-v1 -->
## Manage Hubs

Maintenance â†’ Manage Hubs exposes registry initialization, list, switch, create-new, connect-existing and active-instance information.

The main status view identifies the active Hub by display name and shortened `instance_id`. ChatGPT preparation and Hub package import follow the active instance; Manager update packages remain Manager-global.

<!-- active-instance-exchange-resolution-v1 -->
### Active-instance exchange resolution

ChatGPT preparation resolves the active Hub instance before constructing any exchange destination path. With a valid multi-Hub registry, Workspace and Chat Manager inputs are written only under `exchange/instances/<instance_id>/chatgpt/`. If the registry exists but its active instance cannot be resolved, ChatGPT exchange actions fail closed instead of falling back to the legacy shared exchange directory.
