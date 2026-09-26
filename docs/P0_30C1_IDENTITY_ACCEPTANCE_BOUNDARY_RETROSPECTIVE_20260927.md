# P0-30C1 — Remote identity acceptance boundary retrospective

Date: 2026-09-27  
Status: **PASS**  
Audited / qualified HEAD: `029b49d4c1985cabab722214ac9218d3b5eaf2d9`  
Exact-head CI: **36276633396 — SUCCESS**  
SQLite schema authority: **v27**

## Scope

C1 did not implement the remote materializer-to-identity orchestration yet. It hardened and qualified the existing SAME/NEW acceptance boundary so a later materializer can safely reuse it for an exact source-bound remote ScanSession.

No live provider/OAuth access, content download, CLI/MCP/HTTP exposure, or corpus mutation occurred.

## Reuse and architecture result

C1 reuses the existing:
- `CreateRemoteHistoryIdentityAuthority`;
- SAME / NEW acceptance transactions;
- Artifact / Revision / ContentEvidence model;
- identity mutation replay receipts;
- Google managed-root membership authority;
- P0-30A source sidecar;
- P0-30B ScanSession / Observation / Inventory model.

It adds **no second identity resolver, inventory, provider-specific Artifact model, or durable capability table**.

The duplicated SQLite authority-set resolver was removed in favor of one shared pure `corpus.ResolveIdentityAuthoritySet` path.

B completion and C identity acceptance now share the same Google managed-root/object-scope primitives.

## Findings found and resolved

### C1-B1 — BLOCKER
Non-regular SAME allowed nil ContentEvidence but unconditionally dereferenced it while creating a Revision.

**Resolution:** non-regular SAME assigns the existing Artifact without creating a Revision; exact replay remains mutation-free.

### C1-B2 — BLOCKER
The first source-bound guard accepted any locator path inside the correct provider/root.

**Resolution:** Google source-bound identity acceptance requires exactly one canonical shared `gdrive.FileIDLocatorPath(objectID)` locator.

### C1-B3 — BLOCKER
Source-bound identity acceptance did not bind `Observation.ObservedAt` to the source ScanSession boundary.

**Resolution:** remote SAME/NEW requires `ObservedAt == ScanSession.started_at`.

### C1-L1 — LOW
Google managed-root/root/locator/membership rules were temporarily duplicated between B completion and C identity mutation.

**Resolution:** shared internal primitives now define canonical managed-root and per-object scope once and are reused by both boundaries.

### C1-B4 — BLOCKER
Go-level transaction checks could still be bypassed by direct SQL. A caller could persist source-bound assigned Observation / accepted decision / mutation receipt or a RemoteHistory lifetime→Artifact binding without the validated SAME/NEW application path.

**Resolution:** schema v27 introduces narrow connection-local application capabilities. Source-bound assigned identity state and RemoteHistory lifetime binding can be written only while the already-validated SAME/NEW transaction holds the exact capability. No durable capability state is added.

### C1-T1 / C1-T2 — TEST GAPS
SAME source-bound races, unsupported provider behavior, raw-SQL application guards, ambiguous resolver behavior and capability release were not all directly proven.

**Resolution:** targeted adversarial regressions cover all of those branches.

## Replay / interruption

Exact existing identity-mutation receipt replay still occurs before current-source revalidation. This is intentional: after an uncertain local result or later RemoteHistory advance, an already committed SAME/NEW mutation must reconcile to its durable prior result rather than be duplicated or rejected as if it were new work.

A fresh mutation at an advanced source boundary fails closed inside the final SQLite transaction.

## Durable authority

Schema v27 guards:
- source-bound assigned Observation;
- source-bound accepted continuity;
- source-bound accepted admission;
- source-bound identity mutation receipt;
- RemoteHistory lifetime→Artifact binding.

Capabilities are connection-local, short-lived, and cleared before the transaction scope exits. External/direct SQLite writes without the registered capability fail closed.

## Portability / dependencies

- no new dependency;
- no OS-specific product code;
- Ubuntu 24.04 exact-head PASS;
- Windows 2025 exact-head PASS;
- Android remains architecturally targeted but is not yet CI-qualified.

## External / prior-art posture

C1 continues the existing P0-30 reuse decisions: exact provider checkpoint + local materialized state + replay/resync patterns from mature remote-state systems; SQLite triggers plus narrow application-defined predicates provide the durable mutation boundary. No external system's identity semantics are imported.

## Nonblocking follow-ups

1. `IdentityAuthoritySet.CreatedAt` is not yet globally constrained to be at-or-after the underlying RemoteHistory publication. C1 correctness does not depend on this field, and C2 will use the causal scan boundary when creating authority, but the timestamp should receive a systemic provenance audit before it becomes causal authority.
2. If the SQLite state file is ever treated as untrusted external input, revisit `trusted_schema` / authorizer hardening for intentionally indirect trigger functions.

## Conclusion

**PASS.** No open BLOCKER / HIGH / MEDIUM / LOW product finding remains in the C1 boundary. P0-30C itself is **not** qualified yet. The next permitted substantive slice is C2 materializer→identity/revision integration, followed by a full audit from scratch before any further closure claim.
