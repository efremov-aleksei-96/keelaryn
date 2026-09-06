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

## Repository governance

`REPOSITORY_GOVERNANCE.json` is the machine-readable repository policy and `docs/REPOSITORY_GOVERNANCE.md` is the maintainer setup guide. Changes must enter `main` through the active governance ruleset, required CI and squash-only merge. Do not use administrator bypasses to skip repository controls.

A repository/governance/docs-only PR does not require a Manager version change when `manager/` bytes and the frozen Gate Framework are unchanged. Qualification provenance for an already released Manager must not be rewritten merely because repository governance evolves later.

## Before a pull request

At minimum:

1. run `tools/Verify-PublicRepository.ps1`;
2. run `tools/Verify-RepositoryGovernance.ps1`;
3. parse PowerShell with Windows PowerShell 5.1;
4. run Manager, frontend and archive-tool SelfTests;
5. run the Hub-blind SourceGate through frozen `tests/framework/manager-gate`;
6. run the complete local Full Gate for any release candidate;
7. include benchmark evidence for performance-sensitive changes.

GitHub Actions is an additional source/repository check. It is not a substitute for the CURRENT-backed local Full Gate.

## Release discipline

Correctness, regression prevention, rollback/data safety, determinism and security outrank performance or convenience. Related low-risk changes may be batched to reduce manual Windows gates, but an issued defective candidate requires a new candidate version.

## License

By contributing, you agree that your contribution may be distributed under the repository MIT License.
