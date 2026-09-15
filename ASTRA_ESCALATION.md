# Keelaryn Critical Review Escalation

This protocol defines when Manager Development may spend scarce access to a higher-capability reviewer. The current preferred reviewer is **GPT-6 Astra**. Ordinary engineering remains on **GPT-5.6 Sol** plus repository tests and GitHub-hosted Windows validation.

The purpose is not to make Astra part of every development cycle. The purpose is to reserve a small Plus-plan allowance for review points where an independent, deeper adversarial pass can materially reduce release risk.

## Default rule

Use Sol for implementation, GitHub work, CI diagnosis, harness fixes, metadata/provenance maintenance, ordinary code review, and repeated qualification execution. Do not switch models merely because a task is long.

Astra escalation is **manual and bounded**. The current assistant must never assume that Astra quota is available and must never make candidate qualification depend on an unavailable model. When escalation is justified, the assistant should say so explicitly and produce the compact review packet described below; the maintainer may then switch the task to Astra.

## Allowed critical-point triggers

Escalation is justified when at least one of these conditions is true:

1. **Final pre-freeze adversarial review.** The exact intended head has coherent normal automated evidence, the product/risk range is stable enough to review, and the remaining task is to search for semantic blockers, transaction defects, cross-instance contamination, fail-open behavior, or false-positive tests before candidate freeze.
2. **Evidence/reality contradiction.** Green gates and source/runtime reasoning materially disagree, or a new systemic defect is discovered after evidence that appeared to prove the affected property.
3. **Repeated unresolved classification.** Two evidence-backed Sol iterations have failed to distinguish product defect from gate/framework/harness/environment cause, or have produced materially conflicting hypotheses without narrowing the uncertainty.
4. **High-consequence proof-quality question.** A transaction/commit, rollback, security, multi-Hub identity/isolation, update handoff, migration, or recovery property appears to depend on a test oracle that may pass without proving the production runtime path.
5. **Successor-line escape pattern.** A defect class has repeatedly escaped late review or post-freeze qualification and an independent review of the exact corrected design is cheaper and safer than another broad speculative development loop.

A critical point is not created merely by elapsed time, a large diff, or a failing CI run.

## Do not spend Astra on

Do not use scarce Astra allowance for GitHub Actions polling, waiting for jobs, routine log reading, straightforward code generation, ordinary refactors, mechanical metadata synchronization, deterministic manifest/provenance updates, known harness-only fixes, retrying a known environmental failure, or repeating an already-conclusive test.

Do not hand Astra an open-ended instruction such as “continue development until production.” Its task must be a bounded review question with explicit identities and stop conditions.

## Plus-plan budget discipline

Treat Astra as scarce capacity:

- default to **one Astra review per critical point**;
- prefer one consolidated review after the exact review tree stabilizes rather than several reviews of intermediate heads;
- do not request a second pass unless the first pass found a material blocker that changed the reviewed semantics, or the review could not answer because a specifically identified input was missing;
- return implementation, CI iteration, evidence collection, provenance work and ordinary follow-up to Sol;
- keep the packet compact: changed functions/paths, applicable invariants and exact evidence identities are preferred over full repository history or full runtime source.

## Required review packet

Before escalation, produce a self-contained packet containing:

- repository and authoritative `dev/**` branch;
- exact review **base commit**, **head commit** and **head tree**;
- Manager version and explicit candidate/freeze state;
- exact changed Manager product paths, separated from tooling/knowledge/provenance-only paths;
- the narrow risk question that triggered escalation;
- applicable invariants, state-machine rules, open/recent defect IDs and transaction boundaries;
- last relevant PASS/FAIL evidence with run/job/artifact identities when available;
- known false-positive or harness failure history only where it affects the review question;
- explicit non-goals and forbidden scope expansion;
- a stop condition.

The preferred review request is:

> Perform an independent adversarial review of the exact base-to-head change. Look specifically for correctness, transaction/rollback, security, multi-Hub isolation, recovery, update/migration, and proof-oracle failures that could still pass the listed gates. Report only concrete blockers or material gaps, with severity and exact reasoning. Do not redesign unrelated subsystems. If no blocker is found, say so explicitly. Do not treat your review as qualification or candidate approval.

## Result handling

An Astra result is **advisory evidence, never qualification by itself**.

If Astra finds a plausible release blocker, stop freeze, reproduce or otherwise evidence the issue under the normal failure-classification rules, add permanent regression/knowledge coverage where applicable, fix through the normal `dev/**` lifecycle, and re-run the required exact-head gates. A new review is considered only after the changed semantics stabilize.

If Astra reports no blocker, continue the ordinary Keelaryn promotion contract. The clean review cannot replace parser checks, SelfTest, Development Validation, Risk/Defect Gate, Source/Full Gate, production-specific acceptance, provenance binding, or any other required gate.

## Stop conditions for the current assistant

When a trigger fires, do not enter an unbounded audit loop. Either:

- continue with Sol if the next discriminating test is clear and cheap; or
- declare **“Astra escalation recommended”**, provide the compact packet, and stop expanding the review scope until the maintainer decides whether to spend Astra quota.

After an Astra answer is consumed, return to Sol for normal engineering unless another independently justified critical point is reached.
