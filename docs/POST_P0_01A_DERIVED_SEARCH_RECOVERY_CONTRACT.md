# POST-P0-01A derived search-cache deterministic recovery contract

Status: **SOL DECISION — IMPLEMENTATION READY**

Date: 2026-10-03

Authority: `KEELARYN_CANONICAL.md` remains product architecture authority. This contract narrows canonical post-P0 growth-order item 1 ("reliability and deterministic recovery") to the first protected implementation slice.

## 1. Scope

This stage hardens recovery of **`search.db` only**.

`search.db` is rebuildable derived state. It contains extracted/searchable user text, but it is **not** Artifact, Revision, Observation, provider-history, provenance or identity authority.

This stage MUST NOT:

- repair, replace, downgrade, reconstruct or silently discard `state.db`;
- change Artifact / Revision / ProviderObject / Locator identity semantics;
- add incremental observation;
- add backup/export/restore of non-rebuildable authority;
- implement release upgrade rollback;
- claim Android support;
- change Google Drive credential/scope authority;
- mutate user corpus/provider bytes.

The carried findings `AUDIT_RELEASE_H1_STATE_DB_ROLLBACK_NOT_IMPLEMENTED`, `AUDIT_RELEASE_H2_ANDROID_QUALIFICATION_ABSENT`, and `AUDIT_P0_36C_TOKENINFO_SCOPE_PREFLIGHT_AVAILABILITY` remain outside this slice.

## 2. Problem

Current local protected runtime can rebuild a **missing** search cache, and complete-cache replacement is transactional once the SQLite database opens.

But a corrupt, incompatible, or otherwise unopenable existing `search.db` can prevent the rebuild path from reaching that transaction even though all search state is derived.

The safe recovery rule is therefore asymmetric:

- `state.db` invalid => **fail closed; no repair**;
- `state.db` missing is a fresh bootstrap **only** when no state SQLite sidecar and no active/staged search family exists; otherwise treat it as possible authoritative metadata loss and fail closed;
- `search.db` invalid => MAY be discarded/rebuilt, but only from revalidated authoritative state + exact current corpus evidence.

A persistent `search.lock` alone does not prove prior authority: it may survive process death after writer serialization but before the first state transaction.

Recovery must be deterministic after interruption and must never cause a staged/partial cache to become query authority.

## 3. Existing guarantees reused

The implementation MUST reuse, not duplicate:

- protected control-storage ownership/ACL boundary;
- `LatestCompleteScan` current inventory authority;
- exact local bootstrap commit receipt + snapshot fingerprint;
- pre/post `replayBootstrap` corpus revalidation;
- exact immutable Revision/content-evidence validation;
- `searchsqlite.SourceBoundary`;
- complete-cache `ReplaceAllBound`;
- search DB integrity/foreign-key/FTS/security verification;
- bound read transaction for source-bound search;
- SQLite transaction crash recovery.

SQLite main files MUST NOT be moved away from a live hot rollback journal or WAL as an attempted "repair". Recovery either lets SQLite operate on a database family under its original name or treats the entire **derived** family as disposable after the Keelaryn recovery boundary owns the mutation.

## 4. Durable layout

Protected control storage gains two derived-search recovery entries:

```text
search.db          active derived cache
search.db.next     staged complete replacement
search.lock        persistent lock file; lock state is OS-held, not file-content authority
```

SQLite sidecars for `search.db.next` are allowed only with the same suffix set already permitted for control SQLite files:

- `-journal`
- `-wal`
- `-shm`

No other dynamic recovery filenames are introduced.

`search.db.next` is never query authority.

## 5. Mutation lock

Any operation that creates, rebuilds, replaces or promotes the protected search cache MUST hold one process-crash-safe OS advisory **exclusive** lock on `search.lock`.

Requirements:

- lock acquisition is non-blocking or context-bounded;
- process exit/crash releases the OS lock automatically;
- the persistent lock file itself is not a "locked/unlocked" marker;
- lock file is created only inside already-protected control storage;
- Windows implementation uses an OS file lock, not delete-on-close sentinel semantics;
- Unix implementation uses an OS file lock;
- inability to acquire the lock fails without mutating either active or staged cache.

Read-only search does not need the advisory lock. On Unix, an already-open reader may continue reading its old inode after promotion; on Windows, filesystem sharing semantics may make promotion fail safely while another reader holds the destination. Recovery MUST surface that failure and preserve the staged candidate for a later retry.

## 6. Staged rebuild

A rebuild uses this order:

```text
validate protected control boundary
→ verify state.db read-only / exact schema / authority invariants
→ resolve current complete local scan
→ re-prove exact bootstrap receipt against current corpus
→ derive bounded extraction set
→ re-prove bootstrap receipt after source reads
→ acquire search mutation lock
→ reconcile any prior search.db.next
→ build complete search.db.next
→ bind exact SourceBoundary
→ verify staged SQLite/FTS/security/source boundary
→ close staged SQLite handles
→ promote staged cache
→ reopen active cache read-only
→ verify integrity/security/source boundary
→ verify protected control storage
```

No active-cache destruction is allowed before the complete staged candidate passes all staged verification.

## 7. Recovery of prior staging

At the start of a locked rebuild:

### 7.1 No staging family

Build a new staged cache.

### 7.2 Any prior staging family exists

The first implementation deliberately does **not** make staging a second durable result authority.

After fresh state/corpus proof and after acquiring the exclusive search lock, any prior `search.db.next` family is treated as interrupted derived work, discarded by exact fixed filenames, and rebuilt from the fresh proof boundary.

This avoids inventing a second recovery receipt for extraction outcome counters and ensures a retry never trusts an old staged cache merely because its SQLite bytes are internally valid.

Deleting a staging family MUST target only the exact known staging main/sidecar names. Symlinks/reparse points/non-regular files fail closed.

### 7.3 Orphan staging sidecar without staging main

Treat as interrupted derived staging. Under the exclusive search lock and protected-path checks, discard only the exact staging sidecar set, then rebuild.

## 8. Promotion

Promotion occurs only after the staged SQLite handle is closed.

Before replacing the active main file:

1. reconcile the active derived family; if active SQLite sidecars exist, open the active database under its original name after staging is fully verified so SQLite can perform legitimate hot-journal/WAL recovery, then close it before promotion;
2. do not infer anything from active cache contents for identity/provenance;
3. remove/replace only the exact active derived family under the search mutation lock;
4. rename `search.db.next` to `search.db`;
5. do not move a live SQLite main file away from a sidecar and later try to use the separated family as authority;
6. immediately reopen and verify the promoted active cache.

If process interruption leaves:

- old active + staged candidate;
- no active + staged candidate;
- active new + no staging;
- only disposable derived sidecars;

the next locked recovery MUST classify the state and either prove/promote the exact staged candidate or rebuild from authoritative state.

A promotion failure MUST NOT mutate `state.db`.

## 9. Query authority

Read paths continue to use **only** `search.db`.

They must continue to require the expected current `SourceBoundary` derived from authoritative state. Rootless CLI search MAY read the stored search boundary only as candidate scope metadata, then MUST re-derive the exact expected boundary from `state.db` and execute the query through the bound read transaction. CLI ContextBundle, MCP and other root-scoped reads use the existing bound read path directly.

Therefore:

- an old active cache cannot silently become current after state authority advances;
- staging can never leak into query results;
- a failed or missing active cache is availability loss only, not an identity/provenance mutation.

## 10. Security

Both active and staged caches contain extracted user text.

Therefore:

- both live only inside protected control storage;
- file/reparse/link safety is checked;
- existing secure-delete + FTS5 secure-delete policy applies to staging;
- no staging copy is created in a generic world-readable temp directory;
- recovery does not print extracted text;
- failure messages identify paths/status, not indexed content.

## 11. Adversarial qualification matrix

At minimum add regression coverage for:

1. corrupt active search DB + valid state/corpus => fresh staged rebuild and verified promotion;
2. missing active search DB => rebuild succeeds;
3. valid active cache does not become queryable from staging path;
4. valid prior staged cache => discard/rebuild after fresh proof (staging is not result authority);
5. mismatched staged SourceBoundary => discard/rebuild;
6. corrupt staged cache => discard/rebuild;
7. orphan staging sidecar => cleanup/rebuild;
8. injected failure before staged verification => active cache unchanged;
9. injected failure after staged verification but before promotion => active cache unchanged and staging recoverable;
10. injected failure after active removal but before rename => retry promotes/rebuilds deterministically;
11. promotion while destination is unavailable/busy => no state mutation; staged candidate retained;
12. promoted cache fails post-open verification => command fails closed and never claims success;
13. state DB corruption => no search recovery mutation begins;
14. missing state DB with any state sidecar or active/staged search family => fail closed without reminting authority; truly fresh control remains bootstrappable;
15. corpus fingerprint drift => no search recovery mutation begins;
16. lock contention => zero search-family mutation;
17. authoritative state semantics unchanged across recovery: same current COMPLETE scan, inventory assignments/locators, and Artifact/Revision history; raw SQLite file bytes are not an authority invariant because journal/checkpoint housekeeping may change physical representation without changing logical state;
18. user corpus bytes unchanged across every recovery test;
19. Ubuntu 24.04 + Windows 2025 CI.

## 12. Stage completion

POST-P0-01A is qualified only when:

- implementation is exact-head CI green on Ubuntu 24.04 and Windows 2025;
- staged/recovery adversarial tests pass;
- a Sol retrospective confirms no new identity/provenance authority, unsafe repair path, sidecar separation bug, or cross-platform promotion defect;
- `DEVELOPMENT_STATE.json` records the stage evidence only after that retrospective.

The next post-P0 reliability slice is selected only after this stage retrospective.
