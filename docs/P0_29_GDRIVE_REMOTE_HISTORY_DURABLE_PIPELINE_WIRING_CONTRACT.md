# P0-29 — Google Drive RemoteHistory durable pipeline wiring contract

**Status:** CONTRACT DECIDED / IMPLEMENTATION NEXT  
**Scope:** provider-specific Google Drive wiring into the already-qualified provider-neutral RemoteHistory/lifetime/identity pipeline  
**Live OAuth:** forbidden in this slice  
**Real Drive corpus reads/writes:** forbidden in this slice  
**Corpus mutation:** none

## 1. Goal

P0-28 qualified the provider-neutral durable mechanics:

```text
Adapter bootstrap/change semantics
→ HistoryGeneration
→ immutable publications
→ ProviderObjectLifetimeSegment
→ segment-scoped Artifact binding
→ sealed RemoteHistory authority
→ SAME/NEW mutation-boundary revalidation
```

P0-29 connects the already-existing deterministic Google Drive adapter to that durable pipeline without yet touching a real Google account.

The goal is not merely to call the adapter from the Store. The wiring must preserve the exact provider history boundary that Google actually guarantees.

## 2. Audit finding — provider change-stream scope and managed corpus root are different concepts

Google Drive exposes change logs at provider-defined boundaries:

- one **user / My Drive** change log;
- one change log per **shared drive**.

It does not expose a native change log for an arbitrary descendant folder.

Therefore Keelaryn MUST distinguish:

```text
ProviderHistoryUniverse
!=
ManagedCorpusMembership
```

### ProviderHistoryUniverse

The provider-defined universe inside which one cursor/generation has continuous meaning.

For Google Drive:

```text
MY_DRIVE_UNIVERSE
    authenticated user identity domain
    + canonical My Drive root file ID
    + user change log restricted to My Drive hierarchy

SHARED_DRIVE_UNIVERSE
    shared-drive identity domain
    + shared drive ID
    + that shared drive's change log
```

This is the scope of:

- HistoryGeneration;
- provider cursor;
- immutable publications;
- provider-object lifetime segments.

### ManagedCorpusMembership

The user's selected corpus root, for example a folder such as:

```text
My Drive / 0
```

Membership under that folder is a separate derived view.

Moving the same Google Drive object:

```text
inside managed root
→ outside managed root
→ back inside managed root
```

does not by itself break provider-object lifetime continuity if the whole transition remains continuously visible in the same Google change-log universe.

This separation is necessary for correct corpus-first identity.

## 3. Canonical Google Drive root identity

Google documents `root` as an API alias usable where a file ID is accepted.

The alias is not sufficient durable identity for parent-graph reasoning because file `parents[]` contains actual parent file IDs.

Therefore:

### My Drive

Before creating a durable history scope, the Google binding resolves:

```text
files.get("root", fields="id")
→ CanonicalMyDriveRootFileID
```

The durable Google Drive history scope stores/uses the canonical returned file ID, not the literal alias `root`.

A synthetic test fixture that uses `parents:["root"]` is not accepted as evidence of live correctness.

### Shared drive

The history-universe root is the shared drive ID itself.

No folder alias is substituted for durable shared-drive identity.

## 4. Meaning of RemoteHistory Scope.Root for Google Drive

For P0-29, Google Drive `remotehistory.Scope.Root` means:

> canonical root identity of the provider **history universe**, not an arbitrary managed corpus subfolder.

Thus:

```text
My Drive:
Scope.Root = canonical My Drive root file ID

Shared drive:
Scope.Root = shared drive ID
```

An arbitrary managed subfolder is represented by a separate corpus-membership scope/projection.

This contract clarifies the field's Google Drive meaning without changing provider-neutral Core semantics for other adapters.

## 5. Why the current adapter cannot safely represent arbitrary managed subtrees yet

The existing bootstrap code can compute reachability from a folder because the full file enumeration contains parent IDs.

However incremental `changes.list` is not a folder-subtree feed.

The current durable `RemoteObjectState` retains identity/locator state but does not preserve the parent graph needed to recompute arbitrary managed-root membership after moves.

Therefore P0-29 MUST NOT claim arbitrary-subtree incremental correctness merely by applying:

```text
DriveID == ""
```

to My Drive changes.

Correct arbitrary-root membership requires a separate rebuildable Drive topology projection.

## 6. Google Drive topology/membership projection

A later P0-29 sub-slice introduces provider-specific rebuildable state sufficient to answer:

```text
is ProviderObject X currently under ManagedRoot R?
```

Minimum retained Google topology evidence is expected to include:

- file ID;
- parent file ID(s) as returned by the API;
- Drive ID / My Drive universe identity;
- removed/unavailable/current-state marker;
- folder/file structural role where needed;
- shortcut target only as relation metadata, never as shortcut identity.

The exact SQLite schema is deferred to implementation design.

The projection is:

- durable for query efficiency;
- rebuildable from provider bootstrap/current-state evidence plus ordered changes;
- not Artifact identity;
- not a second content store.

## 7. Bootstrap contract

For one canonical Google history universe:

```text
resolve canonical universe identity
→ obtain start page-token fence
→ enumerate current provider universe
→ replay changes from fence
→ reach terminal newStartPageToken
→ only then publish one complete HistoryGeneration bootstrap
```

No durable generation/cursor is published if the provider read is interrupted before terminal completion.

For My Drive enumeration, reachability is anchored at the **canonical actual My Drive root ID**, not the alias string.

## 8. Incremental change contract

Google documents change entries as current state, not an operation log.

Keelaryn preserves provider order and folds all pages until terminal state:

```text
committed cursor
→ nextPageToken ...
→ terminal newStartPageToken
→ atomic publication + cursor advance
```

Intermediate tokens never become the durable committed cursor.

If an item appears multiple times before the terminal page, ordered processing determines the final current state; Keelaryn does not invent intermediate rename/edit operations beyond retained provider evidence.

## 9. Removal semantics

Google `removed` means removed from that change list, for example by deletion or loss of access. A move between corpora can also create removal semantics.

Therefore P0-29 retains the already-qualified meaning:

```text
REMOVED_FROM_SCOPE
!=
PROVEN_PHYSICAL_DELETION
```

For a move from My Drive to a shared drive:

- the My Drive universe may end its presence;
- the shared-drive universe becomes the relevant change stream;
- continuity across those two provider-history universes is not automatically inferred.

## 10. Page-token and failure taxonomy

Google Drive v3 documents `startPageToken`, `nextPageToken`, and `newStartPageToken` as non-expiring.

Therefore the official Google client MUST NOT map arbitrary HTTP/API failures to a normal `INVALID_CURSOR` or `GAP` lifecycle merely because a request failed.

### No durable history mutation

These classes remain ordinary operation failure unless stronger provider evidence says otherwise:

- cancellation/interruption;
- authentication failure;
- authorization failure;
- rate limiting;
- transient network failure;
- provider 5xx/service failure;
- malformed/unexpected API response.

They do not advance cursor, close generation, or publish membership.

### Trust-break state

A HistoryGeneration closes/rebootstraps only when Keelaryn has explicit semantic evidence that the existing history contract is no longer valid, such as:

- exact configured history universe no longer matches;
- provider explicitly reports history coverage cannot continue;
- future provider/API behavior gives a documented cursor/history invalidation signal.

The existing provider-neutral GAP/INVALID_CURSOR states remain valid abstractions for providers that actually have those semantics; Google Drive HTTP errors are not automatically classified that way.

## 11. Durable orchestrator boundary

P0-29 adds provider-neutral orchestration around the qualified adapter/store APIs.

Conceptual bootstrap turn:

```text
read authoritative durable prestate
→ adapter.Bootstrap(history universe)
→ validate COMPLETE result
→ one atomic StartRemoteHistoryGeneration write
→ read-only verify
```

Conceptual incremental turn:

```text
load exact ACTIVE generation + committed cursor
→ ConsumeChanges(adapter, committed cursor)
→ if COMPLETE:
       one atomic PublishRemoteHistoryCycle
  if explicit trust break:
       one atomic CloseRemoteHistoryGeneration
  if interruption/ordinary provider error:
       no durable mutation
→ read-only verify
```

The orchestrator never publishes partial pages.

## 12. Interruption and replay

After timeout/transport loss:

1. reload the exact HistoryGeneration from SQLite;
2. inspect committed sequence/cursor/status;
3. determine whether the previous write committed;
4. continue only from the first uncommitted boundary.

The expected-sequence + expected-cursor compare-and-swap remains the final durable replay guard.

No external provider retry is allowed to imply a second durable publication automatically.

## 13. Identity authority remains demand-driven

P0-29 wiring does not automatically create an Artifact or a full Observation for every Drive change.

RemoteHistory maintains broad lightweight provider knowledge.

When an identity mutation is actually required:

```text
current history membership
+ active lifetime segment
+ current binding state
→ CreateRemoteHistoryIdentityAuthority
→ final SAME/NEW transaction revalidation
```

This preserves the corpus-wide observation/cache direction without fabricating expensive or unsupported observations.

## 14. Implementation order

### P0-29A — Google history-universe identity hardening

- resolve My Drive `root` alias to canonical actual root file ID;
- make deterministic tests use real-ID parent semantics;
- formalize My Drive vs shared-drive universe identity;
- preserve raw/transient API failures as non-mutating errors;
- no live OAuth.

### P0-29B — durable orchestration wiring

- internal bootstrap orchestration;
- internal incremental orchestration;
- deterministic fake adapter/client;
- complete/gap/interruption/replay tests;
- no real provider calls.

### P0-29C — managed-root topology/membership projection

- retain/rebuild Google parent topology needed for arbitrary managed folder roots;
- derive current corpus membership independently from provider lifetime;
- test move out / move in / ancestor move / removal / shared-drive boundary cases;
- do not create a second content store.

### P0-29D — boundary retrospective

Before live Google account access:

- SQLite/durable-state audit;
- provider error-taxonomy audit;
- subtree/topology adversarial audit;
- interruption/replay audit;
- Ubuntu + Windows exact-head qualification.

Only after P0-29D PASS may a separate live-provider qualification be considered.

## 15. Qualification matrix

At minimum P0-29 must prove:

1. literal `root` alias is never persisted as canonical My Drive parent identity;
2. canonical My Drive root ID is stable inside one configured history universe;
3. shared-drive history uses drive ID and the shared-drive change log;
4. arbitrary managed subfolder is not misrepresented as a native Google change-log scope;
5. bootstrap fence/enumeration/catch-up commits only at terminal cursor;
6. multi-page incremental cycle publishes once;
7. interrupted cycle publishes nothing;
8. transient/auth/rate/service errors do not close generation or advance cursor;
9. explicit provider trust break closes generation fail-closed;
10. post-write ambiguity reconciles before retry;
11. topology projection can rebuild managed-root membership;
12. move outside managed root does not automatically destroy provider lifetime continuity within the same history universe;
13. move into another provider history universe does not automatically prove continuity;
14. all earlier P0-28 identity/lifetime invariants remain green;
15. Ubuntu 24.04 and Windows 2025 pass.

## 16. Explicitly deferred

P0-29 contract does not authorize:

- live OAuth;
- reading the maintainer's real Google Drive;
- writing/moving/deleting Drive content;
- corpus normalization;
- automatic cross-universe Artifact continuity;
- background deep extraction.

Those remain separate qualification/authorization boundaries.

## 17. P0-29A qualification

Google history-universe identity hardening is **QUALIFIED**.

Exact head: `23d8f1b476729e17ca92f1884cd340acd93e644d`  
CI run: `36245721536`

- validate — PASS;
- Ubuntu 24.04 — PASS;
- Windows 2025 — PASS.

Qualified behavior:

- My Drive `root` alias is resolved through `files.get("root")` to the canonical actual root file ID before durable adapter construction;
- literal alias `root` is rejected as durable history scope;
- shared-drive history uses the drive ID as universe root;
- bootstrap fixtures use actual parent ID semantics;
- ordinary HTTP/API failures (401/403/404/429/5xx) remain non-mutating operation errors and are not silently classified as history GAP/INVALID_CURSOR.

No live OAuth/provider access or corpus mutation occurred.

