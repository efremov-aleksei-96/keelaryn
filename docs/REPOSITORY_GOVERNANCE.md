# Repository governance

`REPOSITORY_GOVERNANCE.json` is the machine-readable repository policy. This document is the maintainer-facing setup, audit and recovery guide.

Repository governance is a control-plane boundary. It does not change Manager product bytes, Gate Framework qualification identity, personal Hub state, or historical Manager release provenance. The contract covers branch hygiene, release identity, CI governance and provenance preservation explicitly.

## Main branch and merge policy

The default branch is `main`. The active branch ruleset is named exactly `Keelaryn main governance` and targets only `main`.

Required behavior:

- squash merging enabled;
- merge commits disabled;
- rebase merging disabled;
- auto-merge disabled;
- ordinary merged branches deleted automatically;
- no ruleset bypass actors;
- pull requests required before merge;
- zero required approvals for the single-maintainer repository;
- review-thread resolution required;
- strict required checks: `source-gate`, `repository-governance`, `release-policy`;
- non-fast-forward updates and branch deletion blocked.

## Source and online verification

Repository Governance r5 separates two trust boundaries:

- `tools/Verify-RepositoryGovernance.ps1` validates repository source policy;
- `tools/Verify-RepositoryGovernanceOnline.ps1` validates effective GitHub server state and historical release identities.

The `repository-governance` workflow runs both. The online verifier therefore cannot silently substitute for source validation, and source validation does not depend on GitHub API representation details.

## Conditional release gate

`distribution-gate` is release-specific and path-scoped. The universally required `release-policy` job acts as the proxy:

1. every PR to `main` gets `release-policy`;
2. it reads `release_policy.critical_paths` from `REPOSITORY_GOVERNANCE.json`;
3. non-release diffs pass immediately;
4. release-critical diffs require a successful `distribution-gate` on the exact current PR head SHA;
5. failure, cancellation or timeout blocks merge.

The public-release workflow path filters are independently compared with the same machine-readable policy so release classification cannot drift silently.

## CI concurrency

Repository Governance r5 distinguishes disposable PR work from durable main-SHA evidence.

Obsolete pull-request runs may be cancelled for the explicitly governed workflows:

- `.github/workflows/repository-governance.yml`;
- `.github/workflows/public-release.yml`;
- `.github/workflows/release-policy.yml`.

For workflows governed by r5, push/main runs are not cancelled merely because a newer main commit appears.

### Deferred source validation concurrency

`.github/workflows/windows-powershell.yml` is deliberately **not modified by r5**. It remains byte-identical to the already-qualified `main` baseline.

The audit found that its existing top-level `cancel-in-progress: true` can cancel older main-SHA source evidence. An attempted repo-only fix also exposed that the current disposable qualification scope treats any `windows-powershell.yml` byte change as a reason to run a Manager version-transition Full Gate. With Manager still at 4.15.1, that path incorrectly reaches the historical `source_gate_baseline_manager_version` value 4.15.0, for which no release tag exists.

The Full Gate invariant `candidate_version > baseline_version` is correct and must not be weakened merely to obtain CI cancellation optimization. Therefore r5 records `windows-powershell.yml` in `ci_concurrency.deferred_workflows`, preserves its qualified bytes, and leaves the source-validation scope redesign for a separate independently qualified engineering cycle.

This is an explicit known limitation, not a claim that source validation already satisfies the new concurrency policy.

## GitHub Actions supply chain

All external `uses:` references are pinned to full 40-hex commit SHAs. Moving action tags are not executable references.

Allowed external action families are deliberately narrow:

- `actions/checkout@*`;
- `actions/upload-artifact@*`;
- `actions/download-artifact@*`.

Hosted runners use explicit OS families (`windows-2025`, `ubuntu-24.04`) rather than `*-latest`.

The repository-side policy is checked by `tools/Verify-GitHubActionsPolicy.ps1`. Administration-only Actions settings remain an explicit admin boundary.

## Immutable releases

Future non-legacy Manager releases require GitHub native immutable releases plus release attestation and per-asset attestation verification.

Publication is fail-closed: the workflow creates a draft, uploads the expected assets, publishes, requires native immutability, verifies the release attestation and each asset attestation, and re-downloads assets to prove byte identity. A newly-created unexpectedly mutable release is deleted together with its new tag and publication fails.

Existing historical releases are never silently rewritten.

## Legacy mutable release baseline

These historical releases predate native repository release immutability:

- `v4.11.0`;
- `v4.12.0`;
- `v4.13.1`.

`LEGACY_RELEASE_BASELINE.json` freezes for each legacy mutable release:

- exact release ID;
- exact lightweight tag target commit;
- expected mutable state;
- complete asset-name set;
- exact asset size;
- exact GitHub SHA-256 digest.

`Verify-RepositoryGovernanceOnline.ps1` compares the live release and tag against this baseline. Missing or extra assets, moved tags, changed sizes or changed SHA-256 values fail governance validation.

These legacy mutable releases are historical evidence only. They are never recreated or rewritten merely to conform to newer policy.

## Provenance tag lifecycle

Squash merging can leave rejected-candidate and qualification commits outside `main`. A development branch must therefore never be deleted merely because its product result was later squashed or superseded.

Repository Governance r5 uses this lifecycle:

```text
preserved qualification branch
    -> freeze exact branch-head SHA
    -> refs/tags/provenance/<branch-name>
    -> verify exact tag identity
    -> protect release/provenance tags server-side
    -> only then delete the development branch
```

Preserved-by-default branch prefixes are:

- `candidate-manager-`;
- `framework-`;
- `gate-framework-`;
- `manager-`;
- `release-manager-`.

The provenance tag ruleset is named exactly `Keelaryn immutable provenance tags`. It covers `refs/tags/v*` and `refs/tags/provenance/**`, has an empty bypass list, and blocks deletion and non-fast-forward/tag movement.

## Branch hygiene

Ordinary merged service branches may be deleted once their PR/squash result is durable. Preserved-prefix branches require the provenance flow above.

Rules:

- never delete `main`;
- never delete a branch with an open PR;
- never delete a preserved-prefix branch unless its exact head SHA has already been preserved by a protected identity;
- never wildcard-delete historical refs;
- never rewrite published release history merely to reduce branch count.

`tools/Invoke-RepositoryGovernanceAdmin.ps1` implements this boundary as an explicit `Plan` / `Apply` transaction. `Plan` is the default and performs no mutation. `Apply` creates or verifies the provenance tag ruleset, freezes exact preserved branch heads, verifies the resulting refs, and only then may remove development branch refs.

## Administrator transaction

The admin tool can read policy from the reviewed PR branch before r5 is merged.

Pre-merge plan:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\Invoke-RepositoryGovernanceAdmin.ps1 `
  -Mode Plan `
  -PolicyRef repository-governance-r5 `
  -FreezePreservedBranches `
  -CleanupFrozenBranches
```

After review, the same command with `-Mode Apply` performs the transaction. Server mutations remain outside ordinary Actions jobs because CI keeps read-only default permissions.

The provenance tag ruleset must be active before r5 is merged. During the bootstrap PR only, the online verifier may report its absence as a warning; on `main` its absence is a hard governance failure.

## Bounded public-release smoke

The Generic DISTRIBUTION first-run smoke in `.github/workflows/public-release.yml` uses a bounded child-process wait. A hung console frontend is killed after the explicit timeout and captured diagnostics are reported instead of waiting for the overall job timeout.

## Future provenance source identity

For future Manager releases, qualification provenance must record the exact pre-provenance product-source commit that was qualified, in addition to gate/framework revision and tested UPDATE SHA-256.

The final commit containing the provenance document is a separate identity. Do not attempt an impossible self-reference by storing a commit SHA inside the same commit whose SHA depends on that file.

Historical provenance is not rewritten merely because the future contract is stronger.

## Audit commands

Source contract:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\Verify-RepositoryGovernance.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\Verify-GitHubActionsPolicy.ps1
```

Online enforcement:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\Verify-RepositoryGovernanceOnline.ps1
```

Repository Governance r5 remains repository-only. Manager 4.15.1 product bytes and Gate Framework r12 source bytes are unchanged by this governance cycle.
