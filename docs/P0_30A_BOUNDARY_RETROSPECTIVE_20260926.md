# P0-30A Boundary Retrospective — 2026-09-26

Status: **PASS AFTER BLOCKER HARDENING**

Initial implementation head: `8502548da50f500fb5a85c47378e15f5402b8ab0`  
Initial CI run `36261026382`: validate PASS, Ubuntu 24.04 PASS, Windows 2025 PASS.

Final hardened product head: `bec746f4f2d8975c3ac44405b9aaa14551beb0ea`  
Resolution CI run `36262810988`: validate PASS, Ubuntu 24.04 PASS, Windows 2025 PASS.

No live provider/OAuth access or corpus mutation occurred.

## Scope

P0-30A adds only the durable source boundary for a remote observation attempt:

RemoteHistory exact generation/publication
→ existing OPEN ScanSession
→ immutable remote source sidecar
→ replay/reconcile
→ guarded COMPLETE or ABORTED.

It does not materialize provider metadata into Observations, assign Artifact identity, download content, create a second inventory, or introduce live Google access.

## Findings on the initial implementation

### A-B1 — source sidecar was immutable while its ScanSession context was mutable

Severity: **BLOCKER**

Schema v17 made `remote_scan_sources` immutable, but the referenced `scan_sessions` row had no SQLite guard protecting `provider_id`, `root`, or `started_at`.

The Go API did not intentionally rewrite those fields, but durable authority must not depend on every future caller avoiding direct SQL. Rewriting them would change the meaning of otherwise immutable source provenance and replay scope.

Correction: append-only schema v18 adds `remote_scan_session_update_guard`. For a source-bound scan it preserves scan ID, provider, root and start time and allows only the intended terminal lifecycle transition from OPEN to COMPLETE or ABORTED.

### A-B2 — stale COMPLETE could bypass the guarded completion API

Severity: **BLOCKER**

`CompleteRemoteHistoryScan` correctly revalidated ACTIVE generation + exact publication, and generic `CompleteScan` rejected a source-bound scan. However, schema v17 still allowed direct SQL to set an OPEN source-bound row to COMPLETE after RemoteHistory had advanced.

That would make a stale scan authoritative inventory state while bypassing the final mutation-boundary revalidation required by the contract.

Correction: schema v18 adds `remote_scan_session_complete_source_guard`. Every source-bound OPEN→COMPLETE UPDATE now requires the bound generation to remain ACTIVE and its current sequence to equal the bound publication, regardless of which caller issued the UPDATE.

Regression coverage proves direct stale completion is rejected without mutating the scan.

### A-L1 — audit-clock prose was stale

Severity: **LOW / DOCUMENTATION**

`docs/ENGINEERING_AUDIT_POLICY.md` still described the earlier unresolved P0-29D blocker state even though P0-29D had subsequently passed.

Correction: synchronize the current audit clock with this completed P0-30A retrospective.

## Resolution and adversarial coverage

Schema v17 was not rewritten. The correction is a new v18 migration because existing databases resume from the migration position already applied.

The hardened tests cover:

- direct mutation of source-bound scan provider/root/start context is rejected;
- ordinary guarded COMPLETE still succeeds while the exact source publication remains current;
- stale OPEN→COMPLETE through direct SQL is rejected after RemoteHistory advances;
- ABORT remains allowed;
- terminal source-bound rows cannot be reopened/reinterpreted;
- v17 databases migrate to the v18 guards;
- prior replay/reconcile/reopen and local ScanSession tests remain green.

Final exact-head CI `36262810988` passes validate, Ubuntu 24.04 and Windows 2025.

## Reuse / nearest-analog audit

The architecture remains reuse-first.

Microsoft Graph driveItem delta uses complete enumeration followed by a terminal `deltaLink` for future updates. Google Drive changes similarly uses stored page tokens and exposes the next checkpoint only after the current change list reaches its end. Dropbox cursor continuation and Syncthing full-index/incremental-update patterns support the same broad shape: exact external checkpoint + local materialized state + replay/resync discipline.

These patterns support the existing Keelaryn decision to bind the ordinary ScanSession to exact provider-history provenance. They do not justify importing those products' identity semantics.

SQLite already provides row-level OLD/NEW trigger guards and abort semantics, so a custom provenance service is unnecessary. The existing `zombiezen.com/go/sqlite/sqlitemigration` append-only migration mechanism is retained; no new dependency is needed.

## Simplification decisions

Rejected as unnecessary:

- second remote inventory;
- second remote ScanSession table;
- provider-specific Artifact model;
- new provenance service;
- new database dependency;
- rewriting schema v17;
- provider-specific materializer inside P0-30A.

The minimal durable delta is one existing v17 sidecar plus v18 guards around the already-authoritative ScanSession.

## Portability / security / recovery

- no new OS-specific code was introduced;
- Ubuntu 24.04 and Windows 2025 are qualified on the exact hardened head;
- Android remains a planned target and is not claimed qualified by this stage;
- no credentials or live provider boundary were introduced;
- matching COMPLETE replay remains valid durable-result reconciliation after history advance;
- matching OPEN remains recoverable evidence and must be reconciled/aborted rather than blindly continued;
- previous COMPLETE inventory remains the authority until a later source-bound scan is validly completed.

## Final result

**PASS.**

Open BLOCKER findings: **0**.  
Open HIGH findings: **0**.  
Schema: **v18**.  
Dependencies added: **0**.  
Live provider access: **none**.  
Corpus mutations: **0**.

P0-30A is qualified. The next substantive stage is P0-30B deterministic LIGHTWEIGHT_ALL metadata materialization into the existing ScanSession / Observation / Inventory path. P0-30B must receive its own exact-head CI and mandatory stage retrospective before P0-30C.
