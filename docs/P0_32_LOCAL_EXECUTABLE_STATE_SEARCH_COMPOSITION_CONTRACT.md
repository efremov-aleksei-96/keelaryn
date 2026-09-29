# P0-32 — Local executable state/search composition

Status: **FIRST PRODUCT SLICE**
Date: 2026-09-29

## Goal

Prove the already-qualified local Corpus-first layers are reachable through one Go executable without adding MCP/HTTP/UI yet:

```text
existing local root
→ durable state reconcile
→ first-observation bootstrap if needed
→ assigned inventory
→ exact Revision-bound extraction
→ rebuildable FTS5 cache
→ literal search query
```

This is a development technology-spike runtime surface. It is **not** production/user-runtime qualification while H3 filesystem protection and H4 Doctor/SelfTest remain open.

## Commands

```text
keelaryn bootstrap-index --root <corpus> --state-db <outside-corpus.db> --search-db <outside-corpus.db>
keelaryn search --search-db <search.db> --query <literal terms>
```

The existing raw `keelaryn scan --root` command remains available.

## Interruption rule

`bootstrap-index` read-only reconciles the latest COMPLETE scan for the exact LocalFS provider/root before attempting bootstrap.

- no COMPLETE scan → atomic `BootstrapLocalFS`;
- COMPLETE scan exists → reuse it, do not bootstrap again;
- then rebuild derived extraction/FTS.

Therefore an interruption after durable bootstrap but before FTS publication is recoverable by rerunning the command. This also works for an empty corpus, where inventory length alone cannot distinguish "never bootstrapped" from "bootstrapped with zero objects".

## Corpus safety

The first slice requires explicit state/search DB paths outside the scanned root.

It rejects a database path lexically inside the corpus before opening/creating either database. State and search DB paths must differ.

This does not claim complete production storage hardening against symlink/junction races or hostile multi-user path replacement; H3 remains the later platform storage-adapter gate.

## Extraction/search semantics

- only ASSIGNED regular-file inventory entries are offered to the bounded extractor;
- EXTRACTED results enter FTS;
- UNSUPPORTED, OPAQUE and LIMIT_EXCEEDED are explicit skipped outcomes;
- STALE_REVISION aborts the build before FTS ReplaceAll so the previous complete search cache remains intact;
- search hits preserve exact Artifact/Revision/extractor/evidence provenance;
- search never owns current Locator authority.

## Search-cache privacy hardening

P0-32 advances the derived search-cache schema to **v2** and resolves H6 for newly written/upgraded cache connections:

- SQLite core `PRAGMA secure_delete=ON` is enforced on every pooled search connection;
- FTS5 `secure-delete=1` is persisted in the FTS configuration.

Both are required because SQLite documents that core secure_delete alone does not scrub FTS shadow-table traces.

This does not replace H3 filesystem/ACL protection.

## Explicitly out of scope

- normal post-bootstrap LocalFS rescan/reconciliation runtime;
- MCP/HTTP/web;
- live remote/provider runtime;
- ContextBundle runtime orchestration;
- vectors/embeddings;
- production storage directory/ACL adapter;
- physical corpus mutation.

## Qualification targets

- one executable bootstraps a local text corpus into durable state + FTS and searches it;
- exact hit includes Artifact and Revision;
- rerun reuses the same COMPLETE bootstrap scan rather than creating another;
- empty-corpus rerun also reuses exact scan authority;
- state/search DB inside corpus is rejected before DB creation;
- root content is unchanged;
- search-cache secure-delete settings are qualified;
- Ubuntu 24.04 and Windows 2025 exact-head CI pass.
