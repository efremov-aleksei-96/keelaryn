# Keelaryn Engineering Audit Policy

Status: **MANDATORY DEVELOPMENT GATE**

Purpose: prevent locally green slices from compounding into a system whose trust, recovery, identity or portability assumptions are wrong.

This policy complements `KEELARYN_CANONICAL.md`; it does not redefine product architecture.

## 1. Audit cadence

Keelaryn uses **per-substantive-stage audits plus event-triggered audits**.

A retrospective architecture/reuse/correctness audit is mandatory:

1. before enabling a new live external/provider trust boundary;
2. before enabling a new durable user/corpus mutation path;
3. before exposing identity/state mutation through CLI, MCP, HTTP or another product API;
4. after a material change to Artifact identity, provider identity, transactions, rollback/recovery, schema authority or security/credential semantics;
5. before candidate freeze / Source-Full Gate / release qualification;
6. after a major architectural reset or migration;
7. **after every substantive development stage, before the next substantive stage begins**, even if no other trigger above fired.

A BLOCKER or explicitly-classified CRITICAL finding locks dependent implementation. During a full audit collection pass, discovery continues read-only across the remaining dimensions so the complete finding set can be established before remediation begins.

A substantive stage is a coherent unit that changes or qualifies product behavior, durable authority, provider/runtime integration, schema/transaction semantics, recovery behavior, or another meaningful architectural boundary. Tiny mechanical fixes, narrow test-only corrections, documentation-only commits, and qualification metadata inside the same stage do not create a separate audit ceremony unless they materially change semantics.

The audit is part of stage completion: implementation + exact-head CI alone do **not** close a substantive stage. The stage closes only after its read-only architecture/correctness/reuse audit is complete and any BLOCKER finding is durably handled.

## 2. Required audit dimensions

Every substantive retrospective checks at least:

- canonical invariants versus implementation;
- durable-authority boundaries;
- replay/idempotency/interruption behavior;
- transaction atomicity and mutation-boundary revalidation;
- schema migration and rollback implications;
- negative/adversarial cases, not only happy-path tests;
- runtime call sites: whether a mechanism spike has become reachable product behavior;
- cross-platform assumptions, especially Android/Windows portability;
- security/credential boundaries;
- recovery after lost local state / provider history gaps where applicable;
- stale documentation/state claims;
- dependency/reuse opportunities and nearest existing analogs.

## 3. Reuse audit

For every non-trivial subsystem, the retrospective revisits the closest available analogs, not only the original choices.

Record:
- what comparable systems do;
- which design/code/protocol/test ideas Keelaryn reuses;
- where Keelaryn intentionally differs because of Corpus-first invariants;
- whether a newer/better dependency now exists;
- whether a custom implementation should be replaced, wrapped or deleted.

A green internal test suite is not evidence that reinventing a subsystem was the right decision.

## 4. Evidence and severity

Audit findings are durable development state and are classified:

- `CRITICAL`: reserved for defects with immediate systemic data-safety, authority, or trust-boundary consequences; dependent work is locked;
- `BLOCKER`: correctness/authority defect that also locks dependent work and counts as critical for the development gate;
- `HIGH`: resolve before crossing the next trust/runtime boundary;
- `MEDIUM`: schedule explicitly; may proceed only if it cannot invalidate dependent correctness;
- `LOW`: cleanup/maintainability issue.

For each finding retain:
- exact audited Git HEAD;
- exact CI evidence;
- affected invariants/components;
- runtime reachability;
- external analog/source evidence where used;
- required correction;
- whether previous qualification remains valid, is narrowed, or is superseded.

## 5. Audit transaction discipline

Audits are read-only until findings are complete.

Do not mix discovery of a systemic issue with several speculative code mutations.

Workflow:

```text
reconcile authoritative HEAD / CI / runtime
→ run the COMPLETE read-only audit from the first required dimension
→ record every defensible finding and CONTINUE discovery across all remaining dimensions
→ nearest-analog / reuse audit
→ finish the collection pass with the full finding set
→ remediate the collected findings in coherent safe slices
→ exact-head CI / qualification for changed product heads
→ restart the COMPLETE audit from the first dimension
→ repeat audit → remediation → audit while any CRITICAL/BLOCKER finding remains open
→ when a complete post-remediation pass records ZERO open CRITICAL/BLOCKER findings:
     durably record the gate result
     → dependent development may resume
```

A partial re-check is never sufficient after remediation. A later clean check of only an affected subsystem does not restore qualification. HIGH/MEDIUM/LOW findings remain durable: resolve them or explicitly carry them with rationale and scheduling; they do not silently disappear merely because the critical gate is zero.

## 6. Qualification meaning

Qualification is scoped evidence, never an eternal declaration that a subsystem is perfect.

A later audit may narrow an earlier qualification without erasing its valid evidence.

Example:

```text
transaction mechanics: QUALIFIED
public/runtime trust boundary: NOT YET QUALIFIED
```

This distinction is preferred to pretending an earlier green slice proved behavior it did not test.

## 7. Current audit clock

P0-30C1's earlier v27 qualification remains historical evidence. The current product boundary is hardened through **schema v34** at `77b8d463db6a0cc13cba8f8ce1611aa863911c9b`.

Exact-head CI run `36302664547`: validate PASS, Ubuntu 24.04 PASS, Windows 2025 PASS.

Audit fixes through v34 are product-fixed but remain pending the required zero-findings full requalification pass. In particular: v31 validates reverse RemoteHistory provenance, v32 enforces one RemoteHistory NEW per provider lifetime, v33 seals core identity rows against UPDATE/DELETE, and v34 protects Google topology watermark mutation behind a narrow application capability.

The restarted full audit found `AUDIT_C1_B8_CORE_IDENTITY_INSERT_APPLICATION_AUTHORITY`: future Artifact, Revision, and local provider-binding creation is not yet protected by equivalent SQLite application authority. Direct SQL can create a Revision outside validated evidence/current-sequence semantics and can create a local provider binding outside NEW acceptance.

B8 is **OPEN**. P0-30C2 remains **LOCKED**. The only permitted substantive product slice is schema v35 core identity insert authority, followed by exact-head CI and a complete audit restart from the first dimension.


## 8. Parallel audit/research during execution

Audit and reuse research are continuous supporting activities, not only retrospective ceremonies.

Whenever the active transaction is waiting on CI, provider/runtime evidence, or another external read-only dependency, the engineer should use available time for independent read-only work where useful:

- inspect adjacent trust boundaries and call sites;
- search nearest comparable products, protocols, standards and mature implementations;
- check whether a custom mechanism can be replaced or simplified;
- design adversarial cases from external failure models;
- inspect portability implications for Windows, Linux/Android and provider-neutral behavior.

Requirements:

1. parallel work must be read-only unless it becomes the next explicitly reconciled mutation slice;
2. findings that affect correctness are recorded durably before dependent implementation advances;
3. external analog research is added to the reuse/audit evidence when it materially changes or validates a design;
4. never let a long-running CI job create a long silent period for the maintainer—report status periodically;
5. interruption recovery still begins from authoritative state, not from unfinished parallel scratch work.


## 8A. Full-collection critical-gate loop

The project audits for breadth before remediation. Discovery does not stop at the first defect.

A stage or boundary is not closable merely because the latest defect was fixed, its targeted regression is green, exact-head CI is green, or the previously failing subsystem now passes.

The gate requires a fresh complete audit pass after remediation.

```text
FULL AUDIT COLLECTION FROM SCRATCH
↓
record ALL defensible findings through every required dimension
↓
remediate collected findings
↓
exact-head qualification
↓
FULL AUDIT COLLECTION FROM SCRATCH
↓
open CRITICAL/BLOCKER findings?
├─ YES → remediation → repeat full audit
└─ NO  → record critical gate CLEAR → dependent development may resume
```

Rules:

1. Newly discovered findings are recorded durably and discovery continues through the remaining audit dimensions unless continuing would risk data loss or invalidate evidence.
2. Remediation begins only after the current full collection pass is complete.
3. Any remediation that changes product behavior requires exact-head qualification before the next full audit pass.
4. Test-only, metadata-only, documentation-only, and audit-tool corrections do not by themselves qualify product behavior.
5. Audit-tool/harness failure without a product mutation or product finding is recorded as an interrupted audit; resume or restart the collection pass from authoritative state as evidence permits.
6. No dependent substantive stage may begin while any CRITICAL/BLOCKER finding remains open.
7. The development gate clears only after a complete post-remediation audit pass reaches the end of all required dimensions with zero open CRITICAL/BLOCKER findings.
8. HIGH/MEDIUM/LOW findings remain tracked and must be resolved or explicitly carried with rationale; zero critical findings is not permission to erase or ignore them.
9. The gate result must be recorded durably before the next substantive stage is unlocked.

## 9. Stage-completion audit gate

Every substantive stage follows this default lifecycle:

```text
reconcile authoritative prestate
→ audit/reuse research before design where material
→ implement one coherent stage
→ exact-head CI / platform qualification
→ read-only stage retrospective
→ check blockers, regressions, duplicate mechanisms, unnecessary abstractions and reusable external solutions
→ durably record findings / simplify or fix if needed
→ only then mark the stage QUALIFIED and open the next substantive stage
```

The retrospective explicitly asks:

- did this stage introduce a new correctness or data-safety defect?;
- did it duplicate an existing Keelaryn mechanism?;
- did it add an abstraction/table/API that existing state already made unnecessary?;
- is there a mature external library/protocol/product pattern that should replace, simplify or test the custom implementation?;
- did the implementation weaken Android/Windows/Linux/provider-neutral portability?;
- did any durable state claim become stale or broader than the evidence actually qualifies?;

A green CI run is input to this audit, not a substitute for it.
