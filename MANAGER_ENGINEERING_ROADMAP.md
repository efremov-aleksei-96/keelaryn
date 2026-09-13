# Keelaryn Manager Engineering Roadmap

This document is the durable repository-resident backlog for architectural and engineering ideas that must not be lost when work moves between chats, branches, releases or maintainers.

It is deliberately **not** the authoritative record of the current development branch, current HEAD, candidate identity or qualification state. Volatile execution state belongs in `MANAGER_DEVELOPMENT_STATE.json`; exact historical qualification belongs in immutable commits, PRs, workflow runs and release/gate evidence.

## Priority model

| Priority | Meaning |
| --- | --- |
| **P0** | Required for safe continuation of current engineering work or candidate freeze. |
| **P1** | Next major correctness / safety capability after current blockers. |
| **P2** | High-value systemic improvement; implement when P0/P1 dependencies are stable. |
| **P3** | Valuable future capability or optimization; preserve design intent but do not let it distract from correctness work. |
| **P4** | Research / speculative idea. No implementation commitment yet. |

Statuses: `ACTIVE`, `NEXT`, `PLANNED`, `PARKED`, `RESEARCH`, `DONE`, `REJECTED`.

Priority is relative and may be changed when new defects, security findings or release constraints appear. Correctness, rollback/data safety, deterministic behavior and security always outrank convenience and automation.

## Roadmap

### R-001 — Repository-resident development state

- **Priority:** P0
- **Status:** ACTIVE
- **Goal:** a new Manager-development chat or maintainer can discover the authoritative branch, stable lineage identities, current blockers, qualification state and next exact goal directly from the repository without requiring a human handoff.
- **Design:** machine-readable `MANAGER_DEVELOPMENT_STATE.json`; current branch HEAD is resolved from GitHub rather than stored as a self-referential value in the same commit.
- **Safety:** no personal Hub data; no secrets; development state cannot itself qualify a candidate.
- **Exit:** schema/validation exists and development CI verifies it.

### R-002 — Executable Manager engineering knowledge / Risk-Defect Gate

- **Priority:** P0
- **Status:** ACTIVE
- **Goal:** preserve defect classes, invariants, state-machine expectations, audits and regression obligations in repository-resident machine-readable form and use them before candidate freeze.
- **Safety:** open release blockers must remain visible and must make the strict pre-freeze gate fail closed.
- **Exit:** audit references are validated, task-specific risk context includes applicable audit scenarios, and the strict gate is demonstrated to reject unresolved blockers.

### R-003 — Multi-Hub convergence and recovery completeness

- **Priority:** P0
- **Status:** NEXT
- **Goal:** make registry activation, switching, binding/rebinding, pending input reachability and commit-boundary validation safe under broken/partial states.
- **Required properties:** target-driven recovery; identity-preserving rebind; no silent stranded Hub inputs; commit predicate at least as strong as resulting state; durable/post-commit outcomes explicit.
- **Dependency:** R-001 and R-002 sufficiently operational to preserve context and enforce regressions.
- **Exit:** permanent convergence regression suite + development validation + Risk/Defect Gate PASS before candidate freeze.

### R-004 — Hub artifact handoff protocol

- **Priority:** P2
- **Status:** PLANNED
- **Goal:** define a stable, machine-readable protocol for transferring Hub `CURRENT`, `CANDIDATE`, `APPROVED`, candidate transport and operation receipts between Chat Manager and local Keelaryn tooling without manual ZIP handling.
- **Conceptual operations:** identify/export Hub instance; submit candidate; validate candidate; submit/install approved artifact; query transaction result; run Doctor; return provenance receipt.
- **Required properties:** immutable `instance_id`; exact artifact hashes; ancestry checks; explicit transaction IDs; replay protection/idempotency; fail-closed cross-instance handling; no personal Hub content in public GitHub.
- **Dependency:** multi-Hub invariants and transaction semantics must be stable first.
- **Exit:** protocol schema/spec + disposable end-to-end reference implementation.

### R-005 — Local Keelaryn Agent / Hub Bridge

- **Priority:** P2
- **Status:** PLANNED
- **Goal:** a small local Windows-side agent/service that safely bridges remote orchestration to Manager and per-instance Hub inbox/outbox operations.
- **Responsibility:** transport and orchestration only; Manager remains authoritative for validation/commit semantics.
- **Non-goal:** the agent must not independently edit personal Hub bytes or bypass Manager transaction rules.
- **Security requirements:** least privilege; explicit allowlisted operations; authenticated commands; local audit log; bounded artifact staging; no arbitrary command execution surface; revocable trust; fail closed when identity or state is ambiguous.
- **Dependency:** R-004 protocol plus stable Manager APIs/commands.
- **Exit:** sanitized disposable-Hub prototype with threat model and rollback/recovery tests.

### R-006 — Automated Worker -> Chat Manager -> Manager approval pipeline

- **Priority:** P3
- **Status:** PARKED
- **Goal:** normal Hub maintenance can proceed with minimal human file movement while preserving separation of duties.
- **Intended roles:** Worker proposes `CANDIDATE`; Chat Manager independently reconciles scope/ancestry/preservation and produces or authorizes `APPROVED`; local Manager validates and commits; Agent transports/orchestrates.
- **Human involvement:** only for ambiguous semantic conflicts, destructive changes, trust changes, unrecoverable corruption or policy decisions.
- **Dependency:** R-004/R-005 and a formal approval/reconciliation contract.
- **Exit:** end-to-end disposable workflow proves no actor can silently bypass approval or cross-instance boundaries.

### R-007 — Hub artifact transport becomes invisible UX

- **Priority:** P3
- **Status:** PARKED
- **Goal:** immutable ZIP/packages may remain an internal transport format, but ordinary users should interact with semantic operations (`propose`, `approve`, `install`, `rollback`) rather than manually downloading/moving archives.
- **Dependency:** R-004/R-005.
- **Exit:** standard Hub update/reconciliation requires no manual archive placement in the healthy path.

### R-008 — Offline/reconnect-safe orchestration queue

- **Priority:** P3
- **Status:** PARKED
- **Goal:** tolerate laptop sleep, network loss, VPN changes and remote-session interruption without ambiguous duplicate operations.
- **Required properties:** durable transaction IDs; idempotent retry; explicit staged/validated/committed/post-verified states; stale-command rejection; deterministic resume.
- **Dependency:** R-004 transaction protocol.

### R-009 — Trusted-device and Agent security model

- **Priority:** P2
- **Status:** PLANNED
- **Goal:** formal threat model and trust bootstrap for any future remote-to-local Keelaryn control plane.
- **Questions to resolve:** device enrollment/revocation; command authentication; artifact authenticity; local secret storage; replay resistance; privilege separation; emergency disable; audit/provenance retention.
- **Rule:** no remote automation is enabled for production personal Hub until this model is explicitly qualified.

### R-010 — Private Hub transport/storage research

- **Priority:** P4
- **Status:** RESEARCH
- **Goal:** evaluate whether encrypted/private remote artifact storage is useful for Hub handoff, recovery or multi-device operation without turning personal Hub data into public repository material.
- **Constraints:** zero dependence on public GitHub for personal Hub contents; encryption/key ownership and recovery must be explicit; remote storage must never become an implicit canonical Hub without a separately qualified design.

### R-011 — Autonomous bootstrap for future ChatGPT sessions

- **Priority:** P1
- **Status:** PLANNED
- **Goal:** a future session should need only an instruction equivalent to “continue Manager development”; it can then read the repository development state, engineering roadmap, relevant knowledge/risk context and exact GitHub branch state itself.
- **Dependency:** R-001 plus compact deterministic context generation.
- **Exit:** documented bootstrap route requires no manually copied chat handoff for ordinary continuation.

### R-012 — Context-budget optimization without information loss

- **Priority:** P2
- **Status:** PLANNED
- **Goal:** select exact changed functions, applicable invariants, defects, state-machine rules, audits and current operational state instead of loading full Manager history.
- **Rule:** optimization may remove duplicate context, never required validation or provenance.
- **Dependency:** engineering knowledge and risk-context tooling.

## Intake rule for new ideas

When a future idea appears during development and is intentionally deferred, add it here before leaving the topic. Each item should contain at minimum:

- stable roadmap ID;
- priority and status;
- goal / user value;
- dependency or reason for deferral;
- key safety constraints where applicable;
- a concrete exit condition or trigger for revisiting it.

Do not implement a parked idea merely because it exists here. The current development state and applicable release blockers decide what is executable now.

## Privacy and provenance boundary

This roadmap may describe generic Hub architecture but must never contain personal Hub payloads, private records, credentials, tokens or secrets. Exact candidate/release identities belong in current development state or qualification provenance, not duplicated here unless a historical architectural decision genuinely requires a stable reference.
