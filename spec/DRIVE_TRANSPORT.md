# Keelaryn Core — Google Drive Transport Contract v1

**Architecture basis:** `docs/ZERO_BASED_ARCHITECTURE.md` r2, `spec/STATE_MACHINE.md`, and `spec/DRIVE_BACKEND.md`.  
**Status:** development contract; not a release, deployment, credential, or production-Hub specification.

This document refines the object-level Drive design into the transport contract used by Core. It does not authorize live production Drive access.

## 1. Backend boundary

Drive transaction logic depends on a backend-neutral object interface, not on the in-memory simulator and not directly on HTTP.

The backend exposes exact object metadata separately from blob content:

- metadata reads: file ID, parent ID, name, MIME type, version, trashed state, size, SHA-256 checksum and head revision ID;
- content reads: exact blob bytes through an explicit download operation;
- object mutations: create, copy, move/rename, trash and exact deletion of a known object.

The transaction layer MUST NOT depend on simulator-only fields, stale-memory state, process-local progress counters, or embedded blob bytes inside metadata objects.

## 2. Pre-generated IDs are mandatory for Core-created objects

Google Drive API v3 can pre-generate file IDs and permits those IDs to be supplied to subsequent `files.create` and `files.copy` operations for supported object types.

Keelaryn uses this as the primary creation-idempotency primitive.

Before creating or copying any Core-owned Drive object, Core MUST:

1. obtain an exact Drive file ID through `files.generateIds`;
2. durably bind that reserved ID to the transaction/control state before the mutation can become recovery-relevant;
3. issue `files.create` or `files.copy` using that exact ID;
4. verify the resulting object by direct `files.get(fileId)` plus exact metadata/content verification where required.

A retry with an already-created reserved ID may return HTTP `409`. Core MUST treat this as a collision requiring direct observation of that exact ID, never as permission to allocate a replacement ID silently.

Names are not creation identities. Duplicate Drive names remain legal and are never used as a substitute for a known file ID when an ID is available.

## 3. No hidden mutation retry

The HTTP transport performs one network attempt per mutation call.

It MUST NOT internally retry:

- create;
- copy;
- move/rename;
- trash;
- delete;
- any future content-changing request.

Reason: a connection loss, timeout, HTTP 408/429, or server 5xx may occur after the server has accepted or applied a mutation but before Core has an authoritative response.

Automatic retry below Core could therefore duplicate or reorder state changes.

Recovery instead re-observes exact known object IDs and actual parent/name/content state, then applies the deterministic state machine.

## 4. Failure taxonomy

The backend distinguishes at least:

- `DriveNotFound`: an authoritative observation that the exact requested live object is absent;
- `DriveAlreadyExists`: reserved-ID creation collided with an existing object;
- `DriveTransportError`: a read/definite request failure that is not a valid state observation;
- `DriveUncertainMutation`: a mutation may have reached Drive but its outcome is not authoritatively known.

Transaction classification MUST only convert `DriveNotFound` into absence.

A timeout, authorization problem, malformed API response or other transport failure MUST NOT be reclassified as `ABSENT`, `OLD`, `NEW`, or any other canonical state.

## 5. Metadata parsing

The REST adapter requests and validates the metadata required by the Drive protocol:

```text
id
name
mimeType
parents
version
trashed
size
sha256Checksum
headRevisionId
```

Protocol v1 permits at most one parent for a managed object.

Unexpected multiple parents, malformed numeric fields, malformed checksums, response-ID mismatch or invalid boolean/type data fail closed.

Google Workspace-native editor objects are not valid managed canonical blob targets in Drive backend v1.

## 6. Listing and path resolution

Logical child discovery uses `files.list` constrained by the exact parent ID and, where applicable, exact name.

The adapter:

- handles pagination completely;
- escapes Drive query literals;
- includes Shared Drive-compatible request flags;
- never chooses arbitrarily between duplicate names.

Zero matches means absent only where the caller's protocol permits absence. More than one exact logical-name match is ambiguity and fails closed.

## 7. Blob creation

Blob creation uses one multipart upload containing metadata and exact bytes.

The metadata includes:

- pre-generated `id`;
- exact `name`;
- exact parent ID;
- non-Google-native blob MIME type.

After an authoritative success response, the returned ID must equal the reserved ID. Exact byte verification remains a separate higher-level requirement at transaction boundaries.

## 8. Copy

`files.copy` is permitted only for live blob objects whose byte-oriented metadata is available.

The destination uses a pre-generated exact file ID and explicit destination parent/name.

A copy response with a different ID is invalid.

## 9. Move and rename

Move/rename operates on a known file ID.

Before mutation the adapter freshly retrieves the object's current parent/name. If the desired location already matches, the operation is an idempotent no-op.

Otherwise `files.update` changes the name and, when needed, uses `addParents`/`removeParents` to move the exact known object.

If the response is lost, recovery reads the same exact file ID and classifies its actual location.

## 10. In-place content replacement is forbidden

The Drive REST backend v1 intentionally does not implement in-place blob content replacement.

Canonical REPLACE continues to use copy-on-write object choreography from `spec/DRIVE_BACKEND.md`:

- preserve OLD object identity;
- publish a distinct staged NEW object;
- move objects between canonical/history/rejected locations;
- never overwrite unknown canonical bytes in place.

## 11. Download

Exact blob bytes are downloaded through `files.get` with `alt=media`.

Metadata and content are separate observations. Where an exact transaction boundary requires byte proof, Core MUST download and hash the bytes rather than relying only on a previously cached metadata object.

## 12. Authentication

Credentials and OAuth refresh policy are outside transaction semantics.

The transport receives an access token or token provider and sends it only as the bearer authorization header.

Tokens, refresh tokens and client secrets MUST NOT be stored in:

- the Hub;
- `CHANGE.json` / `CONTROL.json` / history;
- Git source;
- test fixtures;
- qualification evidence.

A token-provider failure is a transport failure, never a canonical-state observation.

## 13. HTTP implementation constraints

The reference adapter uses no automatic request retry.

For mutations:

- connection/timeout failure → uncertain mutation;
- HTTP 408/429/5xx → uncertain mutation;
- reserved-ID HTTP 409 during create/copy → explicit already-exists condition;
- other authoritative 4xx → transport/protocol failure according to the operation.

For reads, connection/timeout/5xx errors remain transport failures and MUST NOT be converted to absence.

## 14. Required test progression

Before any live Drive Hub test, all of the following must pass against disposable deterministic infrastructure:

1. backend-neutral transaction tests;
2. reserved-ID creation tests;
3. REST request-shape tests;
4. pagination/query escaping tests;
5. typed read-failure tests;
6. uncertain-mutation tests;
7. stateful REST-adapter + Drive-model crash/recovery tests;
8. multi-operation commit and rollback recovery through the REST adapter.

Only after those pass may a disposable sanitized real Drive Hub be used.

Production Hub access remains explicitly out of scope until a later production-specific acceptance stage.
