# Keelaryn as a portfolio project

Keelaryn is strongest as evidence of **engineering process around a real stateful system**, not as a demo application or a personal note collection.

The project shows how requirements become architecture, validation boundaries, failure handling, release evidence and operational safeguards.

## Roles this project supports

The most credible fit is entry-level or junior work involving:

- Technical Support / L2 Support;
- IT Operations / Windows Operations;
- Support Engineering / Technical Support Engineering;
- PowerShell / Windows automation;
- QA with a technical or automation focus;
- Junior system administration;
- DevOps-adjacent roles alongside broader Git/Linux/CI/CD skills;
- security-minded operations or application support.

The project should not be used to imply senior-level or commercial production experience.

## What an employer can verify

| Engineering area | Public evidence |
|---|---|
| Windows automation | PowerShell 5.1 runtime, command launchers, filesystem/process integration and Windows-specific tests |
| Reliability | transactional update, rollback snapshots, fault injection, Doctor/SelfTest and post-update validation |
| Release engineering | deterministic builds, artifact manifests, exact tested UPDATE identity and immutable release policy |
| Testing | SourceGate, disposable Full Gate, production-boundary qualification, regression/performance controls |
| Security engineering | package/path/reparse defenses, read-only qualification boundaries and public/private data separation |
| CI/CD | protected `main`, required checks, conditional release gate, pinned runner families and SHA-pinned Actions |
| Systems architecture | product/state separation, explicit identity layers, migration contracts and lifecycle isolation |
| Troubleshooting | diagnostic reports, lock-owner diagnostics, explicit failure paths and recovery-first behavior |
| AI-assisted engineering | generated lossless AI_CONTEXT routes tied to exact managed runtime/source identity |

For machine-readable current release facts, use [`PUBLIC_PROVENANCE.json`](PUBLIC_PROVENANCE.json) and [`PUBLIC_FILE_MANIFEST.json`](PUBLIC_FILE_MANIFEST.json) rather than presentation prose.

## Strong interview stories

The most useful stories are not feature lists; they show a problem, failed assumption, corrective design and validation evidence.

1. **Transactional update and rollback** — why updating a stateful local installation requires staging, snapshots, fault injection and post-install validation.
2. **Deterministic build isolation** — why building twice in the same directory can hide nondeterminism, and why isolated roots became part of the gate.
3. **Rejected candidate discipline** — why an issued candidate is never silently rewritten after a defect is discovered.
4. **Production Hub immutability** — why real user data is useful as a read-only compatibility boundary but unacceptable as a mutable test target.
5. **AI_CONTEXT integrity** — why reducing model context still requires exact binding to the source/runtime it represents.
6. **Windows filesystem edge cases** — traversal, reserved device names, collisions, reparse points and sharing violations are treated as contract inputs, not rare afterthoughts.
7. **Remote qualification** — how deep Windows testing was moved to a disposable hosted runner without weakening final production approval semantics.

See [Engineering case study](docs/ENGINEERING_CASE_STUDY.md) for the detailed versions of these stories.

## Recruiter / hiring-manager path

A first-time visitor should be able to use the repository at three depths:

- **~20 seconds:** README opening, architecture diagram and engineering-challenges table.
- **~1 minute:** [Architecture overview](docs/ARCHITECTURE_OVERVIEW.md) plus the top of the [Engineering case study](docs/ENGINEERING_CASE_STUDY.md).
- **~3–5 minutes:** [Release engineering](docs/RELEASE_ENGINEERING.md), [Security model](docs/SECURITY_MODEL.md), current provenance and the latest immutable release.

The strongest signal is not project size by itself. It is that the repository contains explicit evidence for **rollback, reproducibility, negative testing, qualification identity and release governance**.

## What may look unusual

Keelaryn has more release/governance machinery than a typical junior portfolio repository. That is useful only if the reason remains visible:

- the Hub is stateful and user-owned;
- updates therefore need rollback and migration guarantees;
- exact artifact identity matters because a release is useful only if it is the candidate that actually passed;
- Windows PowerShell 5.1 and filesystem behavior create compatibility constraints that need real Windows validation;
- personal data must remain outside generic/public artifacts.

The public presentation should therefore lead with the engineering problem and evidence, not with internal naming or the size of the documentation set.

## What not to claim

- Do not present Keelaryn as commercial production experience.
- Do not claim that every component was authored without AI assistance.
- Do not claim middle/senior engineering level from the project alone.
- Do not claim a disposable hosted Full Gate is equivalent to final production qualification.
- Do not publish or demonstrate a personal Hub; use Genesis or sanitized disposable instances.

## Concise positioning

> **Keelaryn is an independent Windows automation and state-management project demonstrating transactional updates, deterministic release engineering, integrity validation, migrations, diagnostics, CI/CD, rollback and security-minded failure handling around a real stateful workload.**

That framing is both stronger and more accurate than describing it primarily as a knowledge-management system.
