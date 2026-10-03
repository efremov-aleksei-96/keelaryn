# POST-P0-01A derived search recovery retrospective — 2026-10-03

## Boundary

Audited implementation handoff: `e40a04def266cd39bf75b60662787909cc2d652b`.

Authoritative integration: `e5047c925f2d782d6823e4dc29cbae9b7ec6337c`.

Exact-head qualification: GitHub Actions run `37140223778`.

Sol exact-handoff review: `5401888249`.

Result: **PASS — zero new BLOCKER/CRITICAL findings.**

This retrospective closes canonical post-P0 growth-order item 1 for the currently reachable reliability/recovery boundaries. It does not claim release rollback, backup/export/restore hardening, Android support, metadata-loss reconstruction, or live-provider availability hardening.

## Qualified product surface

POST-P0-01A hardens only the rebuildable local derived search cache:

- `search.db` remains derived FTS/search state, not Artifact, Revision, Observation, provider-history, identity or provenance authority;
- `search.db.next` is a fixed protected staging location and is never query authority;
- `search.lock` is a persistent protected file whose contents carry no authority; writer ownership is the process-crash-safe OS advisory lock;
- existing `state.db` authority and the committed local bootstrap receipt are proved read-only before writer serialization and proved again after lock acquisition;
- any prior staging family is treated as interrupted derived work and discarded only by exact known filenames after fresh proof;
- a new complete staging cache is built from current authoritative state and exact current corpus evidence, source-bound, verified, and closed before promotion;
- an active SQLite journal/WAL family is opened under its original name so SQLite may legitimately reconcile it before the derived active family is discarded;
- promotion replaces only the derived active cache and the promoted result is immediately reopened and reverified;
- CLI search and ContextBundle use authority-bound read-only paths. A rootless search may use the stored search boundary only to identify candidate scope and must rederive the exact expected boundary from `state.db` before returning hits.

No product path repairs, reconstructs, downgrades, replaces, or silently discards `state.db`.

## Architecture and correctness review

### Durable authority

The stage preserves the P0 authority split. `state.db` remains the non-rebuildable identity/provenance authority. Search data is disposable derived state.

Missing `state.db` is treated as fresh bootstrap only when no state sidecar and no active/staged search footprint exists. A missing state database with prior control artifacts fails closed rather than reminting Artifact/Revision identity.

No new Artifact, Revision, ProviderObject, Locator, history-cursor or managed-root authority was introduced.

### Interruption and transaction behavior

Recovery is deliberately asymmetric:

- invalid authoritative state => fail closed, no search recovery mutation;
- invalid/missing derived search => rebuild may proceed only from freshly revalidated authority and corpus evidence.

The writer lock serializes derived-cache mutations across processes. Staging is rebuilt rather than trusted as a durable result receipt. The promotion sequence has explicit deterministic behavior for failure before verification, after verification but before promotion, remove-before-rename interruption, destination/promotion failure, and failure of post-promotion verification.

The implementation never moves a live SQLite main file away from its journal/WAL and later treats the separated family as authority.

### Read behavior

Read-only production surfaces do not acquire write authority and do not consume `search.db.next`. Search results are accepted only under an exact SourceBoundary rederived from authoritative state.

This prevents a stale or orphaned search cache from silently becoming current after state authority advances or disappears.

### Security

Active and staged search caches remain inside the protected control directory. Existing ownership/ACL/link/reparse checks apply to the new fixed staging and lock paths. No extracted text is copied into a generic temp location or emitted in recovery errors.

Fault injection used for adversarial tests is package-private. The exported production entrypoint always supplies the real operations; there is no public runtime switch or bypass.

### Cross-platform

The OS lock has explicit Unix and Windows implementations using `golang.org/x/sys`, which was already present in the dependency graph. The exact handoff passes Ubuntu 24.04 and Windows 2025 tests and vet.

Android is not qualified or implied. The carried Android substrate finding remains open at its portability gate.

## Adversarial qualification

The exact-head suite now proves at least:

1. corrupt active `search.db` recovers from authority;
2. missing active `search.db` recovers;
3. staging is never read/query authority;
4. a valid prior staging database is explicitly discarded and rebuilt;
5. valid staging with a different SourceBoundary is discarded and rebuilt;
6. corrupt staging is discarded and rebuilt;
7. orphan staging sidecars are discarded and rebuilt;
8. failure before staged verification leaves the old active cache unchanged and retryable staging present;
9. failure after staged verification but before promotion leaves the old active cache unchanged and staging present;
10. remove-before-rename failure leaves no active cache but retains the staged candidate and a deterministic promotion retry succeeds;
11. promotion/destination unavailability leaves authoritative state unchanged and staging retryable;
12. post-promotion verification failure reports failure and the next normal recovery deterministically requalifies a complete cache;
13. corrupt state authority blocks recovery before active/staged search mutation;
14. missing state with prior state/search footprint fails closed; a lock-only fresh profile remains bootstrappable;
15. corpus fingerprint drift blocks recovery before derived mutation;
16. writer lock contention produces zero active-search/authority mutation;
17. active SQLite sidecars are reconciled under the original database name before promotion;
18. current authoritative COMPLETE scan, inventory assignments and Artifact/Revision histories remain unchanged across derived recovery;
19. corpus bytes/topology remain unchanged across deterministic recovery/failure tests;
20. Ubuntu 24.04 and Windows 2025 qualification pass.

## Reuse and simplification review

The stage reuses existing Keelaryn mechanisms instead of creating parallel authorities:

- protected `controlstorage` ownership/ACL and path verification;
- current COMPLETE scan and bootstrap receipt authority;
- existing exact local snapshot fingerprint and replay checks;
- existing revision/content-evidence validation;
- `searchsqlite.SourceBoundary`;
- SQLite transactions, journal/WAL recovery behavior, integrity checks, secure-delete and FTS verification;
- existing read-only state/search open paths;
- existing `golang.org/x/sys` dependency for native file locking.

No new dependency is justified. A separate recovery database, durable staging receipt, queue, service, vector store or external lock service would add authority/coordination surface without improving this local derived-cache boundary.

SQLite Online Backup / Litestream-class replication remains relevant later for backup/export/restore or release rollback, not for disposable `search.db` recovery.

## Findings

### New CRITICAL/BLOCKER

None.

### Carried findings

The following existing findings remain valid and unchanged in scope:

- `AUDIT_RELEASE_H1_STATE_DB_ROLLBACK_NOT_IMPLEMENTED` — release/update rollback gate. This stage intentionally does not add backup/restore of non-rebuildable state.
- `AUDIT_RELEASE_H2_ANDROID_QUALIFICATION_ABSENT` — Android portability gate. Ubuntu/Windows qualification is not evidence for Android.
- `AUDIT_P0_36C_TOKENINFO_SCOPE_PREFLIGHT_AVAILABILITY` — live Google Drive bootstrap availability; independent of local derived search recovery.
- `AUDIT_P0_FINAL_L1_REPOSITORY_DESCRIPTION_STALE` — repository metadata housekeeping.

No carried finding invalidates this local derived-search reliability stage.

## Qualification evidence

GitHub Actions run `37140223778` on exact handoff `e40a04def266cd39bf75b60662787909cc2d652b`:

- validate — PASS;
- Ubuntu 24.04 dependency lock — PASS;
- Ubuntu Go tests — PASS;
- Ubuntu Go vet — PASS;
- Windows 2025 dependency lock — PASS;
- Windows Go tests — PASS;
- Windows Go vet — PASS.

The reviewed handoff was integrated through the repository's conditional-fast-forward protocol as `e5047c925f2d782d6823e4dc29cbae9b7ec6337c`, whose tree exactly equals the reviewed handoff tree and whose only parent is the acquired base `338467d9d8ab1bbf200532e11a9ff75e644718b3`.

## Growth-order decision

Canonical post-P0 growth-order item 1 — **reliability and deterministic recovery** — is complete for currently reachable runtime recovery boundaries.

The next substantive objective is item 2: **incremental local/provider observation**.

Before product writes, that objective starts with a read-only provider-neutral contract/reuse audit. The design must preserve the existing Artifact/Revision authority, remote-history cursor semantics, Google Drive managed-root membership semantics, exact source-bound search behavior, and read-only corpus guarantee. Watchers/change feeds are hints/evidence sources; they must not become a second identity authority.
