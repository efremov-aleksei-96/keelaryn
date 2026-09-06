# Keelaryn Manager 4.12.0

Manager 4.12.0 is a first-use onboarding release built on the production-qualified 4.11.0 Manager baseline. It does not change Hub schemas, update schemas, migration semantics or validation boundaries.

The interactive frontend now distinguishes a genuinely empty fresh installation from an existing installation that merely has a missing/invalid Hub. A clean Generic DISTRIBUTION opens a guided first-run screen with Create, Connect, Main menu and Exit actions. Genesis and binding continue to use the existing validated Manager paths rather than a second setup implementation.

After successful first-run Genesis or binding, Manager runs Doctor immediately and only reports setup ready when Doctor succeeds. Existing/colliding state remains fail-closed and routes to recovery; in particular, a source checkout containing the repository-only `hub/README.md` marker is never treated as an empty install target.

## Canonical installed layout

```text
keelaryn/
├── Keelaryn.cmd
├── manager/
│   ├── KEELARYN.cmd
│   ├── README_FIRST.md
│   ├── product/
│   ├── compat/
│   │   └── commands/
│   └── state/
│       ├── baseline/
│       ├── inbox/
│       ├── logs/
│       ├── history/
│       ├── releases/
│       ├── work/
│       ├── binding.json          (when bound)
│       └── layout.json
├── hub/
└── tests/
```

The canonical runtime is `manager/product/runtime/Keelaryn__Manager.ps1`. The canonical installation manifest is `manager/product/install/INSTALLATION.json`. Compatibility commands remain under `manager/compat/commands/`.

Mutable Manager state belongs under `manager/state/`. Historical root runtime/version/manifest files are transport compatibility only and are not part of the canonical installed managed set.

## Update compatibility

Manager 4.12.0 preserves the native update compatibility floor required by the existing release policy. UPDATE artifacts therefore retain the narrow transition envelope (`Keelaryn__Manager.ps1`, `_manager_manifest.json`, `_manager_version.txt`) used by supported older Manager package validators. Those three files are not part of the final 4.11.0 installation manifest.

The one-time 4.7.2 -> 4.8.7 filesystem-finalization migration remains supported as historical compatibility code, but 4.12.0 does not reopen or redesign the filesystem architecture.

## User interface

Use `keelaryn\Keelaryn.cmd` or `manager\KEELARYN.cmd`.

4.12.0 preserves the established menu/action contract and adds a bounded startup layer:

- a genuinely empty canonical installation opens a Create / Connect first-run screen;
- pre-existing or conflicting state routes to Doctor/binding recovery instead of implicit mutation;
- successful first-run creation/binding runs Doctor before setup is declared ready;
- choosing Main menu for now is session-only and does not suppress future setup guidance;
- the ordinary main menu, semantic action results, picker behavior, Full Gate entrypoint and compatibility actions remain available unchanged.

## Hub revision presentation

New Hub revisions may carry immutable UTC `revision_time_utc`. Manager uses this as the human-facing revision time. Existing artifacts without the field remain valid and use their immutable `created` timestamp as the compatibility display fallback.

`data_revision` remains the internal monotonic sequence used for lineage, ordering, deterministic validation and audit cadence. Existing `rNNNN` artifact/history contracts remain valid.

## Release gate

Production approval requires Windows PowerShell 5.1 parser and SelfTests, deterministic release/package validation, a CURRENT-backed disposable 4.11.0 -> 4.12.0 update, rollback verification, Doctor, first-run/Create/Bind/recovery UI coverage, picker/archive orchestration regressions, revision compatibility checks, candidate-transport checks, generic distribution/Genesis smoke tests, AI_CONTEXT validation/performance control, and production immutability. The Windows candidate gate is generated through the independently Windows-qualified frozen Gate Framework v2 r9, which binds gate revisions cryptographically to unchanged managed candidate bytes and publishes the exact tested UPDATE plus a validated one-click production installer only after FULL GATE PASS.
