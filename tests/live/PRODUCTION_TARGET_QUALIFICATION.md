# Production migration target qualification run

This document defines the guarded one-shot live runner for constructing and qualifying the **new zero-based production target** from one exact frozen migration candidate.

It is not a cutover procedure. A PASS from this runner does not authorize selector mutation, does not make the new Hub active, and does not retire the legacy Hub rollback path.

## Preconditions

Run only after all of the following are true:

- the exact `dev/zero-based-keelaryn` source identity intended for qualification has coherent development PASS;
- the private migration pack has been explicitly frozen and its receipt verifies as `FROZEN_UNQUALIFIED`;
- the private pack and freeze receipt remain outside the Git worktree;
- the live legacy source still matches the frozen source boundary;
- a dedicated Drive staging root exists with the exact guarded name/sentinel required by `DriveMigrationProductionTargetQualification`;
- the staging root is reserved only for this migration target workflow;
- production selector/cutover is not being executed concurrently;
- Google OAuth credentials used by the runner have only the access required for the intended Drive operation.

Do not place private migration payloads, source paths, Drive IDs, OAuth values or account identities into GitHub issues, commits, CI artifacts, chat handoffs or public evidence.

## Runner

The executable is:

`tests/live/run_migration_production_qualification.py`

It requires the exact explicit enable value:

`KEELARYN_PRODUCTION_TARGET_QUALIFICATION_ENABLE=YES`

Any other value blocks before OAuth/Drive initialization.

Required local/private environment:

- `KEELARYN_MIGRATION_PACK_DIR`
- `KEELARYN_MIGRATION_FREEZE_RECEIPT`
- `KEELARYN_MIGRATION_REPO_ROOT`
- `KEELARYN_MIGRATION_LEGACY_SOURCE_ROOT_ID`
- `KEELARYN_MIGRATION_TARGET_AUTHORITY`
- `KEELARYN_MIGRATION_QUALIFICATION_EVIDENCE`
- `KEELARYN_PRODUCTION_MIGRATION_STAGING_ROOT_ID`
- `KEELARYN_GOOGLE_CLIENT_ID`
- `KEELARYN_GOOGLE_CLIENT_SECRET`
- `KEELARYN_GOOGLE_REFRESH_TOKEN`

The target authority and qualification evidence paths must remain outside both the Git worktree and the immutable migration pack.

## Safety contract

The runner delegates construction to `DriveMigrationProductionTargetQualification`, which:

1. freshly verifies the exact private pack and frozen candidate receipt;
2. verifies the live legacy source against the frozen source manifest before target creation;
3. verifies the dedicated staging root and exact sentinel;
4. reserves and durably records one exact Drive target ID in private local authority before creation;
5. revalidates the staging root at the target-creation boundary;
6. constructs the new target only through the existing restart-safe migration rehearsal/Core path;
7. performs fresh post-construction pack/freeze/source/staging verification;
8. writes sanitized qualification evidence only after all checks pass;
9. distinguishes a durably constructed target from a later qualification/evidence failure;
10. never mutates the production selector.

The wrapper additionally rejects success output if it contains the staging Drive ID or any configured private path.

## Output

On success stdout contains one compact JSON object with schema:

`keelaryn.migration-production-live-run.v1`

It contains the sanitized target qualification evidence plus:

- `production_selector_mutated=false`
- `cutover_authorized=false`

Real Drive IDs and local/private paths are excluded.

On failure stderr contains only:

- schema `keelaryn.migration-production-live-failure.v1`;
- the coarse execution phase;
- the exception class.

Exception text is deliberately not emitted because transport/protocol errors may contain Drive IDs, URLs, private source names or local paths. Detailed private diagnosis should use the local authority/evidence material and controlled local logs, not public CI output.

## Terminal interpretation

`TARGET_QUALIFICATION_PASS` means only that the exact frozen candidate was successfully constructed and freshly qualified on the new production-target Hub while the legacy Hub remains active.

After PASS:

- preserve the target authority, qualification evidence, frozen candidate receipt and legacy Hub;
- independently review the qualification evidence and exact source/runtime identities;
- obtain explicit production cutover approval as a separate transaction boundary;
- only then run the production selector cutover protocol and post-cutover acceptance.

If construction succeeded but a later post-construction check or evidence publication failed, do not recreate or silently replace the target. Preserve it for diagnosis and classify the failure using the durable target authority.
