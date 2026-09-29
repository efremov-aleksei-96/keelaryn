# P0-30C2 — Materializer / identity / revision integration retrospective

Date: 2026-09-29  
Status: **PASS / P0-30 QUALIFIED**  
Product implementation HEAD: `3b951a66650ab98d213b0823b0bce145b587872c`  
Qualification HEAD: `be12edd43c41ef57896f92706867bb85d9d9c5b2`  
Exact-head CI: **36474994106 — SUCCESS**  
Initial product CI: **36473715486 — SUCCESS**  
SQLite schema authority: **v39**

## Scope

P0-30C2 connected the already-qualified deterministic remote metadata materializer to the already-qualified C1 identity/revision acceptance boundary.

The implementation remains a library boundary. It does not add live Google OAuth/provider reads, content downloading, CLI/MCP/HTTP exposure, corpus mutation, a second inventory, a second identity resolver, or a provider-specific Artifact model.

## Architecture result

The C2 orchestration reuses:

- P0-30B `ScanSession -> Observation -> Inventory`;
- `CreateRemoteHistoryIdentityAuthority`;
- the shared `corpus.ResolveIdentityAuthoritySet` resolver;
- `AcceptNewObservationInScan`;
- `AcceptSameObservationInScan`;
- existing Artifact / Revision / ContentEvidence semantics;
- existing RemoteHistory lifetime segments;
- C1 source-bound transaction validation and replay receipts.

The B materializer was refactored only enough to accept an internal observation-writer seam. The original `MaterializeRemoteMetadata` path still writes unresolved Observations with the same snapshot/fingerprint/completion semantics.

## Qualified identity outcomes

For each exact in-scope provider object:

- **RESOLVED_NEW** uses the existing NEW acceptance transaction.
- **RESOLVED_SAME** uses the existing SAME acceptance transaction when its existing content rules permit it.
- A regular-file SAME without source-bound ContentEvidence remains unresolved.
- A non-regular SAME may preserve the Artifact without inventing a Revision.
- AMBIGUOUS / UNRESOLVED remains an unresolved Observation.
- NEW may create an Artifact without a Revision when content evidence is absent.
- Regular SAME with exact supplied ContentEvidence may preserve the Artifact and create/reuse Revision according to the existing revision rules.

Exactly one Observation is persisted per object in one successful scan attempt.

## Deterministic mutation replay

C2 derives identity mutation request IDs from:

- scan ID;
- source generation;
- publication sequence;
- source scope;
- immutable snapshot fingerprint;
- provider object ID;
- SAME/NEW operation kind.

The existing mutation fingerprint still binds request meaning, including ContentEvidence, so an uncertain retry with changed semantic parameters fails rather than silently becoming a second accepted mutation.

## Source-bound ContentEvidence

The C2 API accepts optional content evidence only when it declares the same:

- generation;
- publication sequence;
- provider object;
- regular-file size;

as the metadata snapshot, and carries a non-empty qualification/source reference.

This does not introduce live content acquisition. The supplier remains responsible for having obtained/qualified that evidence for the declared source boundary; the final SAME/NEW SQLite transaction independently revalidates that the scan's RemoteHistory publication is still current before identity/revision mutation.

## Interruption and history-advance proof

The initial C2 implementation CI passed on Ubuntu 24.04 and Windows 2025.

Retrospective review identified one missing composition-level regression:

### C2-T1 — TEST_GAP — RESOLVED

**Issue:** C1 already proved that fresh source-bound SAME/NEW mutations fail after RemoteHistory advances, but C2 initially lacked an end-to-end regression where the advance happens after orchestration/authority resolution and immediately before SAME acceptance.

**Correction:** qualification HEAD `be12edd43c41ef57896f92706867bb85d9d9c5b2` adds a race harness that advances RemoteHistory at the SAME mutation boundary. The existing C1 transaction guard rejects the stale mutation, the failed scan becomes ABORTED, and the previous COMPLETE inventory remains authoritative.

No product-code change was required for this finding.

## Qualification evidence

CI **36474994106** on exact qualification HEAD:

- validate — PASS;
- go / Ubuntu 24.04 — PASS;
- go / Windows 2025 — PASS;
- dependency lock check — PASS;
- `go test ./...` — PASS;
- `go vet ./...` — PASS.

C2 additionally proves:

- NEW without ContentEvidence creates Artifact without forcing Revision;
- regular SAME without ContentEvidence remains unresolved;
- regular SAME with exact source-bound ContentEvidence preserves Artifact and yields Revision evidence;
- mismatched source-bound ContentEvidence is rejected before scan publication;
- history advance during the final SAME boundary fails closed;
- failed stale attempt does not replace the previous COMPLETE inventory.

## Retrospective findings

Open C2 BLOCKER/CRITICAL findings: **0**.

Open C2 HIGH/MEDIUM/LOW product findings: **0**.

Existing project-level HIGH findings H1-H4 remain explicitly carried for their previously assigned release/security/operability/portability gates. C2 neither resolves nor worsens them.

The earlier VPS `gofmt` probe is not qualification evidence: it failed only because the VPS image does not have `gofmt` installed. It mutated neither repository state nor VPS product/runtime state.

## Reuse / unnecessary-solution review

No new dependency is justified.

Rejected as unnecessary:

- second remote inventory;
- new remote Artifact/Revision model;
- second identity resolver;
- provider-specific SAME/NEW logic;
- durable orchestration/capability table;
- live provider reads solely to complete C2;
- content download solely to force SAME.

The existing Graph/Dropbox/Syncthing snapshot + checkpoint + materialized-view patterns remain the useful external analogues; Keelaryn-specific identity stays in the already-qualified Artifact/Revision/lifetime authority layer.

## Portability and mutation scope

- new product dependencies: **0**;
- schema change: **none**; authority remains **v39**;
- live provider/OAuth use: **none**;
- corpus file mutation: **0**;
- OS-specific product code added: **0**;
- exact-head Ubuntu 24.04 and Windows 2025: **PASS**;
- Android remains planned, not claimed.

## Conclusion

**P0-30C2 PASS. P0-30 is qualified at the library boundary.**

The prior P0 closure audit selected remote provider-state → Observation/inventory → identity orchestration as the earliest remaining gap. That gap is now implemented and qualified. The next safe action is a **read-only P0 closure re-audit** against the qualified C2 boundary to select the next genuine gap rather than assuming one from older plans.
