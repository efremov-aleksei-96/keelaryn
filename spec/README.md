# Keelaryn Zero-Based Protocol Specification

This directory contains machine-facing contracts derived from `docs/ZERO_BASED_ARCHITECTURE.md` r2.

The specification is intentionally independent from Manager 4.x. Legacy Manager schemas, release metadata and state machines are not inherited.

## Layout

```text
spec/
├── README.md
├── STATE_MACHINE.md
├── WORKFLOW.md
├── DRIVE_BACKEND.md
├── DRIVE_TRANSPORT.md
├── DRIVE_ORCHESTRATION.md
├── DRIVE_DISCOVERY.md
├── DRIVE_SERVICE.md
├── PILOT.md
├── MIGRATION.md
├── examples/
│   └── MASTER.ready.json
└── schemas/
    ├── common.schema.json
    ├── master.schema.json
    ├── change.schema.json
    ├── ready.schema.json
    ├── postcheck.schema.json
    ├── control.schema.json
    ├── history.schema.json
    ├── recovery-block.schema.json
    ├── result.schema.json
    ├── drive-result-claim-plan.schema.json
    ├── drive-result-claim.schema.json
    ├── work-state-update-plan.schema.json
    └── work-state-update.schema.json
```

`WORKFLOW.md` defines Workspace navigation, the shared copy-on-write `STATE.md` transition for Project and Reconciliation work, RESULT publication, project-scoped Reconciliation claim authority and the semantic handoff into the existing Ready Change/Core boundary. `DRIVE_BACKEND.md` defines the backend-level copy-on-write object model. `DRIVE_TRANSPORT.md` defines HTTP/idempotency/failure semantics, including pre-generated Drive IDs and the rule that transport failures are never canonical-state observations. `DRIVE_ORCHESTRATION.md` defines immutable transaction authority, copy-on-write MASTER transitions, independent pre-UNSAFE snapshots and state-derived recovery. `DRIVE_DISCOVERY.md` defines restart bootstrap from the active locator to the exact immutable transaction bundle, including zero-MASTER gap recovery without process-local transaction memory. `DRIVE_SERVICE.md` composes bootstrap, Ready Change ingestion, transaction factory, polling, exact Ready-marker consumption and terminal locator cleanup into the Drive MVP service lifecycle. `PILOT.md` defines the private limited-real-Hub-subset pilot boundary: explicit read-only-copy allowlisting, immutable private pack verification, disposable-only import, ordinary Ready Change/Core publication and sanitized evidence. `MIGRATION.md` defines the post-pilot production migration contract: copy-and-cutover rather than in-place transformation, explicit source/mapping authority, disposable full rehearsal, separate production-target construction and cutover transactions, source-drift handling, rollback and qualification requirements.

## Normative logical path layout for the MVP

```text
Keelaryn Hub/
├── README.md
├── MASTER.json
├── INDEX.md
├── canonical/
├── work/
│   ├── projects/
│   │   └── <project_id>/
│   │       ├── STATE.md
│   │       ├── state-history/<update_id>/
│   │       │   ├── PLAN.json
│   │       │   ├── OLD.md
│   │       │   └── DONE.json
│   │       ├── results/<result_id>/
│   │       │   ├── RESULT.md
│   │       │   └── RESULT.json
│   │       └── migration-import/...       # optional, migration-only non-authoritative preserved material
│   └── reconciliation/
│       ├── STATE.md
│       ├── state-history/<update_id>/
│       │   ├── PLAN.json
│       │   ├── OLD.md
│       │   └── DONE.json
│       ├── claims/<project_id>/<result_id>/
│       │   ├── CLAIM_PLAN.json
│       │   ├── RESULT.md
│       │   ├── RESULT.json
│       │   └── CLAIM.json
│       ├── changes/<change_id>/
│       │   ├── CHANGE.json
│       │   ├── READY.json
│       │   └── prepared/...
│       └── postcheck/<change_id>.json
├── control/
│   └── active/
│       └── ACTIVE_TRANSACTION.json   # Drive restart locator while active/prepared
├── history/
│   └── <change_id>/
│       ├── <change_id>.DRIVE_BUNDLE.json
│       ├── <change_id>.READY.consumed.json   # after terminal publication, when source marker existed
│       ├── stage/
│       ├── originals/
│       ├── rejected/
│       ├── snapshots/
│       ├── receipts/
│       ├── markers/
│       └── master-transitions/
└── archive/
    └── migration/<candidate_id>/...  # optional, migration-only historical material outside active work/canonical authority
```

Fresh Drive bootstrap creates the structural folders plus deterministic human-readable `README.md`, `INDEX.md` and initial `work/reconciliation/STATE.md`, freshly verifies them, and publishes `MASTER.json` last. Lost responses for every bootstrap mutation are recovered by re-observation. Once MASTER exists, bootstrap is verification-only: it never creates a missing required human/structural object. `INDEX.md` and Reconciliation STATE may legitimately change afterward and are therefore required by identity/type, not forced back to bootstrap template bytes.

`work/projects/<project_id>/migration-import/` and `archive/migration/<candidate_id>/` are optional migration-only preservation namespaces. They are not created by ordinary fresh bootstrap and never become canonical truth merely by existing. Project preservation remains subordinate to an explicitly initialized Project but is outside Project STATE/RESULT authority; archive preservation is outside active canonical/work authority. Migration mapping must bind every preserved source to one exact Hub-relative destination in the appropriate namespace before any target materialization occurs.

During an incomplete work STATE transition, `NEW.md` may also exist in the update folder. Between OLD displacement and NEW publication there may intentionally be no current `STATE.md`; reads fail closed during that GAP. `NEW.md` becomes the exact new current `STATE.md`, and `DONE.json` is created only after that publication is verified.

Project and Reconciliation use the same deterministic COW engine. Their durable PLAN/DONE records bind `owner_kind` (`PROJECT` or `RECONCILIATION`), `owner_id` and exact owner folder ID, so authority from one semantic role cannot be replayed as the other. Initial Reconciliation STATE publication belongs to bootstrap; the semantic Reconciliation service only verifies those initial bytes and performs later COW updates.

Workspace is an initiator/navigator rather than a new storage authority. Its deterministic service lists, creates, reads and updates Project work areas using the existing Project/work-state protocols. Portfolio listing fails closed on ambiguous or incomplete direct Project structure rather than silently omitting it. `python -m keelaryn_core.workspace_cli` exposes that surface for an initialized Drive Hub and is included in exact-head VPS payload validation.

The limited-subset pilot does not extend Hub authority. `PILOT_SOURCE.json` and the resulting private pilot pack are local test inputs only. The importer converts the exact verified pack into the existing Ready Change/Core path and may target only a fresh disposable Hub. Private pack bytes never become repository fixtures or development artifacts.

Production migration is a separate copy-and-cutover protocol. A qualified migration constructs a distinct zero-based target from a frozen explicit source/mapping candidate, rehearses that exact candidate against a disposable Hub first, and treats target construction and production cutover as separate transactions. The existing production Hub remains read-only rollback material until cutover acceptance and later retirement are explicitly approved.

The local-filesystem backend may materialize equivalent control/history authority differently. A directory or object name does not itself grant trust. Core and workflow layers verify schemas, exact hashes, bound identities, path safety and actual filesystem/Drive state.

## Fingerprints

All content fingerprints in v1 are lowercase hexadecimal SHA-256 over exact file bytes plus exact byte length.

`CHANGE.json` identity is the SHA-256 of the exact UTF-8 bytes stored on disk. JSON reserialization is therefore a different change identity even when semantic fields are equivalent.

Project RESULT markers, claim plans/claims and work STATE transition records similarly bind exact byte fingerprints and Drive object identities where their contracts require them.

## Relative paths

Schema validation is only the first path-safety layer. Runtime validation MUST also reject:

- absolute paths;
- backslashes;
- empty segments, including trailing separators;
- `.` or `..` path segments;
- NUL characters;
- traversal after normalization;
- any resolved target outside its declared root;
- symlink/reparse-style escapes where the backend exposes them.

`target` paths in `CHANGE.json` are relative to `canonical/`. `prepared_path` paths are relative to the change directory. Snapshot paths in `HISTORY.json` are relative to that history directory. Migration preservation `destination` paths are Hub-relative and are valid only within the migration namespaces defined above.

For local-filesystem protocol v1, every canonical target's parent directory MUST already exist, be a real directory, and contain no symlink/reparse-style traversal component. ADD/REPLACE/DELETE operate on files only. Core does not implicitly create or delete canonical directories in v1. This keeps directory topology outside the file transaction until a separately specified directory operation is justified.

## Uniqueness rules not expressible cleanly in JSON Schema

Runtime MUST additionally enforce:

- unique `operation_id` values within one change;
- unique canonical `target` values within one change;
- exactly one unconsumed Ready Change visible when starting a new Core transaction;
- global non-reuse of a `change_id` when conflicting durable history already exists;
- exact equality between READY, CHANGE, MASTER and backend-specific immutable transaction authority for one active transaction;
- a REPLACE must actually change the declared fingerprint rather than encode a no-op;
- Project claim identity is the pair `<project_id>/<result_id>`, not `result_id` alone;
- Workspace portfolio enumeration requires unique valid Project folder names and mandatory Project STATE/results structure;
- at most one incomplete work STATE transition may exist for one owner;
- previous work STATE PLAN/OLD/DONE authority must validate before a later STATE transition begins;
- work STATE role identity and exact owner folder identity must match before restart continuation;
- every preservation-classified migration source has exactly one explicit destination and no two such sources share one destination;
- `PROJECT_WORK_IMPORT` destinations remain under `work/projects/<project_id>/migration-import/`;
- `ARCHIVE_ONLY` destinations remain under `archive/migration/<candidate_id>/`.

## Schema compatibility

Unknown properties are rejected in v1. A future schema revision must be explicit; Core and workflow layers must never silently interpret unknown fields from a newer schema.
