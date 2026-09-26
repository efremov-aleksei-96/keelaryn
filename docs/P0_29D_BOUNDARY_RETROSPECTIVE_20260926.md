# P0-29D Boundary Retrospective — 2026-09-26

Status: **BLOCKERS FOUND / DEPENDENT C3 QUALIFICATION PAUSED**

Audited exact head: b04d321989a379ea54594d1a2323d99ac4b19f23
CI run 36254143711: validate PASS, Ubuntu 24.04 PASS, Windows 2025 PASS.
No live OAuth/provider access or corpus mutation occurred.

## Audit cadence defect

The mandatory Engineering Audit Policy was already in force. A second audit policy is not needed.
At least six qualified substantive slices accumulated after P0-28C3: P0-29A, P0-29B, P0-29C1, P0-29C2A, P0-29C2B and P0-29C2C.
The rolling counter nevertheless remained zero. The four-slice maximum and material schema/transaction triggers were therefore not enforced.

## D-B1 — managed-root binding can cross native-ID reincarnation

Severity: **BLOCKER**

Current managed-root authority is generation + managed_root_object_id + bound_sequence.
If that provider object is REMOVED and the same native ID later appears as a new ProviderObjectLifetimeSegment, the existing C3 query can accept the new incarnation as the old managed root.
This violates the P0-28C invariant that raw provider IDs are not durable identity across lifetime reuse.

Minimal correction: no schema migration.
Reuse binding.bound_sequence and the current active lifetime segment start.
For a non-provider-root managed root:
- no active segment => UNKNOWN;
- current segment start_sequence greater than binding.bound_sequence => UNKNOWN / lifetime mismatch;
- otherwise the binding still refers to the current incarnation.
Sequence granularity is sufficient because bindings are accepted only at a completed publication boundary.
Same-generation automatic rebinding after reincarnation remains unsupported in P0 and must fail closed.

## D-B2 — parent edge can cross parent native-ID reincarnation

Severity: **BLOCKER**

A topology node stores ParentObjectID plus its last publication sequence/ordinal.
If parent P is removed and later reappears with the same native ID, an older child-to-P edge can currently be followed into the new P incarnation without fresh child evidence.

Minimal correction: no new edge/incarnation table.
Reuse:
- topology node last_sequence / last_ordinal;
- current parent ProviderObjectLifetimeSegment start_sequence / start_ordinal;
- existing ordinalValue helper.
Follow an edge only when the edge evidence position is at or after the current parent incarnation start.
If the parent has no active lifetime segment, or the current segment began after the edge evidence, membership is UNKNOWN.
The traversed node should likewise be checked against its own current lifetime segment.

## D-B3 — audit clock accounting failed

Severity: **BLOCKER / PROCESS**

The project already has the correct audit policy. The defect is enforcement/accounting, not missing architecture.
Correction:
- retain the existing policy as sole authority;
- reset the clock with this retrospective;
- increment the rolling substantive-slice counter at future qualification checkpoints;
- material schema/identity/transaction changes trigger retrospective immediately even before the numeric limit.

## D-H1 — green C3 CI is not lifetime-safe qualification

Severity: **HIGH**

The current C3 tests cover IN/OUT/UNKNOWN, missing/unavailable state, stale watermark, cycles, ancestor moves and cross-history-universe separation.
They do not cover same-generation managed-root-ID reincarnation or same-generation parent-ID reincarnation with an unchanged child edge.
Therefore CI run 36254143711 remains useful mechanics evidence but does not qualify C3 lifetime-safe membership semantics.

## Simplification / reuse decisions

Rejected as unnecessary:
- schema v17 solely to add lifetime_segment_id to managed-root bindings;
- a second managed-root lifetime table;
- a parent-edge incarnation table;
- a new generic provider identity layer;
- a second audit policy.

Reuse instead:
- existing ProviderObjectLifetimeSegment;
- existing activeLifetimeSegmentConn;
- topology last_sequence / last_ordinal;
- managed-root bound_sequence;
- existing ordinalValue;
- existing Engineering Audit Policy.

Google Drive documentation states that file IDs are stable throughout the life of a file. That supports a lifetime boundary rather than authority to conflate separate lifetimes.

## Non-blocking observations

- Provider-specific membership query should remain provider-specific for now; premature provider-neutral abstraction is unnecessary.
- O(depth) traversal is acceptable for P0 until measurement proves otherwise.
- Immutable topology evidence + rebuildable current nodes + watermark remains justified and is not duplicate state.
- The canonical provider-history root remains scope authority and does not need a fabricated lifetime segment.

## Qualification narrowing

Still qualified: P0-29A, P0-29B, P0-29C1, P0-29C2A, P0-29C2B, P0-29C2C.
Not qualified: P0-29C3 managed-root membership lifetime boundary.

## Required next slice

One minimal blocker-fix slice only:
1. managed-root binding lifetime revalidation from existing bound_sequence;
2. parent-edge and traversed-node lifetime revalidation from existing evidence/start positions;
3. same-generation root-ID and parent-ID reincarnation adversarial tests;
4. keep schema v16;
5. no live provider access;
6. exact-head Ubuntu + Windows qualification;
7. re-audit before declaring C3 qualified.
