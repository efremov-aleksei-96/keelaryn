# Luna Perpetual Discovery Contract

**Status:** active development governance  
**Authority:** subordinate to `KEELARYN_CANONICAL.md`, live `DEVELOPMENT_STATE.json`, and `docs/DEVELOPMENT_CONTINUATION.md`

## 1. Purpose

Keep the Luna producer/throughput lane useful when the current explicit implementation queue is empty, occupied by Sol, blocked on CI/review/provider evidence, or temporarily contains only protected `SOL_REQUIRED` work.

Perpetual discovery is not random brainstorming and is not a second roadmap authority. It is a bounded evidence generator that continuously searches for concrete defects, proof gaps, reusable upstream work, performance risks, cross-platform hazards, stale assumptions, and direction mismatches that can be converted into ordinary work units.

## 2. Trigger

After every reconcile, Luna first consumes normal ready `LUNA_READY` work, then `EITHER_PROFILE`.

If none is ready and non-overlapping, Luna MUST attempt a discovery unit before concluding that no useful work exists. The same fallback applies while another lane owns the only explicit implementation scope or while ordinary CI/review/provider evidence is pending.

A separate `SOL_REQUIRED` unit blocks only itself and actual dependants.

## 3. Discovery catalog and priority

Choose the first high-value category that has not already been examined in the current cycle against the same authoritative baseline:

1. **DEFECT_ADVERSARIAL** — failure injection, negative paths, crash windows, stale-state behavior, malformed/corrupt inputs, race/concurrency observations, retry/idempotency boundaries.
2. **CORRECTNESS_ARCHITECTURE_MAP** — call graphs, authority boundaries, duplicated mechanisms, implicit invariants, unreachable or weakly enforced contracts, code↔canonical drift.
3. **PERFORMANCE_RESOURCE** — reproducible latency, throughput, memory, disk amplification, startup/index/recovery cost, large-corpus behavior, Windows/Linux differences.
4. **DEPENDENCY_PLATFORM_API** — dependency changes, upstream defects, licenses, filesystem/SQLite/runtime behavior, provider/API semantic changes, portability constraints.
5. **EXTERNAL_REUSE_COMPETITORS** — current competitor/adjacent-system implementations, upstream repositories/issues/docs, reusable libraries and patterns relevant to the active boundary.
6. **DIRECTION_VALUE_AUDIT** — compare canonical roadmap and current implementation emphasis against reachable user-value gaps; detect infrastructure overinvestment or missing product capability. Luna supplies evidence and options, not the final roadmap decision.
7. **TEST_OPERABILITY_DEBT** — missing negative tests, weak assertions, untested error classes, Doctor/SelfTest blind spots, observability gaps, deterministic-fixture opportunities.
8. **DOC_STATE_CONSISTENCY** — stale docs, state/contract/code disagreement, carried findings whose target boundary has become current, misleading comments or examples.

Prefer categories closest to the current objective and most recently changed code before broad repository exploration.

## 4. Bounded-unit contract

Every discovery unit MUST be small enough to finish, classify, and hand off independently. Before work begins, define:

```text
Work-Unit: DISCOVERY-<CATEGORY>-<AREA>-<NN>
Baseline-SHA: <authoritative HEAD>
Category: <catalog category>
Question: <one concrete question or falsifiable risk>
Why-Now: <current objective/change/finding that makes it relevant>
Read-Scope: <bounded files/subsystem/external sources>
Write-Scope: NONE initially
Done-When: <specific evidence threshold>
```

A unit should cover one subsystem or one research question. Do not start an unbounded “audit the whole project” task.

Read-only discovery does not require a GitHub work claim. The moment remediation needs branch/file writes, stop, reconcile, classify the proposed mutation, and acquire a normal work claim under the parallel-lane protocol.

### 4.1 Durable discovery-cycle ledger

Discovery-cycle progress MUST survive chat/Work interruption.

When Luna first enters discovery for an authoritative baseline SHA, it searches GitHub for an issue titled exactly:

```text
[DISCOVERY-CYCLE] <full-baseline-sha>
```

If none exists, create one with:

```text
Baseline-SHA: <authoritative HEAD>
Objective: <current DEVELOPMENT_STATE next objective>
State: ACTIVE
Authority: NONQUALIFIED_DISCOVERY_EVIDENCE
```

Creating or commenting on this coordination/evidence issue does not require a work claim because it is not a branch/file mutation and grants no product write authority.

After every completed or intentionally skipped catalog category, append one durable result comment:

```text
DISCOVERY-CYCLE-RESULT-V1
Baseline-SHA: <exact baseline>
Category: <catalog category>
Work-Unit: <discovery unit id>
Outcome: NO_FINDING | LUNA_FIX_READY | SOL_REVIEW_REQUIRED | BLOCKED_EXTERNAL | SKIPPED_IRRELEVANT
Evidence: <bounded summary plus durable links when applicable>
```

A fresh session reconstructs the cycle from these comments and does not repeat a category that already has a valid result for the exact baseline. Duplicate read-only results caused by a race are harmless evidence; any later branch/file remediation still requires normal work-claim arbitration.

When every category has a valid result, close the cycle issue as completed. A later authoritative baseline uses a new cycle issue; historical cycle issues remain read-only evidence and never become qualified development-state authority.

## 5. Evidence rules

Internal findings should include exact file/call-site/test/CI/runtime evidence sufficient for another session to reproduce or verify the conclusion.

External research should prefer current primary sources: upstream repositories, release notes, official docs, issue trackers, specifications, and measured benchmarks. Record source links and observation dates for material claims. Marketing copy or community opinion may identify a lead but is not enough by itself for an architecture decision.

Competitor research is allowed when tied to a concrete Keelaryn question such as identity continuity, derived-index recovery, corpus observation, local-first storage, search, sync, backup, or deployment. Avoid generic feature-list surveys with no decision relevance.

## 6. Outcomes

Finish each unit with exactly one outcome:

- `NO_FINDING` — the stated risk/question produced no material actionable evidence within the bounded scope. Record the result in the baseline's discovery-cycle issue; no repository file write is required unless the negative result closes a previously durable risk hypothesis.
- `LUNA_FIX_READY` — a reproducible, bounded issue has an already-specified Luna-safe behavior. Convert it into a normal claimed work unit; prove with a failing reproduction/test first when applicable.
- `SOL_REVIEW_REQUIRED` — evidence touches architecture, schema/migration, destructive/recovery authority, concurrency semantics, security/auth/crypto, identity/provenance, irreversible storage, provider authority, or another protected boundary. Persist a concise finding/handoff; do not decide the protected fix in Luna.
- `BLOCKED_EXTERNAL` — the question materially depends on unavailable credentials/environment/approval/source evidence. Record what is missing and continue another independent category when possible.

Material findings must become durable GitHub evidence (issue, PR handoff, review/comment, or committed test/finding) before the session relies on them later. Discovery artifacts are evidence, not qualified project-state authority.

## 7. Follow-up and anti-sprawl rule

A material finding may spawn at most one immediate directly dependent discovery follow-up before returning to the catalog. Further expansion requires either a normal work unit, a Sol decision, or a later discovery cycle.

Do not recursively turn every observation into more research.

## 8. Cycle and stop rule

A discovery cycle is bound to one authoritative baseline SHA and one durable GitHub `[DISCOVERY-CYCLE] <full-baseline-sha>` issue. Chat history or ephemeral in-run memory is never cycle authority.

Against an unchanged baseline, perform at most one bounded unit per catalog category, except the single direct follow-up allowed by §7. Completion is reconstructed from the exact-baseline `[DISCOVERY-CYCLE]` issue. Skip a category only when it is clearly irrelevant to the active objective and persist `SKIPPED_IRRELEVANT` with a short reason in that cycle issue.

The cycle resets when material evidence changes the engineering situation, including:

- authoritative HEAD changes;
- objective/qualified state changes;
- new material CI/runtime evidence;
- a new review finding;
- dependency/platform/provider behavior materially changes;
- a new durable blocker/finding changes priorities.

Luna may stop for lack of work only when both are true:

1. no explicit ready non-overlapping Luna-safe unit exists; and
2. the current bounded discovery cycle is exhausted or every remaining category is concretely blocked/irrelevant.

## 9. Relationship to Sol

Sol consumes material discovery evidence without requiring Luna to stop its lane.

A `SOL_REVIEW_REQUIRED` result should state the evidence, affected boundary, uncertainty, and bounded decision required. While Sol reviews it, Luna returns to the catalog and chooses the next independent unit.

Sol may accept, reject, narrow, or redesign a discovery proposal. Discovery does not amend `KEELARYN_CANONICAL.md` or `DEVELOPMENT_STATE.json` by itself.
