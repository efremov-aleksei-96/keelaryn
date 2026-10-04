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

## 3. Discovery lenses and rolling frontier

The eight catalog entries are **research lenses, not eight one-shot tasks**. A single lens may produce many independent bounded units against different subsystems, questions, competitors, failure classes, platforms, or lifecycle stages.

Luna first drains durable ready backlog items. When the backlog is empty, it runs a lightweight frontier sweep and synthesizes new bounded items from the first high-value unexplored intersections it finds.

Discovery lenses:

1. **DEFECT_ADVERSARIAL** — failure injection, negative paths, crash windows, stale-state behavior, malformed/corrupt inputs, race/concurrency observations, retry/idempotency boundaries.
2. **CORRECTNESS_ARCHITECTURE_MAP** — call graphs, authority boundaries, duplicated mechanisms, implicit invariants, unreachable or weakly enforced contracts, code↔canonical drift.
3. **PERFORMANCE_RESOURCE** — reproducible latency, throughput, memory, disk amplification, startup/index/recovery cost, large-corpus behavior, Windows/Linux differences.
4. **DEPENDENCY_PLATFORM_API** — dependency changes, upstream defects, licenses, filesystem/SQLite/runtime behavior, provider/API semantic changes, portability constraints.
5. **EXTERNAL_REUSE_COMPETITORS** — competitor/adjacent-system implementations, upstream repositories/issues/docs, reusable libraries and patterns relevant to **implemented Keelaryn capabilities and canonical/planned capability gaps**, not only the active objective.
6. **DIRECTION_VALUE_AUDIT** — compare canonical roadmap and current implementation emphasis against reachable user-value gaps; detect infrastructure overinvestment or missing product capability. Luna supplies evidence and options, not the final roadmap decision.
7. **TEST_OPERABILITY_DEBT** — missing negative tests, weak assertions, untested error classes, Doctor/SelfTest blind spots, observability gaps, deterministic-fixture opportunities.
8. **DOC_STATE_CONSISTENCY** — stale docs, state/contract/code disagreement, carried findings whose target boundary has become current, misleading comments or examples.

Frontier synthesis MUST consider more than the current objective. At minimum, scan these durable sources for novel questions:

- active objective, recent diffs, open PR/CI/runtime/review evidence;
- implemented subsystem inventory from canonical architecture + repository structure;
- canonical/planned capabilities that are absent, partial, provisional, or explicitly deferred;
- unresolved findings, known limitations, TODO/proof gaps and weakly exercised invariants;
- platform/dependency/test/performance matrices;
- external competitor/upstream/open-source landscape mapped to concrete Keelaryn capabilities.

Prefer recently changed and high-risk boundaries first, but do not treat current-objective completion as exhaustion of the research frontier.

A candidate is novel when its stable `Discovery-Key` has no terminal result/carry in the current epoch and no active owner. The key represents the concrete question, not merely the lens, for example:

`EXTERNAL_REUSE_COMPETITORS/search/derived-index-recovery-patterns`
`EXTERNAL_REUSE_COMPETITORS/identity/persistent-local-file-identity`
`PERFORMANCE_RESOURCE/corpus/startup-fingerprint-amplification`

## 4. Bounded-unit contract

Every discovery unit MUST be small enough to finish, classify, and hand off independently. Before work begins, define:

```text
Work-Unit: DISCOVERY-<CATEGORY>-<AREA>-<NN>
Discovery-Key: <CATEGORY>/<stable-area>/<stable-question>
Baseline-SHA: <authoritative HEAD>
Epoch-Ref: BASELINE | RESET-COMMENT:<id>
Category: <catalog lens>
Question: <one concrete question or falsifiable risk>
Why-Now: <current change, canonical capability, gap, external lead, or finding that makes it relevant>
Read-Scope: <bounded files/subsystem/external sources>
Write-Scope: NONE initially
Done-When: <specific evidence threshold>
```

A unit covers one subsystem/question. Multiple units from the same category are allowed when their `Discovery-Key` values are distinct. Do not start an unbounded “audit the whole project” or generic “survey all competitors” task.

Read-only discovery does not require a GitHub work claim. The moment remediation needs branch/file writes, stop, reconcile, classify the proposed mutation, and acquire a normal work claim under the parallel-lane protocol.

### 4.1 Durable rolling discovery ledger

Discovery progress MUST survive chat/Work interruption and same-baseline evidence resets.

#### Canonical baseline issue

For authoritative baseline SHA `B`, the ledger title remains exactly:

```text
[DISCOVERY-CYCLE] <full-B>
```

Lookup searches **all issue states (open and closed)** and requires an exact title match. If no exact issue exists, create one with the current baseline/objective and `Authority: NONQUALIFIED_DISCOVERY_EVIDENCE`. After creation, search again; concurrent duplicates arbitrate by lowest issue number and higher-number duplicates close before work.

The issue is a rolling backlog ledger, not an eight-cell checklist.

#### Epoch identity and resets

The initial epoch is `BASELINE`. Material same-HEAD CI/review/finding/runtime/external evidence may create a reset only through a durable unique trigger:

```text
DISCOVERY-CYCLE-RESET-V1
Baseline-SHA: <exact baseline>
Trigger-Kind: <CI | REVIEW | FINDING | RUNTIME | EXTERNAL | DUPLICATE_RESULT>
Trigger-Ref: <durable unique ref>
Reason: <why earlier evidence may be stale>
```

For duplicate reset records with the same Trigger-Ref, the lowest GitHub comment ID is canonical. The newest distinct canonical reset by GitHub `created_at` (tie: higher comment ID) defines the current epoch `RESET-COMMENT:<id>`. Older-epoch backlog/results never satisfy the new epoch.

#### Backlog items

A frontier sweep persists each selected candidate before deep work:

```text
DISCOVERY-BACKLOG-ITEM-V1
Baseline-SHA: <exact baseline>
Epoch-Ref: <current epoch>
Discovery-Key: <stable category/area/question key>
Category: <catalog lens>
Question: <bounded question>
Why-Now: <evidence source>
Read-Scope-Hint: <bounded expected scope>
Priority: <P0 | P1 | P2 | P3>
State: READY
```

For one `(Baseline-SHA, Epoch-Ref, Discovery-Key)`, the earliest identical backlog record is canonical. If same-key records materially disagree on question/scope, do not pick one silently: use a more specific new key or persist a conflict finding.

Fresh sessions reconstruct pending work from canonical backlog items minus terminal current-epoch results/carries. A category may therefore contain any number of pending/completed keys.

#### Unit results

After every completed item append:

```text
DISCOVERY-UNIT-RESULT-V2
Baseline-SHA: <exact baseline>
Epoch-Ref: <current epoch>
Discovery-Key: <exact backlog key>
Category: <catalog lens>
Work-Unit: <discovery unit id>
Read-Scope: <actual bounded repository paths/subsystem/external sources>
Observed-At: <RFC3339 UTC or explicit source-observation date>
Semantic-Assumptions: NONE | <bounded assumptions>
Outcome: NO_FINDING | LUNA_FIX_READY | SOL_REVIEW_REQUIRED | BLOCKED_EXTERNAL | SKIPPED_IRRELEVANT
Evidence: <bounded summary plus durable links>
Follow-Up-Keys: NONE | <new distinct discovery keys suggested by this result>
```

Native-result cardinality is keyed by `(Baseline-SHA, Epoch-Ref, Discovery-Key)`, **not Category**:

- zero results => item pending;
- exactly one result => terminal for that key/epoch;
- more than one native result => ambiguous. Persist a `DUPLICATE_RESULT` reset keyed by the sorted result comment IDs, then rerun that key in the new epoch.

Historical `DISCOVERY-CYCLE-RESULT-V1` records that lack `Discovery-Key` are legacy category-sweep evidence only. Treat them as historical context (conceptually `LEGACY_CATEGORY_SWEEP/<CATEGORY>`); they do **not** exhaust a category, do not close the rolling frontier, and are not silently mapped onto a new V2 key.

#### Frontier sweeps

When no current backlog item is ready, run a lightweight synthesis pass over the frontier sources in §3. Persist:

```text
DISCOVERY-FRONTIER-SWEEP-V1
Baseline-SHA: <exact baseline>
Epoch-Ref: <current epoch>
Observed-At: <time>
Sources-Scanned: <objective/diff/subsystems/planned-gaps/findings/platform/external/etc>
New-Keys: NONE | <distinct keys persisted as backlog items>
Blocked-Sources: NONE | <concrete unavailable source>
Evidence: <bounded explanation>
```

A sweep discovers candidates; it does not perform all deep research itself. If it finds new keys, Luna continues with the highest-priority ready item. Results may themselves add distinct follow-up keys, so backlog drain and frontier synthesis alternate.

A zero-new-key sweep is valid for stopping only when it is **fresh after the latest terminal result/material transition**, scans every currently known frontier source class that is available, and there are no pending ready backlog items. Closing the baseline issue is allowed only at that point. “8/8 categories have results” is never a closure condition.

#### Cross-baseline carry-forward

Carry-forward is per exact `Discovery-Key`, never per category.

For an incomplete key on a new baseline, the newest ancestor native V2 result for that exact key may be carried only when:

1. the source baseline is an ancestor of current baseline;
2. source result belongs to the source baseline's current epoch and is unique for that key;
3. `Question`, `Read-Scope`, and `Semantic-Assumptions` are explicit;
4. direct source-baseline → current-baseline diff is proven disjoint from repository scope and semantic assumptions;
5. a bounded intervening CI/runtime/review/finding/external/reset scan finds no invalidating trigger;
6. external/provider/upstream-dependent evidence receives a fresh primary-source check;
7. `BLOCKED_EXTERNAL` is never carried.

Persist:

```text
DISCOVERY-CYCLE-CARRYFORWARD-V2
Baseline-SHA: <current baseline>
Epoch-Ref: <current epoch>
Discovery-Key: <exact key>
Category: <catalog lens>
From-Baseline: <ancestor>
From-Result-Ref: <durable result ref>
Read-Scope: <source scope>
Semantic-Assumptions: <source assumptions>
Verification: DIFF_DISJOINT
Invalidation-Scan: PASS
Invalidation-Evidence: <refs/range>
Freshness-Check: NOT_REQUIRED | FRESH_PRIMARY_SOURCE_CHECK
Evidence: <why exact question remains answered>
```

A carry is completion evidence for this key/epoch only and is never source evidence for a later carry. If proof is uncertain, rerun the key.

## 5. Evidence rules

Internal findings should include exact file/call-site/test/CI/runtime evidence sufficient for another session to reproduce or verify the conclusion.

External research should prefer current primary sources: upstream repositories, release notes, official docs, issue trackers, specifications, and measured benchmarks. Record source links and observation dates for material claims. Marketing copy or community opinion may identify a lead but is not enough by itself for an architecture decision.

Competitor research is allowed when tied to a concrete Keelaryn capability/question such as identity continuity, derived-index recovery, corpus observation, local-first storage, search, sync, backup, deployment, portability, ingestion, provenance, agent/runtime orchestration, or another canonical/planned capability. It may investigate both already-implemented mechanisms and capabilities not yet implemented. Avoid generic feature-list surveys with no Keelaryn decision/reuse relevance; convert broad landscapes into multiple bounded `Discovery-Key` questions instead.

## 6. Outcomes

Finish each unit with exactly one outcome:

- `NO_FINDING` — the stated risk/question produced no material actionable evidence within the bounded scope. Record the result in the baseline's discovery-cycle issue; no repository file write is required unless the negative result closes a previously durable risk hypothesis.
- `LUNA_FIX_READY` — a reproducible, bounded issue has an already-specified Luna-safe behavior. Convert it into a normal claimed work unit; prove with a failing reproduction/test first when applicable.
- `SOL_REVIEW_REQUIRED` — evidence touches architecture, schema/migration, destructive/recovery authority, concurrency semantics, security/auth/crypto, identity/provenance, irreversible storage, provider authority, or another protected boundary. Persist a concise finding/handoff; do not decide the protected fix in Luna.
- `BLOCKED_EXTERNAL` — the question materially depends on unavailable credentials/environment/approval/source evidence. Record what is missing and continue another independent category when possible.
- `SKIPPED_IRRELEVANT` — the catalog category is clearly irrelevant to the active objective/boundary for the current epoch. Persist a short reason so fresh sessions can count the category as complete without rerunning it.

Material findings must become durable GitHub evidence (issue, PR handoff, review/comment, or committed test/finding) before the session relies on them later. Discovery artifacts are evidence, not qualified project-state authority.

## 7. Follow-up and anti-sprawl rule

A material finding may trigger at most one **immediate depth-first** dependent follow-up. Additional distinct follow-ups are not discarded: persist them as separate `Discovery-Key` backlog items and return to normal priority selection.

This prevents recursive rabbit holes without artificially erasing a large research backlog. A Sol-required finding blocks only the protected decision and true dependants; unrelated queued discovery continues.

## 8. Rolling backlog and stop rule

Discovery is bound to one authoritative baseline SHA, one canonical all-states `[DISCOVERY-CYCLE] <full-baseline-sha>` ledger, and one current epoch. Chat history is never authority.

The catalog lenses are reusable. **There is no “one unit per category” cap.** Against an unchanged baseline/epoch Luna repeatedly:

1. drains explicit ready Luna-safe work;
2. drains durable ready discovery backlog items;
3. persists any distinct follow-up keys produced by results;
4. when backlog is empty, performs a fresh bounded frontier sweep across §3 sources;
5. if new keys appear, repeats from step 2.

A new authoritative HEAD creates a new baseline ledger. Existing V2 keys may be carried only by the exact-key proof in §4.1; legacy V1 category results are historical context and never whole-category completion.

Luna may stop for lack of work only when **all** are true:

1. no explicit ready non-overlapping Luna-safe unit exists;
2. no current-epoch ready discovery backlog item exists;
3. all current-epoch backlog items are terminal or concretely blocked;
4. a fresh post-result frontier sweep on the unchanged binding scanned all available frontier source classes and produced `New-Keys: NONE`;
5. there is no unconsumed material finding or external lead that can be converted into a distinct bounded key.

Thus `8/8 categories`, one direct follow-up, a Sol-only implementation blocker, or a completed competitor survey of one subsystem is **not** evidence that Luna has no work.

## 9. Relationship to Sol

Sol consumes material discovery evidence without requiring Luna to stop its lane.

A `SOL_REVIEW_REQUIRED` result should state the evidence, affected boundary, uncertainty, and bounded decision required. While Sol reviews it, Luna returns to the catalog and chooses the next independent unit.

Sol may accept, reject, narrow, or redesign a discovery proposal. Discovery does not amend `KEELARYN_CANONICAL.md` or `DEVELOPMENT_STATE.json` by itself.
