# P0-34 — Protected control storage contract

Date: 2026-09-30
Status: **P0-34A PLATFORM ADAPTER FIRST SLICE**

## Goal

Resolve the filesystem-protection part of `AUDIT_SECURITY_H3_STATE_DB_FILESYSTEM_PROTECTION` before durable state is exposed as a supported user runtime.

The security boundary is one dedicated directory:

```text
<control-dir>/
├── state.db
├── search.db
└── SQLite journal/WAL/SHM side files when present
```

SQLite side files are intentionally covered by protecting the directory rather than trying to enumerate only the main database filenames.

## Architecture boundary

Platform filesystem protection is not Artifact/Revision/Observation semantics.

The low-level SQLite state/search packages remain OS-neutral. A separate `internal/controlstorage` adapter owns:

- control-directory path resolution;
- secure first creation;
- read-only verification of an existing control directory;
- platform-specific ownership / permission / ACL policy.

The adapter does not own corpus identity, database schemas, search semantics or recovery policy.

## Existing-directory rule

Keelaryn MUST NOT recursively chmod or replace ACLs on an arbitrary existing user directory.

Therefore:

- missing dedicated control directory → create it with the platform security policy;
- existing directory that already satisfies the policy → accept;
- existing directory that does not satisfy the policy → fail closed;
- missing parent hierarchy → fail instead of silently creating arbitrary ancestors;
- symlink/reparse-point control boundaries are rejected.

A later explicit migration tool may harden/move legacy control state, but ordinary runtime open does not silently mutate an insecure existing directory.

## Unix policy

For Linux and other Unix-like adapters in this slice:

- create dedicated directory owner-only;
- normalize the newly-created directory to mode `0700`;
- verify mode remains exactly `0700`;
- verify owner UID equals current effective UID;
- never repair an existing insecure directory in `OpenExisting`.

A protected directory also prevents access to SQLite side files regardless of their transient per-file creation mode.

## Windows policy

Windows uses native DACL semantics through the already-pinned `golang.org/x/sys/windows`.

The directory is created atomically with a security descriptor rather than created permissively and tightened later.

Required DACL:

- current process user — full access, inherited by child files/directories;
- LocalSystem — full access, inherited;
- Builtin Administrators — full access, inherited;
- no additional ACEs;
- DACL is protected from parent inheritance;
- owner is the current process user.

Verification rejects reparse points, inherited/unprotected DACLs, extra/duplicate principals, non-full-access ACEs, wrong inheritance flags and wrong owner.

## Android equivalent

Android control state must live in application-private storage and use the Unix ownership/mode adapter where applicable.

This contract does **not** claim Android runtime support. H2 still requires an Android-capable durable SQLite backend plus compile/emulator/device qualification.

## P0-34A scope

This first slice qualifies the platform control-directory adapter only.

It does not yet:

- change P0-32/P0-33 CLI flags;
- move existing state;
- open SQLite through the adapter;
- resolve H3 completely;
- add MCP/HTTP/web;
- mutate corpus content.

P0-34B will compose the qualified adapter into the executable runtime so durable state/search paths are derived from `--control-dir`.

## Reuse

- standard Go filesystem/path APIs;
- `golang.org/x/sys/windows v0.48.0` already present in the dependency graph;
- `golang.org/x/sys/unix` from the same module.

No new ACL package or OS abstraction framework is introduced.
