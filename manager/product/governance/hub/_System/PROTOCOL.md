---
id: system.protocol
type: system
status: active
updated: {{DATE}}
---

# Keelaryn Protocol

## 1. Canonical model

Keelaryn__Hub is an instance-owned canonical knowledge/state tree. Keelaryn__Manager is product/runtime infrastructure. Product source never contains instance-specific state.

Canonical user-owned content lives primarily in:

- `Areas/` — long-lived domains of responsibility/state;
- `Projects/` — finite outcomes or bounded recurring work;
- `Records/` — durable evidence, events, decisions and snapshots;
- `Resources/` — reusable reference material and prompts.

The `_System/` layer defines identity, governance and deterministic metadata.

## 2. Identity and revision

`instance_id` is a stable UUID stored in `_System/INSTANCE.json`. It survives every normal revision, system-version change, path move and Manager upgrade.

`revision_time_utc` is the immutable human-facing revision timestamp assigned when a checkpoint revision is created. It is UTC ISO-8601 and must be preserved when that revision moves through reconciliation.

`data_revision` remains the internal global monotonic compatibility/order sequence for one instance. It starts at 1 at Genesis and does not reset when `system_version` changes. It is not the preferred human-facing revision label.

`artifact_id` identifies one checkpoint only. It is not an instance identifier.

## 3. Artifact flow

- **CANDIDATE** — complete non-canonical proposal, normally produced by a worker.
- **APPROVED** — complete checkpoint accepted by Chat Manager, or by Keelaryn__Manager only for explicitly defined Genesis/transactional migration roles.
- **CURRENT** — Local Manager's installed canonical alias of the accepted APPROVED checkpoint.

Artifact v3 uses payload identity plus bounded ancestry. A newer checkpoint may safely fast-forward over skipped local installations only when its ancestry proves the exact installed revision/version/payload and, when present, artifact identity.

A package from another `instance_id` must never replace the current instance.

## 4. Canonical and derived files

Canonical source state is Markdown plus identity/state files that are not declared derived. The source manifest defines the portable canonical source set.

Derived/rebuildable files are:

- `_System/INDEX.json`;
- `_System/ROUTER.json`;
- `_System/MANIFEST.json`;
- `_System/VALIDATION.json`.

`_System/ARTIFACT.json` is checkpoint transport metadata and is excluded from payload identity.

Local deployment state such as `.obsidian/**`, `.git/**`, `desktop.ini`, `Thumbs.db` and `.DS_Store` is not portable canonical state and is excluded from checkpoint hashes/packages.

## 5. Metadata requirements

Every canonical Markdown entity must have frontmatter fields:

- `id`;
- `type`;
- `status`;
- `updated`.

Entity IDs and canonical paths must be unique case-insensitively. Indexed wikilinks must resolve unambiguously or be represented as an explicit unresolved/conflict state rather than silently broken.

Router v2 contains only active/waiting fast-path entities and must agree exactly with INDEX for included rows.

Manifest v1 is mandatory for Keelaryn system 2.1.0+ and must match the exact portable source file set, sizes and SHA-256 hashes.

Validation v2 must report clean deterministic integrity and the exact manifest summary.

## 6. Authority and deletion

Current user correction outranks stored state. Fresh primary evidence outranks older summaries. Derived metadata never outranks canonical Markdown.

No information is deleted, discarded or irreversibly replaced without explicit user authorization. Cleanup should prefer archival, supersession markers, conflict preservation and provenance over destructive removal.

## 7. Roles

**Worker:** performs scoped work from an approved baseline and may emit CANDIDATEs.

**Chat Manager:** reconciles CANDIDATEs semantically, preserves canonical invariants, resolves conflicts or blocks approval, and emits APPROVED checkpoints.

**Local Keelaryn__Manager:** validates transport/lineage/integrity, installs APPROVED checkpoints transactionally, manages local identity binding/history/migrations, and builds clean product distributions. It does not invent semantic merges between conflicting user states.

## 8. Migration

System migrations are explicit registry entries. `manager_safe` migrations may change only proven platform-owned paths under constrained operations. Any migration that can alter user-owned semantics, customized governance, unresolved provenance or ambiguous state requires Chat Manager reconciliation.

Historical pre-Keelaryn identifiers remain historical facts where provenance requires them; they are not mechanically renamed into fictitious Keelaryn predecessor schemas.

## 9. Detached workbench

`WORKSPACE CHECKOUT` and `RETURN PACKET` are context-transfer objects, not installable artifacts. Their rules are defined by [[_System/WORKSPACE]].
