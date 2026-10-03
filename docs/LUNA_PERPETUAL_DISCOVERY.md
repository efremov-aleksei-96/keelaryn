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
Trigger-Kind: <CI | REVIEW | FINDING | RUNTIME | EXTERNAL | DUPLICATE_RESULT>
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
Read-Scope: <bounded repository paths/subsystem and/or external sources actually examined>
Observed-At: <RFC3339 UTC or explicit source-observation date>
Semantic-Assumptions: NONE | <bounded invariants/authority/environment assumptions the result depends on>
Outcome: NO_FINDING | LUNA_FIX_READY | SOL_REVIEW_REQUIRED | BLOCKED_EXTERNAL | SKIPPED_IRRELEVANT
Evidence: <bounded summary plus durable links when applicable>
```

Native-result cardinality is part of the durable protocol. For one `(Baseline-SHA, Epoch-Ref, Category)`:

- zero native `DISCOVERY-CYCLE-RESULT-V1` comments means the category is incomplete;
- exactly one native result is the canonical native result for that category/epoch;
- more than one native result is **ambiguous**. There is no first/last/severity winner.

If multiple native results are discovered on the **current authoritative baseline/current epoch**, do not use any of them for completion or carry. Append a reset:

```text
DISCOVERY-CYCLE-RESET-V1
Baseline-SHA: <current exact baseline>
Trigger-Kind: DUPLICATE_RESULT
Trigger-Ref: DUPLICATE_RESULT:<baseline-sha>:<epoch-ref>:<category>:<ascending-native-result-comment-ids>
Reason: multiple native results exist for one category in one epoch; no deterministic evidence winner is authorized
```

Re-fetch comments. The existing lowest-comment-ID arbitration for an exact `Trigger-Ref` chooses the canonical reset if multiple sessions post it concurrently. Rerun the category in the new reset epoch; all duplicate results from the older epoch remain historical evidence only.

If multiple native results are encountered in a **historical source baseline/current epoch** during cross-baseline carry selection, that source category is ineligible. Do not mutate the historical issue, do not pick a winner, and do not search farther back for an older native result. Rerun the category on the current baseline and emit a new native result.

A category counts as complete only when a valid result matches both the exact baseline and the **current epoch**. Fresh sessions reconstruct completion from the canonical issue and its comments instead of chat memory.

When every category has a current-epoch result, close the canonical issue as completed. On unchanged HEAD, a later session searches all states, finds that closed issue, reconstructs the completed current epoch, and does not create or rerun another cycle unless a new durable reset trigger exists.

A later authoritative baseline SHA gets its own exact-title issue and begins again at `BASELINE`. Historical cycle issues remain nonqualified evidence and never become project-state authority.

#### Cross-baseline carry-forward

A new authoritative HEAD still gets its own exact-title baseline issue. HEAD movement is not permission to treat prior results as current, but it also does **not** require a blind full-catalog rerun.

Before starting deep work for an incomplete category, Luna MUST search earlier canonical discovery-cycle baselines **newest to oldest**, skipping only baselines that contain no native current-epoch `DISCOVERY-CYCLE-RESULT-V1` for that category. The **first native result found is the only carry candidate, regardless of that result's objective**. Only after selecting it may Luna evaluate objective equality and the rest of the carry eligibility rules. If that newest native result is ineligible (including objective mismatch, `BLOCKED_EXTERNAL`, legacy/no-scope/no-semantic-assumptions, stale, intersecting, or invalidated), Luna MUST rerun the category and emit a new result; it MUST NOT continue farther back to an older, more convenient native result. A `DISCOVERY-CYCLE-CARRYFORWARD-V1` record is provenance/completion evidence for its own baseline, **not** a new source result. This avoids one-hop limits without allowing newer native evidence to be bypassed: each carry is re-proven directly from the newest native source-result baseline to the current baseline.

Automatic/cheap carry-forward is allowed only when all of the following are proven:

1. the selected source baseline/current epoch contains **exactly one** native `DISCOVERY-CYCLE-RESULT-V1` for the category; zero means keep searching newer→older past baselines with no native result, while multiple native results make this selected source ambiguous/ineligible and force a current-baseline rerun with no older fallback; source evidence is that single native result, never a prior carry-forward record;
2. source baseline SHA is an ancestor of the current baseline SHA;
3. after the newest native result has already been selected, its objective exactly matches the current objective; objective mismatch is an eligibility failure that forces rerun and never authorizes searching for an older native result;
4. the source result belongs to the source baseline's current epoch;
5. the source result already has an explicit durable bounded `Read-Scope` **and** explicit `Semantic-Assumptions` (`NONE` is valid); legacy results lacking either field are ineligible for carry-forward and must be rerun as a new category result;
6. the Git diff from the **native source-result baseline directly to the current baseline** is proven disjoint from the source result's repository read scope **and the exact persisted semantic assumptions**; any intersection or uncertain overlap requires a full category rerun and a new `DISCOVERY-CYCLE-RESULT-V1`;
7. perform an intervening invalidation scan from the source result through the current baseline across durable CI/runtime/review/finding/external evidence refs relevant to the category; no such trigger may invalidate the source evidence;
8. persist that scan as `Invalidation-Scan: PASS` plus the durable refs/range checked; if an invalidating trigger exists or the scan cannot be bounded safely, rerun the category and emit a new `DISCOVERY-CYCLE-RESULT-V1` instead of carrying;
9. the outcome-specific freshness rules below are satisfied. A freshness recheck may add evidence for an otherwise diff-disjoint carry, but it never substitutes for condition 6 or the invalidation scan.

Persist:

```text
DISCOVERY-CYCLE-CARRYFORWARD-V1
Baseline-SHA: <current exact baseline>
Epoch-Ref: BASELINE | RESET-COMMENT:<id>
Category: <catalog category>
From-Baseline: <ancestor baseline sha>
From-Result-Ref: <durable GitHub issue-comment URL/id>
Read-Scope: <verified bounded scope copied from source result>
Semantic-Assumptions: NONE | <exact source semantic assumptions, preserved for this carry>
Verification: DIFF_DISJOINT
Invalidation-Scan: PASS
Invalidation-Evidence: <durable CI/runtime/review/finding/external refs or bounded range checked; NONE_INVALIDATING>
Freshness-Check: NOT_REQUIRED | FRESH_PRIMARY_SOURCE_CHECK
External-Dependency: NONE | <external source/provider/upstream assumption requiring freshness>
Evidence: <why the prior result still applies on this baseline>
```

A valid carry-forward record counts as the category's current-baseline/current-epoch completion. It never changes the original result and never makes the old issue authoritative for the new baseline. It also does **not** become source evidence for a later baseline: later baselines search backward, skip carry-only/no-result baselines, stop at the first newer native result, and then either carry that result or rerun. Carry records preserve the source result's exact `Semantic-Assumptions` so later sessions can audit what was assumed even though the carry itself is never a new source result.

Outcome/category rules:

- `NO_FINDING`, `LUNA_FIX_READY`, and `SOL_REVIEW_REQUIRED` may be carried when their evidence/read scope is still valid; unresolved findings remain unresolved work even though rediscovery is unnecessary.
- `SKIPPED_IRRELEVANT` may be carried only when the objective and relevance assumptions are unchanged.
- `BLOCKED_EXTERNAL` is never carried. Rerun the category against the current external dependency/environment and emit a new `DISCOVERY-CYCLE-RESULT-V1`.
- Any result whose `Read-Scope`, evidence, or semantic assumptions depend on an external source/provider/upstream state may carry only when the repository/semantic diff is already proven disjoint **and** a fresh primary-source check confirms the external evidence/assumption still applies. This rule is based on actual dependency, not the catalog category label.
- A legacy result lacking explicit durable `Read-Scope` **or** explicit `Semantic-Assumptions` must be rerun as a new category result; do not reconstruct historical scope/assumptions after the fact.
- Once the newest ancestor baseline containing native result(s) for the category is found, do not search past it for an older eligible result. Exactly one native result may proceed to eligibility checks; multiple native results are ambiguous and force current-baseline rerun; any other ineligibility also forces rerun.
- Any read-scope/semantic intersection or uncertain overlap requires a full category rerun and a new result. `FRESH_RECHECK` is not a carry-forward escape hatch for changed scope.
- Any durable intervening trigger that invalidates the category's evidence, or any inability to bound the required invalidation scan safely, requires a full category rerun and a new result.

When HEAD moves, close an incomplete old baseline issue as `SUPERSEDED_BASE_MOVED` after its durable results are preserved. The new baseline issue may then carry valid categories individually and rerun only invalidated/unknown categories.

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
- `SKIPPED_IRRELEVANT` — the catalog category is clearly irrelevant to the active objective/boundary for the current epoch. Persist a short reason so fresh sessions can count the category as complete without rerunning it.

Material findings must become durable GitHub evidence (issue, PR handoff, review/comment, or committed test/finding) before the session relies on them later. Discovery artifacts are evidence, not qualified project-state authority.

## 7. Follow-up and anti-sprawl rule

A material finding may spawn at most one immediate directly dependent discovery follow-up before returning to the catalog. Further expansion requires either a normal work unit, a Sol decision, or a later discovery cycle.

Do not recursively turn every observation into more research.

## 8. Cycle and stop rule

A discovery cycle is bound to one authoritative baseline SHA, one canonical all-states GitHub `[DISCOVERY-CYCLE] <full-baseline-sha>` issue, and one current epoch. Chat history or ephemeral in-run memory is never cycle authority.

Against an unchanged baseline/epoch, perform at most one bounded unit per catalog category, except the single direct follow-up allowed by §7. Completion is reconstructed from current-epoch results in the canonical issue. Skip a category only when it is clearly irrelevant to the active objective and persist `SKIPPED_IRRELEVANT` with a short reason for the current epoch.

A new authoritative HEAD creates a new baseline issue. Before rerunning a category, apply the cross-baseline carry-forward proof in §4.1; scope-disjoint evidence may be carried category-by-category, while unknown/intersecting/stale evidence is rerun. Material CI/runtime/review/finding/external evidence on the **same** HEAD resets the cycle only through the durable `DISCOVERY-CYCLE-RESET-V1` protocol in §4.1, which creates a new epoch identity. Dependency/platform/provider observations must first have a durable GitHub evidence ref. Objective/qualified-state changes committed in the repository naturally produce a new HEAD/baseline.

Luna may stop for lack of work only when both are true:

1. no explicit ready non-overlapping Luna-safe unit exists; and
2. the current bounded discovery cycle is exhausted or every remaining category is concretely blocked/irrelevant.

## 9. Relationship to Sol

Sol consumes material discovery evidence without requiring Luna to stop its lane.

A `SOL_REVIEW_REQUIRED` result should state the evidence, affected boundary, uncertainty, and bounded decision required. While Sol reviews it, Luna returns to the catalog and chooses the next independent unit.

Sol may accept, reject, narrow, or redesign a discovery proposal. Discovery does not amend `KEELARYN_CANONICAL.md` or `DEVELOPMENT_STATE.json` by itself.
