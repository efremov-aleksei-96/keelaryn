# GitHub-first Manager development

## Status

This document defines the remote development workspace introduced by `DEVELOPMENT_GOVERNANCE.json`. It is a development accelerator, not a release qualification shortcut.

Keelaryn keeps the existing production/release boundary unchanged. `main`, release tags, GitHub Releases, production Doctor/UX checks, qualification provenance, and any applicable Full Gate remain governed by the existing repository and release policy.

## Development branch model

Unqualified work may be pushed to branches matching:

```text
dev/**
```

A `dev/**` branch is explicitly allowed to contain incomplete or failing intermediate commits. A successful development-validation run does **not** make the branch a Manager candidate and does not make it production-approved.

Recommended lifecycle:

```text
main / qualified source
    -> dev/manager-<version>
    -> iterative remote commits
    -> development-validation on windows-2025
    -> coherent development PASS
    -> candidate freeze / ordinary qualification
    -> PR to main with existing required checks
    -> production boundary where required
    -> squash merge / release publication
```

Development branches are ordinary temporary branches. Once their useful source/provenance is durably preserved by the normal Keelaryn candidate/release process, they should be deleted rather than accumulated indefinitely.

## Remote validation

`.github/workflows/development-validation.yml` runs on pushes to `dev/**` when Manager or development-validation infrastructure changes.

The workflow uses:

- `windows-2025`;
- repository token permission `contents: read`;
- full-SHA-pinned GitHub Actions from the existing allowlist;
- obsolete-run cancellation for the same development ref;
- a disposable runner-local workspace only.

`tools/Invoke-DevelopmentValidation.ps1` performs:

1. Windows PowerShell parser validation of Manager PowerShell source;
2. Manager SelfTest;
3. frontend SelfTest;
4. isolated deterministic `BuildRelease` twice;
5. SHA-256 equality of the expected release outputs;
6. compact JSON evidence generation.

The two disposable release trees are deleted before the workflow finishes. They are not uploaded as Actions artifacts.

## Evidence and storage budget

Development CI uploads only `DEVELOPMENT_VALIDATION.json`, retained for three days.

Do not upload:

- `tests/work`;
- disposable installations;
- duplicate BuildRelease A/B trees;
- ordinary intermediate SOURCE/DISTRIBUTION/UPDATE/AI_CONTEXT archives.

Generated release archives remain runtime/build products, not tracked Git source.

The development budget is intentionally conservative:

- repository target: under 100 MiB;
- repository warning: 250 MiB;
- tracked-file target: under 1 MiB;
- tracked-file warning: 5 MiB;
- tracked-file policy maximum: 50 MiB;
- active-branch target: under 50;
- Actions cache target: under 1 GiB;
- development artifact retention: 3 days.

These are Keelaryn policy budgets, not claims about GitHub hard limits.

## Promotion boundary

Remote development validation is `development_only`.

Before promotion:

- product bytes must use the normal Manager version/candidate discipline;
- a candidate is frozen rather than silently rewritten;
- applicable Source/Full Gate and rollback/migration tests still run;
- final production validation still runs where policy requires it;
- public provenance is written only for the qualified/published identity.

This separation is deliberate: development branches optimize iteration speed while `main` and releases preserve the stronger qualification/provenance model.

## Maintainer interaction model

The intended workflow is that ChatGPT can modify an accessible `dev/**` branch, read CI results, fix failures, and repeat without asking the maintainer to execute every intermediate Windows script.

A local Windows workstation remains necessary only for tests that depend on the actual production installation, real desktop integration, local security/ACL behavior, or other boundaries that GitHub-hosted disposable runners cannot faithfully represent.

For an existing local-only development line, one initial push is required to materialize that exact Git history on GitHub. After that, normal development iterations can occur on the remote branch.
