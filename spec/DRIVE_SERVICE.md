# Keelaryn Core — Drive Service Contract v1

**Architecture basis:** Zero-Based Architecture r2, `DRIVE_ORCHESTRATION.md`, `DRIVE_DISCOVERY.md`, `DRIVE_TRANSPORT.md`.  
**Status:** development contract for a disposable/live Drive poller; not production qualification.

## 1. Scope

This contract composes the already-defined Drive primitives into the process-level MVP lifecycle.

The service starts from one configured Hub root Drive object ID and, without process-local transaction state, can:

1. initialize a fresh disposable Hub protocol structure;
2. verify an already initialized Hub without repairing it;
3. recover an already-active transaction from the active locator;
4. otherwise ingest at most one Ready Change from Reconciliation work;
5. build or recover the exact immutable transaction bundle;
6. execute the state-derived Drive Core transaction;
7. wait for semantic post-check when required;
8. preserve durable `RECOVERY_BLOCKED` when automatic recovery is unsafe;
9. after COMMITTED/ROLLED_BACK, consume only the exact Ready marker;
10. archive the active locator and return to clean READY/SAFE.

The polling service does not own semantic reconciliation. It only consumes a valid Ready Change and a later valid post-check decision.

## 2. Fresh Hub bootstrap

A fresh Hub root has no `MASTER.json`.

Core may idempotently create the protocol-owned folder structure:

```text
Hub/
├── canonical/
├── work/
│   └── reconciliation/
│       ├── changes/
│       └── postcheck/
├── control/
│   └── active/
└── history/
```

`README.md` and `INDEX.md` are presentation/routing material and are not required for Core bootstrap correctness.

Before publishing the first MASTER, Core MUST prove:

- there is no existing root `MASTER.json`;
- canonical is empty;
- reconciliation changes/postcheck are empty;
- control/active is empty;
- history is empty;
- no unexpected protocol-owned structure is present.

The initial MASTER is exactly READY/SAFE with canonical epoch 0 and no active or completed change.

Folder creation and initial MASTER creation are restartable after lost responses by re-observing deterministic names and the exact created object. A duplicate/ambiguous name blocks initialization.

Once any valid `MASTER.json` exists, bootstrap becomes verify-only. It MUST NOT create missing folders or repair initialized state.

## 3. Ready Change intake

Under clean READY/SAFE, Core resolves `work/reconciliation/changes/` and strictly loads all Ready Change material through the v1 CHANGE/READY contracts.

For the selected change Core verifies:

- exact `READY.json -> SHA256(CHANGE.json)` binding;
- `change_id` and folder identity convention;
- base canonical epoch equals the current SAFE MASTER epoch;
- ADD targets are absent;
- REPLACE/DELETE OLD targets have exact expected bytes;
- prepared ADD/REPLACE bytes have exact expected NEW fingerprints;
- canonical target parents resolve uniquely.

ADD/REPLACE prepared bytes are copied into Core-owned per-change staging before activation. Staging copies use deterministic operation names and exact byte verification so a lost copy response is recoverable without duplicate publication.

After all staging work, Core repeats the SAFE epoch, OLD target and staged-copy proof before producing `DriveControl`.

## 4. Per-change recovery structure

Before activation, while MASTER remains READY/SAFE, Core creates or re-observes:

```text
history/<change_id>/
├── stage/
├── originals/
├── rejected/
├── snapshots/
├── receipts/
├── markers/
├── master-transitions/
└── <change_id>.DRIVE_BUNDLE.json
```

The deterministic folders are preparation material, not transaction authority. Unknown material or duplicates under the per-change recovery root block automatic preparation.

After the immutable bundle is created, its exact IDs/fingerprints become transaction authority according to `DRIVE_ORCHESTRATION.md`.

If the process dies after durable bundle creation but before active-locator creation, the factory MUST reuse the exact existing bundle. It MUST NOT generate a second set of transaction identities.

## 5. Polling iteration

One service iteration follows this order.

### 5.1 Recover first

Resolve Drive restart discovery from Hub root.

If a locator exists, recovery of that exact transaction has priority over all new work. No new Ready Change may be selected while an active/prepared locator exists.

### 5.2 Clean READY

If discovery returns clean READY with no active locator:

- select/build/resume at most one Ready Change;
- if no Ready Change exists, return IDLE;
- otherwise durably ensure the exact bundle and active locator;
- only then allow ACTIVE/SAFE publication.

### 5.3 Active transaction

Delegate transaction execution to `DriveCoreRunner`.

The process-level service may return:

- `WAIT_POSTCHECK`;
- `RECOVERY_BLOCKED`;
- `ABORTED_SAFE`;
- `COMMITTED`;
- `ROLLED_BACK`.

`WAIT_POSTCHECK`, `RECOVERY_BLOCKED` and `ABORTED_SAFE` retain the active locator. They are not silently converted into clean idle state.

## 6. Terminal Ready Change consumption

After COMMITTED or ROLLED_BACK, canonical state is already READY/SAFE. External Reconciliation work is no longer recovery authority.

Core does not delete the change folder or prepared blobs.

If the original `READY.json` still exists, Core freshly verifies:

- terminal bundle/MASTER authority;
- exact current `CHANGE.json` hash equals the bundle change hash;
- CHANGE base epoch equals the bundle base epoch;
- READY binds the same exact change identity;
- source Ready marker identity/bytes remain unchanged at the cleanup boundary.

Only then Core moves that exact READY object to durable history as:

`history/<change_id>/<change_id>.READY.consumed.json`

If the external READY marker already disappeared, no work cleanup is required.

If the external marker or CHANGE was changed, Core performs no cleanup mutation and reports a blocked maintenance condition.

A lost response after the READY move is recovered by observing the exact source/destination state. The active locator remains until Ready consumption has been resolved.

## 7. Locator cleanup ordering

The active locator is archived only after terminal Ready consumption succeeds or is proven unnecessary because the external marker is absent.

Therefore terminal cleanup ordering is:

```text
terminal READY/SAFE
  -> consume exact READY marker (or prove source absent)
  -> archive exact active locator
  -> clean READY/SAFE / IDLE
```

A crash after Ready consumption but before locator cleanup leaves a discoverable terminal transaction. A restart repeats the idempotent consumption proof and then archives the locator.

A crash/lost response during locator archive may leave the Hub already clean. On restart the service observes clean READY and proceeds without replaying the consumed change.

## 8. Transport uncertainty

All service mutations inherit the Drive transport rule:

- no hidden mutation retry;
- timeout, lost response, 408/429/5xx after a mutation is uncertain;
- restart re-observes actual remote state;
- no arbitrary replacement IDs or duplicate publication are used to turn uncertainty into success.

This applies to bootstrap folders, initial MASTER, staging copies, bundle/locator creation, snapshots, canonical publication/rollback, receipts/markers, final MASTER, consumed READY and locator archive.

## 9. Process-level single-writer invariant

The MVP VPS deployment permits exactly one writer process per Hub on one configured writer host.

`bootstrap`, `once` and `serve` acquire the same local per-Hub advisory lock before OAuth or Drive access. The lock:

- is held for the complete command lifetime;
- is released by the OS when the process exits/crashes;
- uses a SHA-256-derived local key rather than exposing the Drive Hub ID in its filename;
- requires a real private runtime directory owned by the service user;
- blocks a second local writer before it can create pre-activation Drive material.

This mechanism serializes processes on **one host only**. It does not claim distributed locking across multiple VPS hosts. Running two writer hosts against one Hub is outside the MVP deployment contract and must be prevented operationally.

## 10. OAuth and polling process boundary

The Drive poller supports three commands:

- `bootstrap` — initialize a fresh disposable Hub or verify an initialized Hub;
- `once` — execute one restart-safe polling iteration;
- `serve` — execute the MVP polling loop at a bounded interval.

Continuous `serve` requires OAuth refresh credentials supplied through the process environment. Static access tokens are allowed only for disposable `bootstrap`/`once` use and are rejected for continuous service.

Credential values MUST NOT be written into Hub state, history, normal status output, CI evidence or source control.

Transport uncertainty during `serve` does not cause an in-place mutation retry. The iteration reports `REOBSERVE_REQUIRED`; a later top-level iteration re-observes exact Drive state.

Protocol/configuration blocks terminate with exit status 2 so a supervisor can avoid an automatic restart loop. Unexpected process failures may be restarted by the supervisor.

## 11. Development proof currently required

Development CI MUST prove at minimum:

- fresh bootstrap and idempotent verify-only restart;
- refusal to initialize MASTER over unknown canonical/work/history bytes;
- lost-response recovery after every bootstrap mutation;
- Ready Change ingestion and fresh pre-activation revalidation;
- orphan bundle before locator is resumed exactly;
- full PASS and FAIL polling lifecycle from Ready Change bytes;
- exact Ready-marker consumption after terminal publication;
- changed external Ready material is not silently mutated;
- `RECOVERY_BLOCKED` retains transaction discovery authority;
- lost-response recovery after every server-side mutation of the full PASS path;
- lost-response recovery after every server-side mutation of the full FAIL/rollback path;
- OAuth refresh/cache/error handling without secret disclosure;
- poller configuration/CLI behavior;
- local same-Hub writer contention blocks before network access;
- lock release/reacquire and private runtime-directory enforcement;
- guarded disposable-live acceptance tooling refuses the wrong acceptance root before mutation.

A green simulator/REST-adapter CI line is development evidence only. Real disposable Google Drive acceptance remains a separate gate.

## 12. Remaining external evidence boundary

The deterministic Core, real REST adapter, OAuth refresh provider, polling process, local single-writer lock and hardened systemd development template now exist in source and are covered by development CI.

The next evidence class requires a **real disposable Google Drive** using the same `GoogleDriveBackend` and `DrivePollingService` path. The live gate must use a dedicated test Google identity that has access only to the disposable acceptance root; it must never use credentials capable of reaching the production/personal Hub.

Passing disposable live Drive acceptance still does not authorize production Hub use. Production-specific qualification remains a later, separate gate.
