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
│       └── results/
│           └── <result_id>/
│               ├── RESULT.md
│               └── RESULT.json          # created last
└── reconciliation/
    ├── STATE.md                         # semantic Reconciliation state
    ├── claims/
    │   └── <result_id>/
    │       ├── CLAIM_PLAN.json           # durable reserved IDs
    │       ├── RESULT.md                 # exact claimed copy
    │       ├── RESULT.json               # exact claimed copy
    │       └── CLAIM.json                # created last; authority
    ├── changes/
    └── postcheck/
```

`work/projects/` and `work/reconciliation/claims/` are structural Hub folders created and verified by Drive bootstrap.

## 2. Project STATE

Every project owns `STATE.md`. It is mutable working state, not canonical truth and not a publication instruction. It records at minimum the architecture-defined goal, current state, working findings, canonical dependencies, open work, next action and expected canonical effects.

MVP permits one active writer in one project work area at a time. Additional machine-enforced project locking is deferred.

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
2. the result folder is uniquely named by `result_id`;
3. exactly one live `RESULT.md` and one live `RESULT.json` exist;
4. `RESULT.json` validates and names the enclosing project/result;
5. downloaded `RESULT.md` bytes exactly match its marker fingerprint.

Duplicate names or ambiguous objects block claim.

## 4. Claim preparation

Reconciliation never uses Project bytes as long-lived authority after claim. It first creates a dedicated claim folder under `work/reconciliation/claims/<result_id>`.

Before copying the Result, Reconciliation writes `CLAIM_PLAN.json`. The plan records:

- exact source folder/file IDs and fingerprints;
- exact Project/Result identity and base epoch;
- the claim folder ID;
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
- a second different claim for the same `result_id` is forbidden.

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

## 8. Serialization

Project work and unclaimed results may exist in parallel. Canonical publication remains serialized by the existing rule that at most one Ready Change may be available to Core.

Reconciliation may claim multiple results over time, but each Ready Change is prepared against one current canonical epoch and goes through the existing Core transaction independently.

## 9. Fail-closed rules

Reconciliation claim preparation blocks on at least:

- duplicate/missing project or result folders;
- duplicate/missing RESULT files;
- invalid RESULT marker;
- RESULT.md fingerprint mismatch;
- claim folder collision with incompatible material;
- invalid/tampered claim plan;
- reserved-ID collision with a different object;
- claimed-copy byte mismatch;
- duplicate or mismatched `CLAIM.json`;
- identity disagreement between plan, Result and claim.

No conflict is resolved by choosing the newest object, the first listing result or a friendly name heuristic.

## 10. Non-goals

This MVP contract does not automate semantic Reconciliation, decide whether findings are true, rank conflicting evidence, add multi-model review, enforce physical Drive permissions or implement multiple writers per project. Those remain semantic/hardening concerns described elsewhere in the architecture and roadmap.
