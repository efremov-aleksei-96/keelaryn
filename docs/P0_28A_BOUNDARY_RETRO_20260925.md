# P0-28A Boundary Retrospective — 2026-09-25

Status: **PASS / P0-28A QUALIFIED**

Audited head: `ceb1911057f2d96a07c0e2b90d134383314ff0c3`

Exact-head CI:
- run: `36138112864`;
- validate: PASS;
- Ubuntu 24.04: PASS;
- Windows 2025: PASS.

This retrospective is the mandatory risk-trigger audit required after the identity/transaction/schema hardening in P0-28A.

## Scope

Reviewed:
- caller/runtime trust boundary for SAME and NEW;
- request replay/idempotency semantics;
- semantic request fingerprinting;
- durable authority storage and consumption;
- SQLite immutability/sealing;
- provider-object binding conflict behavior;
- migration v5 -> v6 -> v7;
- runtime reachability;
- retained provider-lifetime limitations.

## Findings resolved before qualification

### Authority immutability

The first P0-28A implementation treated authority sets and identity mutation receipts as append-only by convention.

P0-28A v7 now enforces the boundary in SQLite:
- authority set is sealed after producer construction;
- sealed set UPDATE/DELETE is rejected;
- candidate INSERT/UPDATE/DELETE after seal is rejected;
- identity mutation receipt UPDATE/DELETE is rejected;
- v6 -> v7 migration seals already-existing authority state.

Result: **PASS**.

### Provider binding conflict on SAME

The first implementation could derive SAME for Artifact B even if the same provider-native object already had durable historical binding to Artifact A.

The hardened SAME mutation now revalidates existing provider binding and fails closed when it conflicts with the resolved Artifact.

Result: **PASS**.

### Test-regression correction

The v7 hardening commit initially introduced only a regression-test syntax error and a hidden pool-use problem in the test itself. No product/schema failure was observed before test compilation.

The follow-up test-only commit:
- fixed the Go range syntax;
- released the single SQLite pool connection before invoking Store APIs.

Exact-head CI on the corrected tree is fully green.

## Qualification boundary

P0-28A now qualifies:

```text
caller intent
+ stable request ID
+ semantic fingerprint
+ durable sealed authority-set ID
→ SQLite loads full authority
→ derives SAME / NEW inside transaction
→ revalidates existing binding
→ commits mutation + provenance + replay receipt atomically
```

The caller cannot authorize identity mutation by supplying:
- raw CONCLUSIVE strength;
- raw COMPLETE coverage;
- a preselected RESOLVED_SAME / RESOLVED_NEW.

Exact replay returns the original durable result with zero new mutation. Reuse of a request ID with different semantic input fails explicitly.

## Retained limits — not defects in P0-28A

P0-28A does **not** qualify naked provider-object bindings as live continuity authority.

For provider IDs classified only as `STABLE_FOR_RESOURCE_LIFETIME`:
- history generation is still absent;
- object lifetime/presence segment is still absent;
- REMOVED/reappearance continuity is not yet modeled;
- no live provider authority producer exists.

Therefore live Drive identity acceptance remains blocked until P0-28B/P0-28C.

## Reuse validation

The final P0-28A model deliberately reuses established semantics rather than inventing retry behavior:
- AWS/Stripe-style request-key parameter binding and deterministic replay;
- append-only/sealed durable authority analogous to journal/ledger boundaries;
- Syncthing generation/sequence concept reserved for the next history layer;
- rclone bisync fail-closed last-known-good recovery principle reserved for publication/recovery.

No new dependency was required.

## Conclusion

No unresolved blocker remains inside the P0-28A identity acceptance boundary.

Next safe layer:

**P0-28B — provider-neutral history generation and durable publication contract.**

Do not enable live Google Drive/OAuth or allow provider history to authorize SAME/NEW until P0-28B and the subsequent object-lifetime segment layer are qualified.
