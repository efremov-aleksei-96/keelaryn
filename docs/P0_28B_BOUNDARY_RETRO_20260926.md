# P0-28B Boundary Retrospective — 2026-09-26

Status: **HARDENING IMPLEMENTED / QUALIFICATION PENDING**

Authority: `KEELARYN_CANONICAL.md` and the P0-28B contract remain authoritative.

Audited pre-hardening head: `11624c92bc6e9ce8410c33515961797d860ca99a`  
Pre-hardening CI run: `36237408742` — validate PASS, Ubuntu 24.04 PASS, Windows 2025 PASS.

No live provider access, OAuth, corpus mutation, or user-file write occurred.

## What the green pre-hardening CI proved

The v8 implementation correctly exercised the intended Go API:

- atomic bootstrap generation/publication/membership/cursor creation;
- incremental membership + cursor publication;
- stale sequence/cursor replay rejection;
- trust-breaking generation closure and rebootstrap;
- immutable publication/bootstrap/change rows;
- reopen durability;
- separation of RemoteHistory from full Observation/Artifact authority.

The earlier compile-only regression on head `26ff74e1...` was fixed without semantic change.

## Boundary finding B1 — current history authority was not fully SQLite-bound to immutable publication evidence

Severity: **BLOCKER BEFORE P0-28B QUALIFICATION**

In schema v8, the `remote_history_generations_update_guard` constrained the shape of an ACTIVE generation advance, but did not require a matching immutable `HistoryPublication`.

Therefore direct SQL capable of reaching the database could advance:

```text
current_sequence
committed_cursor
```

without a corresponding publication row.

Similarly, current membership was mutable without a SQLite-level requirement that the mutation correspond to bootstrap/change evidence.

The Go API did the correct operations in one immediate transaction, so ordinary application calls were safe. The missing protection was the durable database trust boundary itself.

## Correction — schema v9

Schema v9 keeps v8 migration history intact and adds a new migration.

It enforces:

1. a new publication must match the ACTIVE generation prestate;
2. incremental change rows may attach only to an incremental publication;
3. current membership insert/update/delete requires matching immutable bootstrap/change evidence;
4. a generation may advance only when the exact next immutable publication exists;
5. the final current membership for every object changed in that publication must match the final change for that object;
6. generation closure retains the prior cursor/sequence and remains the only non-publication advance path.

The current membership table remains a materialized projection. Immutable bootstrap/publication-change rows remain the underlying history evidence.

## Why this is v9 rather than editing v8

A database may already have opened schema v8. Rewriting migration 8 would make schema history dependent on which source revision first opened the database.

Therefore:

```text
v8 = issued history-publication schema
v9 = explicit hardening migration
```

This preserves deterministic migration semantics.

## Retained boundary

Even after v9, RemoteHistory proves stream/membership history only.

It still does **not** authorize Artifact SAME/NEW across provider-object lifetime questions. P0-28C must derive object-specific lifetime segments and bind identity authority to those segments.

## Qualification required

P0-28B may be marked QUALIFIED only after exact-head CI passes:

- validate;
- Ubuntu 24.04;
- Windows 2025;
- all previous tests;
- v7→v8 migration;
- v8→v9 migration;
- forged generation advance rejection;
- wrong-prestate publication rejection;
- membership tamper rejection;
- normal bootstrap/incremental publication remains functional;
- go vet.
