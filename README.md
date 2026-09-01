# Keelaryn

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Keelaryn is a Windows-first PowerShell management and release system for a structured, instance-owned Hub. The project focuses on safe state transitions, deterministic release engineering, diagnostics, migration, rollback, and bounded AI-assisted development context.

The repository intentionally separates **product code** from **instance data**:

```text
keelaryn/
├── manager/   # product/runtime source
├── hub/       # runtime instance location; personal data is never committed
└── tests/     # disposable work + durable test evidence
```

> **Portfolio status:** this repository candidate is derived from verified production Manager **4.4.31**. It contains the generic Manager product and sanitized repository scaffolding only. No personal Hub, CURRENT/CANDIDATE/APPROVED package, binding, logs, inbox, history, or credentials are included.

## What the project demonstrates

- PowerShell 5.1 automation on Windows.
- Deterministic SOURCE / DISTRIBUTION / UPDATE / AI_CONTEXT release builds.
- SHA-256 integrity validation and explicit product/instance identity.
- Staged Manager updates with rollback snapshots and fail-closed target-path checks.
- Hub update isolation: Manager and Hub lifecycle operations are separate by default.
- Read-only `Doctor` diagnostics with granular timings.
- Windows Restart Manager lock-owner diagnostics without terminating processes.
- Path traversal, Unicode/case-collision, reparse-point, reserved-name, and ZIP-envelope defenses.
- Explicit system migrations and compatibility aliases for legacy installations.
- Candidate transport fallback that reconstructs a complete non-canonical CANDIDATE from an exact CURRENT baseline and a verified Base64 delta.
- Task-routed, runtime-hash-bound AI development context that is derived from source rather than maintained as a second implementation.

## Measured engineering work

A Windows PowerShell 5.1 release gate compared Manager 4.4.25 with the later hashing optimization that entered production in 4.4.30 on the same disposable Hub/CURRENT baseline:

| Metric | Before | After | Change |
|---|---:|---:|---:|
| Doctor hub + baseline | 578.5 ms | 503.8 ms | **-12.9%** |
| Doctor total | 828.8 ms | 764.3 ms | **-7.8%** |
| Portable Hub analysis | 153.9 ms | 104.2 ms | **-32.3%** |
| CURRENT baseline | 206.4 ms | 182.2 ms | **-11.7%** |
| Portable + CURRENT target sum | 360.3 ms | 286.4 ms | **-20.5%** |

The optimization did **not** change SHA-256 input bytes or the digest algorithm. It replaced a PowerShell pipeline used only to render digest bytes as lowercase hex with a .NET `BitConverter` path after a microbenchmark demonstrated byte-for-byte equivalence and large formatting overhead.

See [Engineering case study](docs/ENGINEERING_CASE_STUDY.md) for the full reasoning, including rejected experiments.

## Quick start

Requirements:

- Windows 10/11 or Windows Server with **Windows PowerShell 5.1**.
- A normal filesystem path; production data should not live inside this Git repository.

From `manager/`:

```text
GENESIS_KEELARYN__HUB.cmd
DOCTOR.cmd
```

`GENESIS_KEELARYN__HUB.cmd` creates a new canonical sibling `hub` instance. `DOCTOR.cmd` performs read-only validation. See [manager/README_FIRST.md](manager/README_FIRST.md) and [Genesis and onboarding](manager/product/docs/GENESIS_AND_ONBOARDING.md).

## Development and release gates

The repository is designed around disposable Windows testing. Development work belongs under `tests/work`; durable summaries and transcripts belong under `tests/results` and are normally ignored by Git.

The production Manager itself can prepare the local workspace:

```text
manager\PREPARE_TESTS.cmd
```

Canonical release construction:

```text
manager\BUILD_RELEASE.cmd
```

The release builder reconstructs SOURCE, DISTRIBUTION, UPDATE and AI_CONTEXT independently from the managed allowlist, validates hashes before publication, and publishes the release manifest last.

## Repository safety boundary

The `hub/` directory in this repository contains only a boundary README. Real Hub state is ignored by Git. The same applies to Manager runtime directories such as `_inbox`, `_history`, `_logs`, `_releases`, local binding, and CURRENT packages.

Run the public-tree verifier before publishing:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\Verify-PublicRepository.ps1
```

## Documentation

- [Architecture overview](docs/ARCHITECTURE_OVERVIEW.md)
- [Engineering case study](docs/ENGINEERING_CASE_STUDY.md)
- [Security model](docs/SECURITY_MODEL.md)
- [Release engineering](docs/RELEASE_ENGINEERING.md)
- [Portfolio / interview notes](PORTFOLIO.md)
- [Publishing checklist](docs/PUBLISHING_CHECKLIST.md)
- Detailed product documentation lives under [`manager/product/docs`](manager/product/docs/).

## License

Keelaryn is released under the [MIT License](LICENSE). The license applies to the generic product source and public repository scaffolding in this repository. Personal Hub instances, private runtime data, credentials, and other content that is not committed to this repository are outside this public source package.
