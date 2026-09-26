# P0-30B Boundary Retrospective — 2026-09-27

## Scope

P0-30B materializes one deterministic LIGHTWEIGHT_ALL metadata snapshot from an exact RemoteHistory publication into the already-authoritative ScanSession → Observation/Locator → Inventory path.

It does not assign Artifact/Revision identity, perform live Google OAuth/provider reads, download content, mutate corpus files, create a second inventory, or create a second identity system.

Initial implementation head: `574c919247e6a2d5ac023d51f16347a86d11818f`.

Hardened product head: `273141907d1a4af33b760c03ba219643ff77575f`.

Exact-head product CI: `36271236833` — validate PASS, Ubuntu 24.04 PASS, Windows 2025 PASS.

Current SQLite schema: v23.

## Final architecture

The B boundary is:

```text
exact RemoteHistory generation/publication
→ provider-specific deterministic managed-scope membership
→ canonical metadata snapshot + fingerprint
→ existing source-bound OPEN ScanSession
→ existing append-only Observation/Locator evidence
→ persisted-content fingerprint seal
→ provider-scope/topology revalidation inside completion transaction
→ existing COMPLETE ScanSession
→ existing latest-COMPLETE Inventory
```

Google managed-root ScanSession keys are identity-domain-disambiguated. Google file-ID locators reuse the pre-existing canonical `gdrive.FileIDLocatorPath` encoding, which percent-escapes the native object ID.

## Audit findings resolved

### B-B1 — competing fingerprint at one exact source boundary — BLOCKER
The initial replay lookup distinguished fingerprints but did not forbid a different fingerprint for the same root/generation/publication/source-scope/policy.

Resolution: schema v19 and API precheck enforce one deterministic fingerprint authority for that exact boundary.

### B-B2 — Observation evidence SQLite mutability — BLOCKER
ProviderObject occurrence, Observation and Locator rows were logically append-only but could still be directly updated/deleted.

Resolution: schema v20 seals all three evidence tables against UPDATE/DELETE.

### B-B3 — COMPLETE inventory authority bypass — BLOCKER
Generic/direct completion could create a provenance-free COMPLETE on a remote-managed root; an exact completed source could be duplicated; terminal scan evidence could be appended.

Resolution: schema v21 seals evidence writes to OPEN scans, remote-managed-root completion to source-bound scans, deterministic COMPLETE replay, and terminal evidence immutability.

### B-B4 — cross-object Locator collision — BLOCKER
Two provider objects could project to the same locator in one materialization.

Resolution: B rejects cross-object collisions; later v23 structural guards independently seal per-scan locator ownership.

### B-B5 — generic ScanSession lifecycle bypass — BLOCKER
Generic scan rows could be forged as terminal, have scope/start rewritten, be reopened, rewritten or deleted by direct SQL.

Resolution: schema v22 permits only valid OPEN creation and one OPEN→COMPLETE/ABORTED transition while keeping provider/root/start immutable.

### B-B6 — snapshot fingerprint not sealed to persisted content — BLOCKER
The source fingerprint described prepared input but completion did not prove that the actual persisted Observation/Locator set still matched it.

Resolution: the canonical fingerprint primitive moved to RemoteHistory shared code; B completion recomputes it from persisted scan content inside the SQLite completion transaction and rejects mismatch.

### B-B7 — Observation structural authority gaps — BLOCKER
SQLite could accept structures the public Observation API rejects: occurrence reuse, provider/scan mismatch, mode overflow, duplicate observed object, cross-object scan path collision, or COMPLETE observations with no locator.

Resolution: schema v23 adds one-to-one occurrence authority, structure/scope guards, observed-object uniqueness, locator ownership and COMPLETE coverage guards.

### B-B8 — provider scope/topology validation outside completion transaction — BLOCKER
A valid pre-completion IN-set check did not prove that provider topology/source scope was still valid at the mutation boundary.

Resolution: B completion now revalidates the bound Google managed root, topology watermark, exact IN membership and persisted object set in the same IMMEDIATE SQLite transaction that marks the scan COMPLETE.

### B-B9 — COMPLETE replay skipped durable verifier — BLOCKER
MaterializeRemoteMetadata returned a matching COMPLETE scan before invoking the hardened completion verifier.

Resolution: every B COMPLETE replay is re-read through CompleteRemoteHistoryScan, which verifies the immutable persisted-content seal while intentionally allowing historical COMPLETE reconciliation after RemoteHistory advances.

### B-B10 — duplicate/worse Google locator encoding — BLOCKER
The new B projector used raw native object IDs while the already-qualified Google adapter used `url.PathEscape`. That would split locator semantics for IDs containing reserved characters.

Resolution: `gdrive.FileIDLocatorPath` is now the single provider primitive used by the existing adapter, B projector and completion verifier.

### B-L1 — stale durable development state/docs — LOW
After product hardening, DEVELOPMENT_STATE, the audit clock and the P0-30 contract wording still reflected the P0-30A/B-next boundary and unescaped conceptual locator notation.

Resolution: the qualification checkpoint updates revision/state/audit clock and documents the canonical percent-escaped Google locator.

## Qualification evidence

The qualified B test surface includes:
- deterministic metadata fingerprint and exact source binding;
- exact IN / OUT / UNKNOWN behavior;
- missing-metadata fail-closed behavior;
- previous COMPLETE preservation across OPEN/ABORTED attempts;
- non-auto-abort of matching OPEN without worker ownership proof;
- COMPLETE replay verification and replay after history advance;
- two independent managed roots in one provider history universe;
- identity-domain separation of equal raw managed-root IDs;
- cross-object locator collision rejection;
- persisted-content fingerprint sealing;
- provider topology/source-scope transaction-boundary revalidation;
- canonical managed-root and canonical percent-escaped Google file-ID locator validation;
- direct-SQL adversarial authority tests;
- v18→v23 append-only migration regressions;
- unchanged local ScanSession regression behavior;
- Ubuntu 24.04 and Windows 2025 exact-head product CI.

## Reuse review

Rechecked patterns:
- Microsoft Graph delta: complete local state plus durable continuation checkpoint;
- Google Drive changes: page token/new start page token;
- Dropbox list_folder cursor and ordered local cache;
- Syncthing full Index plus Index Update;
- SQLite OLD/NEW triggers with RAISE(ABORT);
- zombiezen/sqlitemigration append-only transactional migrations.

The implementation continues to reuse Keelaryn's existing ScanSession/Observation/Inventory, RemoteHistory membership/topology, and future SAME/NEW identity path.

The final audit also found and removed a local reinvention: Google file-ID locator projection now reuses the already-qualified adapter's escaping semantics through one shared provider primitive.

Rejected as unnecessary:
- a second remote inventory;
- a second scan table;
- a provider-specific Artifact model;
- a new identity resolver;
- a new sync dependency;
- live OAuth/provider access in B;
- content download in B;
- a new durable seal for unscanned Locator append where no supported mutation path exists.

## Portability and security

P0-30B adds no dependency and no OS-specific product code. Product CI qualifies Ubuntu 24.04 and Windows 2025. Android remains a planned target and is not claimed qualified by this stage.

No P0-30B path reads credentials, performs live provider/network access, or mutates corpus files.

## Final repeated audit result

After B-B10 was corrected at `273141907d1a4af33b760c03ba219643ff77575f`, the full product audit was run again across canonical invariants, durable authority, transaction boundaries, replay/interruption, migrations, negative/direct-SQL cases, runtime call sites, portability, security, recovery, stale state and reuse/duplication.

Result: **no new product BLOCKER, HIGH, MEDIUM or LOW finding**.

This checkpoint resolves the remaining documentation/state LOW finding B-L1. A post-checkpoint read-only audit remains mandatory before dependent P0-30C implementation begins.

## Conclusion

P0-30B product boundary: **PASS / QUALIFIED**.

Next substantive stage: **P0-30C — existing identity/revision integration**. No P0-30C implementation begins until the post-checkpoint audit verifies this qualification checkpoint itself.
