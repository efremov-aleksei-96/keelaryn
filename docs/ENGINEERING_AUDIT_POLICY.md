# Keelaryn Engineering Audit Policy

Status: **MANDATORY DEVELOPMENT GATE**

Purpose: prevent locally green slices from compounding into a system whose trust, recovery, identity or portability assumptions are wrong.

This policy complements `KEELARYN_CANONICAL.md`; it does not redefine product architecture.

## 1. Audit cadence

Keelaryn uses **event-triggered audits plus a maximum slice interval**.

A retrospective architecture/reuse/correctness audit is mandatory:

1. before enabling a new live external/provider trust boundary;
2. before enabling a new durable user/corpus mutation path;
3. before exposing identity/state mutation through CLI, MCP, HTTP or another product API;
4. after a material change to Artifact identity, provider identity, transactions, rollback/recovery, schema authority or security/credential semantics;
5. before candidate freeze / Source-Full Gate / release qualification;
6. after a major architectural reset or migration;
7. **no later than after four qualified substantive development slices since the previous retrospective**, even if no trigger above fired.

A blocker finding pauses dependent implementation until the finding is resolved or explicitly re-scoped in durable state.

Tiny mechanical fixes and documentation-only commits do not consume the four-slice budget unless they materially change semantics.

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

The foundation retrospective at head `467b4e810041532ed39e47dd8b5c16a98c3df5dc` resets the rolling substantive-slice counter to zero.

The next full retrospective is mandatory no later than four subsequently qualified substantive slices, and sooner if a trigger fires.

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

