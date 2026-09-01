# Contributing

## Environment

The compatibility target is Windows PowerShell 5.1. Managed executable `.ps1` source is ASCII-only to avoid Windows PowerShell 5.1 UTF-8-without-BOM ambiguity; Unicode behavior is constructed by code point where necessary.

## Development rules

- Work only in disposable `tests/work` copies.
- Do not run destructive development tests against an installed production Hub.
- Do not silently modify an issued candidate after a defect is found.
- Preserve fresh validation at transaction/commit boundaries.
- Prefer removing duplicate work over removing validation.
- Do not add personal Hub data to product source, tests, docs or examples.

## Before a pull request

At minimum:

1. run `tools/Verify-PublicRepository.ps1`;
2. parse all managed PowerShell files with Windows PowerShell 5.1;
3. run Manager `-SelfTest`;
4. build AI_CONTEXT;
5. run deterministic `BUILD_RELEASE` twice and compare artifact hashes;
6. use a disposable Hub for update/migration changes;
7. record benchmark evidence for performance claims.

## Commit scope

Keep security/update/rollback changes separate from unrelated performance experiments when combined risk would make failures harder to diagnose. Related low-risk maintenance changes may be batched when they can share one release gate.

## CI policy

Run Keelaryn development gates locally. The GitHub-hosted Windows workflow is manual-only and is intended for milestone/publication verification, not for every push. Do not change it back to automatic `push`/`pull_request` triggers without a specific repository-level reason.

## Licensing of contributions

By submitting a contribution to this repository, you agree that the contribution may be distributed under the repository's MIT License.
