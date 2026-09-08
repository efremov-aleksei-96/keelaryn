# Remote and disposable Manager qualification

## Purpose

Keelaryn Manager development should not require the maintainer to be physically present at a Windows workstation for every development iteration. Repository-hosted Windows execution can perform a deep disposable prequalification while the maintainer works from a phone or another non-Windows device.

This facility is intentionally narrower than production qualification. It reduces manual Windows cycles; it does not weaken or replace the final production boundary.

## Execution model

The `Windows disposable Full Gate` workflow runs on the pinned GitHub-hosted `windows-2025` runner with repository contents read-only.

For a Manager candidate it:

1. checks out the candidate and the trusted PR base separately;
2. verifies the public repository boundary and GitHub Actions policy;
3. refuses a mixed Gate Framework change;
4. resolves an older Manager baseline;
5. creates an ephemeral canonical Keelaryn installation under the GitHub runner temporary directory;
6. copies only the baseline public Manager source into the synthetic installation;
7. creates a sanitized Hub through non-interactive Genesis;
8. runs baseline Doctor;
9. builds `manager-<version>.zip` with the Gate Framework from the trusted base;
10. runs the frozen Windows PowerShell 5.1 Full Gate against the synthetic baseline;
11. checks that the synthetic Manager, Hub, and CURRENT baseline were not changed by the Full Gate production-read-only boundary;
12. uploads logs, gate results, the exact gate ZIP, and `PREQUALIFICATION.json` as short-lived workflow evidence.

The synthetic Hub contains no personal Hub data. Its Genesis input is a generic qualification fixture only.

## Baseline resolution

For a normal Manager PR where the candidate version is newer than `main`, the exact PR base commit is the disposable baseline.

For repository-infrastructure bootstrap where candidate and base Manager versions are byte-identical, the workflow uses the prior Manager version recorded by the trusted base `PUBLIC_PROVENANCE.json`. This permits the remote qualification infrastructure itself to be tested without inventing a new Manager version.

A manual workflow dispatch may provide an explicit baseline ref. The runner still requires the candidate Manager version to be newer than the resolved baseline.

Changing Manager bytes without changing the Manager version is rejected.

## Gate revision namespace

Disposable/remote qualification uses gate revisions `>= 9000`. These revisions are reserved for CI/disposable evidence and must never be interpreted as production qualification revisions.

The first workflow revision uses gate revision `9002`. Existing ordinary qualification provenance is not rewritten.

## Security boundary

The remote runner is not a general remote PowerShell endpoint. It accepts repository refs and executes a fixed qualification pipeline.

The workflow:

- uses a GitHub-hosted Windows runner, not a maintainer workstation;
- receives no personal Hub archive;
- uses `contents: read` as its default token permission;
- uses full-SHA-pinned external GitHub Actions already permitted by repository governance;
- does not publish releases or modify repository refs;
- does not write to a real production Keelaryn installation;
- rejects reparse points in candidate, baseline, and framework input trees;
- validates the generated gate ZIP before extraction;
- requires the Full Gate's production-path isolation and immutability findings to pass.

For the bootstrap PR only, the trusted base does not yet contain the disposable runner script. In that single compatibility case the workflow uses the candidate copy of the runner, still with a read-only token, no secrets, a synthetic Hub, and the frozen Gate Framework from the trusted base. After this infrastructure is merged, subsequent Manager candidates use the runner implementation from their trusted base.

## Evidence semantics

`PREQUALIFICATION.json` uses schema `keelaryn.manager.disposable-prequalification.v1` and is deliberately explicit:

- `classification = synthetic_disposable_only`;
- `personal_hub_used = false`;
- `production_qualified = false`;
- `requires_real_production_validation = true`.

A green disposable Full Gate means that the candidate survived the deep Windows/disposable regression suite against a synthetic baseline. It is strong development evidence, but it is not sufficient to publish or describe the candidate as production-approved.

## Production release boundary

Normal Keelaryn release discipline remains unchanged. Before production approval, all applicable gates still have to pass against the required real production boundary, including the exact candidate/update identity, production Doctor, production UX smoke where required, Hub immutability, update/rollback behavior, and any other release-specific checks defined by current qualification policy.

The remote workflow is therefore a prequalification accelerator: most defects can be discovered from any device before the maintainer spends a manual Windows cycle on the final candidate.

## Mobile workflow

From GitHub on a phone, the maintainer can review a development branch or PR and inspect the `Windows disposable Full Gate` result and its evidence artifact. Manual runs are available through the workflow dispatch interface by selecting a candidate ref and, when necessary, an explicit older baseline ref.

This keeps Windows as an execution environment rather than a mandatory interactive workstation.
