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

`DRIVE_BACKEND.md` defines the backend-level copy-on-write object model. `DRIVE_TRANSPORT.md` refines that design into the HTTP/idempotency/failure contract, including pre-generated Drive IDs and the rule that transport failures are never canonical-state observations.

## Normative path layout for the MVP

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
│       ├── CONTROL.json
│       ├── CHANGE.json
│       ├── POSTCHECK.json       # only after an accepted semantic decision
│       ├── prepared/...
│       └── RECOVERY_BLOCK.json  # only when blocked
└── history/
    └── <change_id>/
        ├── HISTORY.json
        └── old/...
```

A directory name does not itself grant trust. Core verifies schemas, exact hashes, path safety and actual filesystem state.

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
- exactly one ready change visible when starting a new transaction;
- global non-reuse of a `change_id` when matching durable history already exists;
- exact equality between READY, CHANGE, MASTER, CONTROL and HISTORY identities for one active transaction;
- a REPLACE must actually change the declared fingerprint rather than encode a no-op.

## Schema compatibility

Unknown properties are rejected in v1. A future schema revision must be explicit; Core must never silently interpret unknown fields from a newer schema.
