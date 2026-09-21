# Keelaryn Development Level 0 — current handoff

**Status:** active durable coordination checkpoint for `dev/zero-based-keelaryn`.

This file supersedes older "next step" instructions in `docs/handoffs/zero-based-current.md` where they conflict. Historical candidate, gate, migration and production evidence remains valid provenance unless separately superseded by newer authoritative evidence.

## Architecture disposition

Keelaryn development is now **Corpus-first**.

The old Hub-first Zero-Based r2 content architecture and the prepared production Hub cutover are **PAUSED_PENDING_ARCHITECTURE_DISPOSITION**.

Do not continue Hub selector apply, Hub content migration, writer start, staged credential activation, old pre-apply execution or any other old content-cutover mutation merely to complete the previous plan.

Old Manager 4.x, Zero-Based r2, migration candidates and Operation Control candidates remain provenance/research material and reusable infrastructure where applicable.

## Development priority

Current capability level: **D0 — Autonomous Engineering**.

Goal:

> A fresh ChatGPT conversation can reconstruct exact development state from GitHub/VPS/Google Drive and continue development with minimal or zero maintainer participation.

Chat history is never authoritative state.

Authority order:

- GitHub: source, branch/HEAD, specifications, CI, development history and sanitized checkpoints.
- VPS: controlled runtime/integration and production-specific state.
- Google Drive: real corpus and corpus-specific durable evidence/state where appropriate.
- ChatGPT: engineer/orchestrator, not durable storage.

## Pre-write repository boundary

Read-only reconciliation immediately before creating this checkpoint established:

- repository: `efremov-aleksei-96/keelaryn`
- branch: `dev/zero-based-keelaryn`
- branch exists and is explicitly unqualified development
- compared with `b8a346c6a075f726800e1baeec095f914adba7f6`, the branch was exactly **1 commit ahead / 0 behind**
- that single successor commit contains only the r0017 gate/driver/handoff changes:
  - `.github/workflows/operation-control-r0006-gate-r0017.yml`
  - `docs/candidates/operation-control-r0006-20260921-01.gate-r0017.json`
  - `docs/handoffs/zero-based-current.md`
  - `tools/operation_control_r0006_vps.py`
- frozen r0006 product bytes remain source `b371a9b9f28fe668cc8073019a3d5f352f9d9bf3`; r0017 is gate/qualification-driver-only
- this checkpoint itself is a metadata/documentation-only successor commit; a fresh session MUST read the current branch HEAD rather than infer it from the pre-write anchor above

## Last durable production evidence carried forward

These are **recorded durable facts, not a fresh D0 VPS observation**:

- production source: `e63f371d14eb9b6069cb2f1b5fad5f4b68a49d4f`
- Hub transaction: `PREPARED`
- transaction ID: `61a2bfb65c9a47d088a76eee0df89d14`
- selector: OLD
- writer: inactive / MainPID 0
- installed accepted Operation Control predecessor: r0005 source `08f2e211f53764590f6ff0f05f86b2de62c14418`
- r0006 product source is frozen and historical qualification/gate evidence remains preserved
- old Hub mutation MUST NOT be resumed without a new Corpus-first disposition decision

Before any production mutation, perform fresh read-only VPS reconciliation through the safest available remote path. Never infer current VPS state from this checkpoint alone.

## Google Drive boundary

Read-only Drive search during D0 bootstrap confirmed substantial Keelaryn historical evidence exists, including Engine documentation, gate logs and qualification artifacts.

No Drive mutation was performed.

Drive historical evidence is not a substitute for GitHub source authority. Real corpus files remain the future Corpus-first content authority.

## D0 transaction rule

For every durable development change:

1. read authoritative remote prestate;
2. classify the intended change;
3. perform at most one coherent durable mutation;
4. immediately read back and verify the durable result;
5. update a compact checkpoint when state materially changes.

After interruption or timeout: never blindly retry; reconcile remote authority first.

## D0 implementation sequence

Do **not** expand product recovery/ontology architecture yet.

Build only the minimum autonomous engineering control plane:

1. exact GitHub branch/HEAD and CI discovery;
2. machine-readable development-state/checkpoint contract;
3. reliable read-only VPS state acquisition through remote control infrastructure;
4. Google Drive corpus/evidence discovery contract;
5. deterministic "resume from first uncompleted step" procedure;
6. regression/self-test proving a fresh session can reconstruct the same state;
7. only then begin Corpus-first Product Level 0.

## Product Level 0 after D0

Minimum P0 target:

```text
Physical Corpus
→ read-only discovery
→ inventory
→ artifact identity
→ current locator
→ basic observation/revision
→ minimal extraction
→ task-specific AI context
```

No physical normalization, deduplication, destructive mutation, maximal ontology or disaster reconstruction is required for P0.

## D0-01 — autonomous development state

### D0-01A — COMPLETE

Commit `a457d90277375b90b5f1767205c123bec7c5d710` created the first machine-readable `DEVELOPMENT_STATE.json`.

### D0-01B — implemented in the successor commit to the pre-write HEAD above

This coherent change adds:

- strict fail-closed `tools/development_state.py`;
- duplicate-key and exact-shape validation for the D0 state contract;
- live local Git resolution of HEAD, branch, checkpoint age and basis relation;
- explicit detection of a stale state file;
- `repository_basis_commit`, which avoids impossible self-reference by binding each checkpoint to its pre-write parent;
- nine targeted deterministic regressions;
- zero-based CI path triggers for the state and reader;
- CI enforcement that the state changed in the same HEAD and its basis is that HEAD's first parent.

The exact containing commit SHA and its CI are deliberately resolved live rather than written into the state file itself.

No VPS, Hub selector, writer, credential or Drive content mutation is part of D0-01.

## Next permitted engineering objective

**D0-02 — reliable read-only VPS state acquisition.**

Before D0-02 work, resolve the authoritative branch HEAD and require the D0-01B zero-based Core validation for that exact HEAD to PASS.

D0-02 must reuse the existing remote Operation Control/runtime where safe, but it is read-only: obtain a compact sanitized production snapshot without resuming the paused Hub cutover. The snapshot must distinguish live observations from recorded historical state and be usable by a fresh chat without SSH/PowerShell supplied by the maintainer.

Old Hub mutations remain forbidden.
