# Keelaryn development tests workspace

The canonical local development root is `keelaryn/tests`.

```text
tests/
├── framework/
│   └── manager-gate/       # one current reusable framework source
├── work/                    # disposable active candidate/runtime state
├── results/                 # active/current expanded evidence + concise indexes
├── archives/                # frozen verified historical evidence
└── legacy-layout-backup/    # compatibility evidence only when legacy layout finalization requires it
```

`work/` is disposable and should normally be empty between development cycles. Candidate packs, temporary Hub copies, generated fixtures, fault-injection targets and benchmark runtimes belong below it.

`results/` is not permanent raw-history storage. Expanded gate evidence is valid while qualification is active and while a verdict is being investigated. A completed qualification may be compacted to `archives/`, leaving a concise `QUALIFICATION_INDEX.json` under the result root.

`archives/` stores frozen evidence ZIPs plus per-entry manifests. Compaction reopens the archive and verifies every entry by SHA-256 before expanded source evidence is eligible for cleanup. Cleanup is file-granular with bounded retries; a verified archive plus an empty-but-temporarily-locked directory is reported as pending cleanup rather than a data-integrity failure.

Reparse-point directories are always rejected and never traversed. File reparse points are rejected unless an explicit `keelaryn.reparse-substitution-map.v1` binds the original evidence path to a protected regular non-reparse copy by exact size and SHA-256. The archive is built from the protected copy under the original evidence path, while the manifest preserves original attributes/timestamps plus substitution provenance. Unknown, unused, changed or unsafe bindings fail closed.

Unknown or unclassified top-level test entries are never moved or deleted automatically. `manager/state/history` is outside tests compaction scope and remains protected by its rollback/migration retention policy.

## Manager gate archive

Windows Manager gate ZIPs are named exactly:

```text
manager-<version>.zip
```

The external/manual entrypoint remains:

```text
tests\UNPACK_MANAGER_GATE.cmd
```

Manager UI also exposes Development > Run Full Gate. Both workflows use the same `product/tools/Unpack-KeelarynTestArchive.ps1` validation/unpack contract rather than independent extraction implementations.

## Test archive safety

`Unpack-KeelarynTestArchive.ps1` validates archive naming, path traversal, reserved Windows names, case-insensitive collisions, symlink-like entries and size limits. It extracts through staging and publishes atomically into `tests/work/<archive-name>`.

`-PlanOnly` resolves the validated archive kind/version/destination without extraction. `-NonInteractive` prohibits overwrite prompting. If a destination exists and replacement was not explicitly authorized, the non-interactive backend exits without replacing it. This lets Manager UI own the visible confirmation boundary and prevents hidden child prompts behind redirected stdout.

## Full Gate boundary

The Full Gate may read the current production Manager, Hub and CURRENT baseline for preflight/immutability evidence, but it must not execute production Manager/tool paths or use the personal live Hub as a mutable development target.

Mutable test installation, update, migration, rollback, Genesis, candidate-transport and archive fixtures are disposable and remain under `tests`. A CURRENT-backed Hub copy is used when production-compatible Hub behavior must be exercised.

Production approval requires a complete PASS summary. A failed/rejected candidate retains a concise root-cause/provenance record; raw evidence is frozen only when it has durable value.

## Qualification closing

`product/tools/Compact-KeelarynQualificationEvidence.ps1` accepts only a completed `tests/results/.../GATE_SUMMARY.json`. Default execution is a dry run. Commit mode:

1. inventories exact paths/file count/bytes and rejects reparse points;
2. hashes every source file;
3. writes a frozen evidence manifest with original attributes/timestamps;
4. builds the evidence ZIP;
5. reopens the ZIP and verifies every entry by size and SHA-256;
6. publishes archive/manifest identities;
7. writes a concise qualification index;
8. deletes expanded evidence file-by-file with bounded retries;
9. records pending locked files/directories for idempotent retry.

Archive verification precedes any source deletion.

## Gate Framework v2

Repository `tests/framework/manager-gate` owns the reusable Manager gate harness source. A generated gate carries `gate/GATE_SPEC.json` with candidate version, expected production baseline, gate revision, canonical INSTALLATION SHA-256, managed-content digest and managed-file count. Full Gate validates that binding before substantive candidate checks. Gate-only revisions may change harness bytes only when the bound managed-content digest remains unchanged.

Deterministic BUILD_RELEASE validation uses two isolated clean Manager build roots and compares independent release hashes. The second build does not overwrite the first build's release ZIPs, avoiding false failures caused by external indexers or synchronizers briefly locking build-A artifacts.
