# Keelaryn development entrypoint

For development work, read this file first.

## Durable authority

1. `KEELARYN_CANONICAL.md` — product architecture.
2. `DEVELOPMENT_STATE.json` — current development checkpoint and next objective.
3. Git/GitHub — branch, commit, PR and CI reality.
4. External runtime/provider state — freshly observed when relevant.
5. Chat history is never required authority.

Detailed continuation rules: `docs/DEVELOPMENT_CONTINUATION.md`.

## "Continue work" contract

The user may start a fresh chat and say:

- `продолжить работу над Keelaryn`
- `продолжить работу над Keelaryn при помощи Luna`
- `продолжить работу над Keelaryn при помощи Sol`

Treat these as commands to resume Keelaryn development from durable live state. A bare `продолжить работу` is only a context-bound shorthand as defined below.

## Project identity gate

This repository's canonical project identity is **Keelaryn** (`KEELARYN`). In a multi-project environment, the preferred commands are:

- `продолжить работу над Keelaryn`
- `продолжить работу над Keelaryn при помощи Luna`
- `продолжить работу над Keelaryn при помощи Sol`

A bare `продолжить работу` is valid only when the active chat, Work workspace, or repository context is already unambiguously bound to Keelaryn.

Before any write, verify that the named/active project resolves to this repository and this project's durable state. If the user names another project, or project identity is missing/ambiguous in a multi-project context, **do not write**. Resolve/select the project first. Never reuse Keelaryn branches, PRs, CI, objectives, or `DEVELOPMENT_STATE.json` as authority for another project.

Resolve the execution profile fail-closed:

- explicit `продолжить работу при помощи Luna` always enforces the **Luna-safe** profile, even if the active model is stronger or its identity is unclear;
- explicit `продолжить работу при помощи Sol` enables the **Sol** profile only when the environment positively identifies the active model as Sol;
- generic `продолжить работу` uses the positively identified active model profile;
- if model identity is unavailable, ambiguous, or conflicts with an explicit Sol request, fall back to **Luna-safe / least-privilege** and state the mismatch or uncertainty briefly.

Never claim to have switched models inside the chat. A stronger model may voluntarily operate under the Luna-safe profile; a weaker or unidentified model must never promote itself to Sol privileges.

Before any write:

1. reconcile the authoritative branch and exact HEAD;
2. read the compact development preflight or `DEVELOPMENT_STATE.json`;
3. reconcile open work-claim issues, open PRs, active CI and any unfinished isolated branches relevant to the current objective;
4. read only the architecture/contracts needed for the next slice;
5. classify the slice under the Luna/Sol rules below.

Before selecting any write-capable slice, build the ready queue from the current objective, open PRs/branches and unresolved dependencies. Classification is **per work unit**, not one global classification for the whole objective.

Classify each candidate work unit:

1. `SOL_REQUIRED` — that work unit crosses a STRONG_MODEL_REQUIRED boundary or depends on unresolved architecture/authority judgment.
2. `LUNA_READY` — that work unit is Luna-safe and predominantly mechanical, deterministic, research/test/CI, bounded refactor, or long-running throughput work.
3. `EITHER_PROFILE` — that work unit is Luna-safe but not specifically throughput-oriented.

Selection rules:

- Luna selects the highest-priority ready, non-overlapping `LUNA_READY` work unit, then `EITHER_PROFILE` if no higher Luna-ready unit exists.
- The existence of a separate `SOL_REQUIRED` work unit is **not** a global stop. Luna continues any independent safe unit whose dependencies are satisfied.
- Sol prioritizes immutable Luna handoffs awaiting review/integration, then architecture/authority blockers, then `EITHER_PROFILE`, then `LUNA_READY` when no higher-priority Sol work remains.
- A work unit whose dependency is itself unresolved `SOL_REQUIRED` is not ready for Luna; Luna must choose another independent unit or stop dependent writes.
- Recompute readiness and classification after every reconcile and material transition.
- If Luna has no explicit ready, unclaimed/non-overlapping `LUNA_READY` or `EITHER_PROFILE` unit, it must run the bounded perpetual-discovery fallback in `docs/LUNA_PERPETUAL_DISCOVERY.md` before concluding that no work exists. An occupied implementation slice, a separate `SOL_REQUIRED` unit, or ordinary CI/review waiting does not exhaust the Luna lane while independent discovery work remains.
- Discovery is evidence generation, not architecture authority. Luna may hunt defects, map correctness/architecture, benchmark, inspect dependency/platform/API risks, research competitors/upstream/open-source reuse, and audit roadmap direction against canonical goals. Protected decisions discovered by that work become Sol-ready findings; they are not silently decided by Luna.

After any uncertain write, timeout or transport error: **reconcile only; never blindly repeat the mutation**.

## Luna profile

Luna is the long-running autonomous implementation/research profile.

In Work mode, do **not** stop after one successful slice. Continue the loop described in `docs/DEVELOPMENT_CONTINUATION.md` until a defined stop condition is reached.

When the explicit implementation queue is empty, blocked by another lane, or waiting on CI/review/provider evidence, Luna must attempt a bounded discovery cycle before stopping. The discovery catalog and durable ledger are defined in `docs/LUNA_PERPETUAL_DISCOVERY.md`: lookup the exact `[DISCOVERY-CYCLE] <baseline-sha>` title across open+closed issues, arbitrate duplicate issues deterministically, and bind results to the current durable epoch. Material same-HEAD review/CI/runtime evidence creates a reset-comment epoch, so fresh sessions resume the correct risk generation instead of restarting or trusting stale results.

Luna may autonomously perform read-only research, repository mapping, CI analysis, deterministic verification, tests, benchmarks, documentation consistency work, mechanical refactors, bounded low-risk fixes with proof, adversarial bug hunting, external competitor/upstream/open-source reconnaissance, and evidence-based direction audits.

Luna must not independently decide or finalize core architecture, schema/migration semantics, destructive/recovery protocols, security/auth/crypto boundaries, authoritative workspace semantics, provider identity semantics, irreversible storage changes, or other surfaces classified as strong-model-required.

## Sol profile

Sol is the strong-model development profile.

Sol follows the same reconcile → one coherent mutation → verify → checkpoint discipline, but may own architecture-sensitive decisions, high-risk implementation slices, stage qualification, and authoritative development-state updates when evidence supports them.

## Parallel Luna/Sol lanes

Keelaryn development is a concurrent producer/reviewer/integrator pipeline, not a Luna→Sol→Luna relay.

- **Luna lane — producer/throughput.** Luna may keep implementing or proving work unit N+1 while Sol reviews immutable handoff N.
- **Sol lane — review/architecture/integration.** Sol reviews exact Luna handoff SHAs, resolves protected decisions, and performs serialized integration/state transitions. Sol may also implement its own isolated work units.
- Before the **first branch/file write** for a work unit, publish a GitHub issue titled `[WORK-CLAIM] <work-unit>` containing lane, work-unit ID, exact base SHA, file/semantic scope, dependencies, `State: CLAIMING`, and `Lease-Until` no more than 30 minutes after claim creation.
- Immediately after publishing the claim, reconcile all open `[WORK-CLAIM]` issues and open PR scopes. For occupancy purposes, an **active PR** means an open, transfer-valid PR that is still the unique winner under overlapping-PR arbitration; invalid or losing open PRs must be closed and do not occupy scope. Any material overlap with an active PR makes the new claim lose immediately: **close the losing claim issue** and choose another unit before branch creation or file edits. Only when no active PR owns the scope do materially overlapping claims compete; among those claims, the lowest GitHub claim issue number wins deterministically and every later claimant must **close its losing claim issue** before any branch/file write. Open `ABANDONED` claim issues are forbidden. If claim visibility or overlap is uncertain, fail closed.
- An acquired claim is a **short claim-transfer lease**, not permission for substantive edits. Before `Lease-Until`, the owner creates an isolated exact-base branch whose name includes the claim number, writes only the metadata marker `.keelaryn-work/<work-unit>.json`, and opens a draft PR referencing the claim with its **base explicitly set to the authoritative development branch**. After creation, re-fetch the PR and require its base branch and base SHA to match the authoritative branch/acquired `Base-SHA`; if either differs, close the PR without substantive edits and reacquire correctly. No product/code/document scope may be edited before that PR is verified remotely visible with the correct authoritative base.
- Recommended branch forms are `luna/<work-unit>-c<claim>` and `sol/<work-unit>-c<claim>`; governance-only work may use `governance/<work-unit>-c<claim>`.
- After the draft PR is remotely visible and repeats the ownership fields, reconcile transfer eligibility using GitHub server timestamps. The PR is transfer-valid only if its `created_at` is no later than `Lease-Until` and, if the claim was already closed as stale, the PR `created_at` is earlier than the claim `closed_at`; otherwise close the PR without substantive edits and acquire a new claim. Transfer-valid does not by itself guarantee unique ownership: before substantive writes, arbitrate against every materially overlapping active transfer-valid PR. The unique owner is the PR with the earliest GitHub `created_at`; if timestamps are equal, the lower PR number wins. Any later overlapping PR loses write authority immediately, must stop substantive edits and **close the PR**; an open `ABANDONED` PR state is forbidden, and the losing PR must not merge. A late-observed older valid PR therefore preempts replacement ownership deterministically. For the unique winner, close the issue claim. The claim marker **must be removed before integration**; integration is forbidden while `.keelaryn-work/<work-unit>.json` from that claim remains in the PR diff. The marker is never qualified product/state authority.
- If `Lease-Until` expires before ownership transfers, a fresh session may retire/close the claim only after re-fetching the claim and reconciling that no open PR references it immediately before retirement. If a racing PR is observed later, first decide transfer-validity from GitHub `created_at` / claim `closed_at`, then run the overlapping-active-PR arbitration above before any owner continues. Because substantive edits are forbidden before transfer and every active owner must re-arbitrate before its next write, a late-observed older valid PR cannot coexist as a second writer. Any branch/marker from an invalid, expired, or losing claim/PR is abandoned and must not be reused; recovery starts with a new claim/new claim-numbered branch. An interrupted original session must reconcile before its next write and therefore observes whether its claim/PR still uniquely owns the scope.
- Each active PR/handoff must declare at minimum: claim issue, lane, work-unit ID, base SHA, scope, dependencies, exact handoff SHA, and state.
- Sol review binds to the **exact handoff SHA**. Once that review starts, Luna does not append unrelated/new work to that reviewed head; it starts the next independent work unit on another claim/branch. Any required fix that changes the handoff SHA invalidates the prior review for integration purposes. The reviewed handoff is integrated only through the conditional-fast-forward gate below.
- Authoritative integration uses a **remote integration claim plus an atomic conditional fast-forward**, never GitHub's ordinary PR merge endpoint. The work-unit/PR `Base-SHA` is the acquired base on which the reviewed handoff was built. **Do not graft an old handoff tree onto a newer authoritative base.** Before creating an integration claim, require authoritative HEAD = work-unit `Base-SHA`; if HEAD moved, do **not** rewrite/force-push the reviewed PR. Close that PR as superseded, acquire a new work claim for a successor candidate, create a new exact-base claim-numbered branch/PR from the new authoritative HEAD, replay only the bounded intended diff, produce a new exact `Handoff-SHA`, and rerun all review/CI/proof invalidated by the base change. Only the successor candidate may use the new base as its work-unit/integration `Base-SHA`. Publish `[INTEGRATION-CLAIM] <work-unit>` with PR number, exact handoff SHA, that exact work-unit `Base-SHA`, `State: CLAIMING`, and `Lease-Until` no more than 10 minutes after claim creation; reconcile same-base claims and let the lowest issue number win. For the winner, read the exact tree of `Handoff-SHA`, create an integration commit whose tree is that exact tree and whose **only parent is the same reviewed work-unit `Base-SHA`**, then update the authoritative branch ref to that integration commit with `force=false`. Force updates are forbidden. This non-force ref update is the atomic base guard: if authoritative HEAD moved after qualification, the sibling candidate is not a fast-forward and GitHub must reject it. Never call the PR merge endpoint for authoritative integration. On timeout/uncertain result, reconcile the authoritative ref and candidate commit only; never blindly retry. After verified success, close the PR and integration claim with the integration commit SHA. An expired integration claim may be replaced only through the same conditional-fast-forward primitive, so an older in-flight integration and its replacement can race but at most one can move the authoritative ref. Integration claims are ephemeral GitHub coordination, never qualified project state.
- Ephemeral lane occupancy is derived from open work-claim issues until claim transfer, then from open PRs. It is not stored as mutable live state in `DEVELOPMENT_STATE.json`; that file remains authority for qualified project state only.
- One model must not commandeer or rewrite the other lane's active branch. Review the immutable head, or create a separate claimed remediation/integration unit.

## Shared safety

- one coherent mutation per transactional slice;
- exact-base isolated branch/PR for non-trivial writes;
- targeted proof first, then relevant regression/CI;
- no reset --hard, force-push, destructive checkout, mass clean, history rewrite or blind retry;
- do not create a second live development-state authority;
- waiting on CI should be used for independent read-only work where safe.
