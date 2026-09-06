# Keelaryn

[![Windows source validation](https://github.com/efremov-aleksei-96/keelaryn/actions/workflows/windows-powershell.yml/badge.svg)](https://github.com/efremov-aleksei-96/keelaryn/actions/workflows/windows-powershell.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Keelaryn is a Windows-first local knowledge and project-management system built around two parts:

- **Manager** — a PowerShell application for installation, diagnostics, safe updates, rollback, migrations and release validation;
- **Hub** — your own local, portable knowledge/workspace data.

The public repository contains the product source and test framework. Your personal Hub, credentials and runtime state are never part of the repository.

## Install on Windows

**Recommended:** use the packaged Windows release rather than cloning the source repository.

1. Open [Releases](https://github.com/efremov-aleksei-96/keelaryn/releases/latest).
2. Download `Keelaryn_v<version>_Windows.zip`.
3. Extract the archive to a normal writable folder, for example `Documents\Keelaryn`.
4. Open the extracted `keelaryn` folder and run **`Keelaryn.cmd`**.
5. On Manager 4.11.x choose **Advanced → Genesis new Hub** to create your first Hub, then run **Doctor**.

Requirements: Windows 10/11 or Windows Server with **Windows PowerShell 5.1**.

For the complete first-use path, see **[Getting Started](GETTING_STARTED.md)**.

> The GitHub source tree is intentionally not the recommended installation package. It contains repository-only `hub/` and `tests/` boundary material. Use the Generic DISTRIBUTION attached to a GitHub Release for a clean runtime layout.

## First five minutes

After extracting the release:

```text
keelaryn\
├── Keelaryn.cmd          ← start here
└── manager\
```

Run `Keelaryn.cmd`, create a Hub, run Doctor, then choose **Open Hub**. Genesis creates the canonical sibling layout:

```text
keelaryn\
├── Keelaryn.cmd
├── manager\
├── hub\                  ← your data
└── tests\                ← created when development tooling needs it
```

If you want to use the Hub with ChatGPT, continue with **[Using Keelaryn with ChatGPT](docs/USING_WITH_CHATGPT.md)**.

## Current public source baseline

The current public source is based on production-qualified **Keelaryn Manager 4.11.0**. The Manager source under `manager/` is the exact 61-file managed product set bound by the Windows Full Gate. The reusable Manager gate harness under `tests/framework/manager-gate/` is frozen **Gate Framework v2 revision 9**, independently qualified on Windows PowerShell 5.1.

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
├── hub/                  # public boundary marker only
└── tests/
    └── framework/manager-gate/
```

Machine-local Manager state is created under `manager/state/` at runtime and is ignored by Git.

## What the project demonstrates

- Windows PowerShell 5.1 automation and compatibility engineering.
- Deterministic SOURCE / DISTRIBUTION / UPDATE / AI_CONTEXT construction.
- SHA-256 package and installed-state validation.
- Transactional Manager update with rollback fault injection.
- Read-only Doctor diagnostics and CURRENT/installed identity validation.
- ZIP traversal, Windows reserved-name, case/Unicode collision and reparse-point defenses.
- Windows Restart Manager lock-owner diagnostics without terminating processes.
- Explicit Hub migrations and compatibility boundaries.
- Candidate transport build/reconstruction with independent integrity checks.
- Generated task-routed AI_CONTEXT tied to exact Manager source.
- A separately qualified reusable Windows Gate Framework.

## Development and validation

The local Windows Full Gate is intentionally stronger than hosted CI. It runs only against disposable targets below `tests/work`, uses a disposable CURRENT-backed Hub, validates update/rollback/Doctor/UI/archive/candidate-transport/Genesis behavior, and proves production immutability.

GitHub Actions runs the repository boundary verifier and Hub-blind SourceGate. The public release workflow additionally builds the qualified release bundle and smoke-tests the extracted Generic DISTRIBUTION, including Genesis and Doctor, before publishing a release asset.

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

The exact Manager source currently retains one maintainer-local test-entrypoint example in `manager/product/docs/TESTING.md`. It is non-secret documentation and not a product installation default.

## Documentation

### Start using Keelaryn

- **[Getting Started](GETTING_STARTED.md)**
- **[Using Keelaryn with ChatGPT](docs/USING_WITH_CHATGPT.md)**
- **[Troubleshooting](docs/TROUBLESHOOTING.md)**

### Engineering

- [Architecture overview](docs/ARCHITECTURE_OVERVIEW.md)
- [Engineering case study](docs/ENGINEERING_CASE_STUDY.md)
- [Security model](docs/SECURITY_MODEL.md)
- [Release engineering](docs/RELEASE_ENGINEERING.md)
- [Portfolio / interview notes](PORTFOLIO.md)
- [Publishing checklist](docs/PUBLISHING_CHECKLIST.md)
- [Detailed Manager documentation](manager/product/docs/)

## License

Keelaryn is released under the [MIT License](LICENSE). The license covers public repository source and documentation, not uncommitted personal Hub/runtime data.
