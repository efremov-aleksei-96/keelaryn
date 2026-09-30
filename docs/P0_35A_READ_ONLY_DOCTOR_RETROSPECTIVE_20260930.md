# P0-35A read-only Doctor retrospective — 2026-09-30

## Boundary

Audited product head: `cc4ab2c9bae381efa7e0dde1bef2438968556036`.

Qualification evidence: GitHub Actions run `36678330990` on the exact head.

Result: **PASS — zero open BLOCKER/CRITICAL findings for the P0-35A boundary.**

This retrospective qualifies only the read-only Doctor slice. It does not close H4: P0-35B disposable SelfTest remains required.

## What P0-35A now proves

- `keelaryn doctor --control-dir <existing protected control>` has no user corpus path and no raw database-path bypass.
- Control storage is opened through `controlstorage.OpenExisting`; a missing control directory fails without creation.
- Authoritative state SQLite is opened with `sqlite.OpenReadOnly`, switched to `query_only`, and checked for exact application/schema identity, `integrity_check`, `foreign_key_check`, RemoteHistory authority, Google Drive authority, and core identity authority.
- Derived search SQLite is opened read-only/query-only and checked for exact application/schema identity, search security policy, SQLite integrity, and foreign keys.
- FTS5's write-shaped special integrity command never runs against the user search database. The source is copied through the pinned `zombiezen.com/go/sqlite v1.4.2` Backup API into an in-memory SQLite database, and FTS integrity runs only there.
- The protected control directory is verified again after database diagnostics.
- Doctor emits one structured JSON report to stdout. A diagnostic FAIL exits 1 without adding an unstructured duplicate to stderr.
- Tests prove missing-state non-creation, old-schema non-migration, pending search-security upgrade non-repair, FTS drift detection without source mutation, and byte-for-byte preservation of the protected control fixture.

## Targeted finding resolved during the slice

### P0_35A_C1_STRUCTURED_FAILURE_CHANNEL — RESOLVED

The initial CLI path returned a structured Doctor report and then allowed the generic top-level error path to print an additional unstructured error to stderr.

Resolution at `cc4ab2c9bae381efa7e0dde1bef2438968556036`: `doctor.ErrFailed` remains the non-zero exit signal, but the top-level CLI suppresses the generic stderr line for that sentinel. Machine-readable findings therefore remain stdout-only.

## Architecture / correctness review

No Hub-first authority was reintroduced. Doctor reads the protected control plane and does not treat derived search state as authoritative corpus content.

No migration, repair, rebuild, VACUUM, FTS rebuild, or corpus mutation is reachable from the Doctor surface. The only write-shaped FTS operation executes against disposable in-memory state.

Existing authority verifiers are reused rather than reimplemented. No new dependency was added.

The Doctor does **not** claim metadata-loss reconstruction, release rollback, Android qualification, or live-provider qualification. Those remain separate gates.

## Reuse review

Reused components:

- existing `controlstorage.OpenExisting/Verify`;
- existing state historical-authority verifiers;
- existing search security/FTS validation;
- pinned `zombiezen.com/go/sqlite` read-only connection and Backup APIs;
- legacy Doctor only as inspiration for report shape, not for Hub-first checks.

No external framework or additional diagnostic dependency is justified for this slice.

## Qualification

Run `36678330990`:

- validate — PASS;
- Ubuntu 24.04 dependency lock — PASS;
- Ubuntu Go tests — PASS;
- Ubuntu Go vet — PASS;
- Windows 2025 dependency lock — PASS;
- Windows Go tests — PASS;
- Windows Go vet — PASS.

The earlier Windows slowdown was not a Doctor deadlock; the exact-head run completed successfully under the corrected CI timeout.

## Next boundary

P0-35B must add `keelaryn self-test` with **no user paths** and only disposable temporary state:

1. create a deterministic tiny corpus fixture;
2. bootstrap protected state/index;
3. prove literal search exact Artifact/Revision provenance;
4. prove ContextBundle exact revision provenance and explicit task reason;
5. run Doctor over the generated protected control state;
6. prove fixture bytes/topology did not change;
7. clean up disposable state;
8. emit a structured result.

H4 remains open until that end-to-end SelfTest is qualified.
