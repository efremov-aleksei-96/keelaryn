# Keelaryn Project → RESULT → Reconciliation protocol

**Status:** zero-based MVP development contract.  
**Architecture baseline:** Zero-Based Architecture r2.

This contract defines Workspace navigation, durable working state for Project/Reconciliation roles and the boundary from semantic Project work to serialized canonical publication. It does not change deterministic Core `CHANGE.json` semantics.

## 1. Logical layout

```text
work/
├── projects/
│   └── <project_id>/
│       ├── STATE.md
│       ├── state-history/
│       │   └── <update_id>/
│       │       ├── PLAN.json
│       │       ├── OLD.md
│       │       └── DONE.json
│       └── results/
│           └── <result_id>/
│               ├── RESULT.md
│               └── RESULT.json          # created last
└── reconciliation/
    ├── STATE.md
    ├── state-history/
    │   └── <update_id>/
    │       ├── PLAN.json
    │       ├── OLD.md
    │       └── DONE.json
    ├── claims/
    │   └── <project_id>/
    │       └── <result_id>/
    │           ├── CLAIM_PLAN.json
    │           ├── RESULT.md
    │           ├── RESULT.json
    │           └── CLAIM.json            # created last; authority
    ├── changes/
    └── postcheck/
```

`work/projects/` and `work/reconciliation/claims/` are structural Hub folders created/verified by Drive bootstrap. Fresh Drive bootstrap also publishes the initial Reconciliation `STATE.md` before `MASTER.json`. After MASTER exists, bootstrap is read-only and a missing Reconciliation STATE is a structural failure; semantic services do not recreate it.

## 2. Shared durable STATE contract

Project and Reconciliation both require durable `STATE.md` so a new chat can continue without the previous transcript. They use one shared copy-on-write transition engine and one durable schema family:

- `keelaryn.work-state-update-plan.v1`;
- `keelaryn.work-state-update.v1`.

Role identity is part of transaction authority:

- Project: `owner_kind = PROJECT`, `owner_id = <project_id>`;
- Reconciliation: `owner_kind = RECONCILIATION`, `owner_id = reconciliation`.

PLAN also binds the exact owner-folder Drive ID. A PLAN/DONE authority for one role or owner cannot be replayed for another.

### 2.1 No in-place overwrite

Drive backend v1 forbids in-place content replacement. A STATE update uses:

```text
state-history/<update_id>/
├── PLAN.json
├── NEW.md      # exists only before publication
├── OLD.md      # retained previous exact STATE object
└── DONE.json   # created last after verified NEW publication
```

A normally completed update contains `PLAN.json + OLD.md + DONE.json`; the exact NEW object is now the owner's current `STATE.md`.

### 2.2 Update transaction

For a new non-no-op update:

1. require exactly one owner folder and one exact current `STATE.md`;
2. validate all prior STATE history and block if another update is incomplete;
3. create/resolve `state-history/<update_id>/`;
4. publish immutable `PLAN.json` before removing current STATE;
5. PLAN binds role/owner identity, exact OLD ID/fingerprint, reserved NEW ID/fingerprint and reserved DONE ID;
6. create/verify exact `NEW.md` with the reserved NEW ID;
7. freshly verify exact OLD immediately before displacement;
8. move OLD from current `STATE.md` to this update's `OLD.md`;
9. move exact NEW from `NEW.md` to current `STATE.md`;
10. verify NEW bytes and exact object identity;
11. create `DONE.json` last, binding exact PLAN digest and old/new identities.

A new update with bytes identical to current STATE is rejected before creating new transition material. Repeating an existing completed `<update_id>` with the same exact NEW bytes is idempotent.

### 2.3 Restart classification

No mutable progress counter exists. Restart derives state only from exact IDs, locations and fingerprints:

- `OLD`: OLD is current `STATE.md`; NEW is update `NEW.md`;
- `GAP`: OLD is update `OLD.md`; NEW is update `NEW.md`; current `STATE.md` is absent;
- `NEW`: OLD is update `OLD.md`; exact NEW is current `STATE.md`.

Anything else blocks. Ordinary STATE reads fail closed during GAP.

Lost mutation responses after structural creation, PLAN, NEW, OLD displacement, NEW publication or DONE creation are recovered by re-observing durable state. Existing historical PLAN/OLD/DONE authority is revalidated before a later update begins; a DONE filename alone is never trusted.

A later transition may move an earlier transition's NEW exact object into its own `OLD.md`. Exact object identity therefore forms a retained state chain without duplicating the same state merely for history.

## 3. Workspace surface

Workspace is the Project initiator/navigator. It is not canonical publication authority and introduces no new persistence format.

The deterministic Drive Workspace service exposes four MVP operations:

- `list_projects()` — return all projects sorted by `project_id` with current STATE;
- `create_project(project_id, initial_state)` — create one exact Project folder, `results/` and initial `STATE.md`; exact replay is idempotent;
- `read_project(project_id)` — resolve one exact Project and current STATE;
- `update_project(project_id, update_id, new_state)` — delegate to the shared Project STATE COW transaction.

Workspace listing fails closed rather than returning a partial portfolio when `work/projects/` contains a non-folder, invalid/duplicate project ID or a Project missing mandatory `STATE.md`/`results/` structure.

The machine-facing CLI is `python -m keelaryn_core.workspace_cli` with `list`, `read`, `create` and `update` commands. It uses the same Google credential contract as non-continuous Drive poller commands, accepts STATE input from a UTF-8 file or stdin for mutations, emits JSON and does not expose internal Drive object IDs. Transport uncertainty is surfaced as `REOBSERVE_REQUIRED`; no mutation is retried in place.

One active writer per Project remains an MVP logical invariant. This Workspace surface does not claim distributed multi-writer locking.

## 4. Project RESULT publication

`RESULT.md` is the semantic proposal and contains the architecture-defined findings/evidence/effects/uncertainties.

`RESULT.json` is created **after** final `RESULT.md` and binds:

- `project_id` and `result_id`;
- base canonical epoch used by the Project;
- exact RESULT.md SHA-256 and byte size;
- canonical input fingerprints observed by the Project;
- expected canonical target paths.

A stale base epoch is allowed because Reconciliation must re-read current canonical truth. A result is claimable only when the project/result folders and RESULT objects are unique/live, marker identity matches enclosing folders and RESULT.md bytes match its marker fingerprint.

## 5. Reconciliation claim

Claim namespace is scoped by both identities:

```text
work/reconciliation/claims/<project_id>/<result_id>/
```

Before copying source RESULT objects, Reconciliation writes immutable `CLAIM_PLAN.json`, binding exact source IDs/fingerprints, exact claim folder and reserved destination IDs for claimed RESULT.md, RESULT.json and final CLAIM.json.

Using only those reserved identities it then:

1. freshly verifies source RESULT IDs, locations and bytes;
2. copies RESULT.md and RESULT.json;
3. verifies claimed bytes/fingerprints;
4. creates `CLAIM.json` **last**.

`CLAIM.json` binds exact claim-plan digest plus source/claimed identities. Lost mutation responses are recovered from PLAN-reserved IDs rather than allocating replacements or selecting objects by listing order.

## 6. Authority after claim

Before valid `CLAIM.json`, the claim is incomplete and cannot authorize Reconciliation output.

After CLAIM exists:

- claimed RESULT copies are Reconciliation's immutable input authority;
- Project source objects remain provenance but are not required for continuation;
- later Project-source mutation does not change the claim;
- mutation of claimed copies, CLAIM_PLAN or CLAIM blocks use;
- same `result_id` in another project is independent;
- incompatible reuse of the same `<project_id>/<result_id>` claim is forbidden.

Logical Project discipline still says a claimed RESULT should not be edited, but claim restart correctness does not depend on that discipline.

## 7. Reconciliation → Core boundary

Reconciliation reads claimed RESULT authority, updates its durable STATE as work progresses, re-reads current canonical truth under SAFE/epoch rules, resolves semantic conflicts and prepares final operations.

The Core boundary remains:

```text
claimed RESULT
  → semantic Reconciliation
  → CHANGE.json + prepared/*
  → READY.json created last
  → existing Core Ready Change ingestion
```

RESULT/CLAIM/work-STATE records are semantic-workflow authority. Core does not interpret them and `CHANGE.json` remains `keelaryn.change.v1`.

The deterministic disposable integration suite proves both terminal outcomes:

- Project → RESULT → Claim → Ready Change → Core → PASS → clean READY;
- Project → RESULT → Claim → Ready Change → Core → FAIL → mandatory rollback → clean READY.

This remains development/model evidence, not live Google Drive/VPS or production qualification.

## 8. Serialization

Projects and unclaimed Results may exist in parallel. Canonical publication remains serialized by the existing at-most-one-Ready-Change rule.

Each Project permits at most one incomplete STATE transition. Reconciliation likewise permits at most one incomplete STATE transition. Completed STATE history remains durable.

## 9. Fail-closed rules

Workflow handling blocks on at least:

- duplicate/missing structural folders where uniqueness is required;
- partial/ambiguous Project portfolio structure during Workspace listing;
- missing/duplicate/mismatched STATE, RESULT or claim objects;
- no-op STATE update under a new identity;
- incompatible reuse of STATE `update_id`;
- malformed/tampered STATE PLAN/DONE or retained OLD/NEW object;
- STATE owner role/folder identity mismatch;
- unknown STATE object location or multiple current STATE objects;
- another incomplete STATE transition;
- invalid RESULT marker or RESULT.md fingerprint mismatch;
- claim collision with incompatible material;
- invalid/tampered claim plan or reserved-ID collision;
- claimed-copy mismatch;
- duplicate/mismatched CLAIM authority;
- identity disagreement between plan, Result and claim.

No ambiguity is resolved by choosing newest, first-listed or friendly-name objects.

## 10. Non-goals

This contract does not automate semantic Reconciliation, judge finding truth, rank conflicting evidence, add multi-model review, enforce separate Drive identities or implement multiple simultaneous writers to one semantic work area. Those remain higher-level/hardening concerns in architecture and roadmap.
