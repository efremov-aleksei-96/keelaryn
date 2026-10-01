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

The user may start a fresh chat and say only:

- `продолжить работу`
- `продолжить работу при помощи Luna`
- `продолжить работу при помощи Sol`

Treat these as commands to resume Keelaryn development from durable live state.

Always determine the **actual active model**. Never claim to switch models inside a chat. If the user explicitly names Luna or Sol and the active model does not match, say so briefly and use the actual model profile only if the user asked to continue anyway.

Before any write:

1. reconcile the authoritative branch and exact HEAD;
2. read the compact development preflight or `DEVELOPMENT_STATE.json`;
3. reconcile open PRs, active CI and any unfinished isolated branches relevant to the current objective;
4. read only the architecture/contracts needed for the next slice;
5. classify the slice under the Luna/Sol rules below.

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
