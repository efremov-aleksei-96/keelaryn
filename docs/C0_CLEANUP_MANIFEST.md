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

## Current verified execution status

Completed:
- created `9__Archive/KeelarynLegacy` — ID `1JO9ldvqef64ymCcKnWsYFDiPori1fuVb`;
- created `2026-09-24__PreCorpusP0` — ID `1iMVDc-jnEQoABqsksCixD--nfmECi2AZ`;
- moved `0__Core/keelaryn` preserving Drive ID `13Du6Dbgq2H9zX7mGnmih5pU7k9EvZS3H`.

Tooling-blocked:
- `0__Core/keelaryn-private` remains under `0__Core`;
- three `update_file` move attempts timed out;
- read-only reconcile after every timeout proved `NOT_COMMITTED`;
- current user is owner and source parent is still exact;
- do not blind-retry the same connector action, and do not replace the identity-preserving move with copy/delete.

External corpus projects:
- `CorpusBootstrap` is WAITING only on Yota archival and is not a Keelaryn product-development blocker;
- Yota is `CLOSED_PENDING_ARCHIVE`;
- `SemanticArchiveAudit` is active at SAA-R0078 and still explicitly requires source READ_ONLY while remaining School52/11a work continues;
- therefore no Yota/archive mutation is implied by the Keelaryn cleanup approval.

VPS:
- legacy Drive service is inactive but enabled;
- legacy Drive mutation inhibit is PRESENT;
- existing VPS OAuth credentials must not be used to bypass that inhibit for this cleanup.

CI:
- the first clean workflow run `36003118232` failed before job creation (`startup_failure`);
- GitHub refused failed-job rerun because no jobs existed;
- do not create meaningless commits solely to retry; the next legitimate checkpoint will naturally trigger the workflow again.

