# Repository governance

`REPOSITORY_GOVERNANCE.json` is the machine-readable repository policy. This document is the maintainer-facing setup and recovery guide.

## Why this exists

Manager release qualification is fail-closed, but release engineering alone cannot stop an administrator from bypassing GitHub review and CI by writing directly to an unprotected `main` branch. Repository governance closes that control-plane gap without changing Manager product bytes.

The repository is currently maintained by one person, so the policy requires a pull request record and CI but deliberately requires **zero approving reviews**. Requiring another approval would deadlock ordinary maintenance without adding a real independent reviewer.

## Required repository merge settings

In **Settings > General > Pull Requests**:

- enable **Allow squash merging**;
- disable **Allow merge commits**;
- disable **Allow rebase merging**;
- keep auto-merge disabled.

The resulting `main` history is one reviewed/qualified commit per merged PR.

## Required main ruleset

The active branch ruleset is named exactly:

`Keelaryn main governance`

It must remain:

- Enforcement status: **Active**.
- Target: default branch / `main` only.
- Bypass list: **empty**.
- Require a pull request before merging: **enabled**.
- Required approving reviews: **0**.
- Require code owner review: **disabled**.
- Require approval of the most recent reviewable push: **disabled**.
- Dismiss stale approvals: **disabled**.
- Require conversation resolution before merging: **enabled**.
- Allowed merge methods: **squash only**.
- Require status checks to pass: **enabled**.
- Require branches to be up to date before merging / strict status checks: **enabled**.
- Required status checks, exactly:
  - `source-gate`
  - `repository-governance`
  - `release-policy`
- Block force pushes: **enabled**.
- Restrict deletions: **enabled**.

### Conditional release gate

`distribution-gate` is a real release qualification gate but its expensive public-release workflow is path-scoped. A path-scoped check cannot be listed directly as a universal branch requirement because GitHub would leave unrelated pull requests waiting for a check that never starts.

Repository Governance r2 solves this with the globally required `release-policy` proxy:

1. `release-policy` starts on **every** pull request to `main`.
2. It retrieves the full PR file list using the read-only GitHub token.
3. If no release-critical path changed, it immediately returns PASS.
4. If a release-critical path changed, it watches the **exact PR head SHA** for `distribution-gate`.
5. It returns PASS only when `distribution-gate` succeeds on that same head; failure, cancellation, timeout, or absence blocks merge.

Release-critical paths intentionally mirror the public-release pull-request triggers: Manager source, public provenance, repository governance, the release workflow itself, and the public release/onboarding documentation that is packaged or relied on by release publication.

This gives the branch ruleset a cheap always-present required context while still making the expensive release gate server-enforced only where applicable.

## GitHub Actions supply chain

Repository Governance r2 also treats workflow dependencies as part of the repository control plane.

All external `uses:` references in `.github/workflows` must be pinned to a **full 40-hex Git commit SHA**. Moving tags such as `@v4` or `@v6` are not accepted as executable references. A same-line version comment such as `# v6` is retained so Dependabot can update both the immutable SHA and its human-readable release marker.

The repository allowlist is deliberately narrow:

- `actions/checkout@*`
- `actions/upload-artifact@*`
- `actions/download-artifact@*`

Broad GitHub-owned and Marketplace verified-creator allowances are disabled. Future external actions require an explicit governance change before they can run.

`.github/dependabot.yml` performs weekly `github-actions` version updates so SHA pinning does not freeze dependencies indefinitely.

The server-side repository Actions policy must be:

- Actions enabled;
- `allowed_actions = selected`;
- `sha_pinning_required = true`;
- `github_owned_allowed = false`;
- `verified_allowed = false`;
- `patterns_allowed` exactly the three allowlist entries above;
- default `GITHUB_TOKEN` permissions = **read**;
- GitHub Actions may **not approve pull requests**.

Administrator-authenticated REST endpoints used by the bootstrap are:

```text
PUT /repos/efremov-aleksei-96/keelaryn/actions/permissions
PUT /repos/efremov-aleksei-96/keelaryn/actions/permissions/selected-actions
PUT /repos/efremov-aleksei-96/keelaryn/actions/permissions/workflow
```

`tools/Verify-GitHubActionsPolicy.ps1` validates the repository-side source contract on Windows PowerShell 5.1. The server-side settings require repository Administration permission and are verified by the administrator bootstrap rather than by widening ordinary workflow permissions.

## Immutable releases

Repository Governance r2 requires **GitHub native immutable releases** for every future non-legacy Manager release.

Enable the repository setting through GitHub **Settings > General > Releases > Enable release immutability**, or with an administrator-authenticated GitHub CLI:

```text
gh api --method PUT repos/efremov-aleksei-96/keelaryn/immutable-releases -H "X-GitHub-Api-Version: 2026-03-10"
```

Verify it with an administrator-authenticated token:

```text
gh api repos/efremov-aleksei-96/keelaryn/immutable-releases -H "X-GitHub-Api-Version: 2026-03-10"
```

The expected response contains `"enabled": true`.

GitHub applies this setting only to releases published after it is enabled. Historical mutable releases are therefore represented explicitly by `release_policy.immutable_releases.legacy_mutable_tags` in `REPOSITORY_GOVERNANCE.json`.

A **legacy mutable** release is a historical exception only:

- it must already exist;
- it must never be recreated by the publisher;
- its release assets must remain byte-identical to the gated build;
- it is not evidence that future mutable releases are acceptable.

## Publication contract for future releases

For a new non-legacy release, `.github/workflows/public-release.yml` performs the following sequence:

1. Build and gate the exact Manager artifacts.
2. Create a **draft** GitHub Release and attach all release assets before publication.
3. Publish the draft.
4. Require GitHub to report `isImmutable=true`.
5. Verify the GitHub **release attestation** with `gh release verify`.
6. Verify every published local asset against the release attestation with `gh release verify-asset`.
7. Re-download the release assets and require byte-for-byte identity with the gated build.

If a newly published release is unexpectedly mutable, the workflow immediately deletes that new mutable release and its new tag and fails the publication job. An existing published non-legacy mutable release is never silently overwritten or deleted; publication fails for investigation.

For a workflow retry that finds an unfinished draft, the draft is recoverable only when it targets the exact current publication commit. Expected assets may be refreshed while it is still a draft; publication occurs only after the gated asset set is complete.

## Legacy 4.13.1 boundary

`v4.13.1` predates native immutable-release enforcement and remains a historical mutable exception. Repository Governance r2 does not rewrite its tag, release, or assets. Re-running the release workflow against 4.13.1 succeeds only after the already-published assets are proven byte-identical to the gated artifacts.

Once a release is native-immutable, it must not be added to the legacy exception list.

## Auditing

Local/source-only audits:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\Verify-RepositoryGovernance.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\Verify-GitHubActionsPolicy.ps1
```

Online audit on GitHub Actions is performed by `.github/workflows/repository-governance.yml`. It checks repository merge settings where visible, protected `main`, the named active ruleset, pull-request parameters, the three strict required checks, force-push blocking, deletion protection, the immutable-release source contract, declared legacy release exceptions, action SHA pins, the explicit action allowlist, and Dependabot configuration.

`.github/workflows/release-policy.yml` independently enforces the conditional relationship between release-critical PRs and `distribution-gate` on the exact current head SHA.

The native immutable-releases and server-side GitHub Actions policy settings require GitHub **Administration** permission to read/write. Ordinary Actions jobs deliberately run with read-only repository permissions, so these settings are verified at the administrator bootstrap boundary rather than by weakening workflow permissions.

The policy source stays separate from Manager qualification provenance. Changing repository governance does not retroactively rewrite the provenance of already qualified Manager releases.
