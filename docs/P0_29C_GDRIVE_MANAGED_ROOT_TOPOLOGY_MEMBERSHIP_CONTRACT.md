# P0-29C — Google Drive managed-root topology and membership projection

**Status:** CONTRACT DECIDED / IMPLEMENTATION NEXT  
**Depends on:** qualified P0-29A canonical history-universe identity + qualified P0-29B durable coordinator  
**Live OAuth/provider access:** forbidden  
**Corpus mutation:** none

## 1. Purpose

Google Drive RemoteHistory is intentionally scoped to a provider-native history universe:

- one My Drive user change log, or
- one shared-drive change log.

The user's managed corpus can be a descendant folder inside that universe, for example:

```text
My Drive
└── 0
    ├── 1__Inbox
    ├── 2__Project
    └── ...
```

P0-29C defines rebuildable Google Drive topology state that can answer:

```text
Is provider object X currently under managed root R?
```

without conflating managed-root membership with provider-object lifetime.

## 2. Fundamental separation

Three identities/scopes remain distinct:

```text
Provider history universe
    cursor / HistoryGeneration / lifetime continuity

Managed corpus root
    user-selected subtree membership

Artifact identity
    Keelaryn durable content identity
```

None may substitute for another.

A move outside a managed subtree inside the same Google history universe changes membership but does not automatically end the provider-object lifetime segment.

## 3. Google parent topology

For Google Drive v3, topology is represented by provider object IDs and parent IDs.

Keelaryn stores a rebuildable projection sufficient to derive ancestry.

Conceptual node state:

```text
HistoryGenerationID
ProviderObjectID
ParentObjectID?
DriveID?
PresentInHistoryUniverse
LastPublicationSequence
LastChangeOrdinal?
TopologyEvidenceKind
```

The exact SQLite column layout is implementation detail.

Rules:

- provider object ID is the node key inside one HistoryGeneration;
- parent identity is a provider object ID, never a display path;
- My Drive canonical root ID is the topological root for that history universe;
- shared-drive top-level identity is the shared drive ID/history-universe root;
- names/paths are not required for membership derivation;
- shortcuts remain independent provider objects; shortcut targets are relations, not parent substitution.

## 4. Projection authority

The topology projection is durable for efficiency but rebuildable.

Primary evidence remains:

- bootstrap provider current-state evidence;
- immutable RemoteHistory publications/change ordering;
- canonical provider scope.

The topology projection MUST NOT become independent identity authority.

Loss of topology projection must be recoverable by rebuilding from retained provider evidence where that evidence is sufficient, or by a fresh provider bootstrap when the retained evidence is intentionally insufficient.

## 5. Publication watermark

Every topology projection state is tied to an exact RemoteHistory publication boundary.

Conceptually:

```text
TopologyWatermark =
    HistoryGenerationID
    + PublicationSequence
```

Membership queries MUST NOT silently use topology that is behind or ahead of the caller-required history state.

If topology cannot prove exact alignment with the requested history generation/sequence, membership is:

```text
UNKNOWN
```

rather than guessed IN or OUT.

## 6. Membership result

Managed-root membership is three-valued:

```text
IN
OUT
UNKNOWN
```

### IN

There is a complete parent chain:

```text
object
→ ...
→ managed root
```

within the same compatible history universe.

### OUT

There is a complete parent chain proving the object terminates at the canonical provider root or another known boundary without reaching managed root.

### UNKNOWN

Used whenever proof is incomplete or contradictory, including:

- missing parent state;
- inaccessible parent;
- projection/history watermark mismatch;
- parent cycle;
- object/history-universe mismatch;
- topology corruption;
- ambiguous provider response;
- unsupported boundary transition.

UNKNOWN is first-class and MUST NOT be treated as OUT.

## 7. Managed root identity

A ManagedRootBinding is conceptually:

```text
ProviderID
IdentityDomain
HistoryUniverseRoot
ManagedRootObjectID
```

Requirements:

- ManagedRootObjectID must exist in the same Google history universe;
- managed root may equal history-universe root;
- display name/path is metadata only;
- moving or renaming managed root does not change its identity if provider object continuity is preserved;
- if the managed-root provider object itself leaves the history universe or its continuity is lost, membership becomes UNKNOWN until the root binding is explicitly reconciled.

## 8. Ordered topology application

Topology changes are applied in the exact RemoteHistory order:

```text
publication sequence
→ change ordinal
```

For an UPSERT:

- update/create current topology node from current provider state;
- parent change is a topology mutation, not provider-object re-identification;
- last topology evidence position advances.

For REMOVED_FROM_SCOPE:

- current topology node becomes unavailable/not present in that history universe;
- do not infer physical deletion;
- descendants are not eagerly rewritten merely because an ancestor changed.

The topology projection SHOULD preserve enough evidence to distinguish unknown ancestry from proven outside membership.

## 9. Ancestor moves

Moving a folder changes that folder's parent relation.

Keelaryn MUST NOT require synthetic change events for every descendant.

Example:

```text
Before:
R
└── A
    └── B
        └── file X

After moving A outside R:
Other
└── A
    └── B
        └── file X
```

Only A may receive the relevant parent-state update.

Membership for B and X changes from IN to OUT because ancestry is evaluated through the current topology graph.

This is why materializing a permanent boolean `in_managed_root` per descendant is insufficient unless it is explicitly invalidated/recomputed transitively.

## 10. Move out / move in semantics

Within the same HistoryGeneration:

```text
X IN managed root
→ X OUT managed root
→ X IN managed root
```

does not mint a new ProviderLifetimeSegment solely because membership changed.

Provider lifetime is determined by provider-history continuity, not managed-root reachability.

If the provider change stream itself emits REMOVED and later UPSERT, existing P0-28 segment rules still apply.

## 11. Cross-history-universe move

A move between My Drive and a shared drive changes the relevant native Google change-log universe.

P0-29C MUST NOT automatically join the two lifetimes.

The topology projection may record the observed boundary transition, but Artifact continuity across history universes requires separate stronger evidence and remains deferred.

Google documents that moves between corpora can appear as removal from one change log while the file continues to exist elsewhere. This is not physical deletion.

## 12. Missing-parent semantics

Google may omit parent information where the caller cannot access the parent.

Therefore:

- missing parent does not mean provider root;
- missing parent does not prove OUT;
- inaccessible ancestor produces UNKNOWN membership.

A topology query MUST distinguish:

```text
known root termination
vs
missing/unknown parent
```

## 13. Cycle/corruption defense

Provider topology is expected to be acyclic, but Keelaryn must fail closed.

Ancestor traversal MUST have:

- visited-node detection;
- deterministic maximum traversal bound;
- generation/scope checks on every node.

A detected cycle or impossible self-parent results in UNKNOWN and a validation/audit signal.

It MUST NOT hang.

## 14. Bootstrap integration

P0-29C topology bootstrap must be derived from the same fenced enumeration/catch-up window as RemoteHistory bootstrap.

Conceptually:

```text
start-page-token fence
→ enumerate provider universe with parent evidence
→ catch up ordered changes
→ terminal cursor
→ publish RemoteHistory bootstrap
→ topology state at the same generation/sequence watermark
```

The implementation must define an atomic or explicitly reconciled boundary so the system cannot claim topology sequence N while RemoteHistory durably remains at N-1, or vice versa.

This exact transaction shape is deferred to implementation design, but stale topology MUST fail closed.

## 15. Incremental integration

A complete provider cycle may contain multiple parent changes for the same object.

The final topology projection after the cycle is obtained by ordered folding.

Only terminal completed cycles may advance topology watermark.

If provider reading is interrupted:

```text
RemoteHistory unchanged
Topology unchanged
```

If durable RemoteHistory publication succeeds but post-write response is lost, retry begins with authoritative reconciliation before any topology mutation retry.

P0-29C implementation should prefer one atomic SQLite transaction for history publication + topology projection when practical.

## 16. Rebuild verification

P0-29C must provide deterministic verification that materialized topology agrees with its retained source evidence.

At minimum:

```text
rederive expected current parent/presence state
→ compare to materialized topology
→ fail on drift
```

A mismatched topology projection cannot be used for membership decisions.

## 17. Query API

Conceptually:

```text
ManagedRootMembership(
    generationID,
    publicationSequence,
    managedRootObjectID,
    providerObjectID
) -> IN | OUT | UNKNOWN
```

The API returns evidence metadata sufficient to explain the answer, including:

- generation;
- publication sequence;
- managed root ID;
- queried object ID;
- terminal ancestor/root when known;
- reason for UNKNOWN.

This remains provider-specific/rebuildable knowledge, not accepted Artifact fact.

## 18. SQLite trust boundary

The implementation should enforce where practical:

- topology node key scoped by HistoryGeneration;
- exact publication watermark monotonicity;
- parent/self-parent sanity;
- generation/scope consistency;
- no topology watermark beyond current durable history sequence;
- no direct mutation that fabricates future topology state;
- managed-root bindings reference the same compatible history universe.

Direct-SQL tamper tests are required for authority-bearing/watermark invariants.

## 19. Prior-art alignment

### Google Drive

Official Drive documentation confirms:

- user and shared drives have separate change logs;
- change entries represent current state;
- deletion/removal may mean loss of access or corpus move rather than physical deletion;
- parent/permission changes do not imply synthetic events for every descendant.

### Microsoft Graph delta

Graph independently warns that a parent folder rename does not cause descendants to be returned by delta and clients should track items by ID.

Reuse:

- maintain topology by stable IDs;
- recompute descendant reachability from current ancestor state;
- do not expect transitive descendant events.

## 20. Implementation slices

### P0-29C1 — topology domain + schema

- topology node model;
- managed-root binding model;
- membership enum;
- schema migration;
- direct validation/tamper tests.

### P0-29C2 — bootstrap/incremental projection

- feed parent evidence from Google adapter;
- atomically or reconcilably align topology watermark with RemoteHistory publication;
- ordered parent updates/removals;
- rebuild verification.

### P0-29C3 — membership query

- IN/OUT/UNKNOWN ancestor traversal;
- cycle/missing-parent/watermark defenses;
- move-out/move-in/ancestor-move tests;
- shared-drive boundary tests.

### P0-29D — mandatory retrospective

No live Google account access before C1-C3 qualification plus P0-29D retrospective PASS.

## 21. Qualification matrix

P0-29C must prove at least:

1. direct child of managed root => IN;
2. deep descendant => IN;
3. complete chain to provider root without managed root => OUT;
4. missing/inaccessible parent => UNKNOWN;
5. stale topology watermark => UNKNOWN/fail-closed;
6. parent cycle => UNKNOWN without hang;
7. self-parent => validation failure/UNKNOWN;
8. moving ancestor outside changes descendant membership without descendant change event;
9. moving ancestor back inside restores descendant IN;
10. managed-root rename/move with same provider identity preserves root binding when still in same history universe;
11. provider-object lifetime segment is unchanged by managed-root membership change alone;
12. REMOVED_FROM_SCOPE remains non-deletion evidence;
13. cross-history-universe move does not auto-join lifetime;
14. interrupted provider cycle advances neither history nor topology;
15. materialized topology drift is detected by rebuild verification;
16. exact publication watermark is durable across reopen;
17. prior P0-28/P0-29A/B tests remain green;
18. Ubuntu 24.04 + Windows 2025 pass.

## 22. Deferred

Not authorized by this contract:

- live OAuth;
- real Drive corpus enumeration;
- Drive writes/moves/deletes;
- automatic cross-universe Artifact continuity;
- semantic classification/extraction;
- physical corpus normalization.

## 23. P0-29C1 qualification

Topology domain/schema boundary is **QUALIFIED** through schema v16.

Exact head: `eefb0b847a61588d152626b34d04b915f4a0f761`  
CI run: `36247476074`

- validate — PASS;
- Ubuntu 24.04 — PASS;
- Windows 2025 — PASS.

Qualified properties:

- immutable provider-specific topology evidence is bound to exact RemoteHistory bootstrap/change evidence;
- current topology nodes are rebuildable projections and require matching evidence;
- topology watermark cannot publish until evidence coverage and current projection are complete;
- projection cannot mutate while watermark is active;
- safe rebuild/update protocol is `remove watermark → mutate projection → restore validated watermark` inside one SQLite transaction;
- managed-root bindings are immutable and scoped to the exact history generation.

No live provider access or corpus mutation occurred.

## 24. P0-29C2A qualification

The Google Drive topology-aware adapter bundle is **QUALIFIED**.

Exact product head:

```text
e9c268bca420121c2a1d2392a2d1b015e84d9257
```

GitHub Actions run `36249098269`:

- validate — PASS;
- Ubuntu 24.04 — PASS;
- Windows 2025 — PASS.

The adapter preserves exact provider order across multi-page cycles, including repeated states of the same provider object. `PageMore` explicitly continues to the next page; multiple-parent responses fail closed. Existing generic adapter methods are wrappers over the same topology-aware path.

No live OAuth/provider access or corpus mutation occurred.

## 25. P0-29C2B qualification

Atomic Store-side topology projection is **QUALIFIED** on exact product head:

```text
bbc67bdafe7b224cee0c850c1e97c2175c3c45f3
```

GitHub Actions run `36250152140`:

- validate — PASS;
- Ubuntu 24.04 — PASS;
- Windows 2025 — PASS.

Google bootstrap and incremental publication now commit provider-neutral RemoteHistory state, immutable Google topology evidence, current topology projection and exact topology watermark inside the same SQLite transaction. Injected topology failure proves full transaction rollback.

A remaining wiring boundary is explicit: the generic provider-neutral coordinator consumes only generic history pages. P0-29C2C must route Google through topology-aware bundles and prevent a generic history-only publish from advancing an already topology-managed generation.

No live OAuth/provider access or corpus mutation occurred.

## 26. P0-29C2C qualification

The final Google topology orchestration boundary is **QUALIFIED**.

Exact product head:

```text
7611b85da8af78cfdb77d166f65ec622204ccfc5
```

GitHub Actions run `36251318219`:

- validate — PASS;
- Ubuntu 24.04 — PASS;
- Windows 2025 — PASS.

Google now uses a topology-aware coordinator from provider read through atomic Store publication. The generic coordinator remains valid for history-only providers, while a generation that already owns a Google topology watermark cannot be advanced through the generic history-only publication path.

The shared exact-prestate reconciler guarantees stale caller prestate returns before any provider read. Explicit provider trust-break closes the generation without advancing sequence/cursor.

No live OAuth/provider access or corpus mutation occurred.

## 27. P0-29D pre-qualification retrospective

C3 implementation CI passed on head `b04d321989a379ea54594d1a2323d99ac4b19f23`, but C3 is **NOT QUALIFIED**.

The retrospective found two lifetime/incarnation blockers: stale managed-root binding after native-ID reincarnation, and stale parent edge after parent native-ID reincarnation.

No schema migration is required. Existing lifetime-segment start positions, topology evidence positions and managed-root bound_sequence are sufficient to fail closed.

Detailed findings: docs/P0_29D_BOUNDARY_RETROSPECTIVE_20260926.md.
