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

## Finding C3-B4 — legacy admission FK contradicted segment-only RemoteHistory NEW

Severity: **BLOCKER BEFORE LIVE PROVIDER**

The first v13 CI run (`36242439295`) exposed an older schema constraint that the Go-level audit had not yet removed:

```text
accepted_artifact_admissions
  FOREIGN KEY (identity_domain, provider_id, native_object_id)
  -> provider_artifact_bindings
```

That FK originated in the pre-lifetime v5 admission model. Once C3 correctly stopped RemoteHistory from creating naked bindings, the final accepted admission could not commit and SQLite returned `FOREIGN KEY constraint failed`.

This is a useful failure: it proves the database still enforced the old identity model even after application code stopped trusting it.

### Correction — schema v14

v13 remains intact.

v14 rebuilds only `accepted_artifact_admissions`:

- removes the unconditional naked-binding foreign key;
- retains Observation, Artifact and LifetimeSegment foreign keys;
- local/legacy policies are guarded by an explicit matching naked binding;
- `remote-history:lifetime-segment:v1` is guarded by an explicit matching lifetime-segment binding;
- UPDATE/DELETE immutability is recreated on the rebuilt table.

This makes the SQLite authority model policy-aware without weakening local/legacy admission correctness.

## Final C3 qualification

P0-28C3 is **PASS** after schema v14 and migration-test lifecycle correction.

Qualified exact product head:

```text
1567f0967b7082db66e5605fa69e5c0a4bc8f027
```

GitHub Actions run:

```text
36244269461
```

Results:

- validate — PASS;
- Ubuntu 24.04 — PASS;
- Windows 2025 — PASS.

Additional read-only checks during qualification:

- all SQLite migration tests were checked for the same checked-out-connection / Pool.Close self-deadlock pattern; no second instance was found;
- Kubernetes Name/UID and Microsoft Graph delta semantics were revalidated against current official documentation and remain consistent with the Keelaryn generation/lifetime model;
- no new runtime dependency, live provider call, OAuth flow, Drive read/write, or corpus mutation was introduced.

Effective RemoteHistory identity semantics after C3:

```text
HistoryGeneration
+ ProviderObjectLifetimeSegment
+ immutable publication evidence
+ segment-scoped Artifact binding
+ final-transaction authority revalidation
```

The legacy naked provider-object binding remains only legacy/local provenance and is not RemoteHistory authority.

