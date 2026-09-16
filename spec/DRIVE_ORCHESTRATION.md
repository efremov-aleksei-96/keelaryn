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
5. one decision-specific immutable post-check receipt when a semantic decision has been accepted;
6. one pre-bound immutable execution-rollback marker when deterministic Core execution failure, rather than semantic FAIL, has durably selected rollback;
7. one pre-bound immutable recovery-block record once Core has durably selected `RECOVERY_BLOCKED` from an exact ACTIVE/UNSAFE state.

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

A fail-closed UNSAFE stop may instead become:

```text
ACTIVE / UNSAFE / APPLY
  -> RECOVERY_BLOCKED / UNSAFE / RECOVERY_BLOCKED
```

`SNAPSHOT` on Drive means: re-run/verify all idempotent SAFE preparation, including claimed staged objects, independent OLD snapshots and the fresh pre-UNSAFE boundary checks. It may remain the visible coarse stage even after some or all preparation already completed.

`APPLY` on Drive means: recover the active UNSAFE transaction by inspecting actual operation states, decision-specific post-check receipts and any execution-rollback marker. It covers publication, waiting for post-check, rollback and finalization without requiring a mutable stage counter.

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
- the exact starting READY/SAFE MASTER bytes, identity and fingerprint;
- the ACTIVE/SAFE MASTER candidate ID and exact bytes/fingerprint;
- the ACTIVE/UNSAFE MASTER candidate ID and exact bytes/fingerprint;
- final COMMITTED READY MASTER candidate ID and exact bytes/fingerprint;
- final ROLLED_BACK READY MASTER candidate ID and exact bytes/fingerprint;
- one RECOVERY_BLOCKED/UNSAFE MASTER candidate ID and exact predetermined bytes/fingerprint;
- one reserved PASS receipt ID and one different reserved FAIL receipt ID;
- one reserved execution-rollback marker ID;
- one reserved recovery-block record ID;
- exact history/provenance location for the immutable bundle.

The bundle stores exact serialized bytes plus SHA-256 and byte length for its bound subcontracts. Cross-component consistency is validated, including MASTER transition chaining, snapshot coverage and reserved-ID uniqueness.

The bundle itself is exact-byte identified and never rewritten during the transaction.

A transaction needing different identities is a different bundle, not an update to the old bundle.

## 4. Durable location and finalization survival

The authoritative immutable bundle MUST remain available through final MASTER publication or durable RECOVERY_BLOCKED publication.

It cannot exist only in disposable `control/active`, because finalization or blocked recovery may need to continue after other operational material changed.

Drive v1 therefore keeps the exact transaction/provenance bundle in durable per-change history. `control/active` may contain an immutable pointer/copy for operational discovery, but history is sufficient to recover finalization or a pre-bound blocked transition.

A pre-UNSAFE abort may delete an exact uncommitted bundle/history set only after proving the transaction never entered UNSAFE and canonical targets remain OLD.

## 5. Planning reserved IDs

All Core-created Drive objects that may matter to restart recovery receive pre-generated Drive IDs before their first mutation.

The transaction bundle binds those IDs before activation.

This includes at least:

- staged Core-owned NEW objects where Core creates the Drive copy;
- independent OLD snapshot objects;
- MASTER transition candidates;
- **two mutually exclusive post-check receipt IDs, one bound to PASS and one bound to FAIL**;
- the execution-rollback marker ID;
- the recovery-block record ID;
- the immutable transaction bundle itself;
- Core-owned transaction/control/history records that participate in recovery.

All bound Core-created identities for one transaction MUST be mutually distinct and MUST NOT collide with captured canonical OLD source IDs.

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

The **pre-UNSAFE snapshot verifier** requires both the canonical OLD source and its independent snapshot to remain exact. Snapshot creation may be repeated only through exact reserved-ID observation. It never overwrites an existing unknown object.

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

If a crash leaves zero root `MASTER.json` objects after the old ACTIVE/SAFE MASTER has been displaced, Core MUST repeat the full fresh pre-UNSAFE proof before completing publication of the ACTIVE/UNSAFE candidate.

Any transaction that reaches UNSAFE must not return to READY without incrementing canonical epoch exactly once. A durable RECOVERY_BLOCKED state is not READY and retains the base epoch until a separately specified recovery procedure resolves the transaction.

## 10. UNSAFE recovery is state-derived

While the ACTIVE/UNSAFE MASTER is authoritative, Core derives what to do from:

- actual operation states (`OLD`, `NEW`, recoverable Drive-specific substates, or `UNKNOWN`);
- exact independent snapshot-copy availability;
- decision-specific receipt presence/content;
- execution-rollback marker presence/content;
- recovery-block record presence/content;
- exact known MASTER transition states.

There is no mutable `APPLY -> WAIT_POSTCHECK -> ROLLBACK -> FINALIZE` progress integer/file.

After UNSAFE begins, the **post-UNSAFE snapshot verifier** requires the independent snapshot copies to remain exact but does not require the original OLD source to remain in canonical, because REPLACE/DELETE legitimately move it during publication/rollback.

If an exact recovery-block record already exists, Core does not resume apply, semantic acceptance, commit or rollback. It continues only the pre-bound RECOVERY_BLOCKED MASTER transition.

### 10.1 No decision receipt, execution-rollback marker or recovery-block record

If operations are not all NEW, Core continues idempotent APPLY.

If operations are all NEW, Core waits for a valid semantic post-check and performs no further canonical mutation.

### 10.2 Valid PASS-bound receipt exists and FAIL-bound receipt is absent

Core requires the PASS receipt bytes to validate as an exact matching post-check whose `decision` is `PASS`.

It then requires all operations to remain NEW and proceeds toward COMMITTED finalization.

If an operation is UNKNOWN, recovery blocks. A deterministic OLD/NEW mixture before final commit cannot be declared committed.

A PASS receipt and an execution-rollback marker existing together are conflicting authorities and MUST block recovery.

### 10.3 Valid FAIL-bound receipt exists and PASS-bound receipt is absent

Core requires the FAIL receipt bytes to validate as an exact matching post-check whose `decision` is `FAIL`.

Core performs mandatory reverse-order rollback until every operation is OLD.

Semantic FAIL never authorizes forward repair.

### 10.4 Both receipt IDs exist, or decision does not match its bound ID

Recovery blocks. Core never chooses one arbitrarily.

### 10.5 Execution-rollback marker exists

A deterministic execution failure after UNSAFE may select rollback without fabricating a semantic FAIL.

Core may create the pre-bound execution-rollback marker only after:

1. classifying the failure as deterministic rather than transport uncertainty;
2. re-verifying the immutable bundle and independent snapshot copies;
3. proving actual operation states remain classifiable without UNKNOWN.

The marker is a Core-owned immutable object at one pre-reserved ID bound to the exact transaction identity/base epoch. Once validly present, restart derives rollback direction from that marker.

Transport timeout, lost response, 5xx or another uncertain mutation result MUST NOT create this marker. Those failures are re-observed from exact known IDs on restart.

## 11. Decision-specific post-check receipts

The transaction bundle pre-reserves **two different Core-owned receipt IDs**:

- `pass_receipt_id`, permanently meaning PASS for this exact transaction;
- `fail_receipt_id`, permanently meaning FAIL for this exact transaction.

This separation is required because the exact future post-check hash/reason is unknown when the immutable bundle is created. A single future receipt ID would not by itself prevent a later content edit from flipping PASS to FAIL or FAIL to PASS. Binding the semantic direction to two distinct precommitted IDs makes a direction flip detectable.

When Reconciliation publishes a candidate post-check, Core:

1. downloads exact post-check bytes;
2. strictly validates schema and exact `change_id`, `change_sha256` and base epoch;
3. validates decision is PASS or FAIL;
4. if malformed or mismatched, creates no receipt and remains waiting;
5. selects **only** the pre-bound receipt ID corresponding to that validated decision;
6. creates a Core-owned receipt blob from the exact validated bytes using that ID;
7. downloads/revalidates the receipt after creation and requires its decision to match the ID's pre-bound meaning.

Recovery rules:

- neither ID exists: no accepted semantic decision;
- exactly PASS ID exists with exact matching PASS bytes: accepted PASS;
- exactly FAIL ID exists with exact matching FAIL bytes: accepted FAIL;
- both exist: ambiguity -> block;
- receipt bytes contain the opposite decision from their ID: block;
- receipt identity/epoch mismatch or malformed bytes: block once that Core-owned reserved ID exists.

A lost receipt-create response is recovered by direct observation of the selected reserved receipt ID. Core does not create the opposite receipt or allocate a replacement ID.

After an exact Core-owned receipt has been accepted, the external Reconciliation post-check object and its source work folder are **no longer recovery authority**. They may later move, change or disappear without invalidating commit/rollback finalization. The exact accepted source bytes remain preserved in the Core-owned receipt/provenance. Core-owned receipt/history/transition structure remains mandatory.

## 12. COMMITTED finalization

For PASS, Core freshly verifies:

- all canonical operations are exact NEW;
- required independent history/snapshot copies remain exact;
- exactly the PASS-bound receipt is valid and the FAIL-bound receipt is absent;
- no execution-rollback marker conflicts with PASS;
- no recovery-block authority exists;
- immutable transaction bundle is exact;
- all required Core-owned structural folders/objects remain exact.

External Reconciliation work material is not required after the PASS receipt has become authority.

Core cleans only exact temporary/work/control material whose identities are bound and whose current state is expected. Durable history/provenance remains.

The final COMMITTED READY MASTER is then published through its pre-bound copy-on-write MASTER transition:

- `state = READY`;
- `canonical_read_status = SAFE`;
- no active change/stage;
- `canonical_epoch = base + 1`;
- `last_completed_change.outcome = COMMITTED`.

If a crash occurs in the zero-MASTER gap of final MASTER publication, recovery MUST re-verify all NEW, exact PASS authority, absence of conflicting execution rollback/recovery-block authority, bundle and snapshot copies before completing publication.

Final MASTER recovery remains possible from durable history even if disposable external work material already disappeared.

## 13. ROLLED_BACK finalization

For FAIL or deterministic execution failure requiring rollback, Core requires every operation to reach exact OLD.

For semantic FAIL it requires exactly the valid FAIL-bound receipt and absence of the PASS-bound receipt. For deterministic execution failure it requires the exact pre-bound execution-rollback marker. It must never fabricate a semantic FAIL receipt.

Core freshly verifies independent snapshot copies, immutable bundle, absence of recovery-block authority and Core-owned structural recovery material. External Reconciliation work material is no longer required once an accepted FAIL receipt exists.

After exact cleanup, the pre-bound ROLLED_BACK READY MASTER is published:

- READY / SAFE;
- no active change/stage;
- `canonical_epoch = base + 1`;
- `last_completed_change.outcome = ROLLED_BACK`.

If a crash occurs in the zero-MASTER gap of final rollback MASTER publication, recovery MUST re-verify all OLD and exact rollback authority before completing publication.

Rollback after an UNSAFE window always increments epoch exactly once.

## 14. RECOVERY_BLOCKED

UNKNOWN canonical state, damaged required snapshot, receipt ambiguity/corruption, conflicting PASS/execution authorities, invalid execution marker, or another deterministic ambiguity MUST NOT trigger forward repair or arbitrary rollback.

Core may durably select RECOVERY_BLOCKED only when all of the following remain provable:

1. the immutable transaction bundle is exact;
2. exactly the known ACTIVE/UNSAFE MASTER is the current root `MASTER.json`;
3. the pre-bound recovery-block parent and MASTER-transition parent remain valid Core-owned folders;
4. no transport uncertainty is being reclassified as deterministic corruption.

The blocked transition is:

1. create an immutable `RECOVERY_BLOCK.json` at the one pre-reserved recovery-block ID, binding exact change identity/base epoch, observed phase `ACTIVE_UNSAFE` and the diagnostic reason;
2. re-read and validate that exact record;
3. prepare the pre-bound RECOVERY_BLOCKED/UNSAFE MASTER candidate;
4. freshly revalidate the immutable bundle, exact block record and exact ACTIVE/UNSAFE root MASTER;
5. copy-on-write publish the predetermined blocked MASTER candidate.

The blocked MASTER has:

- `state = RECOVERY_BLOCKED`;
- `canonical_read_status = UNSAFE`;
- `current_stage = RECOVERY_BLOCKED`;
- the same exact active change identity;
- `canonical_epoch = base`, not `base + 1`.

Once the block record exists, it is directional recovery authority: restart MUST continue only the blocked transition and MUST NOT resume apply/commit/rollback. A lost response after record creation or either blocked-MASTER mutation is resolved by observing the exact pre-bound IDs.

If a crash occurs after the exact ACTIVE/UNSAFE MASTER was displaced during an already-authorized blocked transition, the zero-MASTER gap may be completed only when the exact immutable bundle, exact block record and unique blocked transition binding prove that this is that already-started transition.

Core MUST NOT attempt to manufacture a durable blocked state when authority itself is insufficient. In particular, it performs no new MASTER mutation merely to label:

- a missing/corrupt transaction bundle;
- a corrupt/ambiguous recovery-block record occupying its reserved ID;
- an unknown or duplicate root MASTER;
- a zero-MASTER gap that is not uniquely attributable to an already-started known transition.

Those cases remain fail-closed without additional mutation.

RECOVERY_BLOCKED is terminal for automatic v1 orchestration. It does not mean COMMITTED or ROLLED_BACK, does not increment epoch, and does not authorize further canonical writes. A later repair requires a separately specified recovery procedure with its own transaction boundaries and evidence.

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

During copy-on-write MASTER swap, zero or multiple root `MASTER.json` objects are invalid reader states even when Core can deterministically recover them. `RECOVERY_BLOCKED/UNSAFE` is likewise unreadable by ordinary canonical readers.

## 16. No hidden forward repair

The Drive backend must preserve the global Core rule:

- semantic FAIL -> rollback;
- deterministic execution failure -> durable execution-rollback marker, then rollback;
- deterministic ambiguity under exact ACTIVE/UNSAFE authority -> durable recovery-block record, then RECOVERY_BLOCKED/UNSAFE;
- UNKNOWN without sufficient authority to publish blocked state -> stop without mutation;
- transport uncertainty -> re-observe exact known IDs and classify;
- both decision receipts -> block;
- PASS receipt plus execution rollback marker -> block;
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
- exact immutable transaction-bundle roundtrip and cross-component consistency;
- copy-on-write MASTER publish/rollback crash matrices;
- zero-MASTER gap recovery with fresh authority revalidation;
- normal-reader rejection of MASTER swap gaps;
- independent pre-UNSAFE snapshot creation and restart recovery;
- separate pre-UNSAFE source+snapshot verification and post-UNSAFE snapshot-copy verification;
- snapshot corruption/location conflict fail-closed;
- mutually exclusive PASS/FAIL receipt authority with lost-response recovery;
- receipt decision/ID mismatch and dual-receipt ambiguity fail-closed;
- accepted receipt independence from later external post-check work-folder changes/removal;
- durable execution-rollback marker with reserved-ID lost-response recovery;
- PASS/execution-authority conflict fail-closed;
- immutable recovery-block record with reserved-ID lost-response recovery;
- model crash recovery at recovery-block record create and every blocked MASTER mutation;
- REST uncertain-response recovery at recovery-block record create and every blocked MASTER mutation;
- state-derived outer orchestration without a mutable secondary progress counter;
- complete outer PASS/FAIL lifecycle over the actual REST adapter against a stateful Drive simulator;
- restart recovery after an uncertain response following every simulated server-side mutation in COMMITTED, ROLLED_BACK and RECOVERY_BLOCKED paths.

A green simulator/CI line is development evidence only. Live disposable Drive acceptance and production-specific acceptance remain separate gates.
