# Keelaryn Project → RESULT → Reconciliation protocol

**Status:** zero-based MVP development contract.  
**Architecture baseline:** Zero-Based Architecture r2.

This contract defines the durable boundary between semantic Project work and serialized Reconciliation. It does not change the deterministic Core `CHANGE.json` format.

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
    ├── claims/
    │   └── <project_id>/
    │       └── <result_id>/
    │           ├── CLAIM_PLAN.json       # durable reserved IDs
    │           ├── RESULT.md             # exact claimed copy
    │           ├── RESULT.json           # exact claimed copy
    │           └── CLAIM.json            # created last; authority
    ├── changes/
    └── postcheck/
```

`work/projects/` and `work/reconciliation/claims/` are structural Hub folders created and verified by Drive bootstrap. Project `state-history/` is created lazily on the first non-no-op STATE update.

Reconciliation's own durable semantic `STATE.md` remains required by Architecture r2 but is not defined by this Project-state transaction contract yet. It should reuse an equivalent safe state primitive rather than introduce an unrelated overwrite mechanism.

## 2. Project STATE

Every project owns `STATE.md`. It is mutable working state, not canonical truth and not a publication instruction. It records at minimum the architecture-defined goal, current state, working findings, canonical dependencies, open work, next action and expected canonical effects.

MVP permits one active writer in one project work area at a time. Additional machine-enforced project locking is deferred.

### 2.1 No in-place overwrite

Google Drive backend v1 forbids in-place content replacement. Project `STATE.md` therefore uses a copy-on-write object transition.

For one update identity `<update_id>`, the durable record is:

```text
state-history/<update_id>/
├── PLAN.json
├── NEW.md      # exists only before publication
├── OLD.md      # retained previous exact STATE object
└── DONE.json   # created last after verified NEW publication
```

A completed update normally has `PLAN.json + OLD.md + DONE.json`; the NEW exact Drive object has become the project's current `STATE.md`.

### 2.2 STATE update transaction

For a new non-no-op STATE update:

1. require one exact current `STATE.md`;
2. block if another update is incomplete or historical STATE authority is invalid;
3. create/resolve `state-history/<update_id>/`;
4. publish immutable `PLAN.json` before removing current STATE;
5. `PLAN.json` binds exact project/update folder IDs, exact OLD ID/fingerprint, reserved NEW ID/fingerprint and reserved DONE marker ID;
6. create and verify exact `NEW.md` using the reserved NEW ID;
7. freshly revalidate exact OLD immediately before publication;
8. move OLD from project `STATE.md` to this update's `OLD.md`;
9. move exact NEW from `NEW.md` to project `STATE.md`;
10. verify NEW bytes and exact object identity at the current STATE location;
11. create `DONE.json` last, binding the exact PLAN digest and old/new identities.

No-op updates are rejected before creating `state-history/` or a new update folder when no matching transaction already exists. Repeating the same completed `<update_id>` with the same exact NEW bytes is idempotent and returns the same durable authority.

### 2.3 Restart classification

There is no mutable progress counter. Restart derives STATE transition reality only from exact Drive IDs, locations and fingerprints:

- `OLD`: OLD is still project `STATE.md`; NEW is update `NEW.md`;
- `GAP`: OLD is update `OLD.md`; NEW is update `NEW.md`; no project `STATE.md` exists;
- `NEW`: OLD is update `OLD.md`; NEW exact object is project `STATE.md`.

Any other configuration is ambiguous and blocks automated continuation. Ordinary `STATE.md` reads fail closed during GAP.

Lost responses after PLAN creation, NEW creation, OLD displacement, NEW publication or DONE creation are recovered by re-observing exact durable state. The implementation also tolerates restart after pre-authority structural folder creation without treating folder names as transaction authority.

### 2.4 Historical chain

Old STATE bytes are retained. Before a new update starts, previous update folders must have valid exact PLAN/OLD/DONE authority. A prior DONE marker existing by name is insufficient: PLAN/DONE bytes, bound IDs and old/new fingerprints are revalidated.

A later update may move an earlier update's NEW object from current `STATE.md` into the later update's `OLD.md`; the exact object ID and bytes therefore form a retained state chain without duplicating that object merely for history.

Tampered historical PLAN, DONE, OLD or referenced NEW material blocks a later STATE update rather than allowing history corruption to be silently bypassed.

## 3. RESULT publication

`RESULT.md` is the semantic proposal. It contains the architecture-defined project identity, readiness, findings, evidence, canonical inputs, proposed semantic effects, expected canonical targets and unresolved uncertainties.

`RESULT.json` is a small machine-readable marker created **after** final `RESULT.md`. It binds:

- `project_id`;
- `result_id`;
- the canonical epoch on which the project's canonical reading was based;
- exact SHA-256 and size of `RESULT.md`;
- the canonical input fingerprints observed by the Project;
- expected canonical target paths.

A stale `base_canonical_epoch` is allowed. Project work may finish after another canonical publication. Reconciliation, not Project, is responsible for re-reading current canonical truth and resolving parallel changes.

A RESULT is discoverable for claim only when:

1. the project folder is uniquely named by `project_id`;
2. the result folder is uniquely named by `result_id` inside that project;
3. exactly one live `RESULT.md` and one live `RESULT.json` exist;
4. `RESULT.json` validates and names the enclosing project/result;
5. downloaded `RESULT.md` bytes exactly match its marker fingerprint.

Duplicate names or ambiguous objects block claim.

## 4. Claim preparation

Claims are scoped by **both** project and result identity:

```text
work/reconciliation/claims/<project_id>/<result_id>/
```

This prevents two projects that legitimately use the same friendly `result_id` from sharing one claim namespace.

Reconciliation never uses Project bytes as long-lived authority after claim. Before copying the Result, it writes `CLAIM_PLAN.json`. The plan records:

- exact source folder/file IDs and fingerprints;
- exact Project/Result identity and base epoch;
- exact claim folder ID;
- pre-reserved destination IDs for claimed `RESULT.md`, claimed `RESULT.json` and final `CLAIM.json`.

The plan is immutable. It exists so a crash or lost Drive response never forces Reconciliation to allocate replacement identities or infer which copy is authoritative.

## 5. Claim publication

Using only IDs from the exact claim plan, Reconciliation:

1. freshly verifies source `RESULT.md` and `RESULT.json` IDs, locations and bytes;
2. copies both files into the claim folder using their reserved destination IDs;
3. verifies both copied bytes and fingerprints;
4. creates `CLAIM.json` **last** using the reserved claim-marker ID.

`CLAIM.json` binds the exact claim-plan fingerprint and the exact source/claimed object identities and fingerprints.

If a Drive mutation response is lost, restart re-observes the reserved IDs from `CLAIM_PLAN.json`. It does not allocate replacement IDs in the same claim.

## 6. Authority after claim

Before `CLAIM.json`, the claim is incomplete and must not authorize Reconciliation output.

After valid `CLAIM.json` exists:

- claimed `RESULT.md` + claimed `RESULT.json` are Reconciliation's immutable input authority;
- source Project objects remain provenance but are no longer required for continuation;
- source Project mutation after claim does not rewrite the claim;
- mutation of claimed copies, claim plan or claim marker blocks use of that claim;
- a second incompatible claim for the same `<project_id>/<result_id>` is forbidden;
- the same `result_id` in a different project is an independent claim identity.

The logical rule remains that a claimed Project RESULT should not be edited. Physical permission separation is deferred; exact claim copies ensure Reconciliation does not depend on that logical rule for restart correctness.

## 7. Reconciliation → Core boundary

Reconciliation reads the claimed RESULT, re-reads current canonical truth using the SAFE/epoch reader protocol, uses Router + Search, resolves conflicts and prepares final canonical operations.

The deterministic Core boundary remains unchanged:

```text
claimed RESULT
  → semantic Reconciliation
  → CHANGE.json + prepared/*
  → READY.json created last
  → existing Core Ready Change ingestion
```

RESULT/CLAIM provenance is Reconciliation authority. Core does not interpret it and does not gain semantic responsibilities. `CHANGE.json` remains `keelaryn.change.v1`.

The deterministic disposable integration suite proves both outcomes through the full path:

- Project → RESULT → Claim → Ready Change → Core → PASS → clean READY;
- Project → RESULT → Claim → Ready Change → Core → FAIL → mandatory rollback → clean READY.

This is development/model evidence, not live Google Drive/VPS or production qualification.

## 8. Serialization

Project work and unclaimed results may exist in parallel. Canonical publication remains serialized by the existing rule that at most one Ready Change may be available to Core.

Reconciliation may claim multiple project/results over time, but each Ready Change is prepared against one current canonical epoch and goes through the existing Core transaction independently.

For Project STATE, MVP permits at most one incomplete STATE transition in one project's `state-history/`. Completed historical transitions may coexist indefinitely.

## 9. Fail-closed rules

Project STATE or Reconciliation claim handling blocks on at least:

- duplicate/missing project, result, state-history or claim folders where uniqueness is required;
- duplicate/missing RESULT files;
- invalid RESULT marker or RESULT.md fingerprint mismatch;
- no-op STATE update under a new update identity;
- incompatible reuse of a STATE `update_id`;
- malformed/tampered STATE PLAN or DONE authority;
- damaged or missing retained OLD/NEW STATE objects;
- unknown STATE object location or more than one current `STATE.md`;
- another incomplete STATE update;
- claim folder collision with incompatible material;
- invalid/tampered claim plan;
- reserved-ID collision with a different object;
- claimed-copy byte mismatch;
- duplicate or mismatched `CLAIM.json`;
- identity disagreement between plan, Result and claim.

No conflict is resolved by choosing the newest object, the first listing result or a friendly-name heuristic.

## 10. Non-goals

This MVP contract does not automate semantic Reconciliation, decide whether findings are true, rank conflicting evidence, add multi-model review, enforce physical Drive permissions or implement multiple writers per project. Those remain semantic/hardening concerns described elsewhere in the architecture and roadmap.
