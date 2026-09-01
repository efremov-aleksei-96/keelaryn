# Hub CANDIDATE transport fallback

`Keelaryn__Hub_CANDIDATE_*.zip` remains the primary, complete, non-canonical worker checkpoint sent to Chat Manager. Candidate transport does not replace ZIP, does not become canonical state, and is never installed by `UPDATE_HUB.cmd`.

## Build fallback transport

Place one or more validated `Keelaryn__Hub_CANDIDATE_*.zip` files in Manager `_inbox`, keep the matching canonical `Keelaryn__Hub_CURRENT.zip` in place, and run `BUILD_CANDIDATE_TRANSPORT.cmd`.

For every CANDIDATE, Manager writes `Keelaryn__Hub_CANDIDATE_TRANSPORT_<artifact-id>.json` beside it. Schema `keelaryn.hub.candidate-transport.v1` contains a deterministic Base64 delta from the exact CURRENT reconstruction baseline to the complete portable CANDIDATE tree.

The transport records:

- reconstruction CURRENT system/data/instance/artifact identity plus payload/content SHA-256;
- CANDIDATE system/data/instance/artifact identity and declared ancestry;
- source CANDIDATE ZIP filename, size and SHA-256 for provenance;
- ordered `delete` and `put` operations;
- exact byte length and SHA-256 for every embedded `put` payload.

Binary and text files use Base64 uniformly so UTF-8 BOMs, arbitrary binary data and line endings survive byte-for-byte.

## Restore fallback transport

If the original CANDIDATE ZIP is unavailable, place its transport JSON in `_inbox` with the exact CURRENT used as `reconstruction_base`, then run `RESTORE_CANDIDATE_TRANSPORT.cmd`.

Manager validates the JSON schema, path safety, operation uniqueness, Base64 bytes, per-file hashes, CURRENT reconstruction identity and all resulting Hub identities. It reconstructs a complete portable ZIP named `Keelaryn__Hub_CANDIDATE_RECONSTRUCTED_<artifact-id>.zip` and validates STATE, derived metadata, MANIFEST, ARTIFACT, payload/content hashes before publication.

The reconstructed ZIP is still a CANDIDATE. Chat Manager must perform the normal semantic reconciliation/approval workflow. `RESTORE_CANDIDATE_TRANSPORT.cmd` never edits Hub, CURRENT, APPROVED state or candidate transport JSON.

## Scope and limits

Transport v1 is intentionally conservative:

- requires artifact schema `keelaryn.artifact.v3` for both reconstruction CURRENT and CANDIDATE;
- reconstruction is instance-bound;
- operations are `put` and `delete`; rename is represented deterministically as delete+put;
- local deployment state is excluded/rejected exactly like portable Hub packages;
- the JSON is bounded to 128 MiB and embedded changed raw bytes to 90 MiB;
- individual embedded files retain the existing 64 MiB Hub entry limit;
- a candidate whose delta exceeds these limits continues to use the primary ZIP workflow only.

The format is a transport-resilience mechanism, not a persistent cache, backup authority or alternate approval protocol.

## Privacy

The transport JSON may embed exact changed Hub bytes in Base64. Treat it with the same confidentiality expectations as the corresponding CANDIDATE ZIP. It is instance-specific data and must never be included in generic Manager release artifacts.
