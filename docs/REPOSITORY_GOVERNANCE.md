# Repository governance

`REPOSITORY_GOVERNANCE.json` is the machine-readable repository policy. This document is the maintainer-facing setup, audit and recovery guide.

Repository governance is a control-plane boundary. It does not change Manager product bytes, Gate Framework qualification identity or historical Manager release provenance.

## Why this exists

Manager release qualification is fail-closed, but release engineering alone cannot stop repository-level mistakes such as an unprotected `main`, a moved historical tag, an overwritten legacy release asset, or deletion of the sole ref preserving a rejected candidate. Repository Governance r5 covers those GitHub-side identities explicitly.

The repository is maintained by one person. A pull request record and CI are mandatory, while the required approving-review count remains zero so routine maintenance does not deadlock on a nonexistent independent reviewer.

## Merge settings

Required repository settings:

- squash merging: enabled;
- merge commits: disabled;
- rebase merging: disabled;
- auto-merge: disabled;
- automatic deletion of ordinary merged head branches: enabled.

The durable `main` history therefore contains one squash result per merged pull request while qualification provenance is preserved separately.

## Main ruleset

The active branch ruleset is named exactly `Keelaryn main governance` and targets only the default branch / `main`.

It requires:

- no bypass actors;
- pull requests before merge;
- zero required approvals;
- conversation resolution;
- squash-only merge;
- strict required checks:
  - `source-gate`
  - `repository-governance`
  - `release-policy`
- non-fast-forward updates blocked;
- deletion blocked.

`tools/Verify-RepositoryGovernance.ps1 -Online` verifies the effective server rules in addition to the source policy.

## Conditional release gate

`distribution-gate` is intentionally path-scoped because it performs release-specific work. It cannot itself be a universal required check: unrelated pull requests would otherwise wait forever for a workflow that never starts.

The globally required `release-policy` job therefore acts as the proxy:

1. it starts on every pull request to `main`;
2. it reads `release_policy.critical_paths` from `REPOSITORY_GOVERNANCE.json`;
3. non-release diffs pass immediately;
4. release-critical diffs must receive a successful `distribution-gate` on the exact PR head SHA;
5. failure, cancellation or timeout blocks merge.

The public-release pull-request path filter is independently compared with the same machine-readable critical-path set by the governance verifier. This prevents the executable release classifier and workflow trigger list from drifting silently.

## CI concurrency and evidence retention

Repository Governance r5 distinguishes disposable PR work from durable main-SHA evidence.

Obsolete runs for the same pull-request ref may be cancelled. Push runs on `main` must not be cancelled merely because a newer main commit appears. Consequently `windows-powershell.yml`, `repository-governance.yml` and `public-release.yml` use PR-only `cancel-in-progress` expressions. `release-policy.yml` is PR/manual-only and may retain ordinary cancellation behavior.

This reduces iterative CI churn without weakening the evidence associated with an already-created `main` commit.

## GitHub Actions supply chain

All external `uses:` references are pinned to full 40-hex commit SHAs. Moving action tags are not executable references. Human-readable version comments are kept so Dependabot can update immutable SHAs safely.

The allowlist is deliberately narrow:

- `actions/checkout@*`
- `actions/upload-artifact@*`
- `actions/download-artifact@*`

Server policy requires selected actions only, SHA pinning, read-only default workflow permissions, and no Actions approval of pull requests. `tools/Verify-GitHubActionsPolicy.ps1` validates the repository-side contract; administrator-only server settings remain an explicit admin boundary.

Hosted runners use explicit OS families rather than moving `*-latest` labels:

- `windows-2025`
- `ubuntu-24.04`

## Immutable releases

Future non-legacy Manager releases require GitHub native immutable releases plus release attestation and per-asset attestation verification.

The publication workflow:

1. gates the exact Manager release artifacts;
2. creates a draft release;
3. uploads the complete expected asset set;
4. publishes the draft;
5. requires `isImmutable=true`;
6. verifies the release attestation;
7. verifies each asset attestation;
8. re-downloads assets and proves byte identity with the gated build.

If a newly published release is unexpectedly mutable, publication deletes that newly-created unsafe release/tag and fails. Existing published releases are never silently rewritten.

## Legacy mutable release baseline

GitHub release immutability was enabled after the first public releases. Therefore these historical releases remain mutable at the platform level:

- `v4.11.0`
- `v4.12.0`
- `v4.13.1`

They are not merely listed as exceptions. `LEGACY_RELEASE_BASELINE.json` freezes for each release:

- exact release ID;
- exact lightweight tag target commit;
- expected mutable status;
- complete asset-name set;
- exact asset size;
- exact GitHub SHA-256 digest.

`tools/Verify-RepositoryGovernance.ps1 -Online` compares the live GitHub release and tag to this baseline. A missing asset, extra asset, moved tag, changed size or changed SHA-256 fails governance validation.

A legacy mutable release is historical evidence only. It must never be recreated or rewritten. The fact that GitHub still permits mutation is mitigated by exact baseline verification and protected release tags.

## Provenance tag lifecycle

Squash merging is excellent for public history but can leave rejected-candidate and qualification commits outside `main`. A development branch must therefore never be deleted merely because its product result was later squashed or superseded.

Repository Governance r5 introduces an immutable provenance tag lifecycle:

```text
preserved candidate / framework / release branch
    -> freeze exact branch-head SHA
    -> refs/tags/provenance/<branch-name>
    -> verify exact tag identity
    -> protect provenance/release tags server-side
    -> only then delete the development branch
```

Preserved-by-default branch prefixes are:

- `candidate-manager-`
- `framework-`
- `gate-framework-`
- `manager-`
- `release-manager-`

The tag ruleset is named exactly `Keelaryn immutable provenance tags`. It targets:

- `refs/tags/v*`
- `refs/tags/provenance/**`

and blocks both deletion and non-fast-forward/tag movement with an empty bypass list.

The branch name is disposable after freezing; the protected provenance tag is the long-lived snapshot identity. This keeps qualification history without accumulating mutable development branches indefinitely.

## Branch hygiene

The machine-readable branch hygiene policy is authoritative for cleanup decisions.

Ordinary merged service branches can be deleted once their squash result and PR record are durable. Preserved-prefix branches require the provenance flow above.

Cleanup rules:

- never delete `main`;
- never delete a branch with an open PR;
- never delete a preserved-prefix branch unless its exact head SHA is protected by `main`, a release identity, or an exact protected provenance tag;
- never wildcard-delete historical refs;
- never rewrite published release history merely to reduce branch count.

`tools/Invoke-RepositoryGovernanceAdmin.ps1` implements this boundary as an explicit Plan/Apply transaction. Plan mode is the default. Apply mode can create/update the provenance tag ruleset, freeze preserved branch heads, verify the new refs and then delete only the branch refs whose exact commits have already been preserved.

The tool also supports an explicit allowlist for non-provenance branch cleanup; it never treats that path as a bypass around preserved-branch checks.

## Administrator transaction

The admin tool reads policy from a named repository ref, so it can be reviewed on a governance PR before the source policy is merged.

Typical pre-merge plan:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\Invoke-RepositoryGovernanceAdmin.ps1 `
  -Mode Plan `
  -PolicyRef repository-governance-r5 `
  -FreezePreservedBranches `
  -CleanupFrozenBranches
```

After review, the same command with `-Mode Apply` performs the transaction. Server mutations are deliberately outside ordinary Actions jobs because those jobs retain read-only default permissions.

## Bounded release smoke

The first-run Generic DISTRIBUTION smoke in `.github/workflows/public-release.yml` uses a bounded process wait. If the console frontend does not terminate within the smoke timeout, CI kills the child process, performs a bounded cleanup wait and reports captured diagnostics instead of waiting for the entire job timeout.

This aligns repository release smoke behavior with the Gate Framework rule against unbounded child waits.

## Future provenance source identity

For future Manager releases, qualification provenance must record the exact **pre-provenance product-source commit** that was qualified, in addition to gate/framework revision and tested UPDATE SHA-256.

The final commit containing the provenance document is a different identity. Do not create an impossible self-reference by trying to store a commit SHA inside the same commit whose SHA depends on that file.

Existing historical provenance is not rewritten merely because the future contract is stronger.

## Auditing

Source-only audits:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\Verify-RepositoryGovernance.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\Verify-GitHubActionsPolicy.ps1
```

Online governance validates:

- merge policy and protected `main`;
- exact required checks and main ruleset behavior;
- provenance tag ruleset once activated;
- CI concurrency source policy;
- exact legacy mutable release baseline;
- release-critical path synchronization;
- bounded public-release smoke contract;
- Actions SHA pins and runner labels.

During the bootstrap PR only, absence of the new provenance tag ruleset is reported as a warning so the source policy can be reviewed first. The ruleset must be activated before the r5 source is merged; on `main` its absence is a hard failure.

Repository Governance r5 does not alter Manager product bytes or Gate Framework source bytes, and it does not retroactively change historical qualification provenance.
