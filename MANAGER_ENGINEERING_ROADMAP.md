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

Priority is relative and must be reconsidered whenever new defects, security findings, release constraints or dependency changes appear. Correctness, rollback/data safety, deterministic behavior and security always outrank convenience, automation and optimization.

### Priority ordering rule

When two roadmap items compete, rank them by the first material discriminator in this order:

1. current release blocker / possibility of incorrect durable state;
2. data loss, rollback failure, cross-instance contamination or security exposure;
3. repeated-defect prevention and missing executable validation;
4. recovery/diagnostic availability under damaged or partial state;
5. provenance, reproducibility and autonomous context recovery;
6. removal of manual steps that are themselves error-prone;
7. performance / context / maintenance cost;
8. generic UX convenience;
9. speculative capability.

A lower-numbered roadmap item is not automatically more important than a later item; `Priority` and current dependencies are authoritative. Merge overlapping ideas rather than creating parallel backlog items that describe the same underlying capability.

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
- **Status:** ACTIVE
- **Goal:** make registry activation, switching, binding/rebinding, pending input reachability and commit-boundary validation safe under broken/partial states.
- **Required properties:** target-driven recovery; identity-preserving rebind; no silent stranded Hub inputs; commit predicate at least as strong as resulting state; durable/post-commit outcomes explicit; Doctor/diagnostic branches that depend on registry state execute end-to-end in real disposable state, not only through AST/static assertions.
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

### R-013 — Evidence-backed defect and audit lifecycle

- **Priority:** P1
- **Status:** PLANNED
- **Goal:** make `open -> fixed -> qualified/released` transitions first-class repository state instead of ad-hoc JSON edits, while preserving the historical audit that originally proved the defect.
- **Required properties:** a defect cannot close without an exact fix version, permanent executable/static coverage and evidence identity; resolved audits retain their original scenarios and rejected evidence; reopening is explicit rather than destructive history rewriting.
- **Safety:** a green development run alone must never turn a defect into production-qualified state; closure and production qualification remain separate transitions.
- **Dependency:** R-002 knowledge model and stable qualification receipts.
- **Exit:** validated closure/receipt schema binds defect IDs, exact source identity, coverage paths and qualifying evidence, and the validator accepts both active and historically resolved audits without weakening blocker enforcement.

### R-014 — Engineering tooling self-regression and historical-source resilience

- **Priority:** P1
- **Status:** ACTIVE
- **Goal:** gate/risk/knowledge/release-governance tooling must validate its own broken historical states and candidate-bound metadata without silently dropping risk, accepting stale identities, or making cleanup of historical source impossible.
- **Required properties:** current/HEAD source remains fail-closed on parse errors; historical/base parse failure uses an explicit conservative path-level fallback; the fallback is visible in generated risk context; reusable tooling behaviors have permanent regressions; `PUBLIC_FILE_MANIFEST.json` is reproducible from the exact source tree; `PUBLIC_PROVENANCE.json` must identify the same Manager version, installation digest, managed-set digest, Framework revision and development baseline as the canonical source/state; an unqualified development line must not inherit a predecessor's Full Gate/production acceptance receipt; changes to either metadata file or its verifier trigger ordinary development CI.
- **Trigger:** Manager 4.17.9 knowledge closure exposed compact PowerShell parser defects and a historical-source AST failure. Manager 4.17.10 g1 then froze with a stale 4.17.9 `PUBLIC_FILE_MANIFEST.json`; after that was guarded, g2 qualification exposed a second stale candidate-bound file, `PUBLIC_PROVENANCE.json`, still identifying 4.17.9 and retaining predecessor production-validation data. Both candidate attempts were rejected without mutating frozen bytes.
- **Exit:** permanent risk-context regression proves historical unparsable deletion succeeds conservatively and current unparsable source still fails; Development Validation fails closed on stale/noncanonical public manifest and on public provenance/version/hash/baseline/stage inconsistency via repository-resident verification before freeze.

### R-015 — Structured intake of reusable CI and qualification lessons

- **Priority:** P2
- **Status:** PLANNED
- **Goal:** when CI/gate/qualification diagnosis reveals a reusable defect class, invariant gap, tooling weakness or future architecture idea, produce a durable repository-resident intake instead of relying on chat history to remember it.
- **Design direction:** compact machine-readable finding with classification, affected subsystem, recurrence risk, candidate invariant/root-cause/roadmap links and evidence reference; human/Chat Manager reconciliation decides whether it becomes a defect, invariant, regression or roadmap item.
- **Execution-process lesson:** remote Manager development should operate from one explicit atomic goal, reuse already-discovered tool/schema knowledge, and emit progress only on evidence-bearing state transitions (commit, run result, blocker). Repeated tool rediscovery or status-only loops are reusable process findings, not progress.
- **Safety:** intake automation may not close blockers, mutate product bytes, weaken thresholds or publish personal Hub data; failed/rejected evidence remains preserved.
- **Dependency:** R-001/R-002 and evidence-backed lifecycle semantics from R-013.
- **Exit:** CI can emit deterministic reusable finding records and a later session can reconcile them without reconstructing the originating chat/log narrative.

## Roadmap maintenance policy

The roadmap is a mandatory sink for **meaningful reusable ideas** discovered during implementation, review, testing, CI diagnosis, qualification, production acceptance or architecture discussion. Do not rely on chat history to preserve them.

Capture an idea when it could plausibly improve any of the following even if it is not actionable in the current release:

- correctness or transaction safety;
- rollback/recovery behavior;
- security or trust boundaries;
- repeated-defect prevention;
- diagnostics / Doctor / SelfTest;
- provenance and release governance;
- multi-Hub isolation and lifecycle safety;
- autonomous context recovery between sessions;
- CI/gate reliability and evidence quality;
- Windows portability/compatibility;
- performance, hashing, scans or context efficiency;
- remote development / reduced maintainer manual work;
- Hub automation or transport ergonomics;
- generic UX/onboarding;
- maintainability, simplification or removal of duplicated mechanisms.

The backlog should be broad but not noisy. Do not create roadmap items for a one-off implementation detail that is fully resolved inside the current change unless it revealss a reusable class of problem. If a new observation belongs to an existing item, extend that item rather than duplicating it.

### Reprioritization rule

Re-evaluate priorities when:

- a new defect or review finding is confirmed;
- a supposedly isolated failure reveals a recurring root-cause class;
- a roadmap item becomes a dependency of a current release blocker;
- automation would eliminate a repeated unsafe/manual operation;
- security or privacy assumptions change;
- qualification evidence shows an existing control is insufficient;
- a prerequisite becomes complete, making a deferred item actionable.

Promotion and demotion are both expected. Preserve the reason when a non-obvious priority change materially affects sequencing.

## Intake rule for new ideas

When a future idea appears during development, add it here before leaving the topic if it has reusable architectural, safety, automation, reliability, performance, maintenance or UX value — not only when it is explicitly “deferred”. Each item should contain at minimum:

- stable roadmap ID;
- priority and status;
- goal / user value;
- dependency or reason for deferral;
- key safety constraints where applicable;
- a concrete exit condition or trigger for revisiting it.

Before adding a new ID, check whether an existing roadmap item should absorb it. After adding or materially changing an item, reconsider the relative priority of neighboring items rather than merely appending it to the end.

Do not implement a parked idea merely because it exists here. The current development state, risk model and applicable release blockers decide what is executable now.

## Privacy and provenance boundary

This roadmap may describe generic Hub architecture but must never contain personal Hub payloads, private records, credentials, tokens or secrets. Exact candidate/release identities belong in current development state or qualification provenance, not duplicated here unless a historical architectural decision genuinely requires a stable reference.
