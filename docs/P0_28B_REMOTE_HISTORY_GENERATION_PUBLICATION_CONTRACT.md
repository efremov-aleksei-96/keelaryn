# P0-28B — Remote History Generation and Publication Contract

**Status:** CONTRACT DECIDED / IMPLEMENTATION NEXT  
**Scope:** provider-neutral durable RemoteHistory authority  
**Live OAuth/provider access:** forbidden in this slice  
**Corpus mutation:** none

## 1. Problem

P0-23/P0-24 already distinguish provider pagination from a terminal committed cursor, but the cursor alone is not enough to become durable identity evidence.

Keelaryn needs a local authority that answers:

- which provider history stream and scope this state belongs to;
- which uninterrupted local history epoch it belongs to;
- which complete publication is the last committed state;
- which provider objects are currently known to be in that stream/scope;
- whether a history gap invalidated further continuity;
- what exact change records produced each committed publication.

This state is identity/membership evidence. It is **not** a full Keelaryn Observation and MUST NOT fabricate absent metadata.

## 2. Reuse basis

### Syncthing BEP delta indexes

Reuse directly:

- random generation/index identity separate from advancing position;
- reset creates a new generation identity;
- a generation plus monotonic position identifies one local history point.

Keelaryn equivalent:

```text
Syncthing Index ID       -> HistoryGenerationID
Syncthing max sequence   -> HistoryPublicationSequence
provider opaque token    -> HistoryCursor (separate; never replaced by sequence)
```

Do not reuse path-centered file identity semantics.

### Google Drive / Microsoft Graph delta

Reuse:

- opaque provider cursor/token;
- intermediate pagination is not committed state;
- terminal token marks a complete round;
- current-state changes may coalesce operations;
- removals/deletions are explicit feed facts with provider-specific meaning.

Do not derive global Artifact identity from a provider token.

### rclone bisync

Reuse:

- last-known-good state;
- interruption must not silently advance trusted state;
- critical uncertainty blocks dependent continuation until recovery/resync.

Do not use bisync as Keelaryn history authority.

## 3. Durable entities

### 3.1 HistoryGeneration

A `HistoryGeneration` is one uninterrupted **local Keelaryn trust epoch** for one exact remote-history scope.

Fields conceptually include:

```text
HistoryGenerationID
ProviderID
IdentityDomain
HistoryStreamID
Scope/Root
ScopePolicyFingerprint
Status
CreatedAt
ClosedAt?
ClosureReason?
CurrentPublicationSequence
CommittedCursor
```

Rules:

- `HistoryGenerationID` is locally generated, stable, opaque and never derived from provider cursor/path/object ID.
- At most one ACTIVE generation exists for one exact configured history scope.
- A complete bootstrap creates the generation and its first committed publication atomically.
- A closed generation is never reopened.
- Rebootstrap after closure creates a new `HistoryGenerationID`.

### 3.2 HistoryPublication

A `HistoryPublication` is one immutable committed history point inside a generation.

Conceptual fields:

```text
HistoryGenerationID
HistoryPublicationSequence
PreviousCursor
CommittedCursor
Kind: BOOTSTRAP | INCREMENTAL
CommittedAt
PublicationFingerprint
```

Rules:

- sequence is strictly monotonic within one generation;
- the bootstrap publication is sequence 1;
- every later publication is previous sequence + 1;
- publication rows are immutable;
- `PublicationFingerprint` protects publication semantics/replay comparison and is never Artifact identity;
- provider cursor remains opaque and separate from local sequence.

### 3.3 RemoteHistory membership

The current membership materialization contains only RemoteHistory facts that the adapter actually supplied:

```text
HistoryGenerationID
ProviderObjectID
Locator(s) if supplied
LastPublicationSequence
```

It does not invent size, MIME, modified time, content digest, Revision or Artifact assignment.

### 3.4 Publication change evidence

Every incremental publication retains immutable provider-object changes sufficient for later object-lifetime derivation:

```text
UPSERT ProviderObjectID + supplied RemoteObjectState
REMOVED ProviderObjectID
```

A bootstrap publication retains the exact complete starting membership.

This retained evidence is required by P0-28C; current membership alone is insufficient to distinguish uninterrupted presence from removal/reappearance.

## 4. Bootstrap publication

A successful bootstrap is one SQLite transaction:

```text
validate exact scope
validate BootstrapResult COMPLETE
require no ACTIVE generation for scope
allocate HistoryGenerationID
create ACTIVE generation
write bootstrap publication sequence=1
write complete current membership
write bootstrap membership evidence
store provider terminal cursor
commit
```

If any step fails, no generation/publication/membership/cursor authority is created.

If the caller loses the success response, recovery first reads the exact scope. Presence of the ACTIVE generation/publication proves the commit; absence proves it did not commit. Do not blindly bootstrap again.

## 5. Incremental publication

A complete change cycle is published using compare-and-swap semantics:

Inputs include the exact:

```text
HistoryGenerationID
expected current publication sequence
expected committed cursor
complete ChangeCycle
```

Inside one transaction:

```text
load ACTIVE generation
require exact scope/generation
require expected sequence == current sequence
require expected cursor == committed cursor
validate CycleComplete
apply UPSERT/REMOVED to current membership
retain immutable change evidence
append next immutable publication
advance sequence
advance committed cursor to terminal NextCursor
commit
```

If cursor/sequence no longer match, fail closed and reconcile the already committed publication. Never apply the same cycle blindly twice.

## 6. Failure semantics

### 6.1 Interruption / transport failure

An interruption before a complete terminal cycle:

- does not update membership;
- does not append a publication;
- does not advance cursor;
- does not close the generation merely because transport failed.

The next attempt starts from the same last committed cursor unless a qualified provider error establishes a history-gap condition.

### 6.2 Trust-breaking history failures

Provider-confirmed:

- GAP;
- INVALID_CURSOR;
- INSUFFICIENT_HISTORY;

close the ACTIVE generation in one transaction.

A provider-reported `SCOPE_MISMATCH` against an otherwise correctly bound generation also closes it. A caller/configuration mismatch detected before the provider read is an input error and performs no generation mutation.

Closing a generation:

- records closure reason/time;
- preserves the last committed publication/cursor/membership as historical evidence;
- forbids further publications in that generation;
- does not imply deletion of any provider object;
- requires a new bootstrap to obtain a new ACTIVE generation.

No failure result may carry partial membership changes or cursor advancement into authority.

## 7. Generation boundary

Evidence does not flow conclusively across generations merely because provider IDs are equal.

```text
Generation G1
  object X present
  ...
  GAP
  CLOSED

Generation G2
  bootstrap
  object X present
```

At P0-28B this proves only:

- G1 observed provider object X;
- history continuity was lost;
- G2 later observed provider object X.

It does **not** prove that both appearances are one uninterrupted provider-object lifetime.

P0-28C introduces object-lifetime segments and provider binding integration.

## 8. Authority layering

RemoteHistory publication is authoritative only for the provider identity/membership/history facts it actually contains.

Required layering:

```text
RemoteHistory generation/publication
→ provider-object membership/history evidence
→ provider metadata/content Observation
→ object-lifetime evidence
→ SAME/NEW authority
→ Artifact/Revision acceptance
```

RemoteHistory MUST NOT directly create full `ObservationRecordInput`, Artifact or Revision records.

## 9. Immutability and transaction rules

- generation identity immutable;
- publication rows immutable;
- publication change/bootstrap evidence immutable;
- closed generation cannot reopen;
- cursor may advance only through an atomic COMPLETE publication;
- sequence and cursor advance together with current membership;
- no provider/corpus writes;
- no live OAuth required for deterministic implementation/qualification.

## 10. Scope fingerprint

Provider cursor validity may depend on more than `HistoryStreamID`.

A versioned `ScopePolicyFingerprint` binds the generation to the semantic history scope/configuration that affects membership/history, such as:

- ProviderID;
- IdentityDomain;
- HistoryStreamID;
- root/drive scope;
- adapter policy version;
- provider-specific membership settings that alter the stream.

Changing those semantics cannot silently reuse an existing generation/cursor. It requires reconciliation and normally a new bootstrap/generation.

The fingerprint is configuration identity, not Artifact identity.

## 11. Implementation target

P0-28B implementation should add SQLite durable authority and deterministic tests for:

1. bootstrap atomically creates generation/publication/membership/cursor;
2. exact reopen preserves authority;
3. complete incremental publication updates membership + cursor atomically;
4. interrupted cycle advances nothing;
5. GAP closes generation without advancing cursor/membership;
6. INVALID_CURSOR closes generation;
7. INSUFFICIENT_HISTORY closes generation;
8. provider-reported scope mismatch closes a correctly bound generation;
9. input scope mismatch changes nothing;
10. closed generation rejects publication;
11. rebootstrap creates a different generation;
12. same provider object across generations does not become SAME authority;
13. publication sequence/cursor stale replay fails closed;
14. publication/change evidence is immutable;
15. history state never fabricates full Observation metadata.

## 12. Explicitly deferred to P0-28C

- object-specific lifetime/presence segments;
- uninterrupted-presence proof;
- `REMOVED -> later UPSERT` lifetime semantics;
- provider Artifact binding scoped to lifetime segment;
- production creation of `IdentityAuthoritySet` from provider history;
- live SAME/NEW acceptance from remote provider evidence.

