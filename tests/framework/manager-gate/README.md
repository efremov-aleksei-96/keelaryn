# Keelaryn Manager Gate Framework v2

Repository-oriented source for building Windows Manager gate archives. It belongs under `keelaryn/tests/framework/manager-gate`; it is not production Manager state and is not Hub source.

## Goals

- one reusable gate harness instead of version-specific copies;
- candidate/baseline/gate revision carried by `gate/GATE_SPEC.json`;
- cryptographic binding from gate to `INSTALLATION.json` and the full managed-content digest;
- gate-only revisions can change harness files while automatically proving managed candidate bytes are unchanged;
- deterministic release comparison uses two isolated Manager build roots, so build B never overwrites build A artifacts;
- candidate/migration fixtures derive their metadata from real CURRENT/source contracts instead of manually cloning whole Hub metadata;
- all destructive targets remain under `tests/work`; production Manager/Hub remain read-only during Full Gate.

## Builder

`Build-ManagerGate.ps1` accepts either a canonical final Manager source directory or a canonical SOURCE ZIP, an explicit production baseline version, a gate revision and an output path.

Example:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Build-ManagerGate.ps1 `
  -SourceZip D:\0\0__Core\keelaryn\tests\work\candidate\Keelaryn__Manager_SOURCE_v4.10.0.zip `
  -BaselineVersion 4.9.2 `
  -GateRevision 1 `
  -OutputPath D:\0\0__Core\keelaryn\tests\manager-4.10.0.zip
```

The output name must remain `manager-<version>.zip` when it is issued for the Windows gate. The external user entrypoint remains `tests\UNPACK_MANAGER_GATE.cmd`.

## Generated package

The builder copies only the canonical `INSTALLATION.json` allowlist, then generates the three transition-only compatibility files required by Manager UPDATE/gate validation:

- `Keelaryn__Manager.ps1`;
- `_manager_version.txt`;
- `_manager_manifest.json`.

It then adds the generic gate harness and generates exactly one `RUN_<version>_FULL_GATE.cmd` launcher.

`GATE_SPEC.json` records:

- candidate version;
- expected production baseline version;
- gate revision;
- SHA-256 of canonical `INSTALLATION.json`;
- full managed-content digest;
- final managed-file count.

Full Gate validates this binding before reading production baseline state.

## Gate-only revision discipline

If a defect is only in the harness and the managed-content digest is unchanged, increment only `gate_revision` and rebuild the same `manager-<version>.zip`. Do not increment Manager version merely for a test-harness correction.

If any managed Manager byte changes after a candidate was issued, issue a new Manager candidate version.

## Deterministic build isolation

The source gate creates two clean source copies below the candidate workspace and runs BUILD_RELEASE independently in each. Hashes are compared across the two release bundles. This avoids the previous failure mode where an indexer/synchronizer could lock build-A output while build B tried to overwrite the same ZIP.

Fresh validation at publication/commit boundaries remains the Manager runtime's responsibility; the framework does not bypass or weaken it.

## Framework source revision 2

Revision 2 fixes PowerShell top-level helper ordering in the Full Gate template and makes generated-package preflight reject custom helper calls that occur before their function definitions execute. This is a framework-only correction; it does not change Manager candidate bytes or the `keelaryn.manager-gate-spec.v1` schema.

## Canonical path ordering

Candidate binding and manifest-set comparisons use `System.StringComparer.Ordinal`; culture-sensitive `Sort-Object` must not define cryptographic identity.


## Framework source revision 6

Revision 6 is the first framework version prepared for independent Windows qualification.

Hardening added:
- ordinal file/path ordering throughout gate fingerprints and gate ZIP generation;
- generator rejection of culture-sensitive path sorts;
- semantic ZIP-entry diagnostics for deterministic release mismatches;
- independent qualification suite against known-good Manager 4.9.2 managed bytes.

Do not use the framework for a new Manager candidate until the qualification suite reports PASS on Windows PowerShell 5.1.


## Revision 7 hardening

- child-process argument quoting follows Windows CRT escaping rules for spaces, quotes and trailing backslashes;
- SourceGate and FullGate contain no parameterless `WaitForExit()` calls;
- timeout cleanup waits are bounded;
- gate child stdout is explicitly UTF-8;
- identity-sensitive fixture/package comparisons use ordinal ordering.


## Revision 8 release handoff

Revision 8 consolidates the Windows-proven 4.10.2 Gate Revision 3 fixes and replaces path guessing with explicit evidence:

- `SOURCE_GATE_RESULT.json` is the only SourceGate -> FullGate release handoff contract;
- `framework_revision` is bound in `GATE_SPEC.json` and `FRAMEWORK_REVISION.txt`;
- Gate Spec managed digest is explicitly named and kept separate from historical Manager UPDATE hash contracts;
- after `FULL GATE: PASS`, the exact tested UPDATE is copied to `tests/results/manager-<version>/artifacts`;
- `TESTED_RELEASE.json` binds that UPDATE to SourceGate and Full Gate evidence;
- `INSTALL_TESTED_MANAGER_UPDATE.cmd` validates the evidence/hash, installs explicitly, and runs a fresh production Doctor.

The gate remains production-read-only until the user explicitly runs the generated installer after PASS.


## Revision 9 sort-contract guard

Revision 9 fixes an over-broad Framework r8 build guard.

The framework has three intentionally different ordering domains:

- cross-run/cross-machine gate identity uses explicit ordinal ordering;
- historical Manager UPDATE/fault-injection hashes retain the Windows ordering contract required by Manager 4.9.2/4.10.2 validation;
- same-run diagnostic/snapshot ordering may retain the Windows-proven Full Gate behavior because no cross-machine identity is derived from it.

`Build-ManagerGate.ps1` now validates `Sort-Object FullName` / `Sort-Object -Unique` in AST context instead of rejecting those tokens globally. The only allowlisted occurrences are the Windows-proven diagnostic/fixture functions. Canonical `GateSpecManagedDigest` remains explicitly ordinal.
