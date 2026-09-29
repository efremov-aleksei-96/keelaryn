# P0-31 — Rebuildable SQLite FTS5 Search Contract

Status: **CONTRACT + FIRST PRODUCT SLICE**
Architecture: derived search cache over exact Revision-bound extraction
Authority state schema: **unchanged v45**
New external dependency: **none**
Live provider use: **none**
Corpus mutation: **none**

## 1. Goal

Add the smallest useful full-text search layer after the already-qualified extraction boundary:

```text
exact Artifact Revision
→ exact Revision-bound extraction
→ rebuildable search document
→ SQLite FTS5
→ exact Revision search hit
```

Search is not identity authority and does not change Artifact, Revision, Observation, Locator, provider history or accepted decisions.

## 2. Physical authority boundary

P0-31 uses a **separate derived SQLite search-cache file** instead of adding FTS tables to the authoritative identity-state database.

Reasons:

- the existing state Store intentionally owns non-rebuildable identity/provenance authority;
- deletion or complete rebuild of the search cache must be safe;
- FTS corruption or schema replacement must not endanger Artifact/Revision authority;
- one executable can still own both files without introducing another service;
- the same pinned `zombiezen.com/go/sqlite` stack already includes FTS5.

The search-cache application ID is distinct from the identity-state database application ID.

## 3. Indexed document identity

One search document is keyed by:

```text
ArtifactID + RevisionID + ExtractorID
```

This is a **derived cache key**, not a new Artifact identity rule.

The indexed payload carries:

- ArtifactID;
- RevisionID;
- ExtractorID;
- media type when available;
- exact ContentEvidence for that Revision-bound extraction;
- extracted UTF-8 text.

Locator is deliberately not search-document identity and is not stored as current authority. Rename/move may change current Locator without changing Artifact/Revision or requiring a different text document.

## 4. Admission to the index

Only `extract.StatusExtracted` results may become search documents.

Before a result is converted into a search document, the caller must re-read Revision authority and prove that:

- the Artifact exists in Revision history;
- the referenced Revision is the current highest-sequence Revision at that check;
- ArtifactID and RevisionID match exactly;
- ContentEvidence matches exactly.

This check narrows the race window but does not claim cross-database atomic currentness. A search hit therefore always names its exact Revision and never silently claims to be current inventory authority.

Later ContextBundle/current-inventory use must continue to revalidate its exact source boundary.

## 5. FTS5 layout

Use an ordinary STRICT derived document table plus an FTS5 **external-content** table over its text column.

The document table provides relational uniqueness/provenance. Transactional INSERT/UPDATE/DELETE triggers keep the FTS index synchronized.

This choice intentionally reuses SQLite FTS5's built-in:

- `integrity-check`;
- `rebuild`;
- BM25 ordering.

No custom tokenizer is introduced in P0-31; use the built-in `unicode61` tokenizer.

## 6. Replace semantics

The first P0 path publishes search state through **atomic ReplaceAll**:

1. validate every document;
2. reject duplicate derived keys before mutation;
3. deterministic key ordering;
4. one SQLite immediate transaction;
5. delete old derived document set;
6. insert the complete replacement set;
7. run FTS5 integrity verification;
8. commit.

Any failure rolls the search cache back to its previous complete set.

This avoids exposing a partially rebuilt corpus search index.

## 7. Query semantics

The public P0 query is literal all-terms search, not raw FTS5 expression execution.

Input whitespace-separated strings are individually quoted with SQL-style embedded-quote escaping and joined with AND. FTS operators supplied by a caller therefore remain literal text.

Results are ordered by SQLite FTS5 BM25 and return exact:

- ArtifactID;
- RevisionID;
- ExtractorID;
- media type;
- ContentEvidence.

The P0 result does not invent a current Locator.

## 8. Verification and recovery

Two recovery levels exist:

- `Verify`: FTS5 integrity-check including comparison with external content;
- `RebuildFTS`: rebuild only the FTS structures from the derived document table.

A full corpus-derived rebuild is `ReplaceAll` fed from freshly validated extraction results. The entire search-cache file may also be deleted and recreated without identity loss.

An older binary must fail closed when opening a newer search-cache schema. Because the cache is rebuildable, a future runtime may explicitly discard/recreate an incompatible cache, but P0-31 does not silently do so.

## 9. Privacy/security scope

The search cache contains derived extracted text and is therefore sensitive even though it is non-authoritative.

Existing filesystem-protection HIGH H3 must eventually cover this derived cache as well as authoritative state before user-runtime qualification. P0-31 does not claim that hardening complete.

## 10. Explicitly out of scope

- vectors / embeddings;
- semantic ranking;
- external search service;
- MCP / HTTP / web UI;
- live provider/OAuth;
- broader extraction formats;
- background watcher/index scheduler;
- physical corpus mutation;
- search-owned Locator authority.

## 11. Qualification targets for the first slice

- exact Revision-bound extraction converts to a search document;
- stale/non-current extraction is rejected;
- FTS5 ReplaceAll is atomic;
- literal multi-term query returns exact provenance;
- duplicate replacement input cannot destroy the prior complete index;
- Verify passes;
- RebuildFTS preserves query results;
- search cache survives reopen;
- newer search-cache schema fails closed;
- existing full repository tests remain green on Ubuntu 24.04 and Windows 2025.
