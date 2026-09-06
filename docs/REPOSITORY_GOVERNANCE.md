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

In **Settings > Rules > Rulesets**, create a branch ruleset named exactly:

`Keelaryn main governance`

Configure it as follows:

- Enforcement status: **Active**.
- Target: branch.
- Target branch: **main** / `refs/heads/main` only.
- Bypass list: **empty**. Do not grant the repository administrator, GitHub Apps, or other roles an unconditional bypass.
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

## Applying this governance PR

The `repository-governance` check is expected to fail while `main` is still unprotected. That failure is the intended bootstrap boundary.

1. Open the governance PR and allow `source-gate` to complete.
2. Apply the repository merge settings and the ruleset above in GitHub Settings.
3. Re-run the failed `repository-governance` check.
4. The check must report both source-contract PASS and online-enforcement PASS.
5. Merge the governance PR with **Squash and merge**.
6. Verify the post-merge `repository-governance` and `source-gate` checks on `main`.

Do not temporarily add bypass actors merely to merge the bootstrap PR. The PR itself was created before the ruleset, so once the ruleset is active it can be evaluated normally.

## Auditing

Local/source-only audit:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\Verify-RepositoryGovernance.ps1
```

Online audit on GitHub Actions is performed by `.github/workflows/repository-governance.yml`. It checks repository merge settings, protected `main`, the named active ruleset, pull-request parameters, strict required checks, force-push blocking and deletion protection.

The policy source must stay separate from Manager qualification provenance. Changing repository governance does not retroactively rewrite the provenance of already qualified Manager releases.
