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

A blocker finding pauses dependent implementation until the finding is resolved or explicitly re-scoped in durable state.

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

- `BLOCKER`: dependent work must stop;
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
→ run the complete read-only audit from the first required dimension
→ nearest-analog / reuse audit
→ if ANY new product finding appears at ANY severity:
     stop dependent implementation
     → fix one coherent finding slice
     → exact-head CI
     → discard the previous closure attempt
     → restart the COMPLETE audit from the first dimension
→ repeat until one complete pass finds ZERO new product findings
→ durably record CLEAN
→ only then unlock the next substantive stage
```

A partial re-check is never sufficient after a finding is fixed. A later clean check of only the affected subsystem does not restore qualification. The full audit must restart from the beginning and reach the end without discovering another new product finding.

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

P0-30C1's v27 qualification remains historical evidence. The current product boundary is hardened through **schema v29**.

Latest product fix head: `137e20fee3ebdd91b745962b39959198873c461c`.
Latest exact qualification head after the test-only correction: `1a213edf688881a3faa14dcef32dec2e4a5e590c`.

Exact-head CI run `36299795960`: validate PASS, Ubuntu 24.04 PASS, Windows 2025 PASS.

Schema v28 resolved `AUDIT_C1_B1_IDENTITY_CAUSAL_TIME_AUTHORITY`: RemoteHistory authority creation time is bound to its sealed exact publication and source-bound SAME/NEW provenance is causal and schema-guarded.

The next full audit found `AUDIT_C1_B2_GENERIC_REMOTE_IDENTITY_CAUSAL_TIME`: generic non-source-bound RemoteHistory SAME/NEW could return before the RemoteHistory causal-time check, and generic accepted decision/receipt rows lacked equivalent SQLite application authority. Schema v29 resolves that boundary without a new durable table or second identity model: every RemoteHistory acceptance is causal to scan start and current authority creation, generic RemoteHistory decision/receipt writes require the existing connection-local identity capability, and migration from v28 rejects pre-existing noncausal accepted provenance.

The B2 fix is **RESOLVED_PENDING_REQUALIFICATION_AUDIT**, not a CLEAN declaration. P0-30C2 remains **LOCKED**. Only a fresh complete audit on the latest authoritative HEAD with zero new BLOCKER/HIGH/MEDIUM/LOW product findings may durably record CLEAN and unlock C2.

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


## 8A. Zero-findings closure loop

This project uses a stricter closure rule than ordinary retrospective sampling.

A stage or boundary is not closable merely because the latest defect was fixed, its targeted regression is green, exact-head CI is green, or the previously failing subsystem now passes.

Closure requires a fresh complete audit pass after the latest fix.

```text
FULL AUDIT FROM SCRATCH
↓
new finding?
├─ YES → stop → fix one coherent slice → exact-head CI → restart FULL AUDIT FROM SCRATCH
└─ NO  → record CLEAN → unlock dependent stage
```

Rules:

1. Any newly discovered BLOCKER, HIGH, MEDIUM, or LOW product finding invalidates the current closure attempt.
2. Any failed closure attempt that reveals a real product defect also invalidates the current closure attempt.
3. Test-only, metadata-only, and audit-tool corrections do not by themselves qualify product behavior; if they occur before closure, the audit restarts on the new authoritative HEAD.
4. Audit-tool/harness failure without a product mutation or product finding is recorded as an interrupted audit, not as a clean pass; restart the full audit.
5. No dependent substantive stage may begin while the zero-findings loop is active.
6. A clean pass means the engineer reached the end of all required audit dimensions on the latest authoritative HEAD without finding any new product defect.
7. The CLEAN result must be recorded durably before the next stage is unlocked.

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
