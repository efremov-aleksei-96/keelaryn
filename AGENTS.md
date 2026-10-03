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
3. reconcile open PRs, active CI and any unfinished isolated branches relevant to the current objective;
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
- Sol prioritizes immutable Luna handoffs awaiting review/integration, then architecture/authority blockers, then any other ready Sol/Either unit.
- A work unit whose dependency is itself unresolved `SOL_REQUIRED` is not ready for Luna; Luna must choose another independent unit or stop dependent writes.
- Recompute readiness and classification after every reconcile and material transition.

After any uncertain write, timeout or transport error: **reconcile only; never blindly repeat the mutation**.

## Luna profile

Luna is the long-running autonomous implementation/research profile.

In Work mode, do **not** stop after one successful slice. Continue the loop described in `docs/DEVELOPMENT_CONTINUATION.md` until a defined stop condition is reached.

Luna may autonomously perform read-only research, repository mapping, CI analysis, deterministic verification, tests, benchmarks, documentation consistency work, mechanical refactors, and bounded low-risk fixes with proof.

Luna must not independently decide or finalize core architecture, schema/migration semantics, destructive/recovery protocols, security/auth/crypto boundaries, authoritative workspace semantics, provider identity semantics, irreversible storage changes, or other surfaces classified as strong-model-required.

## Sol profile

Sol is the strong-model development profile.

Sol follows the same reconcile → one coherent mutation → verify → checkpoint discipline, but may own architecture-sensitive decisions, high-risk implementation slices, stage qualification, and authoritative development-state updates when evidence supports them.

## Parallel Luna/Sol lanes

Keelaryn development is a concurrent producer/reviewer/integrator pipeline, not a Luna→Sol→Luna relay.

- **Luna lane — producer/throughput.** Luna may keep implementing or proving work unit N+1 while Sol reviews immutable handoff N.
- **Sol lane — review/architecture/integration.** Sol reviews exact Luna handoff SHAs, resolves protected decisions, and performs serialized integration/state transitions. Sol may also implement its own isolated work units.
- Every write-capable work unit uses its own isolated exact-base branch/PR. Recommended prefixes are `luna/<work-unit>` and `sol/<work-unit>`; governance-only changes may use `governance/<work-unit>`.
- Before writing, inspect active open PRs/branches and their declared scope. Two active writers must not own overlapping files/semantic authority. If overlap is material or uncertain, fail closed and choose another unit.
- Each PR/handoff must declare at minimum: lane, work-unit ID, base SHA, scope, dependencies, exact handoff SHA, and state.
- Sol review binds to the **exact handoff SHA**. Once that review starts, Luna does not append unrelated/new work to that reviewed head; it starts the next independent work unit on another branch. Any required fix that changes the handoff SHA invalidates the prior review for integration purposes.
- Authoritative merges and `DEVELOPMENT_STATE.json` transitions are the serialized integration gate. Immediately before either, reconcile authoritative HEAD. If base moved, re-evaluate conflicts and re-run required proof; never assume a previously reviewed base is still merge-safe.
- Ephemeral lane occupancy is derived from GitHub branches/PRs, not stored as mutable live state in `DEVELOPMENT_STATE.json`. That file remains authority for qualified project state only.
- One model must not commandeer or rewrite the other lane's active branch. Review the immutable head, or create a separate remediation/integration branch.

## Shared safety

- one coherent mutation per transactional slice;
- exact-base isolated branch/PR for non-trivial writes;
- targeted proof first, then relevant regression/CI;
- no reset --hard, force-push, destructive checkout, mass clean, history rewrite or blind retry;
- do not create a second live development-state authority;
- waiting on CI should be used for independent read-only work where safe.
