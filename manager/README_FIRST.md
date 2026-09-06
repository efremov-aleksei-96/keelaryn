# Keelaryn Manager 4.11.0

Manager 4.11.0 is a read-path performance release built on the production 4.10.2 release-engineering baseline. The canonical filesystem layout, Hub contracts, update schemas and user interface are unchanged.

4.11.0 removes duplicate work from three hot paths without weakening fresh validation boundaries: Manager UPDATE parsing reuses one opened archive for envelope and payload validation, no-op Manager update cleanup reuses packages already validated during decision-making, and AI_CONTEXT lexical validation reuses the runtime text already parsed into the AST instead of reading the runtime a second time.

## 4.11.0 duplicate-work cleanup

The optimization is deliberately operation-local. It introduces no process-global cache and does not reuse validation across transaction/commit boundaries. Staged Manager UPDATE packages are still reparsed after copy before installation, installed payload hashes are still recomputed after mutation, and release/Doctor integrity checks retain their existing fresh-validation semantics.

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

Manager 4.11.0 preserves the native update compatibility floor required by the existing release policy. UPDATE artifacts therefore retain the narrow transition envelope (`Keelaryn__Manager.ps1`, `_manager_manifest.json`, `_manager_version.txt`) used by supported older Manager package validators. Those three files are not part of the final 4.11.0 installation manifest.

The one-time 4.7.2 -> 4.8.7 filesystem-finalization migration remains supported as historical compatibility code, but 4.11.0 does not reopen or redesign the filesystem architecture.

## User interface

Use `keelaryn\Keelaryn.cmd` or `manager\KEELARYN.cmd`.

4.11.0 retains the 4.9.2 user-interface contract:

- keeps the main status compact and moves diagnostic identity/path detail to Installation info;
- separates visible `COMPLETED`, `NO CHANGES REQUIRED`, `CANCELLED` and `FAILED` results from backend exit codes;
- treats GUI picker Cancel as an immediate cancellation;
- keeps overwrite/confirmation decisions in the Manager frontend so redirected child processes never wait on hidden interactive prompts;
- exposes Full Gate as a first-class Development action while preserving the external `UNPACK_MANAGER_GATE.cmd` workflow;
- simplifies Maintenance and Advanced without removing compatibility capabilities.

## Hub revision presentation

New Hub revisions may carry immutable UTC `revision_time_utc`. Manager uses this as the human-facing revision time. Existing artifacts without the field remain valid and use their immutable `created` timestamp as the compatibility display fallback.

`data_revision` remains the internal monotonic sequence used for lineage, ordering, deterministic validation and audit cadence. Existing `rNNNN` artifact/history contracts remain valid.

## Release gate

Production approval requires Windows PowerShell 5.1 parser and SelfTests, deterministic release/package validation, a CURRENT-backed disposable 4.10.2 -> 4.11.0 update, rollback verification, Doctor, UI/picker/archive orchestration regressions, revision compatibility checks, candidate-transport checks, generic distribution/Genesis smoke tests, AI_CONTEXT validation/performance control, and production immutability. The Windows candidate gate is generated through the independently Windows-qualified frozen Gate Framework v2 r9, which binds gate revisions cryptographically to unchanged managed candidate bytes and publishes the exact tested UPDATE plus a validated one-click production installer only after FULL GATE PASS.
