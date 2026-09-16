# Keelaryn Zero-Based Architecture

**Architecture revision:** r2  
**Status:** accepted implementation baseline  
**Scope:** new minimal Keelaryn architecture; this document does not extend Manager 4.x requirements.

## 1. Purpose

Keelaryn is a software system for maintaining a durable user knowledge base across AI conversations and AI providers.

The **Keelaryn Hub** is the independent long-lived database of user context. It must remain useful without ChatGPT, without Keelaryn itself, and without Windows. The normal working Hub may live in Google Drive and synchronize to devices through ordinary Drive synchronization. It must remain readable offline with ordinary tools such as Obsidian.

The human user must not be the transport layer for ZIP/RETURN packages between AI chats and the Hub.

## 2. Legacy boundary

Manager 4.x, its tests, qualification framework, runtime and engineering primitives remain repository provenance and a source of previously validated technical techniques.

They are **not** requirements for the zero-based system. Mechanisms from Manager 4.x return only when a new requirement justifies them.

The following are therefore not inherited automatically:

- AI_CONTEXT;
- SOURCE archives;
- DISTRIBUTION archives;
- UPDATE package flow;
- Manager self-update machinery;
- the old Doctor contract;
- multi-Hub registry and active-instance machinery;
- global/per-instance inboxes;
- CANDIDATE / APPROVED / CURRENT ZIP topology;
- candidate transport;
- Workspace Checkout/Return;
- full-Hub rebuilds;
- GUI requirements;
- the old release topology.

Production Manager 4.x remains independent from this development line until a later, explicitly designed migration.

## 3. Logical Hub structure

The minimal logical Hub is:

```text
Keelaryn Hub/
├── README.md
├── MASTER.json
├── INDEX.md
├── canonical/
├── work/
│   ├── projects/
│   └── reconciliation/
├── control/
└── history/
```

### `README.md`

A short, stable protocol for humans and AI systems.

### `MASTER.json`

A small Core-owned system state record. At minimum it identifies:

- system state;
- `canonical_read_status`;
- active change;
- current stage;
- last completed change;
- `canonical_epoch`.

After a fully completed operation it returns to a clean `READY` state. Normal AI roles do not modify `MASTER.json`.

### `INDEX.md`

A router and navigation layer describing what exists, where it lives, and which canonical topic owns each class of truth.

Normal navigation is:

`Root INDEX → Domain INDEX → canonical document`.

INDEX files should not duplicate mutable subject truth unless duplication is necessary for routing.

### `canonical/`

The currently accepted truth. It may contain Markdown, PDF and other durable documents.

### `work/`

All unfinished work. Nothing under `work/` is accepted canonical truth.

### `control/`

Core-owned technical state for an active commit or recovery operation.

### `history/`

Previous states of canonical targets affected by changes, sufficient for rollback and per-change recovery. It is not a full snapshot of the Hub after every operation.

## 4. Canonical truth model

Every mutable fact has one canonical storage location. This does **not** imply one fact per file; canonical documents should be logically coherent and large enough that an AI does not need to open dozens of tiny files for one subject.

A project may discover a global fact without becoming its canonical owner.

Before creating a new canonical topic, the system must use:

1. Router / INDEX navigation;
2. Hub search.

Parallel truths should be avoided.

## 5. Project workflow

Projects may execute in parallel.

**Workspace** is the universal project initiator and navigator. Subject work occurs in separate Project Chats.

Each project owns a durable `STATE.md`, updated after every substantial decision rather than only at chat boundaries.

At minimum `STATE.md` records:

- goal;
- current state;
- working findings;
- canonical dependencies;
- open work;
- next action;
- expected canonical effects.

A new chat must be able to continue from `STATE.md` without reading the old chat transcript.

For the MVP, exactly one active writer is allowed for one project's work area at a time.

## 6. RESULT contract

Project Chats do not modify canonical data.

When a project is ready to hand off its findings, it creates `RESULT.md`. At minimum it contains:

- project identity;
- readiness;
- findings;
- evidence;
- canonical inputs;
- proposed semantic effects;
- expected canonical targets;
- unresolved uncertainties.

`RESULT.md` is a proposal to Reconciliation, not a commit instruction.

After Reconciliation claims a specific RESULT, that RESULT becomes immutable.

## 7. Reconciliation role

Reconciliation is a persistent role, but not one permanent chat.

All canonical publications are serialized. Project work may proceed in parallel, but canonical changes are accepted one at a time.

Reconciliation must:

- re-check the RESULT;
- re-read current canonical inputs;
- account for parallel changes completed after the project began;
- use Router + Search;
- find logical dependencies and conflicts;
- prepare final replacement/addition/deletion files;
- perform the semantic post-check after Core publication.

Reconciliation owns its own durable `STATE.md`.

## 8. Ready Change

Reconciliation prepares one exact change package.

For the MVP, at most one change may be in `READY_FOR_COMMIT` state at a time.

The package contains:

- strict `CHANGE.json`;
- prepared files;
- a separate ready marker.

The ready marker is created **last**. Once the marker exists, Reconciliation must not modify that change.

Core claims the exact identity of the ready change into its own `control/` state. Reconciliation does not write `MASTER.json`.

The exact JSON schema and state-machine vocabulary are defined in the next implementation phase, not by implication from Manager 4.x.

## 9. Keelaryn Core

The working name of the new deterministic program is **Keelaryn Core**. The name may be revised later without changing the architecture.

The first implementation targets a Linux VPS.

Core does not interpret the semantic meaning of Hub content. It is a deterministic safe-publication executor.

The MVP supports three canonical operations:

- `ADD`;
- `REPLACE`;
- `DELETE`.

For an accepted ready change, Core performs the following logical sequence:

1. read `MASTER.json`;
2. recover any unfinished prior operation if present;
3. validate the ready change;
4. validate expected old fingerprints;
5. validate prepared new fingerprints;
6. save previous state for all affected targets;
7. verify the saved previous-state snapshots;
8. transition canonical readability to `UNSAFE` before the first canonical replacement;
9. apply operations;
10. after every operation, re-read and verify the resulting target;
11. wait for Reconciliation semantic post-check;
12. on PASS, clean active technical state and return to `READY`;
13. on FAIL, perform mandatory rollback, verify it, clean active technical state and return to `READY`.

Core fails closed on ambiguity.

## 10. Crash and restart invariants

Every critical stage must be durable and idempotent.

After restart, Core does not trust process memory. It derives reality from:

- `MASTER.json`;
- Core control records;
- actual canonical files;
- fingerprints.

For every target, recovery must classify actual state as exactly one of:

- `OLD`;
- `NEW`;
- `UNKNOWN`.

`UNKNOWN` blocks automated continuation and requires recovery handling.

Immediately before every destructive `REPLACE` or `DELETE`, Core must revalidate the original target again.

## 11. Rollback invariants

A semantic post-check FAIL in the MVP **always** causes rollback.

Forward repair inside the failed publication is forbidden. A later repair is a new change with a new identity.

Rollback restores the previous state of each target:

- `REPLACE` → old bytes;
- `DELETE` → old bytes;
- `ADD` → previous state was `ABSENT`, so the added file is removed.

If the current target unexpectedly differs from the expected NEW state, Core enters `RECOVERY_BLOCKED` rather than overwriting unknown bytes.

## 12. SAFE / UNSAFE canonical reads

Before the first canonical replacement, the old canonical state remains readable and safe.

From the start of canonical mutation until semantic PASS or verified rollback:

`canonical_read_status = UNSAFE`.

Ordinary AI readers must not use canonical data while it is UNSAFE. Reconciliation for the active change is the special reader allowed to inspect the publication for semantic post-check.

### Consistent reader protocol

An ordinary AI reader must:

1. read `MASTER.json`;
2. require `canonical_read_status = SAFE` and remember `canonical_epoch`;
3. read the necessary canonical files;
4. re-read `MASTER.json`;
5. use the read data only if status is still SAFE and the epoch is unchanged.

After every UNSAFE window, Core increments `canonical_epoch`, including when a commit is rolled back.

## 13. Cleanup invariant

A successful transaction must end in a clean state.

Temporary prepared/control data are removed. History remains. `MASTER.json` is cleared to:

```text
state: READY
canonical_read_status: SAFE
active_change: none
current_stage: none
```

Residual active state after a reported success is an error.

## 14. Core wakeup

The MVP uses polling from the Linux VPS over the Hub's master/ready state.

No webhook or API-driven wakeup is required for the first version. The wakeup cause is untrusted and semantically irrelevant; on every invocation, Core independently determines the required action from durable Hub state.

Event-driven Google Drive wakeup is deferred to the roadmap.

## 15. History and backup boundary

Per-change `history/` required for rollback is part of the MVP.

Unchanged large immutable files such as PDFs are not recopied for every change.

An automatic independent disaster-backup system is not part of the MVP. The owner may continue making independent copies of the whole Hub through separate means.

No automatic history retention/deletion policy is implemented in the MVP.

## 16. Logical permissions

The logical authority model is:

- Project AI writes only its own project work area;
- Reconciliation AI writes reconciliation work, prepared changes and post-check results;
- Core writes `MASTER.json`, `control/`, `canonical/`, `history/` and cleanup state;
- the human owner retains physical full access.

The first version may operate through one Google account with protocol-level separation. Separate Drive identities and physical permission separation are a hardening item, not an MVP blocker.

## 17. Version discipline

Development commits are identified by commit SHA, branch and CI runs. They are not product releases.

Architecture documents use explicit architecture revisions such as `r2`.

Product versions are assigned only to actual distributable milestones. A possible sequence is:

```text
development commits
→ 0.1.0 first usable preview
→ development commits
→ 1.0.0-rc.1 frozen public candidate
→ 1.0.0 public qualified release
```

`0.2.0` exists only if a distinct distributed preview milestone is actually needed.

The first public `1.0.0` must provide, at minimum:

- install/deployment documentation;
- usable Hub bootstrap;
- Workspace/Project workflow;
- durable project/reconciliation STATE;
- RESULT → Reconciliation flow;
- VPS Core;
- crash/restart recovery;
- safe snapshot/publication behavior;
- rollback on semantic FAIL;
- clean READY completion;
- Hub portability;
- public qualification evidence.

## 18. Implementation sequence

Implementation proceeds in this order:

1. record this Zero-Based Architecture r2 and the durable roadmap in GitHub;
2. develop on a new zero-based `dev/**` line, separate from unfinished Manager 4.17.13 work;
3. leave production Manager 4.17.12 unchanged;
4. define strict JSON schemas and the deterministic state machine;
5. implement Core against a disposable local filesystem first;
6. add fault-injection tests covering a crash after each critical step, external modification, invalid hashes, duplicate ready changes, rollback and clean READY;
7. add the Google Drive backend only after the local filesystem model is proven;
8. deploy Core on a Linux VPS;
9. run a disposable end-to-end Project → RESULT → Reconciliation → Core cycle;
10. pilot against a copy of a limited subset of the real Hub;
11. design production-Hub migration only after that pilot succeeds.

Production is not modified during these phases.

## 19. Repository transition strategy

The zero-based line preserves existing Manager 4.x source and tests in place as legacy provenance. It does not perform a mass rename or deletion.

New implementation material is added alongside the legacy system:

```text
docs/
  ZERO_BASED_ARCHITECTURE.md
  ROADMAP.md
spec/                 # next phase: schemas and deterministic state-machine contracts
core/                 # next phase: new implementation
tests/core/           # next phase: zero-based deterministic/fault-injection tests
```

The existing `manager/`, Manager-specific tests and old release tooling remain untouched until a later cleanup is independently justified. No legacy mechanism is imported into `spec/` or `core/` merely because it already exists.
