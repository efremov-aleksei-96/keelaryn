# Keelaryn Core — Drive Orchestration Contract v1

**Architecture basis:** Zero-Based Architecture r2, `STATE_MACHINE.md`, `DRIVE_BACKEND.md`, `DRIVE_TRANSPORT.md`.  
**Status:** development contract for the Drive-specific outer Core; not a deployment or production-qualification specification.

## 1. Why Drive orchestration differs from the filesystem backend

The local-filesystem Core can atomically replace one small `MASTER.json` after each durable stage. Drive does not provide a multi-object transaction, and an in-place mutable `CONTROL.json` would itself become another object whose crash-safe publication needs orchestration.

Drive v1 therefore does **not** use a mutable secondary progress counter.

Recovery authority consists of:

1. the uniquely resolved logical `MASTER.json` object when one is visible;
2. one immutable transaction bundle bound to the exact active change;
3. exact known Drive object IDs recorded in that bundle;
4. actual fresh Drive metadata and downloaded bytes;
5. an immutable accepted post-check receipt when a semantic decision has been accepted.

Process memory, request completion history and list-cache state are never recovery evidence.

## 2. Coarse MASTER stages

Drive v1 reuses the generic MASTER meanings but needs fewer MASTER rewrites.

The normal lifecycle is:

```text
READY / SAFE
  -> ACTIVE / SAFE / SNAPSHOT
  -> ACTIVE / UNSAFE / APPLY
  -> READY / SAFE
```

`SNAPSHOT` on Drive means: re-run/verify all idempotent SAFE preparation, including claimed staged objects, independent OLD snapshots and the fresh pre-UNSAFE boundary checks. It may remain the visible coarse stage even after some or all preparation already completed.

`APPLY` on Drive means: recover the active UNSAFE transaction by inspecting actual operation states and any accepted post-check receipt. It covers publication, waiting for post-check, rollback and finalization without requiring a mutable stage counter.

The exact substage is derived from durable objects, never inferred from how far the previous process believed it had progressed.

## 3. Immutable transaction bundle

Before publishing ACTIVE/SAFE MASTER, Core creates and verifies one immutable transaction bundle for the exact change.

The bundle binds at least:

- `change_id`;
- exact CHANGE identity/hash and base canonical epoch;
- Hub root and structural folder IDs;
- exact `DriveControl` operation identities;
- exact `DriveSnapshotPlan` identities;
- reserved Core-created Drive IDs used by the transaction;
- the expected READY/SAFE starting MASTER identity and fingerprint;
- the ACTIVE/SAFE MASTER candidate ID and fingerprint;
- the ACTIVE/UNSAFE MASTER candidate ID and fingerprint;
- final COMMITTED READY MASTER candidate ID/fingerprint;
- final ROLLED_BACK READY MASTER candidate ID/fingerprint;
- RECOVERY_BLOCKED MASTER candidate ID/fingerprint where the blocked MASTER bytes can be predetermined;
- one reserved accepted-postcheck receipt ID;
- exact history/provenance location for the immutable bundle.

The bundle itself is exact-byte identified and never rewritten during the transaction.

A transaction needing different identities is a different bundle, not an update to the old bundle.

## 4. Durable location and finalization survival

The authoritative immutable bundle MUST remain available through final MASTER publication.

It cannot exist only in disposable `control/active`, because finalization may need to clean active control before returning to clean READY.

Drive v1 therefore keeps the exact transaction/provenance bundle in durable per-change history. `control/active` may contain an immutable pointer/copy for operational discovery, but history is sufficient to recover finalization after active-control cleanup.

A pre-UNSAFE abort may delete an exact uncommitted bundle/history set only after proving the transaction never entered UNSAFE and canonical targets remain OLD.

## 5. Planning reserved IDs

All Core-created Drive objects that may matter to restart recovery receive pre-generated Drive IDs before their first mutation.

The transaction bundle binds those IDs before activation.

This includes at least:

- staged Core-owned NEW objects where Core creates the Drive copy;
- independent OLD snapshot objects;
- MASTER transition candidates;
- accepted post-check receipt;
- Core-owned transaction/control/history records that participate in recovery.

A lost create/copy response is resolved by direct observation of the bound ID, never by silently allocating a new identity.

## 6. READY preflight and bundle preparation

While the current MASTER is uniquely READY/SAFE, Core performs read-only preflight equivalent to the generic protocol.

Before activation it also:

1. resolves and binds exact structural folder IDs;
2. captures exact canonical OLD object IDs/fingerprints;
3. binds exact staged NEW object IDs/fingerprints;
4. reserves all required Core-created IDs;
5. creates and verifies the immutable transaction bundle;
6. ensures enough durable provenance exists to identify and clean only this exact preparation if activation never occurs.

No canonical target is mutated in this phase.

Unreferenced exact Core-owned preparation residue under a still-READY MASTER is not authority and cannot make a change active.

## 7. Activation: READY/SAFE -> ACTIVE/SAFE

Activation is a copy-on-write MASTER transition.

The old READY MASTER object remains preserved. The ACTIVE/SAFE candidate is published as the unique root `MASTER.json` with:

- exact active change identity;
- unchanged canonical epoch;
- `state = ACTIVE`;
- `canonical_read_status = SAFE`;
- coarse `current_stage = SNAPSHOT`.

Only this MASTER transition makes the transaction active.

A crash during the MASTER swap is recovered from its immutable MASTER transition binding and exact object IDs.

## 8. ACTIVE/SAFE recovery and independent snapshots

Every startup while ACTIVE/SAFE re-runs the SAFE preparation idempotently.

Core:

1. verifies the exact immutable transaction bundle;
2. verifies every staged NEW object;
3. ensures the independent `DriveSnapshotPlan` copies for all REPLACE/DELETE OLD bytes;
4. verifies each snapshot has a distinct bound file ID, exact expected parent/name, metadata fingerprint and downloaded bytes;
5. freshly revalidates every canonical target as OLD;
6. freshly revalidates bound structural folder IDs/relationships.

Snapshot creation may be repeated only through exact reserved-ID observation. It never overwrites an existing unknown object.

If SAFE preparation cannot be completed, Core performs precommit abort by rolling the activation MASTER transition back to the preserved READY MASTER and then cleaning only exact Core-owned preparation material. Epoch does not change.

## 9. ENTER_UNSAFE

Immediately before UNSAFE, Core freshly verifies all items from section 8 again.

If anything is stale or ambiguous, Core aborts while still SAFE.

Otherwise Core performs a second copy-on-write MASTER transition to the predetermined ACTIVE/UNSAFE MASTER candidate:

- same exact active change;
- same base epoch;
- `state = ACTIVE`;
- `canonical_read_status = UNSAFE`;
- coarse `current_stage = APPLY`.

No canonical target is published before this exact UNSAFE MASTER becomes the unique valid root MASTER.

Any transaction that reaches this point must increment canonical epoch exactly once before a later READY state, whether committed or rolled back.

## 10. UNSAFE recovery is state-derived

While the ACTIVE/UNSAFE MASTER is authoritative, Core derives what to do from:

- actual operation states (`OLD`, `NEW`, recoverable Drive-specific substates, or `UNKNOWN`);
- exact independent snapshot availability;
- accepted post-check receipt presence/content;
- exact known MASTER transition states.

There is no mutable `APPLY -> WAIT_POSTCHECK -> ROLLBACK -> FINALIZE` progress integer/file.

### 10.1 No accepted post-check receipt

If operations are not all NEW, Core continues idempotent APPLY.

If operations are all NEW, Core waits for a valid semantic post-check and performs no further canonical mutation.

### 10.2 Accepted PASS receipt

Core requires all operations to remain NEW and proceeds toward COMMITTED finalization.

If an operation is UNKNOWN, recovery blocks. A deterministic OLD/NEW mixture before final commit cannot be declared committed.

### 10.3 Accepted FAIL receipt

Core performs mandatory reverse-order rollback until every operation is OLD.

Semantic FAIL never authorizes forward repair.

## 11. Accepted post-check receipt

The transaction bundle pre-reserves one exact Core-owned receipt ID.

When Reconciliation publishes a candidate post-check, Core:

1. downloads exact post-check bytes;
2. strictly validates schema and exact change identity/base epoch;
3. if malformed or mismatched, creates no receipt and remains waiting;
4. if valid, creates a new immutable Core-owned receipt blob from those exact validated bytes using the pre-reserved ID;
5. downloads/revalidates the receipt after creation.

After a valid receipt exists, its decision is immutable transaction authority even if the external Reconciliation post-check is later moved or modified.

A lost receipt-create response is recovered by direct observation of the reserved receipt ID.

## 12. COMMITTED finalization

For PASS, Core freshly verifies:

- all canonical operations are exact NEW;
- required independent history/snapshot objects remain exact;
- accepted PASS receipt is exact;
- immutable transaction bundle is exact.

Core cleans only exact temporary/work/control material whose identities are bound and whose current state is expected. Durable history/provenance remains.

The final COMMITTED READY MASTER is then published through its pre-bound copy-on-write MASTER transition:

- `state = READY`;
- `canonical_read_status = SAFE`;
- no active change/stage;
- `canonical_epoch = base + 1`;
- `last_completed_change.outcome = COMMITTED`.

Final MASTER recovery remains possible from durable history even if active-control cleanup already completed.

## 13. ROLLED_BACK finalization

For FAIL or deterministic execution failure requiring rollback, Core requires every operation to reach exact OLD.

It freshly verifies independent snapshots/history, accepted FAIL receipt when semantic FAIL caused rollback, and the immutable bundle.

After exact cleanup, the pre-bound ROLLED_BACK READY MASTER is published:

- READY / SAFE;
- no active change/stage;
- `canonical_epoch = base + 1`;
- `last_completed_change.outcome = ROLLED_BACK`.

Rollback after an UNSAFE window always increments epoch exactly once.

## 14. RECOVERY_BLOCKED

UNKNOWN canonical state, unknown MASTER state, bundle identity conflict, damaged required snapshot, or another ambiguity never triggers overwrite/delete.

When the current MASTER is itself still exactly known and safely replaceable, Core may publish a pre-bound RECOVERY_BLOCKED/UNSAFE MASTER and an immutable detailed recovery-block record.

If MASTER identity itself is ambiguous/unknown, Core must not perform another MASTER mutation merely to label the failure. Normal readers already fail because no unique valid SAFE MASTER can be established.

## 15. Reader contract

Normal readers do not execute transition recovery.

They require:

1. exactly one root `MASTER.json`;
2. valid MASTER bytes;
3. `canonical_read_status = SAFE`;
4. record canonical epoch;
5. read canonical data;
6. re-resolve/re-read MASTER;
7. accept the read only if MASTER is still uniquely SAFE with the same epoch.

During copy-on-write MASTER swap, zero or multiple root `MASTER.json` objects are invalid reader states even when Core can deterministically recover them.

## 16. No hidden forward repair

The Drive backend must preserve the global Core rule:

- semantic FAIL -> rollback;
- UNKNOWN -> block;
- transport uncertainty -> re-observe exact known IDs and classify;
- no new identity allocation or arbitrary name-based selection is used to make an ambiguous transaction appear successful.

## 17. Required proof before live Drive

Before a real disposable Drive Hub is used, development validation must prove at minimum:

- backend-neutral metadata/content separation;
- reserved-ID create/copy recovery;
- no hidden mutation retries;
- typed transport failure semantics;
- canonical ADD/REPLACE/DELETE apply and rollback crash matrices;
- immutable Drive control reconstruction;
- multi-operation recovery from durable bytes only;
- copy-on-write MASTER publish/rollback crash matrices;
- normal-reader rejection of MASTER swap gaps;
- independent pre-UNSAFE snapshot creation and restart recovery;
- snapshot corruption/location conflict fail-closed;
- state-derived outer orchestration without a mutable secondary progress counter.

A green simulator/CI line is development evidence only. Live disposable Drive acceptance and production-specific acceptance remain separate gates.
