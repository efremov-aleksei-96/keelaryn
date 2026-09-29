# P0 Closure Re-audit after P0-30 — 2026-09-29

Status: **P0 NOT CLOSED / NEXT AUTONOMOUS PRODUCT GAP SELECTED**

Authority: this document is implementation/evidence audit material. `KEELARYN_CANONICAL.md` remains the product architecture authority and `DEVELOPMENT_STATE.json` remains the live development clock.

## Evidence basis

- authoritative branch: `dev/corpus-first-p0`;
- qualified P0-30C2 product head: `3b951a66650ab98d213b0823b0bce145b587872c`;
- C2 qualification head: `be12edd43c41ef57896f92706867bb85d9d9c5b2`;
- exact-head C2 CI: `36474994106` — validate / Ubuntu 24.04 / Windows 2025 PASS;
- control checkpoint before this audit: `92e07542fb483f966e6ef4a11330bf3b10c98378`;
- control checkpoint CI: `36604971233` — SUCCESS;
- inherited SQLite schema authority: v45;
- no live provider/OAuth use and no corpus mutation occurred in P0-30.

## Result of the previously selected gap

The prior closure audit selected:

> exact remote provider state -> existing ScanSession / Observation / inventory -> existing lifetime-aware identity authority / SAME-NEW acceptance

P0-30A/B/C now close that product-code gap at the deterministic library boundary:

- exact remote source provenance and guarded ScanSession lifecycle;
- deterministic LIGHTWEIGHT_ALL materialization into the existing Observation/inventory model;
- existing RemoteHistory lifetime authority reused;
- existing SAME/NEW acceptance reused;
- regular SAME without exact ContentEvidence remains unresolved;
- exact source-bound ContentEvidence may drive Revision continuity;
- history advance at the final identity boundary fails closed;
- no second inventory, Artifact model or identity resolver was introduced.

## Required P0 path after P0-30

| Canonical capability | Current status after P0-30 |
|---|---|
| one existing corpus root | QUALIFIED local |
| read-only discovery | QUALIFIED local; remote deterministic mechanics qualified |
| durable ProviderObject/Locator observations | QUALIFIED |
| Artifact identity | QUALIFIED mechanics and deterministic remote orchestration |
| Revision continuity | QUALIFIED mechanics; exact evidence required |
| inventory | QUALIFIED |
| minimal extraction | QUALIFIED for bounded local UTF-8/Markdown |
| SQLite FTS search | **ABSENT** |
| task-specific ContextBundle | QUALIFIED for explicit selection |
| MCP/HTTP/CLI product access | PARTIAL; scan CLI only |
| real live remote/provider qualification | **OUTSTANDING CLOSURE GATE** |
| embedded minimal web status spike | ABSENT |

## Earliest next autonomous product gap

The next bounded implementation gap is:

> **P0-31 — rebuildable SQLite FTS5 search over exact Revision-bound extraction**

Why this is selected now:

1. it is the next absent layer in the canonical corpus path after qualified extraction;
2. it can be implemented and qualified deterministically without credentials or corpus mutation;
3. the current `zombiezen.com/go/sqlite` stack already compiles SQLite FTS5, so no new search engine or dependency is needed;
4. FTS/search is derived state and must remain rebuildable/non-authoritative;
5. search results must identify exact Artifact/Revision provenance and must not create or modify identity;
6. MCP/HTTP/UI should consume a coherent search layer rather than invent their own indexing/query semantics.

## Live remote qualification is still required

The canonical technology spike also requires one real maintainer-relevant remote/provider path. Current Google Drive work is deterministic library qualification only; no live OAuth/provider read has been exercised through a user-runtime path.

This remains an explicit **P0 closure gate**. It is not declared solved and must be qualified before P0 is finally closed.

It is not selected as the next autonomous code slice because credentials/runtime authorization are a separate external acceptance boundary. Advancing the independent derived FTS layer does not weaken or replace that gate.

## P0-31 contract constraints

Before implementation, P0-31 must preserve:

- search index is rebuildable derived state, never identity/provenance authority;
- index input is exact Revision-bound extraction only;
- no path/hash/provider object becomes Artifact identity;
- stale extraction must not be indexed as current;
- query hits expose exact ArtifactID + RevisionID + extractor identity;
- current Locator resolution remains inventory authority, not an FTS-owned fact;
- index rebuild must not alter Artifact/Revision/Observation state;
- deterministic replay/upsert for the same revision/extractor;
- corruption/inconsistency has an explicit verification/rebuild path;
- no vector database, embeddings or semantic ontology in P0-31;
- no new dependency unless current SQLite FTS5 proves insufficient.

## Reuse / prior-art decision

Use SQLite FTS5 already present in the pinned SQLite stack.

Preferred initial design direction:

- ordinary derived search-document rows keyed to exact Artifact/Revision/extractor provenance;
- FTS5 index over text;
- explicit transactional synchronization between document row and FTS index;
- built-in FTS5 integrity verification and rebuild semantics where applicable;
- no external search service.

Do not introduce Elasticsearch/OpenSearch/Meilisearch/Tantivy/vector infrastructure for P0.

## Control-state correction discovered during this audit

### P0-30C2-L1 — metadata-only — RESOLVED

The initial C2 checkpoint incorrectly recorded SQLite schema authority as v39. C2 itself added no schema, but it was built on qualified product base `6bf6a0dd...`, whose inherited authority is v45.

This checkpoint corrects the C2 retrospective and live development state to v45. Product bytes and qualification evidence are unchanged.

## Explicitly not selected as P0-31

- MCP/HTTP/UI;
- embedded web status;
- vector/embedding search;
- broader extraction;
- Android backend work;
- physical corpus mutation;
- release rollback/security/Doctor hardening H1-H4;
- a new remote inventory/identity model.

## Conclusion

**P0 remains open. P0-30 is qualified. P0-31 FTS5 is the next autonomous product stage.**

Live remote/provider runtime qualification remains a separate required P0 closure gate and must not be forgotten before final P0 closure.
