# P0-36A provider-neutral Observation optional facts retrospective — 2026-09-30

## Boundary

Audited product head: `50d8793ee19ee2b85492db2403555780af1b4088`.

Exact product tree: `0bff5a5b1033feea9d269878016745cea7147ba9`.

Exact-head qualification: GitHub Actions run `36717965505`.

Result: **PASS — P0-36_B1 resolved; zero new BLOCKER/CRITICAL findings.**

## Problem closed

P0-36 live Google Drive composition exposed a provider-neutrality defect before any live provider was wired: the durable Observation model and `LIGHTWEIGHT_ALL:v1` required `size`, `mode`, and `modified_at` for every provider object, while those facts are not universally available or meaningful across providers.

The rejected shortcut was to invent zero/default metadata and persist it as provider evidence. P0-36A instead makes fact availability explicit.

## Qualified product surface

- `ObservationRecordInput`, `ObservationRecord`, and derived inventory carry optional `size`, `mode`, and `modified_at`.
- LocalFS still records all three facts as exact known observations; its reconciliation path fails closed if its previous inventory unexpectedly lacks required LocalFS facts.
- Remote metadata accepts missing facts only under the new exact `LIGHTWEIGHT_ALL:v2` / `keelaryn.remote-metadata-snapshot:v2` pair.
- Historical `LIGHTWEIGHT_ALL:v1` remains strict and requires all legacy facts.
- The historical v1 remote-metadata fingerprint implementation is textually preserved from the qualified base.
- Identity-mutation fingerprint v1 remains the exact path when all three facts are known; requests containing unavailable facts use a tagged v2 payload.
- SQLite schema v46 adds explicit `size_known`, `mode_known`, and `modified_at_known` authority. Existing rows migrate as known.
- Canonical compatibility sentinels are never exposed as provider facts: structural guards constrain them and a connection-local application capability authorizes the availability flags.
- A pre-v46 writer rejects unavailable facts rather than silently degrading them.

No user corpus content was mutated. No live provider was contacted. No provider write scope, MCP, HTTP, or web runtime was introduced. No dependency, CI, release, update, or rollback surface changed.

## Regression and interruption review

During qualification, the aggregate SQLite test appeared to hang. Diagnostic JSON progress and stack evidence isolated the issue to the new migration regression itself, not the product runtime: the test held the only SQLite pool connection and then called `Store.Observation`, which correctly waited for a connection from the same single-connection pool.

The test now returns that connection before the public API read. The targeted migration regression then passed in 2.151 s, and the full `internal/state/sqlite` suite passed. No production deadlock fix was required.

A separate stale test-runner overlap was also reconciled before diagnosis; no failed mutation was retried blindly.

## Structural / full-risk audit

The post-fix audit reviewed all changed production surfaces and the compatibility boundary.

Findings:

- new BLOCKER: none;
- new CRITICAL: none;
- provider facts are not fabricated;
- LocalFS exact semantics are preserved;
- v1 remote fingerprint behavior is preserved exactly;
- v1/v2 policy-version pairs fail closed;
- pointer optionality consumers use availability checks and value dereference rather than pointer identity;
- schema v46 migration preserves historical semantics and protects future availability writes;
- content revision evidence remains a separate scalar evidence model;
- no dependency or workflow drift;
- no release/update/rollback behavior changed.

The unrelated release rollback and Android portability HIGH findings remain open and unchanged.

## Qualification evidence

GitHub Actions run `36717965505` on `50d8793ee19ee2b85492db2403555780af1b4088`:

- validate — PASS;
- Ubuntu 24.04 dependency lock — PASS;
- Ubuntu Go tests — PASS;
- Ubuntu Go vet — PASS;
- Windows 2025 dependency lock — PASS;
- Windows Go tests — PASS;
- Windows Go vet — PASS.

Additional disposable-VPS qualification on the exact product tree included:

- full `internal/state/sqlite` suite — PASS;
- affected non-SQLite packages — PASS;
- repository compile-all — PASS;
- `go vet ./...` — PASS;
- `git diff --check` — PASS;
- v1 remote fingerprint exact-source comparison — PASS.

## Next boundary

P0-36B may now compose the live Google Drive metadata adapter into the existing RemoteHistory/materialization path under the already-written live-provider runtime contract.

P0-36B remains read-only with respect to user corpus/provider content. It must use the exact v2 optional-fact contract, reuse existing provider/history/transaction authority, and reconcile external plus durable prestate after interruption. Authenticated executable end-user acceptance remains P0-36C and stays locked until P0-36B is exact-head qualified and audited.
