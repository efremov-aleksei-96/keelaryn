# P0-30B Boundary Retrospective — 2026-09-27

## Scope and qualification reopening

P0-30B materializes one deterministic `LIGHTWEIGHT_ALL` metadata snapshot from an exact RemoteHistory publication into the already-authoritative ScanSession → Observation/Locator → Inventory path.

It does not assign Artifact/Revision identity, perform live Google OAuth/provider reads, download content, mutate corpus files, create a second inventory, or create a second identity system.

Initial implementation head: `574c919247e6a2d5ac023d51f16347a86d11818f`.

An earlier audit checkpoint at `1110c394755c606c22468e6a0d08d6923271ff39` claimed B PASS using product head `273141907d1a4af33b760c03ba219643ff77575f`, schema v23 and CI `36271236833`. A mandatory post-checkpoint audit found additional blockers, so that qualification was **reopened and superseded** rather than silently treated as still valid.

Final product-semantics head: `0cf94684182c75ddec688ee8b98710aef0b49c80`.

Final qualification/test head: `b2cc7c043062d47ba781978835a9130e60cc4201`.

Exact-head qualification CI: `36274111034` — validate PASS, Ubuntu 24.04 PASS, Windows 2025 PASS.

Current SQLite schema: **v26**.

Qualification scope: **library boundary only**. No live CLI/MCP/provider wiring is claimed.

## Final architecture

```text
exact RemoteHistory generation/publication
→ canonical nondecreasing publication time
→ source-bound scan starts at/after source publication
→ provider-specific deterministic managed-scope membership
→ canonical LIGHTWEIGHT_ALL metadata snapshot + fingerprint
→ existing source-bound OPEN ScanSession
→ existing append-only Observation/Locator evidence
→ Observation.observed_at == ScanSession.started_at
→ persisted-content fingerprint seal
→ provider-scope/topology/exact-IN revalidation in completion transaction
→ application-only source-bound COMPLETE capability
→ completion must become newest current Inventory
→ existing COMPLETE ScanSession
→ existing latest-COMPLETE Inventory
```

Google managed-root ScanSession keys are identity-domain-disambiguated. Google file-ID locators reuse the existing `gdrive.FileIDLocatorPath` provider primitive and percent-escape native object IDs.

## Findings B-B1 through B-B10

The original retrospective findings remain valid provenance:

- **B-B1 BLOCKER** — competing fingerprint at one exact source boundary. Schema v19 + API precheck enforce one fingerprint authority.
- **B-B2 BLOCKER** — mutable Observation/Locator/provider-occurrence evidence. Schema v20 seals UPDATE/DELETE.
- **B-B3 BLOCKER** — generic/direct completion and terminal append paths could bypass COMPLETE inventory authority. Schema v21 seals those paths.
- **B-B4 BLOCKER** — cross-object Locator collision. Materializer rejection plus later structural guards.
- **B-B5 BLOCKER** — forgeable/rewritable ScanSession lifecycle. Schema v22 seals OPEN→terminal lifecycle.
- **B-B6 BLOCKER** — source fingerprint was not sealed to persisted rows. Completion recomputes canonical fingerprint from persisted Observation/Locator evidence.
- **B-B7 BLOCKER** — SQLite accepted structures rejected by the public Observation API. Schema v23 adds occurrence, scope, uniqueness, locator ownership and COMPLETE coverage guards.
- **B-B8 BLOCKER** — provider scope/topology validation could race completion. It now runs inside the completion transaction.
- **B-B9 BLOCKER** — COMPLETE replay skipped durable verifier. Replay now passes through `CompleteRemoteHistoryScan`.
- **B-B10 BLOCKER** — P0-30B reimplemented Google locator encoding worse than the existing adapter. `gdrive.FileIDLocatorPath` is now shared by adapter, projector and verifier.

## Reopened-audit findings B-B11 through B-B17

### B-B11 — unsupported provider default-success — BLOCKER
The provider-scope completion switch validated Google but returned success for other providers.

Resolution: B completion fails closed unless the provider has a qualified transaction-time validator. P0-30B currently qualifies Google Drive managed-root completion only.

### B-B12 — source-bound raw-SQL COMPLETE bypass — BLOCKER
After B-B6/B-B8, the Go API performed stronger validation than the old SQLite OPEN→COMPLETE trigger. Direct SQL could still make a source-bound scan authoritative without those checks.

Resolution: schema v24 adds `remote_scan_session_complete_application_guard`. `CompleteRemoteHistoryScan` issues a connection-local capability only after all B validators pass. Raw/direct SQL cannot mint source-bound COMPLETE authority.

### B-B13 — snapshot-version/policy semantic mismatch — BLOCKER
The B fingerprint version could be paired with another policy, or LIGHTWEIGHT_ALL with another snapshot version.

Resolution: `keelaryn.remote-metadata-snapshot:v1` and `LIGHTWEIGHT_ALL:v1` are an exact pair in shared source validation. Both mismatch directions have regressions.

### B-B14 — SQLite/Go timestamp disagreement — BLOCKER
SQLite `julianday()` accepted forms such as date-only values, space-separated timestamps or normalized invalid calendar dates that Go `time.Parse(time.RFC3339Nano)` rejected later.

Resolution: schema v25 registers the same Go canonical UTC RFC3339Nano predicate for schema guards. Migration rejects existing noncanonical ScanSession/Observation time without rewriting evidence.

### B-B15 — Observation time not bound to materialization — BLOCKER
The snapshot hash intentionally excluded Observation identity assignment and `ObservedAt`; persisted Observation time could differ from the scan materialization boundary.

Resolution: for the B snapshot version every persisted Observation must have `observed_at == ScanSession.started_at`. Completion and COMPLETE replay verify it.

### B-B16 — newer publication could COMPLETE without becoming current Inventory — BLOCKER
General Inventory selects the latest COMPLETE by `finished_at`. A newer provider publication with an earlier/equal local completion time could become COMPLETE yet remain hidden behind the old inventory.

Resolution: remote completion fails closed unless its finish is **strictly later** than the current latest COMPLETE for the same provider/root. Earlier and equal cases are covered. Local scan semantics are unchanged.

### B-B17 — non-causal RemoteHistory time — BLOCKER
RemoteHistory publication sequence could advance while caller-supplied `committed_at` moved backwards, and a source-bound scan could start before its publication.

Resolution: schema v26 plus application checks make publication committed time canonical and nondecreasing, bind bootstrap committed time to generation creation time, and require source-bound scans to start at or after the bound publication. Direct-SQL bypass and upgrade inconsistencies fail closed.

## Test-only findings

### B-T1 — v25 migration harness — TEST GAP
The partial v25 migration-test pool did not register SQL functions already required by v25.

Resolution: the test harness now uses the same `Store.prepareConn`; product semantics did not change.

### B-T2 — causal/equality boundary coverage — TEST GAP
Explicit B version/policy half-pairs, equal publication time, equal scan/publication time and earlier/equal current-Inventory completion boundaries were not all directly tested.

Resolution: boundary tests were added at `b2cc7c043062d47ba781978835a9130e60cc4201`. Equal publication time and equal scan/source-publication time are valid; earlier source time and earlier/equal current-Inventory finish fail closed as designed.

## Durable-state finding

### B-L2 — stale qualification metadata — LOW
The earlier v23 PASS remained in DEVELOPMENT_STATE and the audit clock after later audits reopened B.

Resolution: revision 132 supersedes that checkpoint with v26 product/qualification evidence. Historical v23 findings remain as provenance but are no longer the current authority.

## Qualification evidence

The final B surface proves:

- exact source provenance and deterministic fingerprint;
- exact fingerprint-version/policy pairing;
- exact IN set, OUT exclusion and UNKNOWN fail-closed;
- required metadata completeness without fabrication;
- unsupported providers fail closed;
- canonical Google managed-root scope and shared percent-escaped locator projection;
- immutable/structurally sealed Observation and Locator evidence;
- canonical ScanSession/Observation time;
- `Observation.observed_at == ScanSession.started_at`;
- canonical nondecreasing RemoteHistory publication time;
- source-bound scan causal start at/after its publication;
- persisted-content fingerprint verification;
- provider topology/scope/exact-IN revalidation in the same completion transaction;
- schema-level prevention of raw-SQL source-bound COMPLETE;
- previous COMPLETE authority while a new attempt is OPEN/ABORTED/rejected;
- successful new remote COMPLETE must actually become latest current Inventory;
- deterministic COMPLETE replay including historical replay after provider history advances;
- two managed roots remain independent;
- v18→v26 append-only migration chain;
- unchanged local ScanSession semantics;
- exact-head validate/Ubuntu 24.04/Windows 2025 PASS.

## Reuse and external review

Rechecked:

- Microsoft Graph delta: complete local state plus durable continuation checkpoint;
- Google Drive changes: page token/new start page token;
- Dropbox list_folder cursor plus ordered local cache;
- Syncthing full Index plus Index Update;
- SQLite OLD/NEW triggers with `RAISE(ABORT)`;
- SQLite application-defined-function security guidance;
- zombiezen/go-sqlite `FunctionImpl.AllowIndirect`;
- zombiezen/sqlitemigration append-only transactional migrations;
- existing Keelaryn Google Drive locator primitive.

The v24 capability uses no new dependency and no durable capability table. The connection-local function has no I/O or SQL side effects; it only answers whether one scan ID is currently authorized after validation. The time functions are pure deterministic predicates. Because these functions are intentionally used by Keelaryn-owned triggers, `AllowIndirect:true` is required. A separate future security review should revisit `trusted_schema`/authorizer hardening before treating the state DB as untrusted external input.

Rejected as unnecessary:

- second remote inventory or scan table;
- provider-specific Artifact model;
- new identity resolver;
- live OAuth/provider integration in B;
- content download in B;
- new synchronization dependency;
- durable completion-capability table;
- automatic repair/normalization of invalid historical evidence;
- expanding this stage into global normalization of every historical timestamp field.

## Portability, security and runtime reachability

P0-30B adds no dependency and no OS-specific product code. Exact-head CI qualifies Ubuntu 24.04 and Windows 2025. Android remains planned and is not claimed qualified by this stage.

No B path reads credentials, performs live provider/network access, downloads content or mutates corpus files.

Runtime call-site audit confirms B remains a **library boundary**: there is no live CLI/MCP/provider execution path invoking `MaterializeRemoteMetadata`. This qualification must not be interpreted as live provider integration.

## Non-blocking systemic follow-ups

- Other historical time fields, including RemoteHistory `closed_at`, must receive their own systemic time-authority audit before a future invariant relies on them causally.
- Re-evaluate SQLite `trusted_schema`/authorizer strategy before accepting state DB files from an untrusted security domain. This is not a B blocker because current indirect functions are narrow and side-effect-free.

## Final repeated audit result

After v26 causal authority and the final causal/equality tests, the complete B boundary was re-audited across canonical invariants, durable authority, replay/interruption, transaction boundaries, migrations, direct-SQL adversarial cases, runtime reachability, portability, security, stale state and reuse/duplication.

Result on qualification head `b2cc7c043062d47ba781978835a9130e60cc4201`: **no open product BLOCKER, HIGH, MEDIUM or LOW finding**.

## Conclusion

P0-30B: **PASS / QUALIFIED at the library boundary**, schema v26.

Next substantive stage: **P0-30C — existing identity/revision integration at the same library boundary**. Live provider/CLI/MCP wiring remains deferred and separately unqualified.
