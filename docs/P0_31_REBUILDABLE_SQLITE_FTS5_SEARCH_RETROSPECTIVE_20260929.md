# P0-31 — Rebuildable SQLite FTS5 search retrospective

Date: 2026-09-29  
Status: **PASS / P0-31 QUALIFIED**  
Initial implementation HEAD: `1e8c55e73741e9caf93ef3916289488ea2321d73`  
Product HEAD: `85d2a5b527203e4bfe6fec82fbf628649b97b30c`  
Qualification HEAD: `c4b850e15a6746ef5dcf9bd73857cb4e940dafbf`  
Exact-head qualification CI: **36615407840 — SUCCESS**  
Authoritative identity-state schema: **v45 unchanged**  
Derived search-cache schema: **v1**

## Scope

P0-31 adds the minimum rebuildable SQLite FTS5 search layer over exact Revision-bound extracted text.

The search cache is a separate SQLite file with a distinct application ID. It is derived/non-authoritative and may be deleted and rebuilt without changing Artifact, Revision, Observation, Locator, RemoteHistory or accepted identity decisions.

No live provider/OAuth access, physical corpus mutation, MCP/HTTP/UI, vectors, embeddings or external search service was added.

## Reused mechanisms

P0-31 reuses:

- the existing `zombiezen.com/go/sqlite` stack and its compiled FTS5 support;
- existing immutable Artifact/Revision authority;
- the qualified `extract/localfs` exact Revision-bound extractor;
- SQLite FTS5 external-content tables;
- transactional INSERT/UPDATE/DELETE triggers;
- FTS5 `integrity-check`, `rebuild`, and BM25.

New external product dependencies: **0**.

## Qualified behavior

The product now proves:

- only `EXTRACTED` results can enter search state;
- persistence revalidates exact ArtifactID + RevisionID + ContentEvidence itself;
- an exact historical Revision may be indexed without pretending it is current;
- current Locator remains inventory authority and is not owned by the search cache;
- duplicate derived keys are rejected before replacement mutation;
- complete search replacement is one SQLite immediate transaction;
- failure preserves the previous complete derived index;
- user query terms are literalized before FTS MATCH and do not become raw FTS operators;
- hits preserve exact Artifact/Revision/extractor/evidence provenance;
- cache reopen preserves queryability;
- a newer search-cache schema fails closed;
- real LocalFS bootstrap -> assigned Revision -> bounded extraction -> FTS -> exact provenance hit works end-to-end in the integration test;
- FTS drift against its external-content table is detected by `integrity-check` with rank=1;
- `rebuild` restores the deliberately drifted FTS index and query behavior.

## Findings resolved during the slice

### P0-31-M1 — exact Revision vs latest Revision — RESOLVED

The initial slice required an extraction to reference the highest-sequence Revision. That was stricter than the Corpus-first derived-state contract.

Correction HEAD `85d2a5b...` changed the boundary to exact immutable Revision matching. Search hits never claim currentness; current inventory remains a separate authority.

### P0-31-T1 — FTS drift recovery proof — RESOLVED

The product already exposed `Verify` and `RebuildFTS`, but the first tests exercised them only on a healthy index.

Qualification HEAD `c4b850e...` deliberately removes one FTS index entry while leaving external content intact. `Verify` must fail; `RebuildFTS` reconstructs the index; subsequent verification and search pass.

No production-code change was required for T1.

## Cross-platform qualification

CI **36615407840** on exact qualification HEAD:

- validate — PASS;
- Ubuntu 24.04 — PASS;
- Windows 2025 — PASS;
- `go mod tidy -diff` — PASS;
- `go test ./...` — PASS;
- `go vet ./...` — PASS.

## Security carry-forward

### AUDIT_SECURITY_H6_FTS_SEARCH_CACHE_RESIDUAL_TEXT — HIGH / OPEN

SQLite FTS5 documents that ordinary FTS updates/deletes may leave old index entries recoverable from the database until merge, unless FTS5 `secure-delete` is enabled. SQLite core also provides `PRAGMA secure_delete` for deleted/free content.

P0-31 is not yet a user-runtime exposure, so this does not invalidate the search-core qualification. It **must be addressed before a user-facing runtime persistently writes the extracted-text cache**.

Required next-runtime correction:

- enable and qualify core SQLite secure deletion for the derived search DB;
- enable and qualify FTS5 secure deletion on the FTS table;
- verify replace/delete/rebuild behavior and version compatibility;
- keep filesystem permission/ACL hardening under existing H3 as a separate protection layer.

Primary external reference: SQLite FTS5 documentation, sections on external content, integrity-check, rebuild and secure-delete:
https://www.sqlite.org/fts5.html

## Runtime reachability observation

P0-31 proves the local physical-file -> durable Revision -> extraction -> FTS chain in tests, but the installed executable still exposes only raw `keelaryn scan --root`.

Therefore P0-31 does **not** claim that a normal user can yet create/open durable state and search it through the one executable required by the P0 technology spike.

## Conclusion

**P0-31 PASS. SQLite FTS5 search core is qualified.**

The next closure step is runtime composition, not an immediate protocol jump: wire the already-qualified local happy path into one executable before layering MCP over an otherwise unreachable library graph.
