# Contributing

## Compatibility target

The primary runtime compatibility target is **Windows PowerShell 5.1 Desktop**. Managed executable PowerShell/CMD source is kept ASCII-compatible where required by the product contracts.

## Development rules

- Work in disposable `tests/work` targets.
- Never use a personal production Hub as a mutable development fixture.
- Do not silently replace an issued candidate after a real product defect.
- Preserve fresh validation at transaction/commit boundaries.
- Prefer eliminating duplicate work over removing validation.
- Keep personal Hub data, credentials and local Manager state out of source/tests/docs.
- Gate Framework revisions are qualified independently before they are frozen for Manager candidates.

## Before a pull request

At minimum:

1. run `tools/Verify-PublicRepository.ps1`;
2. parse PowerShell with Windows PowerShell 5.1;
3. run Manager, frontend and archive-tool SelfTests;
4. run the Hub-blind SourceGate through frozen `tests/framework/manager-gate`;
5. run the complete local Full Gate for any release candidate;
6. include benchmark evidence for performance-sensitive changes.

GitHub Actions is an additional source/repository check. It is not a substitute for the CURRENT-backed local Full Gate.

## Release discipline

Correctness, regression prevention, rollback/data safety, determinism and security outrank performance or convenience. Related low-risk changes may be batched to reduce manual Windows gates, but an issued defective candidate requires a new candidate version.

## License

By contributing, you agree that your contribution may be distributed under the repository MIT License.
