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
## Revision 16 updater-equivalence hardening

Revision 15 was exact-head qualified and frozen but rejected before merge after post-freeze Codex review identified two updater-equivalence gaps that remained in Gate C2.

Revision 16 preserves all r15 transport-alias, UPDATE-internal manifest and checkout-byte protections, and additionally:

- validates the raw UPDATE-internal `_manager_manifest.json.managed_files` array before normalization, rejecting duplicate paths instead of silently deduplicating them;
- hashes the actual compatibility-alias ZIP payload entry and its canonical source payload entry;
- requires both actual payload digests and uncompressed sizes to match their respective manifest rows;
- requires the actual alias payload bytes to equal the actual canonical source payload bytes;
- retains the exact UPDATE transport set, SOURCE/DISTRIBUTION exclusion and final-managed isolation.

The Framework self-test extracts the real SourceGate helpers and includes adversarial regression cases for a duplicated UPDATE transition-manifest path and for corrupted alias payload bytes paired with copied source metadata. Both must be rejected.

Framework r16 must still pass the real exact-byte Manager 4.16.1 SourceGate before commit, then fresh hosted exact-head qualification and review before any provenance freeze. Framework r15 remains immutable historical evidence and is not rewritten.
## Revision 17 UPDATE ZIP identity parity

Revision 16 passed local and hosted exact-head qualification but was rejected before freeze after Codex review found that SourceGate's UPDATE ZIP index silently overwrote duplicate entry keys. The supported baseline updater instead normalizes every ZIP entry name with Unicode Form C, lowercases it, and rejects any duplicate key before indexing.

Revision 17 preserves all r16 protections and adds updater-equivalent ZIP identity handling:

- `Get-ZipEntryIdentityKey` uses `Replace('\','/').Normalize(FormC).ToLowerInvariant()`, matching the supported updater;
- `Get-UniqueZipEntryIndex` rejects duplicate Windows/case/Unicode-equivalent UPDATE ZIP entry keys before any manifest lookup or alias hashing;
- alias/source ZIP lookups use the same identity helper;
- r16 raw transition-manifest duplicate rejection remains intact;
- r16 actual alias/source payload SHA-256 and size validation remains intact.

The Framework self-test extracts the real ZIP identity/index helpers and adds adversarial UPDATE ZIPs containing case-equivalent and Unicode-normalization-equivalent duplicate entries. Both must be rejected.

Framework r17 must pass Windows parser/self-test and the real exact Manager 4.16.1 SourceGate before commit, then fresh hosted exact-head qualification and Codex review before any provenance freeze. Framework r16 remains preserved as a rejected unmerged commit/PR and is not rewritten.
## Revision 18 directory-entry identity parity

Revision 17 passed local and hosted exact-head qualification but was rejected before freeze after Codex review found that explicit ZIP directory records were skipped before duplicate-key tracking.

The supported Manager updater's ZIP envelope validation applies normalized identity collision checks to every archive entry, including explicit directories, before later file-index logic omits directories.

Revision 18 preserves all r17 protections and changes `Get-UniqueZipEntryIndex` so that:

- every archive entry is normalized through `Get-ZipEntryIdentityKey`;
- every entry participates in the duplicate-key seen-set;
- explicit directory entries are excluded only from the returned lookup index after their identity has been validated;
- file, case-equivalent and Unicode-equivalent duplicate rejection remains unchanged;
- raw UPDATE transition-manifest duplicate rejection remains unchanged;
- actual alias/source payload SHA-256 and size verification remains unchanged.

The Framework self-test adds adversarial exact, case-equivalent and Unicode-normalization-equivalent duplicate explicit directory records. All must be rejected.

Framework r18 must pass Windows parser/self-test and the real exact Manager 4.16.1 SourceGate before commit, then fresh hosted exact-head qualification and Codex review before any provenance freeze. Framework r17 remains preserved as a rejected unmerged commit/PR and is not rewritten.
## Revision 19 Doctor transition-WARN parity

Framework r18 was fully qualified, frozen, tagged and merged. During the first real Manager 4.16.1 Full Gate, native disposable update 4.15.1 -> 4.16.1 succeeded, rollback protection succeeded, and the updated Manager SelfTest succeeded. The gate then failed because Manager 4.16.1 Doctor intentionally returned exit code 2 for a missing Hub governance receipt, while Full Gate's generic `Run-Manager` helper rejected every non-zero exit before reading `DOCTOR_REPORT.json`.

Manager 4.16.1 is unchanged. Its Doctor contract intentionally returns 1 for ERROR findings, 2 for WARN findings and 0 for a clean report. Governance `missing` and `stale` are deliberate transition states requiring explicit Chat Manager reconciliation; automatic Manager overwrite remains prohibited.

Revision 19 keeps Doctor qualification strict while supporting that transition contract:

- Doctor exit 0 is accepted only when the report has zero errors and zero warnings;
- Doctor exit 2 is accepted only when every WARN is `governance.status` and is specifically `missing` or `stale`;
- `newer`, `contract_mismatch`, `invalid`, unrelated WARN findings, any ERROR finding, and unexpected process exit codes remain hard failures;
- the same targeted Doctor path is used for D3 post-update qualification and E4 post-CURRENT-repair equivalence;
- the cross-version stable-finding comparison excludes only `governance.status`, because governance compatibility is validated separately by the strict Doctor transition contract;
- same-candidate finding equivalence still includes governance findings.

Framework self-test extracts the real Full Gate helper functions and verifies positive and adversarial Doctor report/exit combinations.

Framework r18 provenance remains immutable historical evidence. Framework r19 requires fresh local qualification, real Manager 4.16.1 Full Gate, hosted exact-head qualification and Codex review before any r19 freeze/tag/merge.
## Revision 20 delayed CURRENT ZIP sharing retry

Framework r19 is preserved as a rejected, unqualified and unfrozen revision. Its Doctor transition-WARN correction was valid, but the real CURRENT-backed Manager 4.16.2 Full Gate failed in E4 before invoking `RepairCurrentTransport`: Framework exhausted its 20 x 250 ms attempt budget while opening the disposable CURRENT ZIP in update mode.

Revision 20 retains all r19 Doctor protections and strengthens only the reusable transient file-sharing boundary:

- shared ZIP access uses one bounded retry primitive for update/read modes;
- the default retry budget is 120 attempts x 250 ms (approximately 30 seconds maximum under a persistent sharing violation);
- E4 explicitly uses the stronger bounded retry for both the pre-repair mutation and the post-repair verification read;
- non-sharing I/O failures still fail immediately;
- a real delayed-unlock self-test launches a separate Windows PowerShell job that holds a ZIP with `FileShare.None`, signals readiness, delays release, and requires the retry helper to wait and eventually succeed;
- the Framework self-test binds the delayed-unlock implementation and the E4 read/write retry calls so the protection cannot silently regress.

A persistent lock beyond the bounded budget still fails qualification. Manager 4.16.2 product bytes remain unchanged at the previously SourceGate-tested commit; this is a Framework-only correction.

Framework r20 must pass parser/self-test, real exact Manager 4.16.2 SourceGate, the full CURRENT-backed Windows gate, hosted exact-head qualification and Codex review before any freeze/tag/merge.
## Revision 21 production installer Doctor transition warnings

Framework r20 remains immutable historical provenance. After r20 was frozen/tagged/merged and exact Manager 4.16.2 passed the final merged-r20 CURRENT-backed Full Gate, release-tooling review found one remaining transition mismatch in the generated `Install-TestedManagerUpdate.ps1`: it treated every nonzero Doctor exit as installation failure. Existing Hubs that legitimately require explicit governance reconciliation therefore caused an otherwise successful tested Manager installation to end with a false failure when Doctor returned exit 2 for `governance.status` missing/stale.

Revision 21 keeps Manager 4.16.2 product bytes unchanged and carries the already-qualified Full Gate Doctor policy into the generated production installer:

- Doctor exit 0 is accepted only when the report has zero errors and zero warnings;
- Doctor exit 2 is accepted only when every warning is exactly `governance.status` and specifically the missing or stale transition state;
- newer governance, contract mismatch, invalid governance, unrelated warnings, Doctor errors, inconsistent warning counts and unexpected exit codes remain hard failures;
- accepted transition warnings are surfaced explicitly as `PRODUCTION DOCTOR: PASS WITH TRANSITION WARNINGS` and still require Chat Manager reconciliation; the installer never mutates Hub governance;
- Framework self-test parses the actual embedded installer PowerShell and semantically exercises healthy/missing/stale acceptance plus all unsafe rejection cases.

r21 must independently pass Windows parser/self-test, exact Manager 4.16.2 SourceGate, CURRENT-backed Full Gate, hosted exact-head qualification and Codex review before freeze/tag/merge. The r20 immutable tag and historical qualification evidence are not rewritten.
## Revision 22 strict Doctor report integrity

Framework r21 passed local Windows qualification and hosted exact-head workflows but was rejected before freeze/merge after Codex review found two P2 gaps in the Doctor transition-WARN policy. First, an exit-2 report could declare `errors=0` while still containing an ERROR finding; the r21 helper trusted the summary count and inspected only WARN rows. Second, the accepted governance `missing`/`stale` messages were prefix-matched, so an unsafe extra suffix could be accepted as a permitted transition warning.

Revision 22 preserves Manager 4.16.2 product bytes and all r20/r21 sharing-retry protections while tightening both Full Gate and the generated production installer:

- ERROR and WARN summary counts must exactly match their corresponding finding rows;
- any ERROR row remains a hard failure even if the summary count lies;
- the permitted missing-governance message must match the complete canonical message exactly;
- the permitted stale-governance message must match the complete canonical pattern through the final period;
- adversarial regressions cover malformed missing/stale suffixes and a mixed permitted WARN + ERROR report with a falsified `errors=0` summary.

Framework r21 remains immutable rejected history at its exact source head and is not frozen or merged. Framework r22 requires fresh Windows parser/self-test, exact Manager 4.16.2 SourceGate, CURRENT-backed Full Gate, hosted exact-head qualification and Codex review before freeze/tag/merge.


## Revision 23 additive Doctor finding compatibility

Framework r22 remains immutable qualified provenance. During exact Manager 4.17.1 g1 disposable qualification, the native 4.16.3 -> 4.17.1 update and candidate Doctor were healthy, but Full Gate rejected the candidate because 4.17.1 intentionally adds the new `instances.registry` OK diagnostic. The r22 cross-version comparison required exact equality of every non-Manager Doctor finding, so a strictly additive healthy diagnostic was misclassified as a compatibility regression.

Revision 23 changes only the reusable cross-version Doctor comparison contract:

- every stable non-Manager finding present in the baseline must still exist exactly once in the candidate;
- each preserved finding must keep the same severity and normalized semantic message;
- duplicate stable finding codes are rejected;
- candidate-only stable findings are accepted only when their severity is exactly `OK`;
- governance transition warnings remain excluded only from this cross-version equality check and continue to be validated by the strict r22 Doctor exit/report contract;
- same-candidate post-repair finding equality remains exact, so CURRENT repair cannot silently change Doctor semantics.

The self-test includes the real Manager 4.17.1 `instances.registry` additive-OK shape plus adversarial removal, semantic-change, duplicate-code and new-non-OK cases. Manager 4.17.1 g1 product bytes remain unchanged; the failed r22 qualification evidence remains historical. Framework r23 requires independent Windows qualification and provenance freeze before it may be used for a new Manager gate revision.

## Revision 24 baseline Doctor transition-WARN call-site binding

Framework r23 remains immutable qualified provenance. Real CURRENT-backed Manager 4.17.1 g2 qualification exposed a Framework-only defect before any candidate update: the disposable 4.16.3 baseline Doctor returned the canonical missing-governance transition warning with exit 2, but Full Gate D still invoked that baseline through generic `Run-Manager`, which rejects every nonzero exit. The strict `Run-DoctorForGate` policy already existed and was used for candidate/post-repair Doctor checks, so r23 tested the policy helper without proving the baseline call-site actually used it.

Revision 24 changes no Manager product bytes and does not broaden the accepted warning set. It routes the Full Gate D baseline Doctor through `Run-DoctorForGate` and binds `$baselineReport` to that validated result. The existing strict policy still accepts only the canonical missing/stale governance transition WARN shapes and rejects unrelated warnings, malformed messages, ERROR findings, inconsistent counts and non-transition exit codes. Framework self-test now asserts the baseline call-site binding directly and rejects reintroduction of the unsafe generic baseline Doctor invocation.

Framework r24 requires fresh Windows parser/self-test, SourceRoot/SourceZip equivalence, hosted Framework qualification, exact Manager 4.17.1 qualification and a new real CURRENT-backed Manager gate revision before freeze/tag/merge and production publication.
