# P0-33 — Task-specific ContextBundle runtime composition retrospective

Date: 2026-09-30  
Status: **PASS / P0-33 QUALIFIED**  
Initial implementation HEAD: `30b619a16c18d0bbcd9f2e9bf763709c2eef2763`  
Bounded-outcome correction HEAD: `0e276b62eb02fa125c21e6d3b30bd503dc5ec3ff`  
Qualified product HEAD: `adaa3cc68cece243cd6d6092bf881120c64064a5`  
Exact-head CI: **36625411480 — SUCCESS**  
Authoritative identity-state schema: **v45 unchanged**  
Derived search-cache schema: **v3 unchanged**  
New product dependencies: **0**

## Scope

P0-33 composes the already-qualified literal FTS search with current Inventory and the P0-18 local ContextBundle builder.

Qualified development-spike path:

```text
literal query
→ ordered exact Artifact/Revision hits
→ exact current Inventory match
→ deterministic current read locator
→ bounded Revision-bound extraction
→ provenance verification
→ source-boundary replay
→ ephemeral task-specific ContextBundle
```

No durable semantic state, ontology, MCP/HTTP/web surface, live provider or corpus mutation was introduced.

## Authority and stale-source rules

A search hit is selection assistance only.

For every returned item:

- ArtifactID + RevisionID must match current Inventory exactly;
- the local extractor identity must match;
- no current Revision may be substituted for a historical/stale search hit;
- search-hit order is preserved;
- path remains only a deterministic read locator, never Artifact identity;
- EXTRACTED/OPAQUE outcomes require exact ContentEvidence;
- UNSUPPORTED/LIMIT_EXCEEDED remain valid bounded outcomes with no text and completely zero-value ContentEvidence;
- STALE_REVISION fails closed as `ErrCorpusChanged`;
- the exact immutable bootstrap/source boundary is replay-proved before and after ContextBundle source reads.

The bundle remains derived and ephemeral.

## Pre-qualification findings

### P0-33-M1 — bounded ContextBundle outcome overconstraint — RESOLVED

The initial composition required fresh ContentEvidence for every bundle item. That contradicted the already-qualified extractor contract for UNSUPPORTED and LIMIT_EXCEEDED, which intentionally return exact identity provenance without reading content bytes.

Commit `0e276b62...` preserves those bounded outcomes while keeping STALE_REVISION fail-closed.

### P0-33-M2 — partial bounded evidence accepted — RESOLVED

Targeted retrospective found that the first M1 correction checked only for an empty evidence digest. A malformed bounded item could therefore have carried a non-empty algorithm or non-zero size while still passing verification.

Qualified HEAD `adaa3cc68cece243cd6d6092bf881120c64064a5` now requires the entire ContentEvidence value to be zero for UNSUPPORTED/LIMIT_EXCEEDED. A regression test injects partial evidence and proves rejection.

## CI timing correction

Control checkpoint `018d5a8...` incorrectly described an in-progress Windows Actions job as stale beyond the job timeout.

That classification was wrong. GitHub timestamps were UTC while the local Yerevan calendar date had already advanced, and historical exact-head runs show the Windows suite normally takes roughly ten minutes because the SQLite/ingest packages are substantially slower on the hosted Windows runner.

The intermediate Windows jobs were cancelled by workflow concurrency after newer commits. No stale-run product or runner defect was established.

Final exact-head CI `36625411480` provides the required evidence:

- validate — PASS;
- Ubuntu 24.04 — PASS;
- Windows 2025 — PASS;
- dependency lock / `go mod tidy -diff` — PASS;
- `go test ./...` — PASS;
- `go vet ./...` — PASS.

## Boundary retrospective

Targeted architecture/correctness review after the final hardening found no new BLOCKER/CRITICAL:

- exact Revision provenance is preserved;
- current Inventory is the currentness authority;
- no Revision substitution exists;
- deterministic locator choice does not redefine identity;
- changed corpus boundary aborts before returning a bundle;
- read-side missing DB paths are not created;
- FTS integrity/rebuild remains an operability/recovery concern for H4 Doctor rather than a full integrity scan on every query.

## Remaining production gates

P0-33 is a development/local composition slice, not production user-runtime qualification.

Still open:

- H3 protected filesystem/ACL storage for durable control/search state;
- H4 aggregate Doctor/SelfTest;
- live remote/provider runtime qualification;
- Android qualification;
- MCP/HTTP/web;
- release/update rollback;
- physical corpus mutation.

## Conclusion

**P0-33 PASS. The local one-executable path now reaches an exact, bounded, task-specific ephemeral ContextBundle.**

The next autonomous product gap is H3: a protected control-storage runtime boundary.
