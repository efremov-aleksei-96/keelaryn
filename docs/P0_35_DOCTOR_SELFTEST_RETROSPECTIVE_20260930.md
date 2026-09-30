# P0-35 Doctor/SelfTest retrospective — 2026-09-30

## Boundary

Audited product head: `b7631e3bccdd34d361612a5be7b6ae011cdc8486`.

Exact-head qualification: GitHub Actions run `36679914886`.

Result: **PASS — H4 resolved; zero new BLOCKER/CRITICAL findings.**

## Qualified product surface

P0-35 now provides two complementary operability surfaces:

1. `keelaryn doctor --control-dir <existing protected control>`
   - strict read-only diagnostics;
   - no create, migration, repair, rebuild or user-state write;
   - exact state/search application and schema identity;
   - SQLite integrity and foreign-key checks;
   - existing RemoteHistory, Google Drive and core identity historical-authority verification;
   - search security policy verification;
   - FTS5 special integrity command only on an in-memory backup;
   - protected control storage verified before and after diagnostics;
   - structured JSON findings on stdout with diagnostic failure signalled by exit 1.

2. `keelaryn self-test`
   - accepts no user paths;
   - creates only a disposable OS-temp workspace;
   - creates a deterministic tiny fixture corpus and sibling protected control root;
   - executes protected bootstrap -> literal search -> ContextBundle -> Doctor;
   - proves non-empty exact Artifact/Revision provenance and that ContextBundle returns the same exact provenance with the explicit task reason;
   - proves fixture corpus bytes and topology are unchanged;
   - removes the disposable workspace before returning;
   - emits a structured JSON result.

## P0-35B architecture / correctness review

The SelfTest reuses the existing protected runtime instead of constructing a parallel test-only ingestion path. It therefore exercises the same control-storage, SQLite state, extraction, derived search and ContextBundle boundaries exposed by the executable.

No user corpus is used. No live provider is contacted. No MCP, HTTP or web surface is introduced. No new dependency is added.

SelfTest-created physical files are its own disposable fixture/control state and are deleted by the same invocation. The product does not claim that this is metadata-loss reconstruction, live-provider qualification, Android support, or release rollback.

The output proves the selected search hit and ContextBundle agree on the exact Artifact/Revision identities. The underlying qualified ContextBundle runtime additionally revalidates current durable inventory and content evidence before returning text.

## Findings

### New BLOCKER/CRITICAL

None.

### P0-35A targeted finding

`P0_35A_C1_STRUCTURED_FAILURE_CHANNEL` remains resolved. Diagnostic failure reports remain structured stdout-only; the CLI does not add a duplicate generic stderr error for the Doctor sentinel.

### H4

`AUDIT_OPERABILITY_H4_DOCTOR_SELFTEST_NOT_INTEGRATED` — **RESOLVED**.

The missing aggregate read-only diagnostic surface and executable disposable end-to-end proof are now both present and cross-platform qualified.

## Reuse review

Reused instead of reimplemented:

- `controlstorage.OpenExisting/Verify`;
- authoritative SQLite historical verifiers;
- search security/FTS verification;
- pinned `zombiezen.com/go/sqlite` read-only and Backup APIs;
- protected bootstrap/search/ContextBundle runtime;
- existing exact Artifact/Revision provenance checks.

No external diagnostic/test framework is justified for this boundary.

## Qualification evidence

Run `36679914886` on `b7631e3bccdd34d361612a5be7b6ae011cdc8486`:

- validate — PASS;
- Ubuntu 24.04 dependency lock — PASS;
- Ubuntu Go tests — PASS;
- Ubuntu Go vet — PASS;
- Windows 2025 dependency lock — PASS;
- Windows Go tests — PASS;
- Windows Go vet — PASS.

The Windows Go-test duration remains within the already-qualified slow SQLite-runner profile and completed without timeout.

## Remaining P0 gates

H4 is removed from the open HIGH set.

Still open:

- `AUDIT_RELEASE_H1_STATE_DB_ROLLBACK_NOT_IMPLEMENTED` — release/update gate;
- `AUDIT_RELEASE_H2_ANDROID_QUALIFICATION_ABSENT` — Android portability gate;
- live remote-provider runtime qualification;
- minimal MCP access;
- embedded minimal web status;
- final P0 proof re-audit.

The next autonomous product boundary is **live remote-provider runtime qualification**. Because it crosses a live external-provider trust boundary, its first step must be read-only reconciliation plus an explicit runtime/trust contract before any new live mutation surface is enabled.
