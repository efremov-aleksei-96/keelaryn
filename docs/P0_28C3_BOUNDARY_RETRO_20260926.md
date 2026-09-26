# P0-28C3 Lifetime Authority Boundary Retrospective — 2026-09-26

Status: **BLOCKERS FOUND / HARDENING IMPLEMENTED / QUALIFICATION PENDING**

Audited development head before hardening: `78c561d8c8ceba0a8cec71a3c8128ba5e99cb835`  
Qualified C2B product head: `427d1d27c94e7644cf4c91f9b2b864617658e044`  
Qualified C2B CI: `36241394864` — validate PASS, Ubuntu 24.04 PASS, Windows 2025 PASS.

No live OAuth/provider access or corpus mutation occurred.

## Reuse audit

Independent mature designs continue to support the chosen boundary:

- Kubernetes separates reusable Name from historical UID.
- Linux NFS filehandles combine inode identity with inode generation.
- Syncthing resets index identity when the sequence space is reset.
- Microsoft Graph delta commits future continuation only at terminal delta state and permits repeated item appearances within a round.

These patterns all reject the idea that one reusable human/native key is sufficient historical identity across an incarnation or history reset.

## Finding C3-B1 — RemoteHistory NEW still dual-wrote naked provider binding

Severity: **BLOCKER BEFORE LIVE PROVIDER**

The C2B transaction correctly created:

```text
LifetimeSegmentID -> ArtifactID
```

but also inserted the legacy table keyed by:

```text
IdentityDomain + ProviderID + ProviderObjectID
```

That legacy key cannot represent:

```text
segment S1 / native ID X -> Artifact A
segment S2 / same native ID X -> Artifact B
```

Therefore a reused provider ID could be blocked or replay could observe the wrong compatibility binding even though the lifetime model correctly distinguishes the segments.

### Correction

RemoteHistory-policy NEW no longer persists a naked provider binding.

The legacy table remains for pre-lifetime/local policies and already-issued historical rows. Schema v13 rejects any new row whose policy is `remote-history:lifetime-segment:v1`.

No existing row is automatically deleted or reinterpreted.

## Finding C3-B2 — accepted lifetime provenance stored but not surfaced/validated

Severity: **BLOCKER BEFORE LIVE PROVIDER**

Schema v12 stored `lifetime_segment_id` on accepted SAME/NEW rows, but the durable domain records and read/replay path did not expose that field.

### Correction

Accepted continuity/admission records now carry `LifetimeSegmentID`.

Readers fail closed unless RemoteHistory decisions reconcile with:

- immutable identity-mutation receipt;
- exact Artifact;
- exact policy;
- existing lifetime segment binding;
- for NEW, the binding source authority set;
- for SAME, the sealed authority set for that segment and selected Artifact.

Remote NEW replay reconstructs its compatibility return value from the lifetime binding rather than querying naked provider binding state.

## Finding C3-B3 — accepted identity decisions were SQL-mutable

Severity: **BLOCKER BEFORE LIVE PROVIDER**

`identity_mutation_requests` were already immutable, but `accepted_continuity_decisions` and `accepted_artifact_admissions` lacked UPDATE/DELETE guards despite being non-rebuildable committed provenance.

### Correction

Schema v13 makes both accepted-decision tables UPDATE/DELETE immutable.

Adversarial tests directly attempt modification/deletion.

## Migration discipline

Schema v12 is not rewritten.

```text
v12 = lifetime provenance columns and insert guards
v13 = accepted-decision immutability + forbid new RemoteHistory naked bindings
```

## Qualification required

Exact-head CI must pass:

- validate;
- Ubuntu 24.04;
- Windows 2025;
- all previous tests;
- v12→v13 migration;
- RemoteHistory NEW creates only segment binding;
- exact NEW replay succeeds without naked binding;
- RemoteHistory SAME ignores conflicting legacy naked binding;
- read APIs expose and validate LifetimeSegmentID;
- accepted SAME/NEW UPDATE/DELETE rejected;
- direct SQL RemoteHistory naked binding rejected;
- stale authority remains zero-mutation fail-closed;
- go vet.
