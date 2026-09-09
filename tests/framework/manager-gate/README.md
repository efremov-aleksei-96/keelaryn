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

Example from the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\framework\manager-gate\Build-ManagerGate.ps1 `
  -SourceZip .\tests\work\candidate\Keelaryn__Manager_SOURCE_v4.10.0.zip `
  -BaselineVersion 4.9.2 `
  -GateRevision 1 `
  -OutputPath .\tests\manager-4.10.0.zip
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

## Revision 10 bounded command sidecars

Revision 10 bounds command-log and exit-code sidecar filenames on Windows. The human-visible command label remains complete, while the filesystem prefix uses at most the first 80 sanitized label characters plus a deterministic 12-hex SHA-256 suffix of the complete label. This prevents long command arguments from exceeding Windows path limits without weakening exit-code capture or log-name uniqueness.

## Revision 11 candidate-lineage fixture correction

Revision 11 preserves the revision 10 path-length hardening and corrects the Full Gate candidate-transport fixture source. Candidate fixtures use the valid non-genesis migration CURRENT already produced by the gate instead of the original Genesis CURRENT. This keeps the candidate transport regression on a normal parented lineage even when the disposable production fixture starts at Genesis.

Revision 11 was independently qualified on Windows PowerShell 5.1 while testing unchanged Manager 4.12.0 g1 bytes. Gate Revision 3 passed SourceGate, CURRENT-backed Full Gate, rollback fault injection, native 4.11.0 -> 4.12.0 update, post-update Doctor, UI/archive/migration/candidate-transport/Genesis coverage, AI_CONTEXT performance control and production immutability.

## Revision 12 transient CURRENT sharing retry

Revision 12 corrects a Framework-only Windows Full Gate defect discovered while qualifying unchanged Manager 4.14.0 bytes. Full Gate E4 previously opened the disposable `Keelaryn__Hub_CURRENT.zip` exactly once in `ZipArchiveMode.Update`; a transient sharing violation from another process could therefore reject an otherwise healthy candidate.

Revision 12:
- retries only the actual disposable CURRENT ZIP update-open operation;
- retries only Windows sharing/lock violations 32/33 and immediately rethrows unrelated failures;
- includes a real Windows `FileShare.None` sharing-violation self-test before gate execution;
- makes `Build-ManagerGate.ps1` statically require the retry/self-test contract and reject the old direct single-attempt E4 open.

The Manager 4.14.0 product bytes are unchanged. Historical r11 / gate-revision-1 qualification evidence remains historical and rejected; repeated qualification uses Framework r12 with gate revision 2.

## Revision 13 hardened SOURCE ZIP boundary

Revision 13 removes the builder's direct `Expand-Archive` trust boundary for `-SourceZip` and replaces it with validated, manual extraction.

Before any SOURCE bytes are written to the extraction tree, r13 validates the whole archive envelope:

- every entry must remain below the exact `keelaryn/` root and use relative paths only;
- empty, `.` and `..` segments are rejected;
- Windows reserved device names, invalid characters, trailing dots/spaces and overlong segments are rejected;
- case-insensitive and Unicode-normalization aliases are rejected before extraction;
- Windows reparse metadata, Unix symlink metadata and other unsafe Unix file types are rejected;
- compressed size, total expanded size, per-entry expanded size, entry count and compression ratio are bounded;
- extraction uses destination-containment checks, refuses pre-existing targets and verifies extracted lengths.

`Test-ManagerGateFramework.ps1` is the independent r13 framework self-test. It exercises a valid SOURCE ZIP through the real builder and adversarial archives covering Zip Slip/dot segments, reserved names, case and Unicode aliases, symlink/reparse metadata, compression-ratio limits, expanded-size limits and entry-count limits.

Framework r13 must pass this self-test on Windows PowerShell 5.1 before it is frozen or used to qualify a new Manager candidate.

## Revision 14 UPDATE transition-alias qualification

Revision 14 extends SourceGate's UPDATE transport boundary for Manager releases that must preserve an obsolete path only for compatibility with a supported older updater.

The canonical final managed set remains authoritative. SourceGate now reads `transition_compatibility_aliases` from `product/manager_release.json` and requires each alias to:

- use a safe relative Manager path;
- remain outside the canonical final managed set and the three root transition files;
- map to an existing canonical final managed `source_path`;
- be unique under Windows case-insensitive and Unicode-normalized identity;
- appear exactly once in the UPDATE transport manifest and payload;
- carry the exact SHA-256 and byte length of its canonical source row;
- remain absent from SOURCE and DISTRIBUTION.

The expected UPDATE transport is therefore `final managed files + three root transition files + declared transition aliases`; SourceGate no longer assumes that every valid UPDATE has exactly `final + 3` rows.

`Test-ManagerGateFramework.ps1` extracts the actual `Get-UpdateTransportCompatibilityContract` function from the SourceGate template AST and tests zero aliases, one valid alias, final-path collision, missing source, case-alias duplication and unsafe traversal. Framework r14 must pass this self-test on Windows PowerShell 5.1 before it is frozen or used for the corrective Manager qualification cycle.
## Revision 15 UPDATE-internal transition-manifest validation

Revision 14 was qualified and frozen but remained unmerged after review exposed an ambiguity in transition-manifest validation. Follow-up investigation distinguished two separate manifests:

- `Build-ManagerGate.ps1` synthesizes the **gate-source root** `_manager_manifest.json` used only to construct and execute `manager-<version>`; its contract remains canonical final managed files plus the three root transition paths.
- Manager `-BuildRelease` generates a separate `_manager_manifest.json` **inside the UPDATE payload**. Supported baseline updaters validate that UPDATE-internal manifest against every UPDATE `manifest.files` path.

Revision 15 keeps the r14 alias safety rules and preserves the gate-source root envelope unchanged. The new validation belongs in Gate C2 after the candidate has built its real release artifacts. SourceGate now:

- derives the full expected UPDATE transport as final managed files + three root transition files + declared compatibility aliases;
- validates UPDATE `manifest.files` against that complete transport;
- opens `Keelaryn__Manager_Update/payload/_manager_manifest.json` from the generated UPDATE;
- requires its schema/version identity and `managed_files` set to equal the complete expected UPDATE transport exactly;
- rejects an UPDATE-internal transition manifest that omits a declared alias or contains an extra transport path;
- preserves SOURCE/DISTRIBUTION exclusion and the independent canonical final managed set, so aliases remain transport-only and disappear from the installed final tree.
- fixes repository .gitattributes precedence so generic *.json/*.md EOL rules cannot override authoritative manager/** or Framework byte preservation.

The r15 Framework self-test extracts and executes the alias-contract and UPDATE transition-manifest equality helpers, including missing-alias and extra-path rejection. Qualification additionally requires a real SourceGate against the exact Manager 4.16.1 candidate and later the disposable Full Gate path exercising the supported Manager 4.15.1 -> 4.16.1 native update.
