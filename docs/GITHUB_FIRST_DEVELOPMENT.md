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

The intended workflow is that ChatGPT performs as much development work as the connected environment safely permits instead of turning the maintainer into a remote shell operator.

After a `dev/**` line exists on GitHub, the remote branch is authoritative. Normal development should therefore prefer, in order:

1. exact GitHub source inspection and direct `dev/**` commits;
2. GitHub Actions for disposable validation, diagnosis and regression evidence;
3. connected Google Drive only when the task genuinely depends on Drive-held authoritative inputs or evidence;
4. the production VPS only for evidence or state transitions that cannot be reproduced on disposable GitHub infrastructure.

The maintainer should not be asked to run intermediate local PowerShell or SSH when an equivalent read-only check, edit or disposable validation can be performed remotely. Production/VPS commands requested from the maintainer should be reduced to one coherent action at a time and only when direct server execution is unavailable or the evidence is inherently production-specific.

Long-running or mutation-capable production operations must not depend on a chat stream, terminal window or SSH connection remaining open. They should execute through the durable Operation Runtime once that runtime is available; until then, every production mutation remains transactional and is followed by durable-state reconciliation before any retry.

### Durable continuation handoff

Chat memory is never authoritative project state. Every active development line should maintain a newest sanitized handoff under `docs/handoffs/` containing:

- authoritative branch and HEAD;
- qualified/frozen identities relevant to the current line;
- current production/development transaction state;
- last confirmed PASS/FAIL or interrupted boundary;
- exact blocker/classification;
- the next permitted action and explicitly forbidden retries.

The handoff must contain no OAuth credentials, private keys, raw private Hub IDs or other secrets. It is updated at significant checkpoints so a new ChatGPT conversation can resume from repository state without reconstructing critical operational facts from chat history. Volatile handoffs are development coordination artifacts and may be retired when their line is durably closed or superseded.

For an existing local-only development line, one initial push is required to materialize that exact Git history on GitHub. After that, normal development iterations can occur on the remote branch.
