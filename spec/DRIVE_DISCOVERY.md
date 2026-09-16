# Keelaryn Core — Drive Restart Discovery Contract v1

**Architecture basis:** Zero-Based Architecture r2, `DRIVE_ORCHESTRATION.md`, `DRIVE_BACKEND.md`, `DRIVE_TRANSPORT.md`.  
**Status:** development contract; not a deployment or production-qualification specification.

## 1. Purpose

`DriveCoreRunner` can recover a transaction from an exact immutable `DriveTransactionBundle`, but a real process restart cannot assume that bundle object is still present in process memory.

Drive discovery v1 defines how Core finds the exact active/prepared bundle from Hub state without scanning for a "latest" file, choosing among duplicate names, or trusting local process history.

Discovery does not replace `MASTER.json` as canonical-read authority. Its purpose is only to recover the exact transaction authority needed to interpret or complete Core state transitions.

`DriveRuntime`, not raw `DriveCoreRunner`, is the process-level entrypoint responsible for publishing/discovering this restart locator around orchestration.

## 2. Stable bootstrap input

The service starts with the configured Hub root Drive object ID.

Under that root, structural folders are resolved by exact single-child names. Drive v1 uses:

```text
Keelaryn Hub/
└── control/
    └── active/
        └── ACTIVE_TRANSACTION.json
```

Resolving `control/active` MUST fail closed if a required folder is missing, not a folder, trashed, or duplicated by name under the same parent.

Friendly display names are never identity. The locator itself binds the exact resolved `control/active` parent ID.

## 3. Active locator

At most one live Core-owned object named `ACTIVE_TRANSACTION.json` may exist in `control/active`.

The locator is immutable and self-binding. It binds at minimum:

- schema version;
- its own generated Drive file ID;
- its expected `control/active` parent ID;
- `change_id`;
- exact CHANGE SHA-256;
- base canonical epoch;
- exact transaction bundle Drive file ID;
- exact bundle parent Drive ID;
- exact bundle object name;
- exact bundle SHA-256 and byte length.

The locator is not semantic commit/rollback authority and does not make canonical data safe. It is an immutable restart index to exact transaction authority.

The bundle remains the transaction authority. The locator points to and fingerprints it; the bundle does not need a reverse pointer because locator presence never authorizes canonical mutation by itself.

## 4. Publication order

The exact bundle bytes must exist before locator bytes can bind their hash and length.

Preparation order is:

1. create/verify the exact immutable transaction bundle;
2. generate one locator Drive ID;
3. construct immutable locator bytes containing that self-ID and the exact bundle ID/location/hash/size;
4. create locator at that generated ID in the exact `control/active` folder;
5. re-read locator by exact ID, verify its bytes/self-ID, and verify `ACTIVE_TRANSACTION.json` is unique by name;
6. load and verify the exact bundle through the locator;
7. only then may the process-level runtime invoke activation of ACTIVE/SAFE MASTER.

If locator creation has an uncertain transport result, that call performs no MASTER mutation. On restart, discovery observes `control/active`:

- if the locator exists, its self-ID and exact bundle binding are validated;
- if it does not exist and MASTER is still clean READY, no transaction is considered active.

Core does not silently create another locator as a mutation retry for an uncertain locator-create request.

## 5. Uniqueness and ambiguity

Discovery never selects the newest locator or bundle.

Rules:

- zero locator objects may be valid only when the root MASTER is clean READY;
- exactly one locator is required for ACTIVE, RECOVERY_BLOCKED, or zero-MASTER transition recovery;
- multiple live `ACTIVE_TRANSACTION.json` objects are ambiguity and fail closed;
- locator metadata ID/parent/name and locator self-bound ID/parent must agree exactly;
- locator/bundle transaction identity mismatch is fail closed;
- malformed locator bytes are fail closed;
- locator bundle hash/size mismatch is fail closed.

## 6. Loading an exact bundle

Given one locator, Core:

1. strictly validates locator bytes;
2. verifies locator metadata ID/parent/name equal the self-bound values;
3. fetches the exact bound bundle file ID directly;
4. verifies bundle metadata location/name and exact SHA-256/size;
5. downloads exact bundle bytes;
6. parses `DriveTransactionBundle` with strict cross-component validation;
7. verifies bundle `change_id`, CHANGE hash, base epoch, bundle ID/name/parent and Hub root equal the locator/runtime context;
8. verifies the durable bundle object through `DriveBundleStore`.

No bundle discovered only by a matching name is accepted.

## 7. Discovery with one root MASTER

### 7.1 READY / SAFE and no locator

Return clean READY. There is no active transaction to recover.

### 7.2 READY / SAFE with one valid locator

Load the exact bundle. This may represent either:

- a prepared transaction whose locator was published before activation and whose activation may resume; or
- a stale operational locator left after COMMITTED, ROLLED_BACK or SAFE abort because cleanup crashed after MASTER had already become READY.

Discovery returns the exact bundle and classifies the root through that bundle's MASTER transitions. It does not guess which case applies.

A stale locator under READY is not canonical-read authority and does not make READY data unsafe, but a new transaction MUST NOT activate until the stale locator has been exactly reconciled/archived.

### 7.3 ACTIVE / SAFE or ACTIVE / UNSAFE

Exactly one valid locator is mandatory.

The locator and loaded bundle transaction identity/base epoch MUST equal `MASTER.active_change`. A missing or mismatched locator blocks recovery.

### 7.4 RECOVERY_BLOCKED / UNSAFE

Exactly one valid locator is mandatory and MUST identify the exact blocked transaction. The locator remains active until a separately specified blocked-recovery procedure resolves that transaction.

## 8. Discovery during zero-MASTER gaps

When no root `MASTER.json` is visible, normal readers already fail.

Core recovery may proceed only when:

1. exactly one valid active locator exists;
2. it loads one exact immutable transaction bundle;
3. that bundle's pre-bound MASTER transitions classify the actual Drive objects as one uniquely recoverable transition gap.

If the bundle cannot attribute the gap uniquely, Core performs no mutation.

This locator is what allows restart recovery when process memory is gone and the root MASTER is temporarily absent during a copy-on-write swap.

## 9. Duplicate or unknown root MASTER

If multiple root `MASTER.json` objects exist, discovery does not use a locator to choose one.

If one root object exists but its identity/bytes do not match the states allowed by the discovered bundle, the locator does not authorize repair.

These conditions remain fail closed.

## 10. Locator lifetime and SAFE cleanup

The locator MUST remain exact in `control/active` from before the first activation MASTER mutation through every ACTIVE state, every recoverable MASTER gap, and RECOVERY_BLOCKED.

It MUST NOT be removed before a COMMITTED/ROLLED_BACK/aborted READY MASTER is durably established.

After READY is established, locator cleanup is a separate SAFE maintenance action:

1. rediscover exact locator and bundle;
2. prove the root MASTER deterministically represents COMMITTED, ROLLED_BACK or SAFE-aborted READY for that bundle;
3. freshly revalidate locator and bundle at the cleanup commit boundary;
4. move the exact locator object, preserving its Drive file ID and bytes, to the bundle's durable per-change history under a deterministic archive name;
5. verify `control/active` no longer contains the active locator name.

A lost response after the archive move is safe: canonical bytes and MASTER are already terminal READY. Restart observes either the still-active exact locator and repeats the separately verified cleanup, or clean READY with no active locator.

Automatic retention/deletion policy for durable history remains outside MVP.

## 11. Transport uncertainty

Locator creation/movement follows the same Drive transport rules as other Core mutations:

- caller-selected generated ID for creation;
- no hidden mutation retries;
- timeout/lost response/5xx mutation outcome is `DriveUncertainMutation`;
- transport uncertainty never authorizes selecting a different existing locator or bundle;
- locator cleanup uncertainty cannot change canonical or MASTER state because cleanup begins only after exact terminal READY proof.

## 12. Process-level runtime contract

`DriveRuntime` provides the process-level flow:

### New transaction

1. discover clean READY or the same already-prepared locator;
2. ensure exact immutable bundle;
3. create/verify exact active locator;
4. re-discover locator -> exact bundle under READY;
5. invoke `DriveCoreRunner`.

### Restart

1. resolve `control/active` from Hub root;
2. discover locator/root MASTER state;
3. when a locator exists, load exact bundle from locator;
4. invoke `DriveCoreRunner` only with that discovered exact bundle;
5. preserve locator while ACTIVE, in MASTER gaps, or RECOVERY_BLOCKED.

### Post-terminal cleanup

Cleanup is separate from transaction finalization and is allowed only for an exact COMMITTED, ROLLED_BACK or SAFE-aborted READY classification.

Raw `DriveCoreRunner` remains a low-level deterministic state machine used by tests and internal composition. Runtime restart correctness must not depend on a caller retaining the original Python bundle object.

## 13. Required proof

Before live disposable Drive acceptance, development validation MUST prove:

- strict locator roundtrip, self-ID and location validation;
- exact locator -> bundle ID/location/hash/size validation;
- lost locator-create response recovery without a second locator mutation;
- process loss after locator publication but before activation resumes from Hub state only;
- ACTIVE recovery from locator + bundle with no process-local transaction object;
- RECOVERY_BLOCKED recovery from locator + bundle;
- zero-MASTER gap recovery from locator + bundle only;
- duplicate locator fail-closed;
- malformed/mismatched locator fail-closed;
- missing locator under ACTIVE/RECOVERY_BLOCKED fail-closed;
- unknown/duplicate root MASTER remains fail-closed even with a valid locator;
- READY without locator is clean;
- READY with a valid stale/preactivation locator is classified without arbitrary selection;
- locator cleanup occurs only after exact READY terminal/abort proof;
- lost response during locator archive cleanup recovers to clean READY without changing canonical/Master state.

A green simulator/CI result remains development evidence, not production qualification.
