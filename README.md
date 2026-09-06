# Keelaryn

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Keelaryn is a Windows-first PowerShell management and release-engineering system for a structured, instance-owned Hub. It emphasizes safe state transitions, deterministic builds, rollback, diagnostics, explicit migrations, package/path hardening, and bounded AI-assisted development context.

## Current public source baseline

This repository sync is based on production-qualified **Keelaryn Manager 4.11.0**. The Manager source under `manager/` is the exact 61-file managed product set bound by the Windows Full Gate. The reusable Manager gate harness under `tests/framework/manager-gate/` is frozen **Gate Framework v2 revision 9**, independently qualified on Windows PowerShell 5.1.

No personal Hub, CURRENT/CANDIDATE/APPROVED package, binding, Manager state, logs, history, credentials or private test evidence is part of the public source tree.

```text
keelaryn/
├── manager/
│   ├── KEELARYN.cmd
│   ├── README_FIRST.md
│   ├── compat/commands/
│   └── product/
│       ├── docs/
│       ├── governance/hub/
│       ├── install/INSTALLATION.json
│       ├── migrations/
│       ├── runtime/Keelaryn__Manager.ps1
│       ├── starter/hub/
│       └── tools/
├── hub/
└── tests/
    └── framework/manager-gate/
```

Machine-local Manager state is created under `manager/state/` at runtime and is ignored by Git. The top-level `hub/` directory is only a boundary marker; real Hub data is not repository source.

## What the project demonstrates

- Windows PowerShell 5.1 automation and compatibility engineering.
- Deterministic SOURCE / DISTRIBUTION / UPDATE / AI_CONTEXT release construction.
- Isolated double-build determinism checks.
- SHA-256 package and installed-state validation.
- Transactional Manager update with rollback fault injection.
- Read-only Doctor diagnostics and CURRENT/installed identity validation.
- ZIP traversal, Windows reserved-name, case/Unicode collision and reparse-point defenses.
- Windows Restart Manager lock-owner diagnostics without terminating processes.
- Explicit Hub migrations and compatibility boundaries.
- Candidate transport build/reconstruction with independent integrity checks.
- Generated task-routed AI_CONTEXT tied to exact Manager source.
- A separately qualified reusable Windows Gate Framework.

## Quick start

Requirements: Windows 10/11 or Windows Server with **Windows PowerShell 5.1**.

Interactive frontend:

```text
manager\KEELARYN.cmd
```

Compatibility commands remain available under:

```text
manager\compat\commands\
```

For example: `DOCTOR.cmd`, `GENESIS_KEELARYN__HUB.cmd`, and `BUILD_RELEASE.cmd`.

## Development and validation

Local release approval is intentionally stronger than hosted CI. The Windows Full Gate operates only on disposable targets below `tests/work`, uses a CURRENT-backed disposable Hub, validates update/rollback/Doctor/UI/archive/candidate-transport/Genesis behavior, and proves production immutability.

GitHub Actions runs the repository boundary verifier and the Hub-blind SourceGate path on a Windows hosted runner. It does **not** replace the local Full Gate.

Run the repository boundary verifier locally:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\Verify-PublicRepository.ps1
```

## Repository safety boundary

The public tree intentionally excludes:

- `manager/state/**`;
- a real `hub/**`;
- `tests/work/**` and `tests/results/**` evidence;
- Manager/Hub UPDATE, CURRENT, CANDIDATE or APPROVED ZIPs;
- candidate transport JSON;
- credentials, private keys and recovery material.

The exact Manager source currently retains one maintainer-local test-entrypoint example in `manager/product/docs/TESTING.md`. It is non-secret documentation and not a product installation default; public-facing instructions in this README use repository-relative paths.

## Documentation

- [Architecture overview](docs/ARCHITECTURE_OVERVIEW.md)
- [Engineering case study](docs/ENGINEERING_CASE_STUDY.md)
- [Security model](docs/SECURITY_MODEL.md)
- [Release engineering](docs/RELEASE_ENGINEERING.md)
- [Portfolio / interview notes](PORTFOLIO.md)
- [Publishing checklist](docs/PUBLISHING_CHECKLIST.md)
- Detailed product documentation: [`manager/product/docs`](manager/product/docs/)

## License

Keelaryn is released under the [MIT License](LICENSE). The license covers public repository source and documentation, not uncommitted personal Hub/runtime data.
