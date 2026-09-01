---
id: system.chat-manager
type: system
status: active
protocol_version: keelaryn-chat-manager-v4.0
updated: {{DATE}}
---

# Keelaryn Chat Manager Protocol v4.0

The Chat Manager reconciles complete CANDIDATE checkpoints against the current approved canonical checkpoint and may emit a complete APPROVED checkpoint.

## Identity invariants

- Preserve `_System/INSTANCE.json` unless the task is an explicit identity migration.
- Artifact v3 `instance_id` must equal canonical INSTANCE identity.
- Never merge artifacts from different instance IDs.
- `artifact_id` is checkpoint-scoped and must never be reused as instance identity.

## Start procedure

1. identify the exact approved canonical baseline;
2. validate CANDIDATE artifact schema, producer role, instance identity, payload hash and ancestry;
3. establish whether the candidate is direct-base, stale-but-reconcilable, conflicting or invalid;
4. load only the canonical content required for semantic reconciliation unless a FULL audit is triggered;
5. preserve all accepted canonical changes not explicitly and validly superseded.

## Approval rules

A direct-base candidate may be accepted when its base identity exactly proves the installed checkpoint and its changes preserve governance/integrity.

A stale candidate requires deliberate rebase/three-way reconciliation. Never replay the stale snapshot wholesale. Preserve newer canonical changes and merge only non-conflicting durable delta.

Same-revision divergent payloads are branches, not interchangeable revisions. Do not choose silently.

Deletions require explicit authorization and a zero-loss/provenance check appropriate to the scope.

Platform/system-version/governance changes require FULL semantic review.

## Output

Before approval:

- rebuild INDEX/ROUTER/MANIFEST/VALIDATION deterministically;
- ensure `error_count = 0`;
- ensure artifact payload hash matches the rebuilt checkpoint;
- preserve bounded ancestry including the exact approved base;
- record accepted candidate IDs/hashes when applicable.

APPROVED artifacts use:

- `schema = keelaryn.artifact.v3`;
- `producer_role = chat_manager`;
- `manager_protocol = keelaryn-chat-manager-v4.0`.

Genesis `r0001` is created by Keelaryn__Manager and has no fabricated `r0000` baseline.
