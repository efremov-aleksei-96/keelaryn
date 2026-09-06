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
- Block force pushes: **enabled**.
- Restrict deletions: **enabled**.

`distribution-gate` is intentionally not a global required check because the public-release workflow is path-scoped and does not run on every documentation/governance PR. It remains a release gate whenever that workflow is triggered, and release publication itself is separately fail-closed.

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

Local/source-only audit:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\Verify-RepositoryGovernance.ps1
```

Online audit on GitHub Actions is performed by `.github/workflows/repository-governance.yml`. It checks repository merge settings where visible, protected `main`, the named active ruleset, pull-request parameters, strict required checks, force-push blocking, deletion protection, the immutable-release source contract, and the existence of declared legacy release exceptions.

The native immutable-releases repository setting itself requires GitHub **Administration** permission to read/write. Ordinary Actions jobs deliberately run with read-only repository permissions, so this setting is verified at the administrator bootstrap boundary rather than by weakening workflow permissions.

The policy source stays separate from Manager qualification provenance. Changing repository governance does not retroactively rewrite the provenance of already qualified Manager releases.
