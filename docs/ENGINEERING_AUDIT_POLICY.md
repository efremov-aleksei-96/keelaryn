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
→ read-only implementation + call-site audit
→ nearest-analog / reuse audit
→ classify findings
→ durably record audit
→ fix one coherent blocker slice at a time
→ exact-head CI
→ re-audit the boundary before enabling dependent live behavior
```

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

P0-29D retrospective at head `b04d321989a379ea54594d1a2323d99ac4b19f23` reset the rolling substantive-slice counter to zero after detecting that the previous counter had not been incremented across at least six qualified substantive slices.

Status: **BLOCKERS FOUND**. The reset records that the retrospective occurred; it does not authorize dependent work. P0-29C3 remains paused until its lifetime/incarnation blockers are resolved and re-audited.

The next retrospective is mandatory at the end of the **current substantive stage**, before any subsequent substantive stage begins. Event triggers may require an earlier audit within the stage.

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
