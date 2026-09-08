# Keelaryn

[![Windows qualification](https://github.com/efremov-aleksei-96/keelaryn/actions/workflows/windows-powershell.yml/badge.svg)](https://github.com/efremov-aleksei-96/keelaryn/actions/workflows/windows-powershell.yml)
[![Repository governance](https://github.com/efremov-aleksei-96/keelaryn/actions/workflows/repository-governance.yml/badge.svg)](https://github.com/efremov-aleksei-96/keelaryn/actions/workflows/repository-governance.yml)
[![Release policy](https://github.com/efremov-aleksei-96/keelaryn/actions/workflows/release-policy.yml/badge.svg)](https://github.com/efremov-aleksei-96/keelaryn/actions/workflows/release-policy.yml)
[![Latest release](https://img.shields.io/github/v/release/efremov-aleksei-96/keelaryn?label=release)](https://github.com/efremov-aleksei-96/keelaryn/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Keelaryn is a **Windows-first local automation and state-management platform** built around Windows PowerShell 5.1. It manages a stateful local Hub through transactional updates, integrity validation, migrations, diagnostics, deterministic release artifacts and gated qualification.

The Hub is the real workload. The engineering focus of this repository is the **Manager runtime, failure handling, release system, validation model and trust boundaries** around that workload.

> This repository is intentionally not a public personal knowledge base. Real Hub data, credentials, runtime state and private qualification evidence are excluded from the public tree.

## Problem

Stateful local automation becomes difficult when product code and user-owned data evolve independently. A useful system has to answer more than “does the script run?”:

- How is an update installed without corrupting existing state?
- What happens if installation fails halfway through?
- Can the exact same source produce the same release artifacts twice?
- How is a package rejected before it can escape the intended filesystem boundary?
- How do tests exercise migrations, rollback and UI behavior without mutating production data?
- How is a released artifact tied back to the exact candidate that passed qualification?

Keelaryn treats these as product requirements rather than post-release cleanup tasks.

## What Keelaryn is

| Component | Responsibility |
|---|---|
| **Manager** | Windows PowerShell application for lifecycle operations: diagnostics, updates, rollback, migrations, release construction and validation. |
| **Hub** | Stateful local workload managed by the system. A real Hub is user-owned and never committed to the public repository. |
| **Gate Framework** | Reusable Windows qualification harness that binds tests to candidate identity and exercises disposable update/recovery paths. |
| **Repository governance** | CI/CD, provenance, branch protection, release policy and supply-chain controls around the source/release boundary. |

## Architecture

```mermaid
flowchart LR
    U[User / operator] --> M[Manager\nPowerShell 5.1]
    M --> H[Hub\nuser-owned state]
    M --> S[Manager state\nbindings / history / rollback]

    R[Managed product source] --> B[Deterministic release builder]
    B --> A[SOURCE / DISTRIBUTION / UPDATE / AI_CONTEXT]

    A --> G[Gate Framework]
    G --> D[Disposable Windows qualification]
    D --> P[Production qualification boundary]
    P --> C[Public provenance + immutable release]

    M -. validates .-> H
    G -. never uses personal Hub as mutable target .-> H
```

The central boundary is **product source vs instance-owned state**. `manager/product/install/INSTALLATION.json` defines the managed Manager file set; runtime state and the real Hub live outside that source set.

See [Architecture overview](docs/ARCHITECTURE_OVERVIEW.md) for identity layers, mutation boundaries and the release/gate model.

## Engineering challenges

| Challenge | Implemented approach | Evidence |
|---|---|---|
| Safe in-place Manager updates | staged validation, rollback snapshot, post-install checks and rollback fault injection | [Release engineering](docs/RELEASE_ENGINEERING.md) |
| Reproducible releases | isolated deterministic builds for SOURCE, DISTRIBUTION, UPDATE and AI_CONTEXT | [Public file manifest](PUBLIC_FILE_MANIFEST.json) |
| Stateful integrity | instance/checkpoint identity, portable-content validation and Doctor diagnostics | [Architecture](docs/ARCHITECTURE_OVERVIEW.md) |
| Hostile/corrupt filesystem inputs | traversal, reserved-name, case/Unicode collision and reparse-point defenses | [Security model](docs/SECURITY_MODEL.md) |
| Test isolation | disposable Hub/update targets; production Hub is never a mutable qualification target | [Engineering case study](docs/ENGINEERING_CASE_STUDY.md) |
| Windows-specific behavior | PowerShell 5.1 compatibility, filesystem semantics, file-lock diagnostics and retry controls | [Detailed Manager docs](manager/product/docs/) |
| AI context cost | generated task-routed AI_CONTEXT bound to exact managed runtime/source identity | [Engineering case study](docs/ENGINEERING_CASE_STUDY.md) |
| Remote development | GitHub-hosted Windows disposable Full Gate with synthetic Hub and explicit non-production evidence semantics | [Remote qualification](docs/REMOTE_QUALIFICATION.md) |
| Supply-chain identity | SHA-pinned Actions, read-only default token, required checks and immutable-release policy | [Repository governance](docs/REPOSITORY_GOVERNANCE.md) |

## Release and qualification pipeline

```mermaid
flowchart LR
    X[Manager candidate] --> SG[SourceGate\nstatic + SelfTest + deterministic build]
    SG --> DG[Disposable Full Gate\nsynthetic Hub on Windows]
    DG --> FG[Production Full Gate\nreal production boundary read-only]
    FG --> E[Exact tested UPDATE\nDoctor / UX / Hub immutability]
    E --> PR[Public-source PR]
    PR --> CI[source-gate + repository-governance + release-policy]
    CI --> REL[Immutable GitHub Release]
```

Disposable qualification is deliberately classified as **prequalification**, not production approval. Final release evidence still requires the applicable real production boundary checks.

## Evidence

Current identities are intentionally **not duplicated in prose**. They are available from machine-readable or immutable sources:

- [Latest GitHub Release](https://github.com/efremov-aleksei-96/keelaryn/releases/latest) — published install/update assets and release immutability.
- [`PUBLIC_PROVENANCE.json`](PUBLIC_PROVENANCE.json) — current Manager identity, framework identity and production qualification facts.
- [`PUBLIC_FILE_MANIFEST.json`](PUBLIC_FILE_MANIFEST.json) — deterministic hashes for authoritative Manager and Gate Framework source sets.
- [`REPOSITORY_GOVERNANCE.json`](REPOSITORY_GOVERNANCE.json) — required checks, merge policy, Actions supply-chain policy and release policy.
- [`tests/framework/manager-gate/`](tests/framework/manager-gate/) — reusable Windows gate source.
- [Remote qualification](docs/REMOTE_QUALIFICATION.md) — synthetic/disposable evidence semantics and security boundary.

## Interesting failure modes and lessons

The project deliberately preserves negative engineering lessons rather than presenting only successful releases:

- isolated build roots exposed release nondeterminism that a same-root rebuild could hide;
- an issued AI_CONTEXT candidate was rejected and corrected in a new Manager version instead of silently replacing candidate bytes;
- update qualification includes injected failure and rollback verification, not only the happy path;
- ZIP/filesystem validation treats Windows path rules, traversal, collisions and reparse points as part of the input contract;
- test infrastructure is itself a trust boundary, so reusable gate changes are qualified separately from Manager product changes.

The detailed stories and supporting repository history are in [Engineering case study](docs/ENGINEERING_CASE_STUDY.md).

## Reliability and security model

Keelaryn is designed for a trusted local operator, not as a sandbox for arbitrary hostile code. It fails closed around the boundaries that can damage local state or invalidate release evidence:

- exact managed-file identity;
- fresh validation at transaction/commit boundaries;
- rollback snapshots and post-update validation;
- package/ZIP path and filesystem safety checks;
- read-only production paths during qualification;
- explicit provenance for candidate, gate and release identity;
- personal Hub/runtime/private evidence excluded from public artifacts.

See [Security model](docs/SECURITY_MODEL.md).

## Technology

- Windows PowerShell 5.1 and .NET Framework APIs
- Windows filesystem/process integration and Restart Manager diagnostics
- JSON manifests and explicit schemas
- SHA-256 content identity
- ZIP packaging and defensive extraction/inspection
- Git and GitHub Actions on pinned OS-family runners
- deterministic release construction and artifact roundtrip validation
- Mermaid/Markdown documentation for architecture and operational flows

## Explore the repository

**20 seconds:** read this page and the architecture diagram above.

**About 1 minute:** open [Architecture overview](docs/ARCHITECTURE_OVERVIEW.md) and [Engineering case study](docs/ENGINEERING_CASE_STUDY.md).

**About 3–5 minutes:** inspect [Release engineering](docs/RELEASE_ENGINEERING.md), [Security model](docs/SECURITY_MODEL.md), [`PUBLIC_PROVENANCE.json`](PUBLIC_PROVENANCE.json) and the [latest release](https://github.com/efremov-aleksei-96/keelaryn/releases/latest).

For interview-oriented interpretation, see [Portfolio notes](PORTFOLIO.md).

## Try it on Windows

Use the packaged release rather than the repository source ZIP:

1. Open [Releases](https://github.com/efremov-aleksei-96/keelaryn/releases/latest).
2. Download `Keelaryn_v<version>_Windows.zip`.
3. Extract it to a normal writable folder.
4. Run `Keelaryn.cmd` inside the extracted `keelaryn` folder.
5. On a clean installation, create or connect a Hub and run **Doctor**.

Requirements: Windows 10/11 or Windows Server with **Windows PowerShell 5.1**.

See [Getting Started](GETTING_STARTED.md) for the complete onboarding path.

## Public repository boundary

The public tree includes product source, generic Hub governance/starter material and reusable qualification tooling. It excludes:

- `manager/state/**` runtime data;
- a real personal `hub/**`;
- private `tests/work/**` and `tests/results/**` evidence;
- CURRENT/CANDIDATE/APPROVED transports and generated release ZIPs;
- bindings, credentials, private keys and recovery material.

## License

Keelaryn is released under the [MIT License](LICENSE). The license covers public repository source and documentation, not uncommitted personal Hub/runtime data.
