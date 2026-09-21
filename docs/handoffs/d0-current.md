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

## D0-02A — read-only production snapshot protocol

Pre-write authority: `93f9851d283e181f788b509bc0e19eabad012e05`; D0-01B Core run `35631451089` PASS (681 tests) and Windows run `35631451344` PASS (131 tests).

The successor development commit containing this section adds the first strict remote observation protocol:

- `PRODUCTION_SNAPSHOT` is a read-only allowlisted operation with `approval=NOT_REQUIRED` and no command/path parameters;
- a static template worker `keelaryn-production-snapshot@.service` runs without network access or Linux capabilities;
- the worker hides known Drive/GitHub credential paths and writes only one create-once mode-0600 result beneath the exact operation directory;
- observation is two-pass and fails if release selectors, service state, legacy Hub transaction, selector classification or mutation inhibit drift between passes;
- raw old/new Hub IDs are used only for local classification and are never returned;
- relay v2 adds one strict `result` field; historical relay v1 remains accepted;
- structured relay output is accepted only for a terminal successful `PRODUCTION_SNAPSHOT` and must match `keelaryn.production-snapshot.v1`;
- replay of a completed request republishes the immutable snapshot without rerunning the worker.

The snapshot reports only sanitized source commit identities, normalized service state/PID, legacy Hub state, transaction identity/hash, selector role and mutation-inhibit hash/match flags. It explicitly states that no production or Drive mutation was performed.

No production/VPS/Drive mutation is performed by D0-02A development.

## Next permitted engineering objective

**D0-02B — installable read-only Operation Control successor.**

First require exact-HEAD Core/Windows development CI PASS for D0-02A. Then adapt the existing transaction-safe control-plane update/materialization path so the snapshot worker unit is installed as a static, non-enabled unit and prove the successor's effective remote allowlist/worker boundary in disposable qualification. Do not resume `HUB_PRE_APPLY` or any old Hub content mutation.

### D0-02A CI correction

Initial D0-02A development HEAD `7aae6557d4956a92c883e449133dc672146578a2` reached the deterministic Core suite but failed 5 new snapshot tests. All failures had one root cause: the ISO-8601 UTC timestamp validator contained a double-escaped raw-regex digit token and rejected valid timestamps such as `2026-09-21T17:30:00Z`.

This successor changes only that validator plus the required durable D0 checkpoint. No protocol shape, security boundary, VPS state, Hub state or Drive state is changed. The initial failed run is retained as development evidence; do not rerun or rewrite that commit.

## D0-02B — installable read-only control successor

Pre-write authority: `1950a72c777d3da1a7cf808593ca1e2535b3a6e2`; D0-02A Core run `35635338340` PASS with 690/690 deterministic tests.

This development successor keeps old Hub-first update machinery as provenance and creates a separate active D0 path:

- effective `operation_agent.py` exposes exactly `RUNTIME_SELFTEST` and `PRODUCTION_SNAPSHOT`; both are non-mutating and non-approval-gated;
- `HUB_PRE_APPLY` is removed from the effective remote allowlist and request validator;
- `operation_control_d0_update.py` reuses only low-level transaction/filesystem/systemd primitives from the old updater, while its own durable authority schemas and update root are D0-specific;
- before creating PREPARED authority it statically proves the successor HANDLERS AST is exactly the two read-only operations and validates the snapshot worker's network/capability/secret-isolation policy;
- the transaction preserves production current and GitHub credential identity, quiesces transport/agent, revalidates the exact predecessor boundary, publishes only control-current + persistent control units + the static snapshot worker, verifies service stability, and writes COMPLETED;
- failures before COMPLETED restore exact predecessor control-current/unit bytes and remove the snapshot worker if the predecessor did not have it;
- `operation_control_d0_validate.py` independently qualifies exact payload identity, read-only allowlist, static worker policy and installed unit bytes;
- deterministic VPS-payload CI executes this D0 validator on the materialized exact HEAD.

The production snapshot legacy-Hub observation is strengthened so mutation inhibit must bind the active transaction, production/tool source, tool hash and canonical OLD/NEW selector hashes. Authority disagreement is surfaced only as sanitized `BLOCKED / MUTATION_INHIBIT_AUTHORITY_MISMATCH`.

No VPS, production Hub, writer, credential or Drive mutation is performed by this development commit.

## Next permitted engineering objective

**D0-02C — freeze and qualify the read-only successor candidate.**

First require exact current-HEAD Core CI PASS. Then create one immutable D0 Operation Control candidate bound to the current source/payload, prove r0005 → candidate update and rollback/recovery in disposable qualification, and prepare one production bootstrap transaction. The old Hub cutover remains paused and cannot be authorized by the D0 candidate.

### D0-02B CI correction

Initial D0-02B HEAD `9df0de0c99db854b82aa1d7592036a1d8a7ef8a8` preserved the intended product/control bytes but Core run `35637755891` failed after 693 tests with exactly two fixture defects in `test_production_snapshot.py`:

1. selector hashes were calculated from a literal backslash+n instead of the canonical selector newline;
2. the deliberate inhibit-tamper fixture rewrote bytes with the test-local compact serializer rather than the authoritative `mutation_inhibit_bytes()` contract.

The same HEAD's Windows run `35637755870` completed SUCCESS.

This corrective successor changes only those two test fixtures plus this durable checkpoint. Production/control implementation bytes are intentionally unchanged. The failed Core evidence remains preserved and must not be rerun/reinterpreted as PASS.

## D0-02C1 — frozen read-only Operation Control r0007

Pre-freeze authoritative source: `833123b6a7ad2c61087ee8a86700bb9ad8a46298`, tree `bbca9e3a17162e12a7a0f649138e8c469518ad2a`.

Frozen candidate:
- `operation-control-r0007-20260921-01`
- payload SHA-256 `c833a385e03d313497f865a669dbce8050fa4b296dc587836dad2fa5d3f560e9`
- payload size `414534`
- payload file count `208`

The freeze is bound to exact-head Core run `35638117240` (SUCCESS, 693/693 tests), exact deterministic payload artifact `10656858049`, and D0 materialized-release validation. Windows run `35637755870` is retained only as evidence for the unchanged relevant Windows surface; the corrective source delta to the frozen candidate contains only DEVELOPMENT_STATE, handoff and the Linux snapshot fixture.

Dedicated candidate gate `operation-control-d0-gate-r0001` independently:
- checks the immutable candidate receipt;
- checks out the exact frozen source/tree;
- reruns the full frozen Core suite;
- proves cross-user relay DAC;
- rebuilds the payload twice and requires byte identity to the frozen SHA/size/count;
- materializes the exact frozen release;
- runs target-host validation;
- installs exact persistent control units plus the static snapshot worker into a disposable unit directory;
- runs the D0 control validator and requires the exact two-operation read-only allowlist with zero mutation handlers;
- emits compact evidence with `production_qualified=false` and zero production/Drive mutations.

No VPS, production, Hub selector, writer, credential or Google Drive mutation occurs in D0-02C1.

## Next permitted engineering objective

**D0-02C2 — resolve r0007 gate r0001 and, only after PASS, prove disposable r0005 → r0007 update/rollback/interruption recovery.**

Production bootstrap remains forbidden until that disposable transition qualification passes and a fresh read-only VPS reconciliation confirms the real predecessor boundary.

