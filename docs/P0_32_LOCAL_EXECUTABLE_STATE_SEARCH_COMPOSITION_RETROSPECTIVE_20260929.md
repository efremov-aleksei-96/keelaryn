# P0-32 — Local executable state/search composition retrospective

Date: 2026-09-29  
Status: **PASS / P0-32 QUALIFIED**  
Initial implementation HEAD: `b34628c57b56b562ffeab6847075f94cfe2f9e5b`  
Runtime hardening HEAD: `4930c19e288fd7d0c1fcd971d0e9846713b9008e`  
Qualified product HEAD: `926fc82e9abdb831d5fce6f67b3d04df73dee824`  
Exact-head CI: **36619723490 — SUCCESS**  
Authoritative identity-state schema: **v45 unchanged**  
Derived search-cache schema: **v3**  
New product dependencies: **0**

## Scope

P0-32 makes the already-qualified local Corpus-first chain reachable through the single Go executable without adding MCP, HTTP, web UI, vectors, live remote access or physical corpus mutation.

Qualified development-spike commands:

```text
keelaryn bootstrap-index --root <corpus> --state-db <outside-corpus.db> --search-db <outside-corpus.db>
keelaryn search --search-db <search.db> --query <literal terms>
```

The original raw read-only `scan` command remains available.

This is **development runtime reachability**, not production/user-runtime qualification. H3 filesystem/ACL protection and H4 aggregate Doctor/SelfTest remain open.

## Reused mechanisms

P0-32 composes existing qualified layers rather than duplicating them:

- LocalFS read-only provider;
- atomic BootstrapLocalFS and immutable local-ingest receipts;
- latest COMPLETE scan authority;
- assigned Inventory;
- exact Revision-bound bounded extraction;
- P0-31 FTS5 ReplaceAll / Search / Verify;
- authoritative state remains separate from derived search state.

No new identity resolver, Artifact model, inventory, search engine or extraction engine was introduced.

## Qualified happy path

```text
existing local root
→ explicit runtime-local state/search paths outside corpus
→ reconcile durable bootstrap
→ bootstrap only if no COMPLETE authority exists
→ assigned inventory
→ bounded exact Revision extraction
→ source-boundary replay check
→ atomic FTS publication
→ literal search via the same executable
```

The corpus remains read-only.

## Interruption and stale-source handling

An existing COMPLETE scan is not trusted solely because it exists.

P0-32 replays the exact immutable bootstrap receipt using the original scan `StartedAt` against the current root. The same proof runs again after source extraction and before FTS replacement.

Therefore:

- interruption after durable bootstrap but before FTS publication is safely resumable;
- an empty corpus still has explicit durable COMPLETE authority;
- additions/removals/metadata/content drift fail with `ErrCorpusChanged`;
- the previous complete search cache remains intact on stale-source failure;
- a regular-file Inventory row lacking Artifact+Revision assignment fails closed;
- read-only `search` refuses a missing cache path instead of creating an empty SQLite database.

## Search-cache security / H6

### AUDIT_SECURITY_H6_FTS_SEARCH_CACHE_RESIDUAL_TEXT — RESOLVED

The first v2 hardening enabled SQLite core `secure_delete=ON` on each pooled search connection and persistent FTS5 `secure-delete=1`.

Targeted review found that this was insufficient for an **upgraded legacy cache**: text deleted before secure-delete was enabled could still reside in old FTS segments or free pages.

Qualified product HEAD `926fc82...` advances the derived search cache to schema v3:

1. enable FTS5 secure-delete;
2. rebuild FTS from current external content;
3. persist a security-upgrade `vacuum_pending=1` marker;
4. commit the schema migration;
5. run one resumable `VACUUM` outside the migration transaction;
6. mark the upgrade complete;
7. verify core secure-delete, FTS secure-delete and upgrade completion before use.

If interrupted before completion, the durable pending marker causes the next Open to repeat the cleanup rather than assume success.

This resolves the residual-content upgrade gap for the derived search-cache contract. It does **not** replace filesystem access protection; H3 remains separate.

## Pre-qualification findings

### P0-32-T1 — newer-schema regression fixture drift — RESOLVED

After search schema v2 was added, the existing newer-schema regression still wrote `user_version=2`, which had become the current version. Ubuntu CI therefore failed only that assertion.

Commit `0ef11e19a79e6dcb4d0e3ed098c58fba3758b90f` updated the adversarial fixture to the next unsupported version. No product semantics changed.

### P0-32-C1 — stale bootstrap reuse boundary — RESOLVED

Initial runtime composition would reuse any current COMPLETE bootstrap and then reread files, allowing a changed root to be treated as the old durable snapshot until extraction happened to notice a changed assigned file.

Hardening HEAD `4930c19...` requires exact bootstrap receipt replay before and after source reads. Additions, removals and other snapshot drift now fail before FTS publication.

### P0-32-M1 — missing query cache could create state — RESOLVED

The first query path delegated directly to search `Open`, whose normal semantics include create. A mistyped query path could therefore create an empty derived DB.

Hardening HEAD `4930c19...` requires an existing non-directory search-cache path before Open.

## Cross-platform qualification

CI **36619723490** on exact product HEAD `926fc82e9abdb831d5fce6f67b3d04df73dee824`:

- validate — PASS;
- Ubuntu 24.04 — PASS;
- Windows 2025 — PASS;
- dependency-lock / `go mod tidy -diff` — PASS;
- `go test ./...` — PASS;
- `go vet ./...` — PASS.

## Remaining boundaries

P0-32 intentionally does not claim:

- normal post-bootstrap LocalFS rescan/reconciliation runtime;
- production filesystem/ACL protection;
- aggregate Doctor/SelfTest;
- live remote/provider runtime qualification;
- ContextBundle runtime orchestration;
- MCP/HTTP/web;
- Android support;
- release/update qualification.

## Conclusion

**P0-32 PASS. The local durable state → extraction → secure FTS search chain is reachable through one executable.**

The next autonomous product gap is task-specific ContextBundle runtime composition, reusing the already-qualified P0-18 builder. MCP remains downstream of that composition and of the production-runtime security gate.
