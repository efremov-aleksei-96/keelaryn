# P0-28C — Provider-Object Lifetime Segment Contract

**Status:** CONTRACT DECIDED / IMPLEMENTATION NEXT  
**Scope:** provider-neutral lifetime continuity on top of qualified P0-28B HistoryGeneration/publication evidence  
**Live OAuth/provider access:** forbidden in this slice  
**Corpus mutation:** none

## 1. Problem

A provider-native object ID is not automatically a timeless Keelaryn identity.

For contracts such as Google Drive file IDs, the documented guarantee is stable identity for the life of the provider resource. RemoteHistory can prove an uninterrupted interval, but a `REMOVED` event or HistoryGeneration boundary breaks that proof.

Therefore Keelaryn needs an explicit identity for one **provably uninterrupted provider-object presence lifetime**.

The lifetime segment is evidence identity. It is not an Artifact and is never derived from path or content hash.

## 2. Reuse basis

### Kubernetes object UID

Kubernetes separates reusable object names from a UID that distinguishes historical occurrences.

Reuse:
- one visible/native identifier can refer to different historical incarnations;
- identity decisions must carry incarnation context.

Do not reuse:
- Kubernetes UID as Keelaryn Artifact identity.

### NFS filehandles

NFS persistent filehandles are valid for the lifetime of a file-system object and become stale when the object is removed. The NFS specification also describes generation numbers for volatile handle slots so reuse of a slot does not resurrect old identity.

Reuse:
- stable-for-lifetime identifier is valid only inside the proven lifetime;
- expiry/removal ends continuity;
- a generation/incarnation component prevents unsafe reuse.

### NTFS MFT segment references

NTFS file references pair an MFT segment address with a sequence number that changes as the record is reused.

Reuse:
- a native slot/object number without incarnation context is weaker than the compound historical reference.

### Google Drive

Drive documents file IDs as stable throughout the life of the file. Drive change-log removal can mean deletion, loss of access, or removal from the tracked corpus.

Reuse:
- file ID is provider identity evidence;
- `REMOVED` is a presence/visibility boundary, not proof of physical deletion;
- later same-ID visibility does not automatically bridge that boundary.

## 3. Lifetime segment definition

A `ProviderObjectLifetimeSegment` is one maximal interval of **proven uninterrupted presence** for one provider-native object inside one exact HistoryGeneration.

Conceptual fields:

```text
LifetimeSegmentID
HistoryGenerationID
ProviderObjectID

Start:
    PublicationSequence
    ChangeOrdinal?        # absent for bootstrap
    Kind = BOOTSTRAP | UPSERT

End?:
    PublicationSequence
    ChangeOrdinal?
    Reason = REMOVED_FROM_SCOPE | HISTORY_GENERATION_CLOSED

Status = ACTIVE | CLOSED
```

Rules:

- a segment never crosses a HistoryGeneration boundary;
- at most one ACTIVE segment exists for one `(HistoryGenerationID, ProviderObjectID)`;
- `REMOVED` closes the active segment but does not assert physical deletion;
- a later UPSERT while absent starts a new segment even when `ProviderObjectID` is identical;
- closing a HistoryGeneration closes every still-active segment with `HISTORY_GENERATION_CLOSED`;
- rebootstrap creates segments in the new generation and never silently joins them to old segments.

## 4. Publication ordinal matters

One complete provider cycle can contain multiple changes for the same object.

Therefore publication sequence alone is not sufficient to name a segment boundary.

Changes are interpreted in retained immutable order:

```text
(HistoryPublicationSequence, ChangeOrdinal)
```

Examples:

```text
UPSERT
REMOVED
```

inside one publication can create and close a segment in that same publication.

```text
REMOVED
UPSERT
```

closes the old segment and starts a different segment even though both transitions share the same publication sequence.

Bootstrap starts have no change ordinal and are distinguished by `StartKind=BOOTSTRAP`.

## 5. Deterministic rebuildable segment identity

Lifetime segments are derived from immutable P0-28B history evidence. Their identifier therefore SHOULD be deterministic and rebuildable.

Canonical segment identity tuple:

```text
version = provider-lifetime-segment:v1
HistoryGenerationID
ProviderObjectID
StartKind
StartPublicationSequence
StartChangeOrdinal? 
```

`LifetimeSegmentID` is:

```text
hseg_ + SHA-256(canonical tuple)
```

This hash is **not Artifact identity** and is not content identity. It is a deterministic name for one exact immutable evidence interval.

The tuple is stored alongside the ID. Recalculation mismatch is corruption and MUST fail closed.

Why deterministic:

- segment rows can be reconstructed from immutable bootstrap/change evidence;
- a rebuild recreates the same segment IDs;
- non-rebuildable accepted Artifact bindings can safely reference those stable segment IDs.

## 6. Segment derivation state machine

For each provider object, replay one HistoryGeneration in exact publication/change order.

### Bootstrap

Every object in the complete bootstrap membership creates one ACTIVE segment beginning at publication 1 / BOOTSTRAP.

### Incremental UPSERT

If an ACTIVE segment already exists:

```text
UPSERT
→ same segment continues
```

If no ACTIVE segment exists:

```text
UPSERT
→ create new ACTIVE segment at this publication/ordinal
```

### Incremental REMOVED

If ACTIVE:

```text
REMOVED
→ close segment at this publication/ordinal
→ reason REMOVED_FROM_SCOPE
```

If already absent:

```text
REMOVED
→ retain immutable provider evidence
→ no invented segment transition
```

### HistoryGeneration closure

For every still-ACTIVE segment:

```text
generation closes
→ close segment at last committed publication boundary
→ reason HISTORY_GENERATION_CLOSED
```

This means Keelaryn proved continuity **through** the last committed publication, not after it.

## 7. Derived-state durability

The segment table is durable for efficient queries but is rebuildable from:

- immutable bootstrap membership;
- immutable ordered publication changes;
- immutable HistoryGeneration closure state.

P0-28C implementation MUST provide deterministic reconciliation/rebuild verification.

A segment row alone is not stronger authority than the retained P0-28B evidence from which it derives.

## 8. Artifact binding must be segment-scoped

The existing naked key:

```text
(identity_domain, provider_id, native_object_id)
```

is too strong for stable-for-resource-lifetime providers.

P0-28C introduces a segment-scoped binding:

```text
LifetimeSegmentID
→ ArtifactID
```

with accepted policy/provenance.

Rules:

- one segment binds to at most one Artifact;
- one Artifact may legitimately bind to multiple segments when stronger accepted evidence later proves continuity;
- same native ProviderObjectID in another segment does not automatically inherit the binding;
- same native ID in another HistoryGeneration does not automatically inherit the binding.

The old `provider_artifact_bindings` table remains legacy/unscoped provenance during migration. A live RemoteHistory identity producer MUST NOT treat an old naked binding as conclusive lifetime authority.

A legacy binding for the same native provider object is an ambiguity blocker until reconciled into a qualified segment binding.

## 9. RemoteHistory identity-authority producer

P0-28C adds a **source-specific internal producer** of sealed `IdentityAuthoritySet` records. There is still no exported generic caller-controlled authority writer.

For the current provider object, the producer loads and validates:

```text
ACTIVE HistoryGeneration
+ current committed publication
+ current membership
+ ACTIVE LifetimeSegment
+ provider identity contract
+ existing segment binding(s)
+ historical segment/legacy bindings relevant to the same native provider identity
```

### 9.1 Current segment already bound

If the current ACTIVE segment is bound to Artifact A:

```text
candidate A = conclusively SAME
GenerationID = exact generation
LifetimeSegmentID = exact segment
```

The sealed authority may authorize SAME after mutation-boundary revalidation.

### 9.2 Current segment unbound and no prior accepted binding candidate exists

Under the qualified provider-lifetime policy, if the exact candidate universe contains no prior accepted Artifact binding relevant to this native identity:

```text
UniverseCoverage = COMPLETE
Candidates = []
```

This may authorize NEW, meaning:

> allocate the first accepted Artifact identity for this current provider-object lifetime segment under policy.

It does not claim physical creation time.

### 9.3 Current segment unbound but an older/legacy binding exists

A prior segment or legacy naked binding for the same provider-native identity is a plausible predecessor across a broken continuity boundary.

Provider ID equality alone cannot decide it.

Therefore:

```text
do not emit mutation-authorizing COMPLETE/CONCLUSIVE authority
→ remain unresolved/ambiguous
→ require stronger evidence or explicit reconciliation
```

## 10. Acceptance mutation boundary

An `IdentityAuthoritySet` containing generation/segment references can become stale after it is sealed.

Therefore SAME/NEW acceptance MUST, inside the same SQLite mutation transaction:

1. load the sealed authority set;
2. load the exact HistoryGeneration;
3. require generation ACTIVE;
4. require generation ID/scope/provider/identity domain to match;
5. load the exact LifetimeSegment;
6. require segment ACTIVE and owned by that generation/object;
7. require the object still exists in current membership;
8. re-evaluate the current segment binding/conflict state;
9. only then perform Artifact/Revision/Observation decision mutation;
10. atomically create/reconcile the segment→Artifact binding.

If any condition changed, fail closed and require fresh authority.

## 11. SAME and NEW behavior

### SAME

```text
current segment already bound to Artifact A
→ provider lifetime continuity can authorize SAME A
→ changed content may create a new Revision of A
```

If the segment is bound to another Artifact, fail as binding conflict.

### NEW

```text
current segment unbound
+ qualified COMPLETE zero-candidate authority
→ create new Artifact
→ bind current segment to it atomically
```

Replay/idempotency semantics from P0-28A remain unchanged.

## 12. Cross-segment continuity

Neither of these is automatic:

```text
same ProviderObjectID across REMOVED → reappearance
same ProviderObjectID across HistoryGeneration boundary
```

Stronger later evidence may explicitly decide that two segments correspond to the same Artifact.

If accepted, the **new/current segment** receives a binding to that Artifact. Historical segments are not merged or erased; provenance remains intact.

## 13. Implementation order

### P0-28C1 — segment derivation

- schema v10 lifetime-segment table;
- deterministic `LifetimeSegmentID`;
- bootstrap/UPSERT/REMOVED state machine;
- generation-close segment closure;
- rebuild/reconciliation from immutable history;
- repeated changes within one publication;
- migration and reopen tests.

### P0-28C2 — binding and authority integration

- segment-scoped Artifact binding table;
- preserve legacy naked bindings as non-conclusive provenance;
- internal RemoteHistory authority producer;
- stale authority revalidation inside SAME/NEW transaction;
- SAME/NEW atomically create/reconcile lifetime binding;
- previous segment / legacy binding blocks unsafe auto-NEW.

### P0-28C3 — boundary retrospective

Before any live provider wiring:

- direct-SQL immutability/integrity audit;
- interruption/replay audit;
- reconstruction audit;
- cross-generation/reappearance adversarial tests;
- Ubuntu + Windows exact-head qualification.

## 14. Explicitly deferred

P0-28C still does not:

- perform live Google OAuth;
- read or mutate the real Drive corpus;
- infer physical deletion from REMOVED;
- automatically merge cross-generation segments;
- solve cross-provider Artifact continuity;
- make AI inference identity authority.

Only after P0-28C is qualified may the deterministic Google Drive RemoteHistory adapter be wired into this durable identity pipeline.

## 15. P0-28C1 qualification

P0-28C1 segment derivation is **QUALIFIED**.

Exact product head:

```text
e08085239c04906c13c749b14c60d4e8968b5fda
```

GitHub Actions run:

```text
36238911921
```

Results:

- validate — PASS;
- Ubuntu 24.04 — PASS;
- Windows 2025 — PASS.

Qualified schema: v10.

This qualifies deterministic provider-object lifetime-segment derivation and reconstruction verification only. Segment-scoped Artifact binding and RemoteHistory-backed mutation authority remain P0-28C2.

