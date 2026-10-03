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

Discovery-cycle progress MUST survive chat/Work interruption and same-baseline evidence resets.

#### Canonical baseline issue

For authoritative baseline SHA `B`, the ledger title is exactly:

```text
[DISCOVERY-CYCLE] <full-B>
```

Lookup MUST search **all issue states (open and closed)** and require an exact title match. A closed canonical issue is still the ledger for that unchanged baseline; do not create a replacement merely because it is closed.

If no exact-title issue exists, create one with:

```text
Baseline-SHA: <authoritative HEAD>
Objective: <current DEVELOPMENT_STATE next objective>
State: ACTIVE
Authority: NONQUALIFIED_DISCOVERY_EVIDENCE
Initial-Epoch: BASELINE
```

Immediately after creation, search all states again for the exact title before doing any catalog work. GitHub titles are not unique: if concurrent creation produced multiple issues, the **lowest issue number is canonical**. Every higher-number duplicate must be marked `State: DUPLICATE`, link the canonical issue, and close before that session performs discovery work. New results and reset records are written only to the canonical issue.

Creating/updating/commenting on this coordination/evidence issue does not require a work claim because it is not a branch/file mutation and grants no product write authority.

#### Epoch identity and same-baseline resets

The initial epoch is `BASELINE`. Category results from an older epoch never satisfy completion for a newer epoch.

A material event that changes the engineering risk without changing authoritative HEAD creates a reset only when it has a **durable unique Trigger-Ref**, for example:

- `CI_RUN:<run-id>:<conclusion>`;
- `PR_REVIEW:<review-id>` or `REVIEW_COMMENT:<comment-id>`;
- `GITHUB_FINDING:<issue-or-comment-url>`;
- `RUNTIME_EVIDENCE:<durable-github-evidence-url>`.

An external dependency/platform/provider observation must first be persisted as durable GitHub evidence before it may reset the cycle.

Before posting a reset, fetch all canonical-issue comments. If the exact `Trigger-Ref` already has a reset record, reuse it. Otherwise append:

```text
DISCOVERY-CYCLE-RESET-V1
Baseline-SHA: <exact baseline>
Trigger-Kind: <CI | REVIEW | FINDING | RUNTIME | EXTERNAL>
Trigger-Ref: <durable unique ref>
Reason: <why prior category results may no longer be sufficient>
```

Re-fetch comments immediately after posting. Concurrent duplicate reset comments for the same `Trigger-Ref` are possible; the **lowest GitHub comment ID for that exact Trigger-Ref is canonical** and the others are ignored for epoch selection.

The epoch identity for a reset is:

```text
RESET-COMMENT:<canonical-reset-comment-id>
```

Among distinct canonical reset records, the current epoch is the one with the latest GitHub `created_at`; an exact timestamp tie is broken by the higher comment ID. Thus a later material trigger on the same HEAD invalidates completion from earlier epochs without changing the baseline issue identity.

If the canonical issue was closed because the previous epoch completed, a new canonical reset record requires reopening that same issue before further discovery.

Material evidence that already existed when the baseline issue was first created is part of the initial `BASELINE` epoch and should influence unit selection/Why-Now; it does not cause an immediate self-reset.

#### Category results

Before starting a unit, fetch the canonical issue and derive the current epoch. Before recording its result, fetch again; if the current epoch changed while the unit ran, the result may be retained as historical evidence but does **not** satisfy the new epoch.

After every completed or intentionally skipped category, append:

```text
DISCOVERY-CYCLE-RESULT-V1
Baseline-SHA: <exact baseline>
Epoch-Ref: BASELINE | RESET-COMMENT:<id>
Category: <catalog category>
Work-Unit: <discovery unit id>
Outcome: NO_FINDING | LUNA_FIX_READY | SOL_REVIEW_REQUIRED | BLOCKED_EXTERNAL | SKIPPED_IRRELEVANT
Evidence: <bounded summary plus durable links when applicable>
```

A category counts as complete only when a valid result matches both the exact baseline and the **current epoch**. Fresh sessions reconstruct completion from the canonical issue and its comments instead of chat memory.

When every category has a current-epoch result, close the canonical issue as completed. On unchanged HEAD, a later session searches all states, finds that closed issue, reconstructs the completed current epoch, and does not create or rerun another cycle unless a new durable reset trigger exists.

A later authoritative baseline SHA gets its own exact-title issue and begins again at `BASELINE`. Historical cycle issues remain nonqualified evidence and never become project-state authority.

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

A discovery cycle is bound to one authoritative baseline SHA, one canonical all-states GitHub `[DISCOVERY-CYCLE] <full-baseline-sha>` issue, and one current epoch. Chat history or ephemeral in-run memory is never cycle authority.

Against an unchanged baseline/epoch, perform at most one bounded unit per catalog category, except the single direct follow-up allowed by §7. Completion is reconstructed from current-epoch results in the canonical issue. Skip a category only when it is clearly irrelevant to the active objective and persist `SKIPPED_IRRELEVANT` with a short reason for the current epoch.

A new authoritative HEAD creates a new baseline issue. Material CI/runtime/review/finding/external evidence on the **same** HEAD resets the cycle only through the durable `DISCOVERY-CYCLE-RESET-V1` protocol in §4.1, which creates a new epoch identity. Dependency/platform/provider observations must first have a durable GitHub evidence ref. Objective/qualified-state changes committed in the repository naturally produce a new HEAD/baseline.

Luna may stop for lack of work only when both are true:

1. no explicit ready non-overlapping Luna-safe unit exists; and
2. the current bounded discovery cycle is exhausted or every remaining category is concretely blocked/irrelevant.

## 9. Relationship to Sol

Sol consumes material discovery evidence without requiring Luna to stop its lane.

A `SOL_REVIEW_REQUIRED` result should state the evidence, affected boundary, uncertainty, and bounded decision required. While Sol reviews it, Luna returns to the catalog and chooses the next independent unit.

Sol may accept, reject, narrow, or redesign a discovery proposal. Discovery does not amend `KEELARYN_CANONICAL.md` or `DEVELOPMENT_STATE.json` by itself.
