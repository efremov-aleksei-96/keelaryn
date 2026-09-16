# Keelaryn Zero-Based Protocol Specification

This directory contains machine-facing contracts derived from `docs/ZERO_BASED_ARCHITECTURE.md` r2.

The specification is intentionally independent from Manager 4.x. Legacy Manager schemas, release metadata and state machines are not inherited.

## Layout

```text
spec/
├── README.md
├── STATE_MACHINE.md
├── DRIVE_BACKEND.md
├── DRIVE_TRANSPORT.md
├── DRIVE_ORCHESTRATION.md
├── DRIVE_DISCOVERY.md
├── DRIVE_SERVICE.md
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
    └── recovery-block.schema.json
```

`DRIVE_BACKEND.md` defines the backend-level copy-on-write object model. `DRIVE_TRANSPORT.md` defines HTTP/idempotency/failure semantics, including pre-generated Drive IDs and the rule that transport failures are never canonical-state observations. `DRIVE_ORCHESTRATION.md` defines immutable transaction authority, copy-on-write MASTER transitions, independent pre-UNSAFE snapshots and state-derived recovery. `DRIVE_DISCOVERY.md` defines restart bootstrap from the active locator to the exact immutable transaction bundle, including zero-MASTER gap recovery without process-local transaction memory. `DRIVE_SERVICE.md` composes bootstrap, Ready Change ingestion, transaction factory, polling, exact Ready-marker consumption and terminal locator cleanup into the Drive MVP service lifecycle.

## Normative logical path layout for the MVP

```text
Keelaryn Hub/
├── MASTER.json
├── canonical/
├── work/
│   └── reconciliation/
│       ├── changes/<change_id>/
│       │   ├── CHANGE.json
│       │   ├── READY.json
│       │   └── prepared/...
│       └── postcheck/<change_id>.json
├── control/
│   └── active/
│       └── ACTIVE_TRANSACTION.json   # Drive restart locator while active/prepared
└── history/
    └── <change_id>/
        ├── <change_id>.DRIVE_BUNDLE.json
        ├── <change_id>.READY.consumed.json   # after terminal publication, when source marker existed
        ├── stage/
        ├── originals/
        ├── rejected/
        ├── snapshots/
        ├── receipts/
        ├── markers/
        └── master-transitions/
```

The local-filesystem backend may materialize equivalent control/history authority differently. A directory or object name does not itself grant trust. Core verifies schemas, exact hashes, bound identities, path safety and actual filesystem/Drive state.

## Fingerprints

All content fingerprints in v1 are lowercase hexadecimal SHA-256 over exact file bytes plus exact byte length.

`CHANGE.json` identity is the SHA-256 of the exact UTF-8 bytes stored on disk. JSON reserialization is therefore a different change identity even when semantic fields are equivalent.

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

`target` paths in `CHANGE.json` are relative to `canonical/`. `prepared_path` paths are relative to the change directory. Snapshot paths in `HISTORY.json` are relative to that history directory.

For local-filesystem protocol v1, every canonical target's parent directory MUST already exist, be a real directory, and contain no symlink/reparse-style traversal component. ADD/REPLACE/DELETE operate on files only. Core does not implicitly create or delete canonical directories in v1. This keeps directory topology outside the file transaction until a separately specified directory operation is justified.

## Uniqueness rules not expressible cleanly in JSON Schema

Core MUST additionally enforce:

- unique `operation_id` values within one change;
- unique canonical `target` values within one change;
- exactly one unconsumed Ready Change visible when starting a new transaction;
- global non-reuse of a `change_id` when conflicting durable history already exists;
- exact equality between READY, CHANGE, MASTER and backend-specific immutable transaction authority for one active transaction;
- a REPLACE must actually change the declared fingerprint rather than encode a no-op.

## Schema compatibility

Unknown properties are rejected in v1. A future schema revision must be explicit; Core must never silently interpret unknown fields from a newer schema.
