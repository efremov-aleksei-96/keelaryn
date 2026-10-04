# POST-P0-02B accepted local source retrospective — 2026-10-04

## Result

**PASS — POST-P0-02B qualified; complete A01–A12 retrospective finished; A13 synthesis found zero new findings at every severity.**

POST-P0-02B is the read-side foundation required before any post-bootstrap LocalFS accepted publication. It separates generic scan chronology from the narrower source boundary that protected search and ContextBundle may treat as accepted current authority.

This retrospective does **not** enable a watcher, incremental scheduler, new LocalFS durable publication path, generic conclusive identity writer, schema migration, or remote-history behavior change.

## Qualified provenance

Implementation handoff:

- PR #135
- handoff `bcb8554728623c1a4d7b2305fd6870d10184bc36`
- exact tree `c5339239a9aaf5f74501814cf6d636a1a1ab0ac8`
- exact-head CI run `37204610224`: validate + Ubuntu 24.04 + Windows 2025 PASS
- dependency lock PASS
- all Go tests PASS
- Go vet PASS
- Codex exact-head review: clean
- Sol exact-head semantic review: PASS

Serialized integration:

- integration claim #136
- authoritative integration head `7b678af4523f0edb9fa83d8794274b71f0f57cf2`
- integration commit has exactly one parent, revision-240 base `587fc1d756346af5777c91e499e6a1ffca9cfc11`
- integration tree is exactly the reviewed handoff tree
- ordinary GitHub merge was not used
- authoritative push CI run `37205431103`: PASS

## What changed

The previous protected LocalFS runtime coupled current search/context authority to generic latest COMPLETE scan chronology. That was unsafe for item 2 because an ordinary repeated LocalFS scan is unresolved observation evidence and must not silently replace an accepted Artifact/Revision inventory.

POST-P0-02B adds a narrow accepted-source read boundary:

1. durable BOOTSTRAP receipts are selected separately from generic COMPLETE scan chronology;
2. selection is qualified by the supported fingerprint version before newest-source ordering;
3. a later unsupported bootstrap cannot eclipse a still-qualified accepted source;
4. a later ordinary metadata-only SCAN receipt remains chronology/evidence only and cannot become accepted search/context authority;
5. inventory is read from the exact accepted scan with `InventoryAtScan`;
6. search and ContextBundle reuse the existing `searchsqlite.SourceBoundary`;
7. accepted source/corpus fingerprints are re-proven around corpus reads and drift fails closed.

The implementation introduced no new durable write path. The future accepted SCAN publication remains POST-P0-02C work and must use a distinct qualified fingerprint contract rather than overloading the existing metadata-only SCAN v1 meaning.

## Correction during qualification

The first 02B candidate contained literal escaped newline/tab characters in several Go files. Those were mechanical generation defects and were corrected without changing intended semantics.

The Sol exact-head review then found one substantive edge case: choosing the newest BOOTSTRAP before checking fingerprint support could let a newer unsupported receipt eclipse an older qualified source. The selector was corrected so fingerprint qualification is part of SQL selection itself, and an adversarial regression now covers that case.

No unresolved finding remains from either correction.

## Mandatory full engineering retrospective

Audit policy: `docs/ENGINEERING_AUDIT_POLICY.md`

Pinned immutable product head: `7b678af4523f0edb9fa83d8794274b71f0f57cf2`

### A01 — canonical invariants versus implementation

**PASS.** Generic scan chronology remains historical chronology; accepted runtime source authority is narrower. Artifact/Revision/provider identity semantics are unchanged. Search remains derived and source-bound.

### A02 — durable-authority boundaries

**PASS.** Accepted source derives from `state.db` receipt/bootstrap authority, not from search cache or filesystem metadata alone. Exact accepted inventory is selected by ScanID.

### A03 — replay, idempotency and interruption

**PASS.** No new durable write or replay token exists in 02B. Existing bootstrap replay remains intact. Read-side interruption cannot partially mutate identity/state.

### A04 — transaction atomicity and mutation-boundary revalidation

**PASS.** No state transaction path is added or weakened. Accepted-source proof brackets index/context corpus reads; protected read-only search re-derives the expected state boundary before and after the bound search operation.

### A05 — schema migration and rollback implications

**PASS WITH CARRIED HIGH.** No schema or durable format changes. Existing HIGH `AUDIT_RELEASE_H1_STATE_DB_ROLLBACK_NOT_IMPLEMENTED` remains a later release/update gate.

### A06 — negative and adversarial cases

**PASS.** New regressions cover later unresolved ordinary COMPLETE scans, newer unsupported bootstrap fingerprints, exact historical inventory reads and OPEN-scan rejection. Existing corruption, drift, recovery, cancellation and failure-window suites remain green.

### A07 — runtime call-site reachability

**PASS — REACHABLE PRODUCT PATH.** CLI search/context, MCP search/context and protected index rebuild all traverse the new accepted-source boundary.

### A08 — cross-platform assumptions

**PASS WITH CARRIED ANDROID GATE.** No new OS-specific identity mechanism or dependency. Ubuntu 24.04 and Windows 2025 are qualified. Existing HIGH `AUDIT_RELEASE_H2_ANDROID_QUALIFICATION_ABSENT` remains carried.

### A09 — security and credential boundaries

**PASS WITH EXISTING CARRIED GATE.** No credential, network/provider write or corpus-write trust boundary changed. Existing MEDIUM `AUDIT_P0_36C_TOKENINFO_SCOPE_PREFLIGHT_AVAILABILITY` remains separately scoped.

### A10 — lost-local-state/provider-history-gap recovery

**PASS.** Missing non-rebuildable state with prior control artifacts still fails closed; full read-only state verification remains the recovery authority gate; RemoteHistory cursor/gap semantics are unchanged.

### A11 — stale documentation and state claims

**PASS.** Revision 240 intentionally remains conservative until this qualification checkpoint integrates. The 02A contract still correctly locks 02C behind 02B qualification. No current product document falsely claims accepted ordinary SCAN authority, watcher authority, Android qualification or a new LocalFS publication path.

### A12 — dependency/reuse and nearest analogs

**PASS — NO NEW DEPENDENCY.**

Internal reuse remains preferred:

- `local_ingest_commits` + bootstrap authority for source evidence;
- `scan_completion_authorities` for deterministic ordering;
- existing `searchsqlite.SourceBoundary`;
- exact `InventoryAtScan`;
- RemoteHistory's OPEN → revalidate → identity-aware write → final revalidate → guarded COMPLETE lifecycle as the nearest model for POST-P0-02C.

Fresh external evidence reconfirmed the existing design direction:

- fsnotify remains notification-oriented and does not supply a portable durable committed-history contract;
- Watchman clocks/since plus fresh-instance/recrawl semantics are useful optional gap-aware hints, not Artifact authority;
- Windows USN journal provides persistent per-volume records with journal identity + USN continuity checks, making it a possible Windows-specific accelerator rather than the portable default;
- Android SAF remains URI/DocumentsProvider based and belongs behind a provider adapter rather than POSIX identity assumptions.

Sources reviewed:

- https://github.com/fsnotify/fsnotify
- https://facebook.github.io/watchman/docs/clockspec
- https://facebook.github.io/watchman/docs/troubleshooting
- https://learn.microsoft.com/en-us/windows/win32/fileio/using-the-change-journal-identifier
- https://developer.android.com/training/data-storage/shared/documents-files

### A13 — synthesis and finding freeze

Complete collection reached the end of every mandatory dimension.

- new CRITICAL: **0**
- new BLOCKER: **0**
- new HIGH: **0**
- new MEDIUM: **0**
- new LOW: **0**
- critical development gate: **CLEAR**
- remediation cycle required: **no**

Existing carried findings remain exactly scoped:

- HIGH `AUDIT_RELEASE_H1_STATE_DB_ROLLBACK_NOT_IMPLEMENTED` — release/update gate;
- HIGH `AUDIT_RELEASE_H2_ANDROID_QUALIFICATION_ABSENT` — portability gate;
- MEDIUM `AUDIT_P0_36C_TOKENINFO_SCOPE_PREFLIGHT_AVAILABILITY` — production live-provider credential/availability gate;
- LOW `AUDIT_P0_FINAL_L1_REPOSITORY_DESCRIPTION_STALE` — housekeeping.

## Closure decision

POST-P0-02B is complete and eligible for qualification.

The next objective is **POST-P0-02C_SOURCE_BOUND_LOCAL_OBSERVATION_ATTEMPT**, but no 02C product write is authorized merely by this document. Revision 241 must first pass exact-head validate + Ubuntu 24.04 + Windows 2025 CI and exact-head review, then integrate through the serialized conditional-fast-forward protocol.

After revision 241 is authoritative, POST-P0-02C may begin from that exact state.
