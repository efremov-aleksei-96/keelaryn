# P0 Closure Re-audit — 2026-09-26

Status: **P0 NOT CLOSED**

Authority: this document is implementation/evidence audit material. `KEELARYN_CANONICAL.md` remains the sole product architecture authority.

## Evidence basis

- authoritative branch: `dev/corpus-first-p0`;
- audited head: `057535e98b686fb6edfba8cb98c4c911562abea2`;
- exact-head CI run: `36258258088` — validate PASS, Ubuntu 24.04 PASS, Windows 2025 PASS;
- P0-29 final product head: `be53c465823855704d5ac14b12f1bfc3de0160b7`;
- P0-29 qualification CI: `36257933663` — validate PASS, Ubuntu 24.04 PASS, Windows 2025 PASS;
- SQLite schema: v16;
- no live Google OAuth/provider access or corpus mutation has occurred.

The previous closure audit from 2026-09-25 is historical evidence. Its post-bootstrap NEW and provider-lifetime gaps have since been closed by P0-27 through P0-29.

## Required P0 path

| Canonical capability | Current status | Evidence / remaining gap |
|---|---|---|
| one existing corpus root | QUALIFIED FOR LOCAL | localfs reads a user-selected existing root without reorganization |
| read-only discovery | QUALIFIED FOR LOCAL; REMOTE MECHANICS QUALIFIED | local snapshot is product-usable; Google RemoteHistory/topology is qualified deterministically but has not yet been materialized into the general Observation/inventory path |
| durable ProviderObject/Locator observations | QUALIFIED LOCAL; REMOTE BRIDGE ABSENT | ScanSession/Observation/Locator authority is qualified; RemoteHistory has durable membership/lifetime/topology but does not itself create general Observation rows |
| Artifact identity | QUALIFIED MECHANICS / PARTIAL END-TO-END | bootstrap, SAME, NEW, authority sealing, replay, lifetime-scoped remote authority are qualified; remote provider current state is not yet orchestrated through ScanSession + Observation + acceptance |
| Revision continuity | QUALIFIED MECHANICS / PARTIAL REMOTE END-TO-END | SAME creates/reuses Revision only with exact ContentEvidence; no remote content-evidence acquisition/materialization loop exists |
| inventory | QUALIFIED LOCAL; REMOTE GENERAL INVENTORY ABSENT | latest COMPLETE scan defines local inventory; RemoteHistory membership is separate provider evidence, not current general inventory |
| minimal extraction | QUALIFIED | bounded Revision-bound UTF-8/Markdown extraction |
| SQLite FTS search | ABSENT | no FTS implementation exists in the active tree |
| task-specific ContextBundle | QUALIFIED FOR EXPLICIT LOCAL SELECTION | exact Artifact/Revision/source provenance; no search-driven selection yet |
| MCP/HTTP/CLI product access | PARTIAL | current CLI only performs local read-only scan; MCP/HTTP usable inventory/search/context surfaces are absent |

## Canonical P0 proof cases

| Proof | Status | Current evidence |
|---|---|---|
| unchanged object rescanned -> same Artifact and Revision | QUALIFIED MECHANICS / PARTIAL PRODUCT LOOP | SAME transaction and lifetime-scoped authority are qualified; a real remote Observation materialization loop is absent |
| rename/move with strong continuity -> same Artifact/Revision, new Locator | QUALIFIED MECHANICS / PARTIAL PRODUCT LOOP | P0-29 proves provider lifetime/topology/move semantics; general remote ScanSession/Observation orchestration is absent |
| content modification -> same Artifact, new Revision | QUALIFIED STORE MECHANICS / PARTIAL REMOTE LOOP | SAME changed-content behavior is qualified; remote exact content evidence is not yet acquired/orchestrated |
| true copy -> new Artifact despite identical bytes | QUALIFIED ACCEPTANCE MECHANICS | NEW admission and distinct provider lifetime identity preserve copy semantics |
| ambiguous continuity -> explicit ambiguity | QUALIFIED | no best-effort winner |
| unsupported content -> valid Artifact + unsupported extraction | QUALIFIED | extraction is independent of identity |
| restart -> exact durable identity state resumes | QUALIFIED | SQLite authority/replay/migrations survive reopen |
| derived extraction/index rebuild without identity change | PARTIAL | extraction is rebuildable; FTS is absent |
| ContextBundle cites exact Revision/source evidence | QUALIFIED | explicit ContextBundle path |
| corpus bytes unchanged by P0 operations | QUALIFIED FOR IMPLEMENTED PATHS | all current provider/corpus work is read-only; no live Google write has occurred |

## What P0-27 through P0-29 already solved

Do **not** rebuild these mechanisms:

- safe post-bootstrap NEW admission;
- hardened SAME/NEW request replay and parameter fingerprinting;
- durable trusted IdentityAuthoritySet boundary;
- RemoteHistory generation/publication/cursor discipline;
- ProviderObjectLifetimeSegment incarnation authority;
- lifetime-scoped provider-to-Artifact binding;
- RemoteHistory identity-authority producer;
- final SAME/NEW transaction revalidation against lifetime authority;
- Google history-universe identity;
- Google topology/membership projection;
- managed-root IN/OUT/UNKNOWN semantics;
- provider-ID reincarnation fail-closed behavior;
- deterministic topology projection verification.

The remaining gap is orchestration/materialization, not another identity model.

## RemoteHistory-to-identity status

The Store already provides:

```text
HistoryGeneration + active LifetimeSegment
→ CreateRemoteHistoryIdentityAuthority
→ sealed IdentityAuthoritySet
→ AcceptNewObservationInScan / AcceptSameObservationInScan
→ lifetime-scoped Artifact binding
```

Tests prove NEW, SAME, stale-authority rejection, replay, and immutable provenance.

However, those tests create `ScanSession` and `ObservationRecordInput` manually. No active product component currently turns exact remote provider state into a complete general Keelaryn scan/inventory.

## Remote metadata / Revision boundary

`RemoteObjectState` intentionally carries only:

```text
ProviderObjectID
Locator(s)
```

It is identity/membership evidence, not a fabricated full Observation.

Therefore the next stage MUST NOT silently invent size, timestamps, entry kind, or other metadata merely to populate Observation rows.

Likewise:

- regular-file `SAME` currently requires exact `ContentEvidence`;
- `NEW` may be accepted without content evidence, producing Artifact + assigned Observation but no Revision;
- the next stage MUST NOT weaken Revision semantics to make remote ingestion look complete.

When SAME requires a Revision decision, the orchestration must either obtain qualified content evidence through a bounded provider read / qualified provider content-evidence source, or leave identity/revision assignment unresolved until such evidence is available.

## Technology-spike checklist

| Item | Status |
|---|---|
| one Go executable direction | PARTIAL |
| SQLite state | QUALIFIED |
| local read-only scan | QUALIFIED |
| one real remote scan/materialization | ABSENT |
| provider/native identity evidence preserved | QUALIFIED MECHANICS |
| FTS query | ABSENT |
| minimal MCP endpoint | ABSENT |
| embedded minimal web status | ABSENT |

## Earliest remaining correctness/product gap

The earliest remaining gap is:

> **exact remote provider state -> existing ScanSession / Observation / inventory materialization -> existing lifetime-aware identity authority / SAME-NEW acceptance**

This precedes FTS, MCP, HTTP and UI because those surfaces should query a coherent end-to-end inventory rather than expose a provider-specific parallel state model.

It also precedes live Google qualification as a product-completeness step: the deterministic contract and fake-provider path can first prove the orchestration without credentials or user corpus access.

## Required next-stage contract

The next substantive stage should define, before implementation, the smallest orchestration/materialization contract that reuses the existing model.

Requirements:

1. **Reuse ScanSession/Observation/inventory.** Do not create a second remote inventory authority.
2. Bind one materialization attempt to an exact `HistoryGenerationID + PublicationSequence`; for Google managed roots also require the exact topology watermark/membership view.
3. Publish a COMPLETE scan only from one internally consistent exact provider-state boundary.
4. If provider/history state advances during preparation, reconcile and restart from authoritative state rather than mixing sequences.
5. Map only provider metadata actually obtained from a qualified source. Missing metadata is explicit/fail-closed; do not fabricate Observation facts.
6. Include only proven `IN` managed-root members. `UNKNOWN` membership must not be silently treated as OUT/absent.
7. Preserve ProviderObject identity + current Locator(s) as provider evidence, never Artifact identity.
8. Reuse `CreateRemoteHistoryIdentityAuthority`; do not create a second remote identity resolver.
9. Reuse `AcceptNewObservationInScan` and `AcceptSameObservationInScan`; do not bypass their final mutation-boundary revalidation.
10. NEW may remain Revision-less when content evidence is unavailable, as current semantics permit.
11. SAME regular-file acceptance must obtain exact ContentEvidence or remain unresolved/deferred; do not weaken Revision invariants.
12. Interruption before COMPLETE publication must leave the previous COMPLETE inventory authoritative.
13. Replay after timeout must reconcile scan/history prestate before any repeated durable write.
14. The first implementation should use deterministic/fake provider inputs and existing qualified Google history/topology structures; live OAuth remains a separate later qualification boundary.
15. After the stage passes CI, perform the mandatory per-stage correctness/reuse retrospective before moving to FTS/search/access work.

## Reuse / nearest-analogue findings

The required shape is not novel:

- Microsoft Graph driveItem delta uses initial enumeration to establish local state and later delta tokens to update that local representation; resynchronization rebuilds/reconciles local state.
- Dropbox list_folder + cursor is explicitly intended for maintaining a local cache/state from ordered entries.
- Syncthing BEP separates full Index publication from Index Update and binds incremental state to index identity/sequence.

Reuse the **full-state snapshot + incremental source + exact checkpoint + local materialized view** pattern.

Do not import their identity semantics as Artifact identity; Keelaryn-specific identity remains the already-qualified Artifact/Revision/authority layer.

## Explicitly not next

This audit does **not** authorize or select as the immediate stage:

- live OAuth against the maintainer's Drive;
- FTS implementation;
- MCP/HTTP/UI work;
- Android adapter work;
- physical mutation;
- a new identity or inventory schema.

Those remain candidates only after the remote Observation/materialization gap is closed and the next stage audit re-evaluates ordering.

## Next objective

Define the deterministic provider-state-to-Observation materialization contract and reuse plan. No live provider access and no product mutation beyond disposable/deterministic test state.
