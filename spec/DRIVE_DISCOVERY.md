# Keelaryn Core — Drive Restart Discovery Contract v1

**Architecture basis:** Zero-Based Architecture r2, `DRIVE_ORCHESTRATION.md`, `DRIVE_BACKEND.md`, `DRIVE_TRANSPORT.md`.  
**Status:** development contract; not a deployment or production-qualification specification.

## 1. Purpose

`DriveCoreRunner` can recover a transaction from an exact immutable `DriveTransactionBundle`, but a real process restart cannot assume that bundle object is still present in process memory.

Drive discovery v1 defines how Core finds the exact active/prepared bundle from Hub state without scanning for a "latest" file, choosing among duplicate names, or trusting local process history.

Discovery does not replace `MASTER.json` as canonical-read authority. Its purpose is only to recover the exact transaction authority needed to interpret or complete Core state transitions.

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

Friendly display names are never identity. The resolved folder IDs are checked against the active transaction bundle once that bundle has been loaded.

## 3. Active locator

At most one live Core-owned object named `ACTIVE_TRANSACTION.json` may exist in `control/active`.

The locator is immutable. It binds at minimum:

- schema version;
- `change_id`;
- exact CHANGE SHA-256;
- base canonical epoch;
- exact transaction bundle Drive file ID;
- exact bundle parent Drive ID;
- exact bundle object name;
- exact bundle SHA-256 and byte length;
- its own expected `control/active` parent ID.

The locator is not semantic commit/rollback authority and does not make canonical data safe. It is a restart pointer to exact transaction authority.

## 4. Pre-bound locator identity

Before the immutable transaction bundle is serialized, Core reserves one Drive ID for the active locator and binds that ID plus the expected `control/active` parent ID into the bundle.

The locator content is created only after the exact bundle bytes are known, so it can bind the exact bundle hash and byte length without a hash cycle:

1. reserve locator ID;
2. serialize immutable bundle containing the locator ID/parent binding;
3. publish and verify exact bundle;
4. construct locator bytes containing exact bundle ID/hash/size;
5. create locator at the pre-bound locator ID;
6. re-read and verify locator and bundle;
7. only then may activation publish ACTIVE/SAFE MASTER.

A lost locator-create response is recovered by direct observation of the pre-bound locator ID. Core never allocates a replacement locator ID for the same bundle.

## 5. Uniqueness and ambiguity

Discovery never selects the newest locator or bundle.

Rules:

- zero locator objects may be valid only when the root MASTER is clean READY and no prepared transaction is being resumed;
- exactly one locator is required for ACTIVE, RECOVERY_BLOCKED, or zero-MASTER transition recovery;
- multiple live `ACTIVE_TRANSACTION.json` objects are ambiguity and fail closed;
- locator ID, parent, name or bytes inconsistent with the loaded bundle are ambiguity and fail closed;
- locator/bundle transaction identity mismatch is fail closed;
- malformed locator bytes are fail closed.

## 6. Loading an exact bundle

Given one locator, Core:

1. strictly validates locator bytes;
2. fetches the exact bound bundle file ID directly;
3. verifies bundle metadata location/name and exact SHA-256/size;
4. downloads exact bundle bytes;
5. parses `DriveTransactionBundle` with strict cross-component validation;
6. verifies bundle `change_id`, CHANGE hash and base epoch equal the locator;
7. verifies bundle pre-bound locator ID and locator parent ID equal the actual locator;
8. verifies the durable bundle object through `DriveBundleStore`.

No bundle discovered only by a matching name is accepted.

## 7. Discovery with one root MASTER

### 7.1 READY / SAFE and no locator

Return clean READY. There is no active transaction to recover.

### 7.2 READY / SAFE with one valid locator

Load the exact bundle. This may represent either:

- a prepared transaction whose locator was published before activation and whose activation may resume; or
- a stale operational locator left after COMMITTED, ROLLED_BACK or SAFE abort because cleanup crashed after MASTER had already become READY.

Discovery returns the exact bundle and the actual root MASTER. It does not guess which case applies. The bundle/MASTER transition state is then classified deterministically.

A stale locator under READY is not canonical-read authority and does not make READY data unsafe, but a new transaction MUST NOT activate until the stale locator has been exactly reconciled/archived.

### 7.3 ACTIVE / SAFE or ACTIVE / UNSAFE

Exactly one valid locator is mandatory.

The locator and bundle transaction identity/base epoch MUST equal `MASTER.active_change`. A missing or mismatched locator blocks recovery.

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

## 10. Locator lifetime

The locator MUST remain exact in `control/active` from before the first activation MASTER mutation through every ACTIVE state, every recoverable MASTER gap, and RECOVERY_BLOCKED.

It MUST NOT be removed before a COMMITTED/ROLLED_BACK/aborted READY MASTER is durably established.

After READY is established, locator cleanup is a separate SAFE maintenance action:

- verify the locator and bundle are exact;
- verify the root MASTER deterministically represents the terminal/aborted state for that bundle;
- move/archive or delete only the exact bound locator;
- a crash during this cleanup may leave a stale locator but must not change canonical data or MASTER.

Automatic retention/deletion policy for durable history remains outside MVP.

## 11. Transport uncertainty

Locator creation/movement follows the same Drive transport rules as other Core mutations:

- caller-selected pre-generated ID for creation;
- no hidden mutation retries;
- timeout/lost response/5xx mutation outcome is `DriveUncertainMutation`;
- restart re-observes exact locator ID and actual remote state;
- transport uncertainty never authorizes allocating a different active locator.

## 12. Required proof

Before live disposable Drive acceptance, development validation MUST prove:

- strict locator roundtrip and identity validation;
- bundle pre-binding of locator ID and parent ID;
- lost locator-create response recovery by exact ID;
- ACTIVE recovery from locator + bundle with no process-local transaction object;
- RECOVERY_BLOCKED recovery from locator + bundle;
- zero-MASTER gap recovery from locator + bundle only;
- duplicate locator fail-closed;
- malformed/mismatched locator fail-closed;
- missing locator under ACTIVE/RECOVERY_BLOCKED fail-closed;
- unknown/duplicate root MASTER remains fail-closed even with a valid locator;
- READY without locator is clean;
- READY with a valid stale/preactivation locator is classified without arbitrary cleanup or activation;
- locator cleanup occurs only after exact READY terminal/abort proof.

A green simulator/CI result remains development evidence, not production qualification.
