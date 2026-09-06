# Keelaryn development tests workspace

The canonical local development root is `keelaryn/tests`.

```text
tests/
├── work/
├── results/
└── legacy-layout-backup/   # only when a legacy-layout operation actually requires it
```

`work/` is disposable. Candidate packs, temporary Hub copies, generated fixtures, fault-injection targets and benchmark runtimes belong below it.

`results/` is durable gate evidence. Windows gates write summaries, command logs and Doctor reports under `results/manager-<version>/`.

Unknown or unclassified top-level test entries are never moved or deleted automatically.

## Manager gate archive

Windows Manager gate ZIPs are named exactly:

```text
manager-<version>.zip
```

The external/manual entrypoint remains:

```text
D:\0\0__Core\keelaryn\tests\UNPACK_MANAGER_GATE.cmd
```

Manager UI also exposes Development > Run Full Gate. Both workflows use the same `product/tools/Unpack-KeelarynTestArchive.ps1` validation/unpack contract rather than independent extraction implementations.

## Test archive safety

`Unpack-KeelarynTestArchive.ps1` validates archive naming, path traversal, reserved Windows names, case-insensitive collisions, symlink-like entries and size limits. It extracts through staging and publishes atomically into `tests/work/<archive-name>`.

`-PlanOnly` resolves the validated archive kind/version/destination without extraction. `-NonInteractive` prohibits overwrite prompting. If a destination exists and replacement was not explicitly authorized, the non-interactive backend exits without replacing it. This lets Manager UI own the visible confirmation boundary and prevents hidden child prompts behind redirected stdout.

## Full Gate boundary

The Full Gate may read the current production Manager, Hub and CURRENT baseline for preflight/immutability evidence, but it must not execute production Manager/tool paths or use the personal live Hub as a mutable development target.

Mutable test installation, update, migration, rollback, Genesis, candidate-transport and archive fixtures are disposable and remain under `tests`. A CURRENT-backed Hub copy is used when production-compatible Hub behavior must be exercised.

Production approval requires a complete PASS summary; a failure must identify its phase/check and preserve evidence under `tests/results`.

## Gate Framework v2

Repository `tests/framework/manager-gate` owns the reusable Manager gate harness source. A generated gate carries `gate/GATE_SPEC.json` with candidate version, expected production baseline, gate revision, canonical INSTALLATION SHA-256, managed-content digest and managed-file count. Full Gate validates that binding before substantive candidate checks. Gate-only revisions may change harness bytes only when the bound managed-content digest remains unchanged.

Deterministic BUILD_RELEASE validation uses two isolated clean Manager build roots and compares independent release hashes. The second build does not overwrite the first build's release ZIPs, avoiding false failures caused by external indexers or synchronizers briefly locking build-A artifacts.
