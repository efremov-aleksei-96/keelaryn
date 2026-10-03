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

Before selecting any write-capable slice, classify the **highest-priority ready work** (not the whole roadmap) through the objective/profile suitability gate:

Evaluate in this order, stopping at the first match:

1. `SOL_REQUIRED` — the next material decision or write crosses a STRONG_MODEL_REQUIRED boundary or depends on unresolved architecture/authority judgment.
2. `LUNA_READY` — after `SOL_REQUIRED` is false, the next material work is Luna-safe **and** is predominantly mechanical, deterministic, research/test/CI, bounded refactor, or long-running throughput work suited to Luna.
3. `EITHER_PROFILE` — after both predicates above are false, the next material work is still Luna-safe, but is not specifically Luna-throughput work; either Luna or Sol may execute it.

Recompute this classification after every reconcile and after any material transition (merge, CI result, new blocker/finding, objective/state change).

If the selected profile is Luna and the classification is `SOL_REQUIRED`, Luna must not perform the protected write. It should continue any independent safe analysis, tests, proof, mapping, or candidate handoff work, then stop dependent writes when no safe work remains. Sol may proceed on any of the three classifications while preserving the same transaction discipline.

After any uncertain write, timeout or transport error: **reconcile only; never blindly repeat the mutation**.

## Luna profile

Luna is the long-running autonomous implementation/research profile.

In Work mode, do **not** stop after one successful slice. Continue the loop described in `docs/DEVELOPMENT_CONTINUATION.md` until a defined stop condition is reached.

Luna may autonomously perform read-only research, repository mapping, CI analysis, deterministic verification, tests, benchmarks, documentation consistency work, mechanical refactors, and bounded low-risk fixes with proof.

Luna must not independently decide or finalize core architecture, schema/migration semantics, destructive/recovery protocols, security/auth/crypto boundaries, authoritative workspace semantics, provider identity semantics, irreversible storage changes, or other surfaces classified as strong-model-required.

## Sol profile

Sol is the strong-model development profile.

Sol follows the same reconcile → one coherent mutation → verify → checkpoint discipline, but may own architecture-sensitive decisions, high-risk implementation slices, stage qualification, and authoritative development-state updates when evidence supports them.

## Shared safety

- one coherent mutation per transactional slice;
- exact-base isolated branch/PR for non-trivial writes;
- targeted proof first, then relevant regression/CI;
- no reset --hard, force-push, destructive checkout, mass clean, history rewrite or blind retry;
- do not create a second live development-state authority;
- waiting on CI should be used for independent read-only work where safe.
