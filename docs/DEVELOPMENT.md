# Development

## Authority
- Product architecture: `KEELARYN_CANONICAL.md`
- Current checkpoint: `DEVELOPMENT_STATE.json`
- Source/history/CI: GitHub
- Runtime/provider reality: freshly observed external state
- AI/chat: orchestrator, never durable authority

## Branches
- `dev/corpus-first-p0`: active clean Corpus-first line
- `legacy/pre-corpus-p0-20260924`: frozen pre-P0 implementation
- `dev/zero-based-keelaryn`: superseded provenance line

## Transaction discipline
1. Read-only verify authoritative prestate.
2. Validate failure-prone conditions.
3. Perform at most one coherent mutation.
4. Immediately read-only verify durable result.
5. Checkpoint concise state.
6. After interruption, never blindly retry.

## Reuse gate
Before custom implementation, evaluate existing standards/projects for fit, invariants, maintenance, security, license, platform support, runtime cost, API stability, lock-in and replacement path.

Preferred order: reuse → wrap → subprocess/service integration → permissive fork/upstream → reuse design/tests → custom Keelaryn-specific gap.

P0 development starts only after C0 completes.
