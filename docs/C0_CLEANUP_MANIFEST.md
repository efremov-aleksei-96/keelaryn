# C0 Cleanup Manifest

Frozen pre-P0 reference:

`legacy/pre-corpus-p0-20260924` → `ece811aea9bbf73d46460f5bb022013a5dfa6038`

## Active Git policy

Keep only current Corpus-first architecture, compact development state, minimal docs, Go module/toolchain declaration and one primary CI workflow.

The following stay in Git history/legacy reference rather than an `archive/` directory in the active branch:

- legacy `manager/**`, `hub/**`, `core/**`, `deploy/**`, `spec/**`, `tools/**`, `tests/**`;
- candidate/evidence/authorization/handoff trees;
- r0001-r0009 workflows and control-plane machinery;
- Hub/migration/pilot/cutover code;
- superseded architecture/roadmap documents.

## Approved Google Drive archive plan

No deletion is authorized.

Create:

`9__Archive/KeelarynLegacy/2026-09-24__PreCorpusP0/`

Move existing Drive objects, preserving identity:

1. `0__Core/keelaryn` — ID `13Du6Dbgq2H9zX7mGnmih5pU7k9EvZS3H`
2. `0__Core/keelaryn-private` — ID `1BFoaqU8a3arOFHUMWlsuoPgs1YCKR-56`

Leave `2__Project/CorpusBootstrap` (ID `1tKmVnS9oSHkOxwqk4FmXceaLo4JjSUz1`) in place until its remaining boundary is reconciled and the project can be closed cleanly.

Genuine user projects/records/library content are never development garbage.
