# Disposable Google Drive live acceptance

This directory contains the **manual live acceptance gate** for the zero-based Drive line. It is development evidence only. It must never target the production/personal Hub.

## Safety model

The gate does **not** receive an existing Hub ID. It receives only a dedicated empty acceptance-root folder and then creates fresh disposable child Hubs for PASS and FAIL scenarios.

Before its first mutation the harness verifies all of the following:

1. the configured Drive object is a live folder named exactly `Keelaryn__DISPOSABLE_LIVE_ACCEPTANCE_ROOT`;
2. it contains exactly one ordinary file named `README.md` whose bytes exactly match `fixtures/README.md`;
3. every other existing child is a folder created by a prior acceptance run and has the expected disposable prefix;
4. the run ID is syntactically safe.

Any mismatch blocks before the harness creates new Drive objects.

## Required Google identity boundary

Use a **dedicated test Google identity** for this gate. That identity must have access only to the disposable acceptance root needed by the test and must not have access to the production/personal Hub.

The GitHub secrets are therefore not merely alternate credentials for the normal account; they are a separate security boundary.

## One-time Drive preparation

Using the dedicated test identity:

1. Create one folder named exactly:

   `Keelaryn__DISPOSABLE_LIVE_ACCEPTANCE_ROOT`

2. Upload `tests/live/fixtures/README.md` into that folder as an ordinary file named exactly `README.md`. Do not create a Google Docs document; the harness verifies exact downloaded bytes.
3. Record the Drive file ID of the acceptance-root folder.
4. Do not place personal files or normal Keelaryn Hub material inside this root.

Prior disposable child folders created by successful/failed acceptance runs may remain there; the harness recognizes only the expected disposable prefix and does not reuse them.

## Required GitHub secrets

Configure these repository secrets only when the dedicated test identity/root exist:

- `KEELARYN_DISPOSABLE_ENABLE` = `YES`
- `KEELARYN_DISPOSABLE_GOOGLE_CLIENT_ID`
- `KEELARYN_DISPOSABLE_GOOGLE_CLIENT_SECRET`
- `KEELARYN_DISPOSABLE_GOOGLE_REFRESH_TOKEN`
- `KEELARYN_DISPOSABLE_ACCEPTANCE_ROOT_ID`

Never store secret values in repository files, Hub history, issue/PR text, CI artifacts, or chat handoffs.

## Manual run

The zero-based live gate is routed through the existing default-branch workflow named **Development validation**.

In GitHub Actions:

1. Open **Development validation**.
2. Choose **Run workflow**.
3. Select branch `dev/zero-based-keelaryn`.
4. Set `confirm_disposable_drive` to **YES**. The default is **NO**; leaving it at NO makes the disposable job ineligible.
5. Start the run.

For that exact branch/manual-event combination:

- the legacy Manager development job is skipped;
- only the guarded zero-based Drive disposable acceptance job is eligible;
- only the repository owner is allowed by the job condition;
- the explicit workflow input must be `YES`;
- `KEELARYN_DISPOSABLE_ENABLE` must independently be `YES`;
- all dedicated disposable credential/root secrets must be non-empty;
- the live harness still independently verifies the exact acceptance-root name and sentinel bytes before its first Drive mutation;
- runs are queued rather than canceling an earlier live acceptance mid-mutation.

Normal zero-based push validation remains the separate **Zero-based Core validation** workflow.

## Execution budget and interrupted-run recovery

The guarded GitHub live job has a **45-minute** execution budget. External VPS/systemd wrappers for the same official harness must allow at least the same 45-minute budget unless a separately qualified tighter bound exists. This is an orchestration ceiling, not a transaction timeout: Drive latency can make a valid PASS+ROLLBACK run substantially slower than deterministic CI.

If the process, transport, shell, CI job, or wrapper times out after Drive mutation may have begun, the result is incomplete evidence rather than permission to rerun blindly. Preserve the failed execution evidence, inspect the durable PASS/FAIL child Hub state and service safety read-only, and classify whether Core or only the gate wrapper failed. A retry **must not reuse the same run ID**; use a fresh run ID only after reconciliation proves the prior run's durable state and it is safe to start another independent disposable run.

A timeout does not convert already durable COMMITTED/ROLLED_BACK state into PASS evidence by itself. The successful gate still requires the official harness to return its complete compact PASS JSON and exit successfully.

## Expected live evidence

A successful live gate creates two fresh child Hubs under the acceptance root and proves, through the real Google Drive REST API path, all of the following in **both** PASS and FAIL child Hubs:

- fresh Hub bootstrap as SAFE epoch 0;
- exact deterministic bootstrap `README.md`, `INDEX.md` and initial Reconciliation `STATE.md`;
- fresh Workspace starts with no Projects;
- Project creation is exact and idempotent;
- Workspace list/read returns the exact created Project;
- Project `STATE.md` update uses the restart-safe copy-on-write work-state path and becomes visible through list/read;
- ADD + REPLACE + DELETE transaction reaches semantic post-check;
- semantic PASS → `COMMITTED`;
- semantic FAIL → `ROLLED_BACK` with OLD canonical state restored;
- canonical epoch increments exactly once in each child Hub;
- final Ready Change consumption + locator cleanup;
- subsequent polling returns clean `IDLE`.

The harness prints only compact status JSON. Each case reports `human_surface_verified=true` and `workspace_verified=true`; Hub IDs and credential values are intentionally omitted from normal output.

A PASS here is still **not** production authorization. It is live disposable Drive development evidence only. Production-specific qualification is a later, separate gate.

## Exact migration-candidate disposable rehearsal

The generic PASS/FAIL acceptance above proves the normal Core transaction path. Before production-target qualification, an **exact private migration candidate** also requires its own full disposable rehearsal through `DriveMigrationDisposableRehearsal`.

Use `tests/live/run_migration_disposable_rehearsal.py` on a controlled operator host that has the private migration pack. Do not upload the private pack to GitHub Actions or place it inside the Git worktree.

The runner requires:

- `KEELARYN_MIGRATION_DISPOSABLE_REHEARSAL_ENABLE=YES`;
- `KEELARYN_MIGRATION_REHEARSAL_RUN_ID=<fresh-safe-run-id>`;
- `KEELARYN_MIGRATION_PACK_DIR=<private-pack-outside-repository>`;
- `KEELARYN_DISPOSABLE_ACCEPTANCE_ROOT_ID=<dedicated-test-root-id>`;
- the normal `KEELARYN_GOOGLE_CLIENT_ID`, `KEELARYN_GOOGLE_CLIENT_SECRET`, and `KEELARYN_GOOGLE_REFRESH_TOKEN` for the dedicated disposable test identity.

Before mutation it verifies the exact private pack, initializes OAuth, reuses the same exact acceptance-root/sentinel guard as the generic live gate, proves that the requested run ID has no existing child, and re-verifies the pack at the mutation boundary. It then creates one **fresh** child named with the normal disposable prefix and runs the complete migration rehearsal against that child only.

PASS evidence requires the exact pack/candidate identity, `canonical_epoch=1`, final `IDLE`, restart discovery `READY_CLEAN`, and the complete migration rehearsal evidence. Raw Drive IDs and private paths are excluded from stdout. The runner never receives or changes the production selector and never reuses an existing Hub as the rehearsal target.

If execution is interrupted after the child may have been created, do not rerun the same run ID. Reconcile that child read-only, preserve the incomplete evidence, then use a fresh run ID for an independent retry. The prior child may remain under the acceptance root because its name uses the accepted disposable prefix.

This rehearsal is still development/candidate evidence only. It does not freeze the candidate, construct the production target, authorize cutover, or mutate the personal/production Hub.
