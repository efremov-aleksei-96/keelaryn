# Keelaryn Core State Machine v1

**Architecture basis:** Zero-Based Architecture r2.  
**Purpose:** deterministic local-filesystem publication protocol for the first Core implementation.

## 1. Authority model

`MASTER.json` is the only mutable stage indicator for an active transaction.

`control/active/` stores exact claimed inputs and staged new bytes. It does not contain a second mutable progress counter.

A stage names the **next action to perform**, not an assertion that the action already completed. This makes every stage restartable: if a process crashes after completing a step but before advancing MASTER, the same step is executed again and must verify/reuse its already-created durable output.

Process memory is never recovery evidence.

## 2. System states

`MASTER.state` has three values:

- `READY` — no active transaction; canonical is SAFE; active control must be absent.
- `ACTIVE` — one exact transaction is in progress.
- `RECOVERY_BLOCKED` — Core observed a state it cannot safely classify or repair automatically.

`MASTER.canonical_read_status` is either `SAFE` or `UNSAFE`.

`READY` is always SAFE. `RECOVERY_BLOCKED` is always UNSAFE in v1.

## 3. Active stages

The v1 active stages are:

1. `CLAIM`
2. `SNAPSHOT`
3. `ENTER_UNSAFE`
4. `APPLY`
5. `WAIT_POSTCHECK`
6. `ROLLBACK`
7. `FINALIZE_COMMIT`
8. `FINALIZE_ROLLBACK`
9. `ABORT_PRECOMMIT`
10. `RECOVERY_BLOCKED`

`CLAIM`, `SNAPSHOT`, `ENTER_UNSAFE` and `ABORT_PRECOMMIT` are SAFE stages. No canonical target may have been mutated while MASTER is in one of them.

`APPLY`, `WAIT_POSTCHECK`, `ROLLBACK`, `FINALIZE_COMMIT`, `FINALIZE_ROLLBACK` and `RECOVERY_BLOCKED` are UNSAFE stages.

## 4. READY discovery and preflight

When MASTER is clean READY/SAFE and no active control exists, Core scans `work/reconciliation/changes/*/READY.json`.

- zero ready changes: no-op success;
- exactly one: continue preflight;
- more than one: fail closed without changing MASTER or canonical.

Before activating a transaction, Core validates all of the following from the reconciliation work area:

- READY schema;
- CHANGE schema;
- READY `change_id` equals CHANGE `change_id`;
- READY `change_sha256` equals SHA-256 of exact CHANGE bytes;
- CHANGE `base_canonical_epoch` equals current MASTER epoch;
- operation IDs and targets are unique;
- all paths pass runtime path-safety checks;
- operation old/new states are legal for their kind;
- every prepared new file has the declared hash and size;
- every canonical target currently matches its declared OLD state;
- no durable `history/<change_id>` already establishes reuse of that change identity.

A preflight failure causes no durable transaction state and no epoch change. The immutable bad ready change must be retired externally before a different change can become the sole ready change.

## 5. Transaction activation

After clean preflight, Core atomically replaces MASTER with:

- `state = ACTIVE`;
- `canonical_read_status = SAFE`;
- exact active change identity;
- `current_stage = CLAIM`;
- unchanged `canonical_epoch`.

From this point startup always follows active recovery before scanning for another ready change.

## 6. CLAIM

Core creates or verifies `control/active/` for the exact active identity.

It copies into Core-controlled storage:

- exact `CHANGE.json` bytes;
- all prepared files required by ADD/REPLACE operations;
- `CONTROL.json` binding change ID, change hash and base epoch.

Every staged file is re-hashed after copy. Existing staged material may be reused only when it exactly matches the active identity and declared fingerprints.

If CLAIM cannot complete while canonical is still SAFE, Core advances to `ABORT_PRECOMMIT`.

After successful CLAIM, MASTER advances to `SNAPSHOT`.

## 7. SNAPSHOT

Core snapshots the previous state of every target into `history/<change_id>/`.

For `REPLACE` and `DELETE`, old bytes are copied to `old/` and verified against the declared OLD fingerprint. For `ADD`, the previous state is ABSENT and no old-byte file exists.

`HISTORY.json` is written **last** after all required old snapshots have been verified. Its `status` is `VERIFIED` and it records both OLD and NEW expected states for every operation.

Core must not enter UNSAFE without a fully verified HISTORY manifest.

If snapshot preparation fails while canonical remains SAFE, Core advances to `ABORT_PRECOMMIT`.

After successful SNAPSHOT, MASTER advances to `ENTER_UNSAFE`.

## 8. ENTER_UNSAFE

Core performs one atomic MASTER replacement that keeps the same active identity and epoch but changes:

- `canonical_read_status = UNSAFE`;
- `current_stage = APPLY`.

No canonical target is modified before this durable write succeeds.

Any transaction that reaches UNSAFE must later increment `canonical_epoch` exactly once before returning to READY, whether it commits or rolls back.

## 9. Target classification

For each operation, Core classifies actual target state from bytes on disk:

- `OLD` — actual state equals the operation's declared OLD state;
- `NEW` — actual state equals the operation's declared NEW state;
- `UNKNOWN` — neither OLD nor NEW.

For an ABSENT expected state, absence is the matching state. For a PRESENT expected state, both byte length and SHA-256 must match.

`UNKNOWN` at any UNSAFE stage immediately transitions to `RECOVERY_BLOCKED`. Core does not overwrite the unknown state automatically.

## 10. APPLY

Operations execute in CHANGE order.

For each operation:

- if target is already NEW, the operation is treated as already applied and verified;
- if target is OLD, Core performs the operation;
- if target is UNKNOWN, Core blocks recovery.

Immediately before a destructive `REPLACE` or `DELETE`, Core re-reads and re-verifies OLD again.

Publication behavior:

- `ADD`: require ABSENT, publish staged new bytes, verify NEW;
- `REPLACE`: require OLD PRESENT, atomically publish staged new bytes, verify NEW;
- `DELETE`: require OLD PRESENT, delete, verify ABSENT.

The local-filesystem backend must use an atomic same-filesystem replacement strategy for ADD/REPLACE publication.

If an execution error occurs after entering UNSAFE and all affected targets remain classifiable only as OLD or NEW, Core transitions to `ROLLBACK`. If any target is UNKNOWN, Core transitions to `RECOVERY_BLOCKED`.

After all targets verify NEW, MASTER advances to `WAIT_POSTCHECK`.

## 11. WAIT_POSTCHECK

Core first verifies that every target still classifies as NEW.

If any target is UNKNOWN, recovery blocks. If targets are a mixture of OLD and NEW, transaction integrity has been lost but rollback remains deterministic, so Core transitions to `ROLLBACK`.

Core then looks for `work/reconciliation/postcheck/<change_id>.json`.

A usable post-check must:

- validate against the postcheck schema;
- bind the exact active `change_id` and `change_sha256`;
- report the active base canonical epoch.

Decision handling:

- no valid matching post-check: remain in `WAIT_POSTCHECK`;
- `PASS`: advance to `FINALIZE_COMMIT`;
- `FAIL`: advance to `ROLLBACK`.

A semantic FAIL is never repaired forward inside the active transaction.

## 12. ROLLBACK

Rollback runs operations in reverse CHANGE order.

For each operation:

- if target is OLD, that operation is already rolled back;
- if target is NEW, restore OLD from verified history;
- if target is UNKNOWN, transition to `RECOVERY_BLOCKED`.

Restoration rules:

- original `REPLACE`: restore old snapshot bytes and verify OLD;
- original `DELETE`: restore old snapshot bytes and verify OLD;
- original `ADD`: remove the NEW file and verify ABSENT.

Rollback never overwrites UNKNOWN bytes.

After all targets verify OLD, MASTER advances to `FINALIZE_ROLLBACK`.

## 13. FINALIZE_COMMIT

Before final success, Core verifies every target is still NEW using HISTORY's recorded new states.

- all NEW: continue cleanup;
- OLD/NEW mixture with no UNKNOWN: transition to `ROLLBACK`;
- any UNKNOWN: transition to `RECOVERY_BLOCKED`.

Core then removes temporary claimed/staged control material, the exact consumed reconciliation change and its matching post-check material. Durable `history/<change_id>` remains.

Only after cleanup is complete does Core atomically write final MASTER:

- `state = READY`;
- `canonical_read_status = SAFE`;
- `active_change = null`;
- `current_stage = null`;
- `canonical_epoch = base_canonical_epoch + 1`;
- `last_completed_change.outcome = COMMITTED`.

If a crash occurs after cleanup but before final MASTER replacement, restart may finalize from MASTER active identity plus verified HISTORY and actual canonical NEW states.

## 14. FINALIZE_ROLLBACK

Core verifies every target is OLD using HISTORY.

Any UNKNOWN blocks recovery. Any NEW target returns the machine to `ROLLBACK`.

After verified OLD state, Core removes temporary control, the consumed reconciliation change and matching post-check material. HISTORY remains.

Only then does Core atomically write final MASTER with:

- READY / SAFE;
- no active change or stage;
- `canonical_epoch = base_canonical_epoch + 1`;
- `last_completed_change.outcome = ROLLED_BACK`.

## 15. ABORT_PRECOMMIT

This stage is valid only while canonical is SAFE and before `ENTER_UNSAFE` completed.

Core removes partial `control/active` and partial unverified history for the active change, verifies that no canonical target differs from its declared OLD state, then atomically returns MASTER to READY/SAFE with the **same epoch** and without changing `last_completed_change`.

If any target is not OLD, precommit abort is no longer safe and the system enters `RECOVERY_BLOCKED` rather than claiming success.

## 16. RECOVERY_BLOCKED

Core atomically sets:

- `state = RECOVERY_BLOCKED`;
- `canonical_read_status = UNSAFE`;
- `current_stage = RECOVERY_BLOCKED`.

A durable `control/active/RECOVERY_BLOCK.json` records the exact transaction identity, reason and observed state.

While blocked, Core performs no automatic canonical writes. Recovery requires explicit human-directed diagnosis and a separately designed recovery action. Normal AI readers must continue to reject canonical data.

## 17. Startup invariants

On every start:

1. parse and validate MASTER;
2. inspect active control and history presence;
3. if MASTER is ACTIVE or RECOVERY_BLOCKED, recover that exact transaction before discovering new ready work;
4. classify actual target bytes rather than trusting previous process progress;
5. reject impossible combinations instead of guessing.

Examples of impossible combinations include READY with active control residue, ACTIVE with a different CONTROL identity, verified HISTORY bound to another change hash, or an epoch inconsistent with the active base epoch.

## 18. Epoch invariant

A transaction that never entered UNSAFE does not change epoch.

A transaction that entered UNSAFE increments epoch exactly once on final return to READY, including a fully verified rollback.

This ensures readers that began before the UNSAFE window cannot accept stale reads after the system becomes SAFE again.

## 19. Required fault-injection coverage

Before any Google Drive backend, the local-filesystem implementation must prove at minimum:

- crash/restart after every durable stage boundary;
- crash during staged prepared-file creation;
- crash during history snapshot creation;
- crash immediately after MASTER enters UNSAFE;
- crash before and after each individual canonical operation;
- crash after semantic PASS before cleanup;
- crash during commit finalization cleanup;
- crash during rollback and rollback finalization;
- prepared-file hash mismatch;
- old-target hash mismatch;
- external target modification producing UNKNOWN;
- duplicate ready changes;
- stale `base_canonical_epoch`;
- change-ID reuse/history collision;
- semantic FAIL → mandatory rollback;
- rollback restoration for ADD, REPLACE and DELETE;
- clean READY with no active residue after COMMITTED and ROLLED_BACK outcomes.
