# Release Build

Development > Build full release (compatibility command `compat/commands/BUILD_RELEASE.cmd`) is the canonical release constructor. It uses only `product/install/INSTALLATION.json` managed files and is Hub-blind.

A successful run reads the canonical managed allowlist with presentation-invariant hidden-safe metadata access, captures each managed source file once into an in-memory byte snapshot, then constructs SOURCE, DISTRIBUTION, UPDATE, AI_CONTEXT and the release manifest in a temporary same-volume staging directory. SOURCE, DISTRIBUTION and the final managed portion of UPDATE are materialized from the same captured bytes, so they cannot diverge because of repeated source reads during one build. The generated UPDATE and complete release-bundle manifest/hash set are validated before publication. The four artifacts are then published atomically one file at a time and the release manifest is published last, so an interrupted publication cannot advertise a new complete bundle.

SOURCE contains generated `Development/AI_CONTEXT`; DISTRIBUTION and UPDATE are reconstructed independently from the managed allowlist, so Development data cannot leak into installable artifacts.

UPDATE uses `keelaryn.manager.update.v2`: release/system identifiers, compatibility floor, exact file set, SHA-256 and size for every managed file. The generated UPDATE is parsed again by the running Manager before release completion.

The three transition-only compatibility files in UPDATE (`Keelaryn__Manager.ps1`, `_manager_manifest.json`, `_manager_version.txt`) are generated deterministically. The transition bootstrap must retain literal `$PSScriptRoot`, `$PSHOME`, `$runtime` and `@args` references and must never capture an absolute build-workspace path. SelfTest and SourceGate both enforce this contract.

## Release retention

Retention runs only after the newly published bundle has passed post-publication hash validation. `state/releases/` keeps the current complete Manager release plus the nearest previous valid release. Older complete valid bundles are copied and revalidated under `state/history/manager_releases/v<version>/`, then removed from `state/releases/`; up to three validated older release bundles are retained there. Archive pruning considers only complete bundles that pass manifest/hash validation.

Invalid, incomplete, unrecognized or future-version release bundles are never removed automatically. Archive conflicts also fail safe: the source bundle remains in `state/releases/` and Manager emits a warning.

Retention has one deliberately narrow historical compatibility path: the production-era three-artifact release-bundle contract through Manager 4.3.1 (`source`, `distribution`, `update`) may be archived only after exact filename/version/schema/system-identity and SHA-256 validation. This compatibility reader is retention-only; the current release builder and modern release-bundle validator remain strictly four-artifact (`+ ai_context`). Later or structurally different three-artifact manifests remain untouched.
Generic DISTRIBUTION stores generated distribution provenance at `manager/product/install/DISTRIBUTION_MANIFEST.json`; generated provenance must not add another visible file to the Manager root.

## Human-facing build result

The runtime suppresses internal AI_CONTEXT temporary workspace paths during normal BUILD_AI_CONTEXT/BUILD_RELEASE output. A successful release build prints the exact SOURCE, DISTRIBUTION, UPDATE, AI_CONTEXT and release-manifest paths plus a compact retention summary. Detailed transient paths remain available through Manager logs when relevant to an error.
