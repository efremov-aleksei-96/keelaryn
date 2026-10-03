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
   - open PRs against the authoritative branch;
   - CI runs for the authoritative HEAD and relevant open PR heads;
   - unfinished branches that clearly belong to the current objective.
6. Read the minimum architecture/contracts needed for the next action.
7. If chat memory disagrees with live durable state, durable state wins.

No write is permitted before this reconcile.

## 3.1 Objective/profile suitability gate

After startup reconcile, and again after every material transition, classify the **highest-priority ready work** before choosing a write-capable slice. The classification is about the next material prerequisite/action, not a permanent label on the whole objective.

Exactly one classification applies by evaluating these predicates **in order and stopping at the first match**:

1. **SOL_REQUIRED** — the next material decision or write crosses a `STRONG_MODEL_REQUIRED` boundary, or correctness depends on unresolved architecture/authority judgment.
2. **LUNA_READY** — only after `SOL_REQUIRED` is false: the next material work is within `SAFE_AUTONOMOUS` / `SAFE_WITH_VERIFY`, has no unresolved Sol-only prerequisite, **and** is predominantly mechanical, deterministic, research/test/CI, bounded-refactor, or long-running throughput work that fits Luna's autonomous profile.
3. **EITHER_PROFILE** — only after both predicates above are false: the next material work is still Luna-safe and has no unresolved Sol-only prerequisite, but it is not specifically Luna-throughput work. Either Luna or Sol may execute it.

This ordered decision rule makes the three labels mutually exclusive and reproducible across fresh sessions.

Rules:

1. Recompute the classification after every reconcile, PR merge, material CI/runtime result, newly discovered blocker/finding, or `DEVELOPMENT_STATE.json` transition.
2. A mixed objective is classified by its **next material prerequisite**, while independent safe work remains eligible for Luna.
3. Explicit Luna + `SOL_REQUIRED` is fail-closed: Luna performs no protected write. It may continue independent read-only analysis, deterministic tests/proof, impact mapping, or a bounded candidate handoff, then stops dependent writes when no safe work remains.
4. Explicit Sol may proceed on `LUNA_READY`, `EITHER_PROFILE`, or `SOL_REQUIRED`; selecting Sol never requires needless hand-back to Luna.
5. Generic continuation uses the resolved active profile from §2 and applies the same gate.
6. The gate does not create a second state authority. Durable truth remains `DEVELOPMENT_STATE.json` + Git/GitHub + fresh external evidence where relevant.
7. If classification is uncertain, use `SOL_REQUIRED` for protected writes and Luna-safe behavior for all other work until the uncertainty is resolved.

The session should state the classification briefly when it materially constrains what it can do, but it should not ask the user to choose a model when the current profile can still make useful safe progress.

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

A session first builds a ready queue from:

- the current qualified objective and durable dependencies;
- open PRs/branches and their declared work-unit scope;
- pending immutable handoffs awaiting review/integration;
- current CI/runtime evidence.

Readiness and profile classification are per work unit:

- `LUNA_READY`: safe producer/throughput work;
- `SOL_REQUIRED`: protected architecture/authority work;
- `EITHER_PROFILE`: safe work either profile may own.

A `SOL_REQUIRED` unit blocks only itself and dependants. It does not block independent `LUNA_READY` work.

#### Work-unit identity and ownership

Every write-capable unit uses an isolated exact-base branch/PR and declares:

```text
Lane: LUNA | SOL
Work-Unit: <stable bounded id>
Base-SHA: <authoritative sha observed before branch creation>
Scope: <files and semantic authority owned by this unit>
Depends-On: <none or immutable prerequisite ids/shas>
Handoff-SHA: <exact candidate sha when ready for review>
State: ACTIVE | HANDOFF_READY | REVIEWED | INTEGRATION_READY
```

Recommended branch prefixes are `luna/<work-unit>` and `sol/<work-unit>`. Governance-only protocol work may use `governance/<work-unit>`.

Before any write, reconcile active work-unit scopes. Parallel writes are allowed only when their file/semantic authority does not materially overlap. If overlap is material or uncertain, the later writer fails closed and chooses another independent unit.

#### Immutable handoff

Sol review is bound to an exact `Handoff-SHA`. While Sol reviews that SHA, Luna may immediately start the next independent unit on another branch.

Luna does not append unrelated/new work to a head already under Sol review. If a requested fix changes the handoff SHA, the previous review is stale for integration and the new SHA must be reviewed/qualified as required.

#### Serialized integration gate

Parallel preparation does not imply parallel authority mutation. Merges into the authoritative branch and qualified `DEVELOPMENT_STATE.json` transitions are serialized.

Immediately before merge/state transition:

1. reconcile authoritative HEAD;
2. confirm the work-unit base/review is still applicable;
3. re-evaluate overlapping merged work since the base;
4. run any proof invalidated by base movement;
5. perform one integration mutation;
6. verify and checkpoint before another integration mutation.

Ephemeral lane occupancy is derived from GitHub branches/PRs. Do not add rapidly changing lane locks to `DEVELOPMENT_STATE.json`; it remains authority for qualified project state.

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
