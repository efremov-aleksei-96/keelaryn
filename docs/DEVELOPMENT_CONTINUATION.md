# Development Continuation Contract

**Status:** active development governance  
**Authority:** subordinate to `KEELARYN_CANONICAL.md` and live `DEVELOPMENT_STATE.json`

## 1. Goal

A fresh ChatGPT development session must be able to resume Keelaryn from durable sources without needing the previous chat.

The intended user interaction is deliberately project-scoped:

```text
продолжить работу над Keelaryn
```

or, when the model is explicitly selected:

```text
продолжить работу над Keelaryn при помощи Luna
продолжить работу над Keelaryn при помощи Sol
```

The phrase is a resume command, not a request to guess from conversation memory.

## 1.1 Project identity and multi-project routing

This continuation contract belongs only to **Keelaryn**. Its canonical project ID is `KEELARYN`.

In a multi-project environment, project identity must be resolved before model profile selection and before any write. Preferred invocations are:

```text
продолжить работу над Keelaryn
продолжить работу над Keelaryn при помощи Luna
продолжить работу над Keelaryn при помощи Sol
```

A bare `продолжить работу` may be accepted only when the current ChatGPT project/Work workspace/repository context is already uniquely and verifiably Keelaryn.

Fail-closed routing rules:

1. Named project = Keelaryn → continue with this contract.
2. Named project != Keelaryn → do not use this repository/state; route to that project's own durable authority.
3. Project omitted in a multi-project or ambiguous context → no mutation; resolve/select the project first.
4. Project context conflicts with repository/state identity → no mutation; reconcile the mismatch first.
5. Never mix branches, PRs, CI runs, objectives, checkpoints, credentials, or runtime state between projects.

Project identity resolution precedes the Luna/Sol profile resolution below.

## 2. Model identity

The active model identity and the user's explicit invocation jointly determine the execution profile, using fail-closed resolution.

Profile precedence:

1. **Explicit Luna request** — `продолжить работу при помощи Luna` always selects the Luna-safe profile. This is safe even if the active model is Sol, because a stronger model may operate under lower privileges.
2. **Explicit Sol request** — `продолжить работу при помощи Sol` selects the Sol profile only if the environment positively identifies the active model as Sol.
3. **Generic request** — `продолжить работу` uses the positively identified active model profile.
4. **Unknown, ambiguous or mismatched identity** — use Luna-safe / least-privilege. Never infer or assume Sol.

A session must never pretend that it changed models merely because the user named another model. The user selects the model in the ChatGPT UI; this contract constrains what the selected model may do.

If an explicit Sol request cannot be positively matched to a Sol identity, report that fact briefly and continue only under Luna-safe rules unless the user changes the selected model.

## 3. Mandatory startup reconcile

Every fresh session starts read-only.

1. Read `AGENTS.md`.
2. Resolve the authoritative branch from `DEVELOPMENT_STATE.json`.
3. Read the exact branch HEAD.
4. Run or reproduce the compact read-only development preflight.
5. Reconcile:
   - current `DEVELOPMENT_STATE.json` revision;
   - current objective and audit gate;
   - open `[WORK-CLAIM]` issues and their declared scopes;
   - open PRs against the authoritative branch;
   - CI runs for the authoritative HEAD and relevant open PR heads;
   - unfinished branches that clearly belong to the current objective.
6. Read the minimum architecture/contracts needed for the next action.
7. If chat memory disagrees with live durable state, durable state wins.

No write is permitted before this reconcile.

## 3.1 Objective/profile suitability gate

After startup reconcile, and again after every material transition, build the set of currently known **work units** for the qualified objective and evaluate each unit independently. An objective may simultaneously contain `SOL_REQUIRED`, `LUNA_READY`, `EITHER_PROFILE`, blocked, and already-owned units; there is no single global model classification for a mixed objective.

For each candidate unit:

1. Resolve its dependencies. A unit with an unresolved prerequisite is not ready.
2. If the unit crosses a `STRONG_MODEL_REQUIRED` boundary, or correctness depends on unresolved architecture/authority judgment, classify that unit `SOL_REQUIRED`.
3. Otherwise, if the unit is within `SAFE_AUTONOMOUS` / `SAFE_WITH_VERIFY` and is predominantly mechanical, deterministic, research/test/CI, bounded-refactor, or long-running throughput work, classify it `LUNA_READY`.
4. Otherwise, if the unit remains Luna-safe, classify it `EITHER_PROFILE`.
5. If a unit's classification is uncertain, treat **that unit** as `SOL_REQUIRED`; do not promote the uncertainty to an objective-wide stop.

Selection rules:

1. Luna selects the highest-priority ready, unclaimed/non-overlapping `LUNA_READY` unit, then `EITHER_PROFILE` if no higher Luna-ready unit exists.
2. A separate `SOL_REQUIRED` unit blocks only itself and units that actually depend on it. It does not block independent Luna-safe writes.
3. Sol prioritizes immutable Luna handoffs awaiting review/integration, then ready architecture/authority blockers, then `EITHER_PROFILE`, then `LUNA_READY` when no higher-priority Sol work remains.
4. Explicit Luna never performs a protected `SOL_REQUIRED` write. If no independent Luna-safe unit exists, it may continue read-only analysis/proof and then stop dependent writes.
5. Explicit Sol may execute `LUNA_READY`, `EITHER_PROFILE`, or `SOL_REQUIRED` units; selecting Sol never requires needless hand-back to Luna.
6. Generic continuation uses the resolved active profile from §2 and the same per-unit queue.
7. Recompute readiness/classification after every reconcile, PR merge, material CI/runtime result, new blocker/finding, work-claim change, or `DEVELOPMENT_STATE.json` transition.
8. This scheduler does not create a second qualified-state authority. Durable qualified truth remains `DEVELOPMENT_STATE.json` + Git/GitHub + fresh external evidence where relevant.

The session should state a classification briefly only when it materially constrains the selected work unit.

## 4. Shared transactional loop

Every development profile uses the same loop:

```text
RECONCILE
→ choose highest-priority ready slice
→ classify risk
→ establish proof / failing reproduction when applicable
→ one coherent mutation
→ targeted verification
→ relevant regression / CI
→ durable checkpoint
→ RECONCILE
→ continue
```

A timeout, lost response, tool error or uncertain write changes the loop to:

```text
UNCERTAIN RESULT
→ READ-ONLY RECONCILE
→ determine whether the mutation already happened
→ continue from observed reality
```

Never blindly repeat the write.

### 4.1 Parallel lane scheduler

The shared loop is executed concurrently by independent work units. Keelaryn does **not** require Luna and Sol to alternate.

A session builds its lane queue from:

- the current qualified objective and durable dependencies;
- open `[WORK-CLAIM]` issues;
- open PRs and their declared work-unit scopes;
- pending immutable handoffs awaiting review/integration;
- current CI/runtime evidence.

A `SOL_REQUIRED` unit blocks only itself and dependants. It does not block independent `LUNA_READY` work.

#### Remote scope claim before the first write

A local/read-only decision to work on a unit is not ownership. Ownership becomes durable only through a remotely visible GitHub claim.

Before creating a work branch or editing any file for a write-capable unit:

1. reconcile authoritative HEAD and existing open claims/PR scopes;
2. create a GitHub issue titled `[WORK-CLAIM] <work-unit>` with:

```text
Lane: LUNA | SOL
Work-Unit: <stable bounded id>
Base-SHA: <authoritative sha observed for acquisition>
Scope: <files and semantic authority requested>
Depends-On: <none or immutable prerequisite ids/shas>
State: CLAIMING
Lease-Until: <RFC3339 UTC, no more than 30 minutes after claim creation>
```

3. immediately reconcile **again** after the issue is remotely visible;
4. compare the requested scope with every open claim and active PR;
5. if the requested scope materially overlaps an **active PR**, the new claim loses immediately; mark/close it as abandoned and choose another unit before branch creation/file edits;
6. only when no active PR owns the scope, order materially overlapping claims by GitHub issue number; the lowest claim number wins and all later claimants abandon before branch creation/file edits;
7. if visibility, scope overlap, or winner ordering is uncertain, fail closed and perform no file write;
8. the winner acquires only a short **claim-transfer lease**. It may create an isolated exact-base branch whose name contains the claim number and write only `.keelaryn-work/<work-unit>.json`, containing the claim metadata needed to open the first draft PR. It must not edit product/code/document scope yet;
9. before `Lease-Until`, open a draft PR that references the claim and repeats the ownership fields, then reconcile that the PR is remotely visible;
10. after the remote PR is visible, reconcile transfer eligibility using GitHub server timestamps. The PR is transfer-valid only when its `created_at` is no later than `Lease-Until` and, if the claim was already closed as stale, its `created_at` is earlier than the claim `closed_at`. Invalid/late PRs close without substantive edits and require a new claim. A transfer-valid PR must then arbitrate against every materially overlapping active transfer-valid PR: earliest GitHub `created_at` wins; equal timestamps break by lower PR number. Losing PRs immediately lose write authority, stop substantive edits, and close or become explicitly abandoned before either side continues. A late-observed older valid PR therefore preempts any later replacement ownership. For the unique winner, close the issue claim; substantive writes may then begin on the PR branch.

This publish→reconcile→winner→draft-PR-transfer sequence prevents two sessions that started from the same read-only prestate from both silently becoming writers and bounds claim-only ownership after interruption.

If `Lease-Until` expires before transfer:

1. a fresh session reconciles open claims **and** open PRs;
2. immediately before retirement, re-fetch the claim and referencing PRs;
3. if no open PR references the expired claim, the claim may be marked stale/retired and closed;
4. if a racing PR is observed after retirement, decide transfer-validity from GitHub server timestamps: a PR created no later than `Lease-Until` and before the claim `closed_at` is transfer-valid; a PR created after either boundary is invalid and must close without substantive edits;
5. if that transfer-valid PR materially overlaps any later active transfer-valid replacement PR, arbitrate all overlapping PRs before any further write: earliest GitHub `created_at` wins, with lower PR number as the deterministic tie-break; every loser immediately loses write authority and closes or is explicitly abandoned;
6. any leftover claim-only branch or `.keelaryn-work/<work-unit>.json` marker from an invalid/expired/losing claim or PR is abandoned and must not be reused;
7. recovery begins with a new claim and a new claim-numbered branch only when no active winning PR already owns the scope;
8. every interrupted session must reconcile and repeat this arbitration before its next substantive write.

If an open PR uniquely owns the scope under this rule, later lease expiry is irrelevant. The marker is transport/bootstrap metadata only and must be removed before integration; it never becomes product or qualified-state authority.

#### Work-unit branch and handoff

The active PR carries:

```text
Claim-Issue: #<claim>
Lane: LUNA | SOL
Work-Unit: <stable bounded id>
Base-SHA: <acquired base sha>
Scope: <files and semantic authority owned by this unit>
Depends-On: <none or immutable prerequisite ids/shas>
Handoff-SHA: <exact candidate sha when ready for review>
State: ACTIVE | HANDOFF_READY | REVIEWED | INTEGRATION_READY
```

Recommended branch forms are `luna/<work-unit>-c<claim>` and `sol/<work-unit>-c<claim>`. Governance-only protocol work may use `governance/<work-unit>-c<claim>`.

Sol review is bound to an exact `Handoff-SHA`. While Sol reviews that SHA, Luna may immediately acquire and start the next independent unit on another claim/branch.

Luna does not append unrelated/new work to a head already under Sol review. If a requested fix changes the handoff SHA, the previous review is stale for integration and the new SHA must be reviewed/qualified as required.

#### Serialized integration gate

Parallel preparation does not imply parallel authority mutation. Merges into the authoritative branch and qualified `DEVELOPMENT_STATE.json` transitions are serialized.

Immediately before merge/state transition:

1. reconcile authoritative HEAD;
2. reconcile all materially overlapping active PRs and confirm this PR is still the unique owner under the transfer-validity / earliest-`created_at` ordering;
3. confirm the work-unit claim/PR ownership and exact reviewed head are still applicable;
4. re-evaluate overlapping merged work since the base;
5. run any proof invalidated by base movement;
6. perform one integration mutation;
7. verify and checkpoint before another integration mutation.

Ephemeral lane occupancy is derived from open work-claim issues before transfer and open PRs after transfer. Do not add rapidly changing lane locks to `DEVELOPMENT_STATE.json`; it remains authority for qualified project state.

## 5. Luna: continuous Work profile

Luna is optimized for long autonomous runs and mechanical throughput.

When Luna is started in ChatGPT Work for Keelaryn, the default behavior is **continuous development**, not “perform one task and stop”.

After each successful slice Luna immediately reconciles and selects the next safe **unclaimed/non-overlapping** ready slice. It continues until a stop condition in §7 is reached or the Work execution itself ends. A concurrent Sol review/integration lane is expected and does not by itself stop Luna.

### 5.1 Luna — SAFE_AUTONOMOUS

Luna may perform and complete autonomously:

- repository/cartography and call-site inventories;
- read-only architecture and correctness mapping;
- CI/log analysis and failure clustering;
- deterministic test execution and benchmark collection;
- dependency/license/platform/API research;
- documentation/state consistency checks;
- Doctor/SelfTest execution on disposable state;
- deterministic generated fixtures;
- formatting/lint/mechanical cleanup;
- bounded non-authoritative tooling;
- low-risk CI improvements;
- narrowly localized bug fixes when a failing reproduction exists and the fix does not cross a protected authority boundary.

### 5.2 Luna — SAFE_WITH_VERIFY

Luna may implement on an isolated exact-base branch and prove with tests/CI:

- deterministic tests for already-specified behavior;
- mechanical refactors with no semantic redesign;
- candidate implementation of a previously specified contract;
- low-risk developer tooling;
- documentation changes;
- localized correctness fixes with bounded blast radius.

Before merge, Luna must inspect the exact diff and verify that no protected surface below was crossed.

### 5.3 Luna — STRONG_MODEL_REQUIRED

Luna must not independently finalize or qualify:

- core architecture or canonical invariants;
- public semantic/API design where behavior is not already specified;
- authoritative database schema or migration design;
- destructive migration or downgrade semantics;
- backup/restore and release rollback protocol;
- interruption/recovery authority;
- concurrency semantics;
- security/auth/credential/crypto boundaries;
- irreversible storage semantics;
- provider/corpus identity semantics;
- authoritative project/workspace state semantics;
- parser/source-boundary semantics;
- cross-platform storage/backend architecture;
- large subsystem refactors whose correctness depends on architectural judgment.

For these, Luna may continue read-only analysis, build tests, produce an impact map and prepare a candidate branch/PR, but the final decision/qualification belongs to Sol.

### 5.4 Luna merge rule

Luna may merge its own PR only when **all** of the following are true:

- the change is classified SAFE_AUTONOMOUS or SAFE_WITH_VERIFY;
- authoritative HEAD/base has been freshly reconciled;
- exact diff is bounded and contains no protected surface;
- required tests and full relevant CI are green;
- the merge does not itself declare a stage/audit/architecture qualification;
- `DEVELOPMENT_STATE.json` is not being changed to claim completion of a product stage;
- no competing write has invalidated the base.

Otherwise Luna leaves a proved PR/branch as durable handoff and continues independent safe work.

## 6. Sol: strong-model profile

Sol uses the same transactional loop but may own the high-risk decisions listed in §5.3.

Sol should:

- consume Luna's immutable handoff SHAs, durable PRs, test evidence and impact maps instead of repeating discovery;
- review/integrate work unit N while Luna is free to produce independent work unit N+1;
- never take over or rewrite Luna's active branch; use review or a separate Sol remediation/integration branch;
- reconcile every candidate against current HEAD;
- make architecture/authority decisions explicitly;
- implement or revise protected-surface changes;
- qualify stages and audits;
- update `DEVELOPMENT_STATE.json` after material qualified transitions;
- merge only after exact-base/diff/CI reconciliation.

Sol may also perform ordinary low-risk work; it is not restricted to review.

## 7. Stop conditions

A long Luna Work run stops dependent writes only when at least one is true:

1. the next required action is STRONG_MODEL_REQUIRED and no independent safe work remains;
2. a required credential, secret, external approval or unavailable environment blocks progress;
3. authoritative state is inconsistent and cannot be reconciled safely;
4. a real BLOCKER/CRITICAL finding requires architecture-level remediation;
5. CI or runtime evidence establishes a product defect whose correct fix needs Sol-level judgment;
6. all currently ready work for the objective is complete.

A single completed slice, an ordinary CI wait, or a recoverable tool error is **not** a stop condition.

While waiting on CI/provider/runtime evidence, Luna should continue independent read-only work from the existing approved categories.

## 8. Durable handoff and interruption recovery

Do not create a second live development-state authority.

Use:

- `DEVELOPMENT_STATE.json` for qualified project-development state;
- Git commits/branches/PRs for durable slice work and exact diffs;
- GitHub Actions for qualification evidence;
- contract/retrospective documents when the stage requires them.

For Luna, an open PR/branch plus its tests/CI is the durable ledger for unfinished implementation. For Sol, the exact reviewed handoff SHA plus review/integration evidence is the durable ledger. Do not rely on uncommitted scratch or the chat transcript.

After interruption, a new session starts from §3, reconstructs active work-unit scopes from GitHub, and resumes the highest-priority ready unit for its own lane without duplicating another lane's active work.

## 9. Work mode usage

For multi-hour Luna development, select **Luna + Work** in ChatGPT, then send:

```text
продолжить работу
```

or:

```text
продолжить работу при помощи Luna
```

The Work run should keep iterating under §5 until §7 applies.

In a separate chat/window, select **Sol** and send the same generic command or the explicit Sol form. Luna and Sol are intended to run concurrently: Luna keeps the producer queue moving while Sol consumes immutable handoffs and protected decisions.

The repository protocol is designed so that even if either Work run or chat ends, the next session reconstructs progress and lane ownership from GitHub plus `DEVELOPMENT_STATE.json` instead of losing or duplicating work.
