# Keelaryn Manager 4.4.31
Keelaryn Manager is the single universal implementation used to create, bind, validate, migrate, service and release Keelaryn Hub instances. Product source is strictly separated from instance-specific state.

## Everyday commands

- `OPEN_KEELARYN__HUB.cmd` — open the bound Hub.
- `DOCTOR.cmd` — read-only diagnostics and preflight report.
- `UPDATE_MANAGER.cmd` — process Manager product updates only; Hub packages are untouched.
- `UPDATE_HUB.cmd` — process validated Hub APPROVED packages only; Manager packages are untouched.
- `UPDATE_ALL.cmd` — explicitly run Manager updates first, then Hub updates after the Manager chain is current.

## Instance and recovery maintenance

- `BIND_INSTANCE.cmd` — explicitly bind this runtime to an existing Hub path.
- `SHOW_INSTANCE_INFO.cmd` — display identity/release information.
- `REPAIR_CURRENT_TRANSPORT.cmd` — remove workstation-local state from a legacy CURRENT ZIP without changing canonical payload identity.
- `CHECK_MIGRATIONS.cmd` — plan system migrations.
- `APPLY_MIGRATIONS.cmd` — apply only registry-declared manager-safe migrations.
- `MIGRATE_INSTANCE_IDENTITY.cmd`, `MIGRATE_TO_KEELARYN.cmd`, `MIGRATE_LAYOUT.cmd`, `FINALIZE_LAYOUT.cmd` — explicit compatibility/migration entrypoints for older installations; keep them available, but they are not normal daily actions.

## Creation and development

- `GENESIS_KEELARYN__HUB.cmd` — create a new canonical r0001 instance.
- `BUILD_GENERIC_DISTRIBUTION.cmd` — build a clean generic distribution.
- `BUILD_RELEASE.cmd` — build source + distribution + future update + release manifest from one managed source tree.
- `BUILD_AI_CONTEXT.cmd` — build deterministic task-routed AI development context.
- `PREPARE_TESTS.cmd` — create/validate the canonical `tests/work` and `tests/results` development workspace without moving existing test data.
- `BUILD_CANDIDATE_TRANSPORT.cmd` — build a verified Base64 delta fallback for Hub CANDIDATE ZIPs in `_inbox`.
- `RESTORE_CANDIDATE_TRANSPORT.cmd` — reconstruct and verify Hub CANDIDATE ZIPs from fallback transport JSON without installing them.

## Update contract

Manager and Hub lifecycle operations are separate by default. Prefer `UPDATE_MANAGER.cmd` or `UPDATE_HUB.cmd` when only one layer should change. `UPDATE_ALL.cmd` is an explicit compound action, not an implicit inbox mode. Update commands never repair CURRENT transport as a side effect; use `REPAIR_CURRENT_TRANSPORT.cmd` explicitly when Doctor recommends it.

## System release

The current product system release is Keelaryn 2.1.0; Manager and system release versions are intentionally independent. Genesis and migration converge on one canonical governance source, with mandatory portable MANIFEST v1 and VALIDATION v2 semantics.

Legacy `Core__*` identifiers exist only as explicit compatibility/history knowledge. Canonical installed layout is now `keelaryn/manager`, `keelaryn/hub`, and `keelaryn/tests`. `Keelaryn__Manager` / `Keelaryn__Hub` remain compatibility names for pre-4.4 installations and protocol artifacts.

## Fast development context

`BUILD_AI_CONTEXT.cmd` builds a deterministic runtime-SHA-bound development context for ChatGPT. Use it for ordinary Manager analysis; use full SOURCE for cross-cutting edits/release reconstruction.

