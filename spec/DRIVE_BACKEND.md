# Keelaryn Core — Google Drive Backend Model v1

**Architecture basis:** Zero-Based Architecture r2 and Core State Machine v1.  
**Status:** development contract for the next backend; not a deployment or release specification.

## 1. Purpose

This document maps the logical Core publication protocol onto Google Drive without assuming POSIX filesystem guarantees that Drive does not provide.

The Drive backend MUST preserve the same logical invariants as the local-filesystem backend:

- exact change identity;
- OLD / NEW / UNKNOWN target classification;
- durable restart recovery;
- SAFE before the first canonical mutation;
- UNSAFE through commit or verified rollback;
- no overwrite of UNKNOWN state;
- semantic FAIL always rolls back;
- epoch increments after every UNSAFE window;
- clean logical READY after completion.

## 2. Supported Drive object type

Protocol v1 manages **Drive blob files only**.

Google Docs, Sheets, Slides, shortcuts and other Google Workspace-native objects are not valid managed canonical targets in Drive backend v1.

Reason: Drive exposes exact byte-oriented metadata for blob files, including size, SHA-256 checksum and head revision identity. Native editor objects do not provide the same byte identity contract.

A future backend revision may define explicit semantics for native editor objects. Core v1 MUST reject them rather than export/import them silently.

## 3. External API facts used by this design

The design relies only on documented Drive API v3 behavior:

- every file has a stable `fileId`;
- blob files expose `size`, `sha256Checksum` and `headRevisionId`;
- `version` is a monotonically increasing server-side version number reflecting every server change;
- `files.create` creates a new object;
- `files.update` can update metadata/content and can add/remove parents;
- `files.copy` creates a separate object;
- folders are Drive file objects and are addressed by file ID;
- the Changes collection can later be used as an optimization/change detector, but is not a commit authority.

Normative references:

- https://developers.google.com/workspace/drive/api/reference/rest/v3/files
- https://developers.google.com/workspace/drive/api/reference/rest/v3/files/create
- https://developers.google.com/workspace/drive/api/reference/rest/v3/files/update
- https://developers.google.com/workspace/drive/api/guides/change-overview
- https://developers.google.com/workspace/drive/api/guides/manage-changes

The documented Drive v3 `files.update` contract does not expose a content compare-and-swap precondition tied to `version`, `headRevisionId` or a checksum. Keelaryn therefore MUST NOT rely on an undocumented `If-Match` behavior for safety.

## 4. Consequence: no in-place canonical content replacement

Drive backend v1 MUST NOT replace the bytes of an existing canonical file in place.

Fresh read → upload-to-same-file has a race window: another writer could change the file after Core's check and before Core's content update. Without a documented conditional write, such an update could overwrite bytes that Core no longer recognizes.

Instead, all publication uses object-preserving copy-on-write semantics:

1. create/stage a new Drive blob with a distinct file ID;
2. verify exact uploaded bytes;
3. keep the existing canonical object intact until UNSAFE;
4. move/rename objects to change which exact file ID occupies the logical canonical path;
5. retain displaced OLD objects rather than destructively overwriting them.

## 5. Hub root binding

A Drive backend instance is configured with an exact **Hub root folder ID**.

The root is not rediscovered globally by name on every run.

All path traversal starts from that folder ID. Each path segment is resolved by listing direct children of the current parent and requiring an exact name match.

For a required path segment:

- exactly one matching non-trashed object of the expected type: continue;
- zero: absent;
- more than one: ambiguity → fail closed.

Drive permits duplicate names. A duplicate logical path is never resolved by picking an arbitrary result.

## 6. Remote object identity

For a managed blob, Core records at least:

```text
file_id
parent_id
name
mime_type
version
head_revision_id
sha256_checksum
size
trashed
```

Logical content fingerprints remain SHA-256 plus exact byte length, matching the backend-neutral Core protocol.

`file_id` is object identity. Name/path is presentation/location identity and can change.

At transaction boundaries Core MUST freshly retrieve object metadata. When exact byte verification is required, Core MUST also download and hash the bytes rather than trusting stale process memory.

## 7. Directory identity

The Drive backend binds the Hub structural folders by file ID during a transaction:

- Hub root;
- canonical;
- work;
- work/reconciliation;
- control;
- history;
- active change/control/history folders involved in the transaction.

A folder moving, disappearing, changing type, or resolving ambiguously is a transaction conflict.

Core MUST NOT recreate a missing canonical parent during an active transaction and then assume it is the same directory.

## 8. Ready-change discovery

Ready discovery is performed under the exact reconciliation changes folder ID.

A change directory is ready only when it contains exactly one valid `READY.json` and exactly one exact `CHANGE.json`, with no path ambiguity.

As in the local backend:

- zero ready changes → idle;
- exactly one → preflight;
- more than one → fail closed without starting a transaction.

Listing is only discovery. Before claim, Core re-fetches the selected objects by exact file IDs and validates their current versions/bytes.

## 9. Claim

Claim copies exact reconciliation inputs into Core-owned control objects.

The control record persists both logical identities and Drive object identities. At minimum it records:

- active change ID/hash/base epoch;
- source CHANGE file ID/version;
- claimed CHANGE file ID/version;
- each source prepared file ID/version;
- each claimed prepared file ID/version;
- bound structural folder IDs.

Claimed blobs are downloaded/rehashed after creation or copy.

## 10. Snapshot

Before UNSAFE, every REPLACE/DELETE target gets an independent exact snapshot object under `history/<change_id>/snapshot/`.

Snapshot verification includes:

- source canonical target still exact OLD;
- snapshot blob SHA-256 and size equal OLD;
- snapshot is under the expected history parent ID;
- snapshot has a distinct file ID from the canonical source.

`HISTORY.json` is published last, as in the filesystem backend.

The snapshot object is the rollback safety copy. The original canonical object is still untouched while MASTER remains SAFE.

## 11. Drive MASTER publication

Drive backend v1 MUST NOT overwrite `MASTER.json` bytes in place.

A logical MASTER replacement is copy-on-write:

1. create and verify a candidate MASTER blob under Core-owned transition state;
2. persist a transition record binding old MASTER file ID/version and new candidate file ID/version;
3. remove the old object's canonical `MASTER.json` name/location without deleting its bytes;
4. move/rename the candidate into the Hub root as `MASTER.json`;
5. verify that the Hub root has exactly one `MASTER.json`, with the expected new bytes;
6. retire the previous Core-owned MASTER object only after the transition is durably recoverable.

During the swap, zero or multiple root `MASTER.json` objects are an invalid read state. Normal readers MUST reject canonical data unless MASTER resolves uniquely and validates.

Core startup has a Drive-specific MASTER-transition recovery path so it can recover a crash that occurred while root MASTER was temporarily absent/ambiguous.

## 12. ENTER_UNSAFE

Immediately before the SAFE → UNSAFE MASTER transition, Core freshly verifies:

- exact claimed change/control identity;
- all staged NEW blobs;
- verified history snapshot blobs;
- every canonical target remains exact OLD by file ID/location/content identity;
- all bound folder IDs and expected parent relationships.

Only after the new UNSAFE MASTER is uniquely visible may canonical publication begin.

## 13. ADD publication

For ADD:

1. logical target must resolve ABSENT;
2. claimed staged NEW blob must still be exact NEW;
3. move/rename the staged object into the canonical parent with the target name;
4. re-resolve the logical target and require exactly that file ID;
5. verify NEW bytes and metadata.

Core never creates two competing canonical objects deliberately.

If an external object appears at the target name during the operation, path ambiguity is UNKNOWN and recovery blocks.

## 14. REPLACE publication

For REPLACE, the old canonical object is preserved.

1. require exactly one canonical target bound to the expected OLD file ID and OLD bytes;
2. move/rename the OLD object out of canonical into `history/<change_id>/original/` using a reserved non-canonical name;
3. verify the OLD file ID still exists there with OLD bytes;
4. move/rename the staged NEW file ID into the canonical parent/name;
5. require exactly one canonical target and require that its file ID is the staged NEW ID;
6. verify NEW bytes.

The original OLD Drive object is not deleted on commit. It becomes durable history. The independent pre-UNSAFE snapshot may later be compacted only by a separately validated history-compaction mechanism; MVP may retain both copies.

A crash between steps is recovered from exact file IDs plus actual parent/name/content state.

## 15. DELETE publication

DELETE is implemented as a non-destructive logical removal:

1. require exact OLD canonical object;
2. move/rename that OLD file ID into `history/<change_id>/original/`;
3. verify exact OLD there;
4. verify the canonical logical target is ABSENT.

The displaced OLD object remains history. Core does not issue a destructive Drive delete for user-originated canonical OLD bytes in normal MVP publication.

## 16. Target classification on Drive

Classification uses both the logical target path and bound object IDs.

`OLD` means the exact OLD identity is in the location appropriate to the current recovery stage and its bytes remain OLD.

`NEW` means the exact NEW identity is in the canonical target location and bytes remain NEW.

`UNKNOWN` includes, but is not limited to:

- duplicate canonical-name objects;
- expected file ID disappeared unexpectedly;
- unexpected file ID occupies the target path;
- checksum/size mismatch;
- version changed in a way that cannot be reconciled with exact bytes/location;
- bound parent folder changed or disappeared;
- object became a shortcut/native editor object;
- object was externally trashed/moved;
- required structural path became ambiguous.

UNKNOWN never triggers automatic overwrite/delete.

## 17. Rollback

Rollback uses exact file IDs and reverses operations.

### REPLACE

- NEW must be exact NEW or already absent from canonical;
- OLD original must still be exact OLD in history/original;
- move NEW out of canonical into Core-owned rejected material;
- move OLD original back to exact canonical parent/name;
- verify one exact OLD target.

### DELETE

- move exact OLD original back from history/original to canonical;
- verify exact OLD target.

### ADD

- remove the exact Core-created NEW object from canonical only if it is still exact NEW;
- if it changed externally, classify UNKNOWN and block instead of deleting it.

The pre-UNSAFE snapshot remains durable history even after rollback.

## 18. Cleanup

Cleanup removes only Core-created temporary objects whose exact file IDs and expected states are known.

User-originated displaced OLD canonical objects are retained in history rather than destructively deleted.

Unexpected or modified temporary objects are not silently deleted. They produce a cleanup conflict and fail closed, matching the filesystem backend principle.

## 19. Polling and change log

MVP wakeup remains polling.

Drive `changes.list` may be used later to reduce list/get traffic or detect external changes, but it is not transaction authority. Every commit/recovery boundary still performs fresh direct reads of the exact relevant file IDs and paths.

## 20. Authentication boundary

Authentication implementation is separate from transaction semantics.

Initial supported deployment may use one Google account with protocol-level role separation, consistent with Architecture r2. Credentials/tokens are VPS secrets and MUST NOT be stored in the Hub or repository.

Separate Drive identity/permission isolation remains a hardening roadmap item.

## 21. Required simulation before live Drive

Before using a real Google Drive folder, implement a deterministic in-memory Drive model supporting:

- immutable file IDs;
- duplicate names;
- parent moves/renames;
- monotonically increasing versions;
- exact blob checksums;
- external edits/moves/trash;
- injected crashes after every remote mutation;
- stale list/read simulation.

Prove the same commit/rollback/fail-closed invariants against that model.

Only after the model passes should the REST transport be connected to a disposable real Drive Hub.

## 22. Live integration boundary

The first live Drive test MUST use a disposable sanitized Hub, never the production Hub.

Minimum live proof:

1. bootstrap disposable Drive layout;
2. ADD/REPLACE/DELETE publication;
3. PASS commit;
4. FAIL rollback;
5. restart recovery after selected remote mutation points;
6. duplicate-name ambiguity;
7. external edit/move conflict;
8. exact READY/SAFE cleanup;
9. no production Hub file IDs or personal canonical data in logs/evidence.
