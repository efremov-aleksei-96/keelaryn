# Release Build

`BUILD_RELEASE.cmd` is the canonical release constructor. It uses only `_manager_manifest.json` managed files and is Hub-blind.

A successful run constructs SOURCE, DISTRIBUTION, UPDATE, AI_CONTEXT and the release manifest in a temporary same-volume staging directory. The generated UPDATE and complete release-bundle manifest/hash set are validated before publication. The four artifacts are then published atomically one file at a time and the release manifest is published last, so an interrupted publication cannot advertise a new complete bundle.

SOURCE contains generated `Development/AI_CONTEXT`; DISTRIBUTION and UPDATE are reconstructed independently from the managed allowlist, so Development data cannot leak into installable artifacts.

UPDATE uses `keelaryn.manager.update.v2`: release/system identifiers, compatibility floor, exact file set, SHA-256 and size for every managed file. The generated UPDATE is parsed again by the running Manager before release completion.

## Release retention

Retention runs only after the newly published bundle has passed post-publication hash validation. `_releases/` keeps the current complete Manager release plus the nearest previous valid release. Older complete valid bundles are copied and revalidated under `_history/manager_releases/v<version>/`, then removed from `_releases/`; up to three validated older release bundles are retained there. Archive pruning considers only complete bundles that pass manifest/hash validation.

Invalid, incomplete, unrecognized or future-version release bundles are never removed automatically. Archive conflicts also fail safe: the source bundle remains in `_releases/` and Manager emits a warning.

Retention has one deliberately narrow historical compatibility path: the production-era three-artifact release-bundle contract through Manager 4.3.1 (`source`, `distribution`, `update`) may be archived only after exact filename/version/schema/system-identity and SHA-256 validation. This compatibility reader is retention-only; the current release builder and modern release-bundle validator remain strictly four-artifact (`+ ai_context`). Later or structurally different three-artifact manifests remain untouched.
