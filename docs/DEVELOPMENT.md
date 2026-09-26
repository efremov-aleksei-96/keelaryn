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

C0 is closed. Active development is now the minimal P0 technology spike. Deferred inert legacy cleanup must not silently become active architecture or block P0.

## Project continuity contract
D0 was the development-specific bootstrap for Keelaryn. The reusable rule is broader: every long-lived managed project that claims autonomous resumability keeps a compact durable state artifact physically inside the project boundary, normally `.keelaryn/PROJECT_STATE.json`. External authorities are referenced and freshly reconciled when needed; chat is never the only project checkpoint.

Keelaryn product development itself follows this rule through repository-local `DEVELOPMENT_STATE.json`. See `docs/PROJECT_CONTINUITY_AND_OBSERVATION_POLICY.md`.

## Observation policy
Baseline corpus discovery is `LIGHTWEIGHT_ALL`: keep low-cost observations for every in-scope object. Expensive hashing/extraction is separately configurable and may run on change or in bounded background mode. Exact fresh derived results should be reused before rereading unchanged source bytes.

## Execution cadence and anti-stall discipline

Long engineering runs must be decomposed into short transactional slices.

Default operating rule:

- avoid silent stretches that make a healthy run indistinguishable from a stalled one;
- send a concise progress heartbeat at least every few minutes during tool-heavy work, even when the only active dependency is CI;
- do not hold several speculative mutations open while waiting for one external result;
- keep each durable write coherent and independently reconcilable;
- if a tool/transport response is lost, reconcile authoritative state before retrying;
- waiting for CI/provider/runtime evidence must not block safe read-only work.

When transaction independence allows it, use waiting time for **parallel read-only work**, especially:

- architecture/correctness/security audit;
- call-site and migration audit;
- nearest-analogue / prior-art research;
- dependency/license/platform review;
- adversarial test design;
- documentation/state consistency review.

Parallel work must never weaken mutation ordering: discoveries may prepare the next slice, but a dependent write waits for the current authoritative mutation/qualification boundary.

