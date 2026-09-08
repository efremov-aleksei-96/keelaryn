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
- `revision_time_utc` is the immutable human-facing revision timestamp; preserve it across reconciliation of the same proposed revision.
- `data_revision` remains an internal monotonic compatibility/order sequence.
- `system_version` and generic `governance_revision` are independent compatibility axes.

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

## Generic governance convergence

When Local Manager reports missing or stale generic governance, treat the Manager-provided `product/governance/hub` set as the target generic contract, not as permission to replace the whole Hub.

- Preserve all unrelated user-owned Areas/Projects/Records/Resources and local governance customization that is still semantically compatible.
- Reconcile only the paths declared by the target `_System/GOVERNANCE.json` `managed_paths` set.
- Do not copy `product/starter/hub` over an existing Hub.
- Do not advance `system_version` merely to adopt a newer `governance_revision`.
- Write the target `_System/GOVERNANCE.json` receipt only after the corresponding governance semantics have actually been incorporated.
- Advance the normal Hub `data_revision`, preserve instance identity/lineage, and rebuild deterministic metadata before approval.
- If local customization conflicts with the target governance contract, surface the conflict instead of silently overwriting it.

A Hub whose governance revision is newer than the local Manager must not be downgraded. Update/review the Manager compatibility first.

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

Genesis creates internal `data_revision: 1` (legacy sequence `r0001`) and an immutable `revision_time_utc`; it has no fabricated revision-zero baseline. Genesis also receives the current generic governance receipt directly from the canonical Manager governance overlay.
