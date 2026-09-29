# P0 Closure Re-audit after P0-33 — 2026-09-30

Status: **P0 NOT CLOSED / NEXT AUTONOMOUS GAP SELECTED**

Authority: `KEELARYN_CANONICAL.md` remains product architecture authority. `DEVELOPMENT_STATE.json` remains the live development clock.

## Qualified boundary

P0-33 qualification:

- product / qualification HEAD: `adaa3cc68cece243cd6d6092bf881120c64064a5`;
- exact-head CI: `36625411480` — validate / Ubuntu 24.04 / Windows 2025 PASS;
- authoritative state schema: v45;
- derived search-cache schema: v3;
- literal FTS hits now compose into exact current task ContextBundles;
- corpus mutations: 0;
- live remote/provider use: none;
- new dependencies: 0.

## Required P0 path now

| Capability | Current state |
|---|---|
| local read-only discovery | QUALIFIED |
| durable observation / inventory | QUALIFIED |
| Artifact / Revision identity | QUALIFIED |
| minimal extraction | QUALIFIED |
| SQLite FTS5 search | QUALIFIED |
| one-executable local state/search composition | QUALIFIED |
| task-specific ContextBundle runtime composition | **QUALIFIED by P0-33** |
| production filesystem/ACL protection | **OUTSTANDING H3** |
| aggregate Doctor/SelfTest | OUTSTANDING H4 |
| real live remote/provider runtime qualification | OUTSTANDING |
| minimal MCP access | ABSENT |
| embedded minimal web status | ABSENT |

## Next autonomous product gap

The next bounded stage is:

> **P0-34 — protected control storage**

This resolves `AUDIT_SECURITY_H3_STATE_DB_FILESYSTEM_PROTECTION` before any supported production/user-runtime or MCP qualification.

### Selected storage boundary

Use one dedicated control directory containing runtime-local Keelaryn state:

```text
<control-dir>/
├── state.db
├── search.db
└── SQLite transient/side files when present
```

The directory, not a single database filename, is the primary security boundary because SQLite journal/WAL/SHM files are created beside the database.

### Platform adapter rules

- low-level state/search stores remain OS-neutral;
- permission semantics live behind a platform storage adapter;
- a new control directory is protected before SQLite is opened;
- an existing directory is verified fail-closed rather than silently changing ACL/mode on an arbitrary user directory;
- Unix/Linux: owner-only control directory, ownership/mode verified;
- Windows: real protected DACL semantics via the already-present `golang.org/x/sys/windows`, not POSIX-style `chmod` emulation;
- Android equivalent: app-private control storage; direct Android runtime remains unqualified until H2 is separately resolved;
- corpus paths remain read-only and independent from control-state placement.

No separate ACL library is justified.

## Why H3 precedes MCP

The executable now stores:

- non-rebuildable Artifact/Revision/Observation authority;
- corpus locators and timestamps;
- rebuildable extracted search text.

Exposing those files through a supported runtime before enforcing their filesystem boundary would turn a known HIGH security finding into a user-facing surface. MCP remains downstream of H3 and H4.

## Remaining P0 closure gates after P0-34

- H4 aggregate Doctor/SelfTest;
- live real remote/provider runtime qualification;
- minimal MCP endpoint using the official maintained Go SDK where practical;
- embedded minimal web status;
- final P0 proof/closure re-audit.

H1 release rollback and H2 Android qualification remain carried at their existing later gates.

## Conclusion

**P0 remains open. P0-33 is qualified. P0-34 protected control storage is the next autonomous product stage.**
