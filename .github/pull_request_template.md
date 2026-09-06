## Scope

Describe the change and why it belongs in this repository.

## Boundary classification

- [ ] Manager product bytes changed. If yes, use a new Manager candidate/version and provide its exact identity.
- [ ] Gate Framework source changed. If yes, use a new framework revision and qualify it independently.
- [ ] Repository/governance/docs-only change; Manager product bytes and frozen Gate Framework are unchanged.

## Validation

- [ ] `tools/Verify-PublicRepository.ps1` PASS.
- [ ] `tools/Verify-RepositoryGovernance.ps1` source contract PASS.
- [ ] `source-gate` PASS.
- [ ] Any change that can alter released Manager bytes has the applicable Windows Full Gate / production evidence.
- [ ] No personal Hub data, credentials, local Manager state, disposable test evidence, or maintainer-only paths were introduced.

## Release discipline

State whether this PR changes release artifacts, qualification evidence, repository governance only, or no release state at all. Never rewrite an already issued candidate after a product defect.
