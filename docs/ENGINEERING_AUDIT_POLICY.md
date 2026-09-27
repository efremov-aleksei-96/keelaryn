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
→ run ONE COMPLETE read-only audit from the first required dimension
→ record every defensible finding and CONTINUE through all remaining dimensions
→ nearest-analog / reuse audit
→ freeze the collected finding set for this cycle
→ remediate the ENTIRE collected CRITICAL/BLOCKER set in coherent safe slices
     for each product slice:
       → targeted/adversarial regression
       → exact-head CI / qualification
       → continue to the next remediation slice
     DO NOT restart the full audit between individual remediation slices
     if a new CRITICAL/BLOCKER is exposed during remediation:
       → record it
       → add it to the current remediation set
       → continue remediation
→ when the current CRITICAL/BLOCKER remediation set is fully resolved and qualified:
     run ONE COMPLETE audit again from the first dimension
→ open CRITICAL/BLOCKER findings?
   ├─ YES → freeze the new complete finding set → remediate it fully → one new full audit
   └─ NO  → durably record critical gate CLEAR → dependent development may resume
```

The process does **not** require the audit to stop finding every HIGH/MEDIUM/LOW issue before development can ever continue. Those findings remain durable and must be resolved or explicitly carried with rationale and a target stage/deadline. The critical development gate is cleared only by a complete post-remediation audit with zero open CRITICAL/BLOCKER findings.

A targeted subsystem re-check or exact-head CI is sufficient to qualify an individual remediation slice inside the current remediation set; it is **not** a substitute for the one complete post-remediation audit that clears the stage gate.

## 6. Qualification meaning

Qualification is scoped evidence, never an eternal declaration that a subsystem is perfect.

A later audit may narrow an earlier qualification without erasing its valid evidence.

Example:

```text
transaction mechanics: QUALIFIED
public/runtime trust boundary: NOT YET QUALIFIED
```

This distinction is preferred to pretending an earlier green slice proved behavior it did not test.

## 7. Current development-state authority

This reusable policy MUST NOT duplicate volatile branch HEADs, schema revisions, open findings, CI run IDs, or the currently permitted remediation slice.

The sole live development clock is:

```text
DEVELOPMENT_STATE.json
```

Timestamped retrospectives, qualification records, CI evidence and historical audit documents remain valid provenance for the exact HEADs they qualified, but they never override the current `DEVELOPMENT_STATE.json`.

After chat loss, timeout, connector interruption, or a new engineering session:

1. reconcile the remote branch and exact product/control HEADs;
2. read `DEVELOPMENT_STATE.json`;
3. reconcile relevant CI/VPS/provider evidence;
4. resume from the first incomplete work-ledger item;
5. never infer the current permitted product slice from an older PASS/QUALIFIED document or from this reusable policy file.

Normative process documents define stable rules. Volatile current development state belongs only in the durable development-state/checkpoint authority.

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

The project audits for breadth before remediation. Discovery does not stop at the first defect, and remediation does not trigger a new full audit after every individual fix.

A stage or boundary is not closable merely because the latest defect was fixed, its targeted regression is green, exact-head CI is green, or the previously failing subsystem now passes.

The gate uses **batch discovery + complete critical remediation + one full re-audit**.

```text
FULL AUDIT COLLECTION FROM SCRATCH
↓
record ALL defensible findings through every required dimension
↓
freeze the cycle's finding set
↓
remediate ALL CRITICAL/BLOCKER findings in coherent safe slices
↓
targeted regressions + exact-head qualification for each changed product head
↓
when the current CRITICAL/BLOCKER set is fully resolved:
    FULL AUDIT COLLECTION FROM SCRATCH
↓
open CRITICAL/BLOCKER findings?
├─ YES → freeze the new full set → remediate all critical findings → one new full audit
└─ NO  → record critical gate CLEAR → dependent development may resume
```

Rules:

1. Newly discovered findings are recorded durably and discovery continues through the remaining audit dimensions unless continuing would risk data loss or invalidate evidence.
2. Remediation begins only after the current full collection pass is complete.
3. During remediation, **do not run a complete audit after each individual fix**. Each product fix receives its targeted/adversarial regressions and exact-head qualification, then remediation continues with the next item in the current critical set.
4. If targeted testing or implementation work exposes another CRITICAL/BLOCKER during remediation, record it and add it to the current remediation set. Do not interrupt the remediation set with a full audit.
5. Run the next complete audit only after the current CRITICAL/BLOCKER remediation set is fully resolved and qualified.
6. Test-only, metadata-only, documentation-only, and audit-tool corrections do not by themselves qualify product behavior.
7. Audit-tool/harness failure without a product mutation or product finding is recorded as an interrupted audit; resume from authoritative durable state and the work ledger.
8. No dependent substantive stage may begin while any CRITICAL/BLOCKER finding remains open or before the required post-remediation full audit has cleared the critical gate.
9. The development gate clears only after a complete post-remediation audit reaches the end of all required dimensions with zero open CRITICAL/BLOCKER findings.
10. HIGH/MEDIUM/LOW findings remain tracked and must be resolved or explicitly carried with rationale and a target stage/deadline. They do not silently disappear, but they do not by themselves keep the critical gate closed.
11. The gate result must be recorded durably before the next substantive stage is unlocked.

## 8B. Interruption-safe durable work ledger

Long-running audits and multi-step engineering work MUST maintain a durable work ledger outside ChatGPT conversation memory.

Rules:

1. Pin an immutable `audited_product_head` for the active read-only audit. Metadata/documentation checkpoints may advance the control branch without changing the product snapshot under audit.
2. Record the ordered work queue with explicit `DONE / IN_PROGRESS / TODO` states, plus any candidate findings that are not yet sufficiently proven to become formal findings.
3. Update the ledger after each completed audit dimension or other meaningful multi-step boundary, and before an expected long external wait when practical.
4. After chat loss, timeout, connector interruption, or a maintainer message reporting lost connection, first reconcile GitHub/VPS/CI and then continue from the first ledger item that is not `DONE`. Do not reconstruct the plan from conversation memory alone.
5. Never blindly repeat a mutation after interruption. Reconcile durable external authority first and distinguish a committed operation from failed post-verification.
6. Uncommitted scratch/prototypes are non-authoritative. They may be reused only after their base HEAD and contents are revalidated against current authority.
7. If an actual product commit changes the audited product bytes, close or invalidate the current collection pass as appropriate and pin a new product HEAD before continuing.

This ledger is D0 development infrastructure: it exists specifically so a new chat can recover not only the latest result, but also the exact remaining sequence of work.

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
