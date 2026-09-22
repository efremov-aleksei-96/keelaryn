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

### r0007 dedicated gate PASS / development-state schema correction

Dedicated frozen candidate gate:
- run `35643121287`
- conclusion `SUCCESS`
- frozen Core `693/693 PASS`
- artifact `10658574549`
- artifact ZIP SHA-256 `bf31f59afc002206075f40701884af16edacd9bfb52bf17ac87f92d417f3251a`

The ordinary Core workflow on freeze commit `b37e123988e66abb29a7476892af36415e184e8d` stopped at the D0 checkpoint parser before product tests because the r0007 constrained-candidate entry included an unsupported `payload_sha256` key. The candidate receipt itself remains the authority for frozen payload identity.

This corrective checkpoint removes only that schema-incompatible field from `DEVELOPMENT_STATE.json`, records r0007 as `FROZEN_DEDICATED_GATE_PASS`, and leaves frozen source, candidate receipt, gate workflow, payload bytes and production state unchanged.

### D0 checkpoint objective-ID grammar correction

Ordinary Core run `35644041061` stopped before product tests because durable-state schema v1 accepts objective IDs matching `^D[0-9]+-[0-9]+[A-Z]?(?:_[A-Z0-9_-]+)?$`; `D0-02C2` was therefore invalid.

This checkpoint changes only the objective identifier to `D0-02C_TRANSITION`, increments the durable state revision, and preserves the same transition-qualification meaning. Frozen r0007 candidate bytes, receipt, dedicated gate, payload identity and production state are unchanged.

## D0-02C transition gate r0001

Pre-write development authority: `e0697a1119326358e7b09b0c4957615a1c51c395`; ordinary Core run `35644590430` SUCCESS with 693/693 deterministic tests.

Qualification-only files added:
- `tests/ci/operation_control_r0007_transition.py`
- `.github/workflows/operation-control-r0007-transition-gate-r0001.yml`

The harness is deliberately excluded from the frozen VPS payload. It operates only on a disposable GitHub-hosted Linux filesystem and loads the updater from the exact materialized r0007 release.

The gate independently rebuilds twice and byte-verifies both frozen payload authorities:
- r0005 source `08f2e211f53764590f6ff0f05f86b2de62c14418`, payload `6272afbe918d33c29a3f72354baca9e781b3960b3f0f465e1598b5bbc794a7e7`;
- r0007 source `833123b6a7ad2c61087ee8a86700bb9ad8a46298`, payload `c833a385e03d313497f865a669dbce8050fa4b296dc587836dad2fa5d3f560e9`.

It then materializes both releases into one disposable release root and proves six transition states against the exact frozen r0007 updater:
1. exact r0005 → r0007 success / COMPLETED;
2. injected successor service failure → exact r0005 rollback / ROLLED_BACK;
3. PREPARED + OLD_EXACT process interruption → resume to COMPLETED;
4. PREPARED + NEW_EXACT process interruption → terminalize without unit/control-current republication;
5. PREPARED + foreign PARTIAL boundary → fail closed without overwriting foreign bytes or writing terminal authority;
6. already-COMPLETED successor with stopped services → service recovery without republishing control bytes or terminal authority.

Every scenario pins a canonical production-current symlink, credential bytes, Hub selector sentinel and Drive-authority sentinel and requires all four to remain unchanged.

This gate does not access the real VPS, real Hub selector, real credential or Google Drive and cannot claim production qualification.

## D0-02C transition qualification PASS

Development HEAD `eb001fe5b02a71cd14b3958bd3b2058a06dd0074` passed ordinary Zero-based Core validation run `35645443161` with 693/693 deterministic tests.

Dedicated exact frozen transition qualification:
- workflow: `Operation control r0007 transition gate r0001`
- run: `35645443118`
- conclusion: `SUCCESS`
- evidence artifact: `10660201981`
- artifact ZIP SHA-256: `9726a3a2c538f2e7a934b9e2a32e06afc2b5c9562c5529863604a23b4bff4618`

The disposable gate rebuilt and materialized exact frozen r0005 and r0007 payloads and passed all six scenarios:
1. exact success → COMPLETED;
2. injected successor failure → exact predecessor rollback / ROLLED_BACK;
3. PREPARED + OLD_EXACT interruption → recovered to COMPLETED;
4. PREPARED + NEW_EXACT interruption → terminalized without republishing control bytes;
5. foreign PARTIAL boundary → fail closed, preserve foreign bytes, require reconcile;
6. already-COMPLETED successor with stopped services → idempotent service recovery without republishing bytes or terminal authority.

All scenarios preserved production-current, credential bytes, Hub selector sentinel and Drive sentinel. The gate performed no real VPS, production or Drive mutation and explicitly did not claim production qualification.

## D0-02D — fresh VPS reconcile

Before any production r0007 bootstrap, evidence must be refreshed against real external authority.

Sequence:
1. send a new read-only `RUNTIME_SELFTEST` request for exact installed r0005 source through GitHub Issue #65 and require an exact terminal PASS;
2. separately obtain fresh read-only VPS evidence for production current, control-current, installed r0005 control-unit bytes/state, writer state, Hub PREPARED transaction, OLD selector, mutation inhibit and credential identity;
3. compare those facts to the recorded production anchor;
4. only if the complete boundary is exact may a later transaction prepare r0007 production bootstrap.

The existing Issue #65 selftest PASS at 2026-09-21T05:58:16Z is historical only and is not fresh enough for a production mutation boundary.

## Canonical architecture boundary — Corpus-first layered authority

The active canonical architecture is now explicitly Corpus-first. The previous Hub-first r2 model is superseded product architecture and remains only in Git/legacy provenance.

Layered authority is normative:
- physical corpus objects are authoritative for object existence, stored bytes/content, the physical identity referent and physical location;
- explicit project/workspace STATE is authoritative for operational/current state owned by that project/workspace;
- LifeOS is a separate permanent master/life-orchestration workspace and is authoritative only for cross-life orchestration semantics that it owns; it references project truth rather than copying it;
- Keelaryn `0__Core/__Keelaryn` is a compact control/semantic plane for indexes, fingerprints, identity/revision observations, relations, classifications, accepted/derived state, transactions and recovery metadata; it is not a second content corpus;
- semantic classification never overrides the underlying physical object, while physical location alone never defines the object's complete semantic meaning.

Legacy production Hub authority is permanently constrained to provenance plus the temporary pre-cutover runtime boundary. Its selector/current/PREPARED transaction may be read for r0005 → r0007 safety reconciliation, but old Hub Areas/Projects/Records/Resources are not imported as the new canonical organization, Google Drive corpus is not reconciled against old Hub semantics, and no corpus mutation may be derived from old Hub state.

The old Hub cutover state is therefore `PAUSED_LEGACY_RUNTIME_ONLY`, not pending architectural disposition. Frozen r0006 remains a forbidden legacy Hub line.

D0-02D may resume only after the canonical architecture commit itself passes CI, and then only as strictly read-only legacy-runtime safety observation.

## D0-02D — fresh legacy-runtime safety reconcile PASS

Fresh read-only control-channel selftest:
- Issue #65 request comment `5766792375`
- status comment `5766795620`
- operation id `50000000000000000000000000000002`
- exact r0005 source `08f2e211f53764590f6ff0f05f86b2de62c14418`
- terminal `SUCCEEDED / READ_ONLY / PASS`
- timestamp `2026-09-21T20:08:20Z`

Fresh two-pass stdin-only VPS observation completed at `2026-09-21T20:16:10Z` and returned PASS. Sanitized evidence is stored at `docs/evidence/D0_02D_LEGACY_RUNTIME_RECONCILE_2026-09-21T201610Z.json`.

Observed safety boundary:
- production current exact `e63f371d14eb9b6069cb2f1b5fad5f4b68a49d4f`;
- control-current exact r0005; payload `6272afbe918d33c29a3f72354baca9e781b3960b3f0f465e1598b5bbc794a7e7`, 365052 bytes, 190 files;
- operation agent + transport ACTIVE/enabled and byte-exact to r0005;
- writer INACTIVE / MainPID 0;
- legacy Hub PREPARED, transaction `61a2bfb65c9a47d088a76eee0df89d14`, selector role OLD;
- active transaction SHA and tool/finalizer identities exact;
- mutation inhibit PRESENT and bound to the same transaction/source/tool/OLD+NEW selector hashes;
- GitHub operations credential canonical; bootstrap receipt and bootstrap transaction identity exact;
- r0007 snapshot unit ABSENT, proving no partial successor publication.

This evidence is strictly `RUNTIME_SAFETY_ONLY`: it is not legacy-Hub semantic/content authority, performs no Google Drive/content reconciliation, contains no raw Hub IDs, and authorizes no production mutation.

## D0-02E — bootstrap preparation

Next work is production-specific preparation only. It must determine and qualify the exact frozen-r0007 materialization/update mechanism, prove rollback/interruption behavior remains applicable to the freshly observed r0005 predecessor, and define a mutation-boundary revalidation. Production mutation remains forbidden in D0-02E.

## D0-02E — r0007 bootstrap-prep gate r0001

Pre-write authority: `34bca27e7b4150b870977d001d7fe7dd37f45c8d`; Core run `35650589808` SUCCESS with 697/697 tests.

Qualification-only tooling introduced:
- `tools/operation_control_r0007_vps.py`;
- `tests/core/test_operation_control_r0007_vps.py`;
- `.github/workflows/operation-control-r0007-bootstrap-prep-r0001.yml`.

The tool deliberately exposes exactly two commands:
- `reconcile`: two-pass, root-only, strictly read-only observation of the legacy runtime safety boundary;
- `qualify`: current-repository authority validation plus exact frozen r0007 checkout, double deterministic payload rebuild, disposable materialization, target-host validation and D0 control validation.

There is intentionally no `stage`, `upgrade`, `repair`, Hub-preapply or Drive mutation command in this D0-02E surface.

The qualification command binds:
- frozen r0007 source/tree/payload;
- durable r0007 transition-gate PASS state;
- fresh D0-02D live-r0005 evidence;
- layered Corpus-first authority;
- legacy Hub scope `RUNTIME_SAFETY_ONLY`;
- exact predecessor source/payload and recorded credential identity.

All candidate materialization in this gate is disposable/temp-only. The evidence must state:
- `stage_implemented=false`;
- `upgrade_implemented=false`;
- `production_mutation_allowed=false`;
- `drive_content_mutation_allowed=false`;
- `production_qualified=false`;
- `requires_fresh_mutation_boundary_revalidation=true`.

Only after this gate passes may the next development step design a separate durable stage transaction. That later stage transaction is not authorized by D0-02E.

### D0-02E bootstrap-prep gate r0001 failure / r0002 correction

Development HEAD `01defeb0a5e586fdf2309af5553f79ce4c62f80a` passed ordinary Core validation run `35651750917` with 703/703 tests.

Bootstrap-prep gate r0001 run `35651750931` failed after:
- compile step PASS;
- all 6 bootstrap-prep regression tests PASS;
- qualification command completed without semantic/identity/validation error.

The failure was gate hygiene only: `python3 -B -m py_compile` created `__pycache__/*.pyc`, after which the gate's own `git status --porcelain` clean-worktree assertion correctly failed.

Frozen r0007 bytes, bootstrap-prep framework code, D0-02D evidence, production and VPS state were not changed.

Gate r0002 is therefore a workflow/evidence revision only:
- bootstrap-prep framework revision remains `operation-control-r0007-bootstrap-prep-r0001`;
- gate workflow revision becomes `operation-control-r0007-bootstrap-prep-r0002`;
- syntax validation uses in-memory Python `compile(...)` and immediately proves the worktree remains clean;
- r0001 remains preserved as failed evidence and is never rewritten.

## D0-02E bootstrap preparation PASS

Corrective bootstrap-prep gate r0002:
- run `35653073762`
- conclusion `SUCCESS`
- evidence artifact `10662513908`
- artifact ZIP SHA-256 `a40172fe907593867a4b331046edb76fa250efe97e44c117c22dbddf9695d48e`

Current development HEAD `3fc6274b3796f2378672a631353dc4dadad61794` also passed Zero-based Core run `35653073690` with 703/703 tests.

The r0007 bootstrap-prep framework remains revision `operation-control-r0007-bootstrap-prep-r0001`; gate r0002 is only the hygiene/evidence correction over failed r0001.

Qualified invariants:
- frozen r0007 source/tree/payload exact;
- materialization occurred only in disposable temp storage;
- target-host and D0 control validation PASS;
- remote allowlist is exactly `RUNTIME_SELFTEST` + `PRODUCTION_SNAPSHOT`;
- remote mutation handlers = 0;
- `stage_implemented=false`;
- `upgrade_implemented=false`;
- `production_mutation_allowed=false`;
- `drive_content_mutation_allowed=false`;
- `production_qualified=false`;
- a fresh read-only mutation-boundary revalidation remains mandatory before any later production write.

## D0-02F — stage transaction qualification

The next engineering level separates inert release publication from control activation.

A future stage transaction may only publish exact frozen r0007 as an immutable release directory. It must not change `production current`, `control-current`, systemd unit bytes/state, writer, GitHub operation credential, legacy Hub selector/transaction or Google Drive corpus.

Required qualification states:
1. destination ABSENT → atomic materialization → STAGED_EXACT;
2. destination already STAGED_EXACT → idempotent success without rewrite;
3. destination exists but is foreign/partial → fail closed without overwrite/delete;
4. interruption before publication → no successor release;
5. interruption/post-publication uncertainty → reconcile exact release identity and never blindly retry/delete;
6. before any real stage write, fresh read-only live boundary revalidation is mandatory.

The installed r0005 and frozen r0007 share the exact same `materialize_payload.py` Git blob `ece36ad98d4a15442f5f081db76345525fe1b8c1`; this reusable mechanism is therefore a strong candidate for stage publication, but D0-02F must qualify the transaction wrapper separately before any real VPS stage.

### r0007 candidate lifecycle-state correction

Closeout HEAD `5c4c06025c61f96b1533c81eb17a25a56759590a` incorrectly changed the r0007 constrained-candidate lifecycle state from `FROZEN_TRANSITION_GATE_PASS` to `FROZEN_BOOTSTRAP_PREP_GATE_PASS`.

That was a durable-state modeling error. `constrained_candidates[].state` describes the frozen candidate lifecycle, not the progress of later release-engineering qualification gates. Bootstrap-prep PASS is preserved by CI/gate evidence and handoff/checkpoint provenance; it must not rewrite the frozen candidate lifecycle token.

Observed failures caused only by this state mismatch:
- Zero-based Core run `35653966321` — FAIL, one error in `test_recorded_boundary_accepts_current_layered_authority`;
- bootstrap-prep gate r0002 run `35653966511` — FAIL at the same recorded-boundary check before qualification.

This correction restores r0007 to `FROZEN_TRANSITION_GATE_PASS`. Frozen source/tree/payload, bootstrap-prep framework, r0002 PASS evidence, D0-02D live VPS evidence, production state and next objective `D0-02F_STAGE_QUALIFICATION` are unchanged.

## D0-02F — stage transaction qualification r0001

Pre-write authority: `139addd9d1f48794f3a74823709322c250c084a2`; Core run `35654752516` SUCCESS with 703/703 tests; bootstrap-prep gate r0002 rerun `35654752660` SUCCESS.

Qualification-only stage framework:
- `tools/operation_control_r0007_stage.py`;
- `tests/core/test_operation_control_r0007_stage.py`;
- `.github/workflows/operation-control-r0007-stage-gate-r0001.yml`.

The CLI exposes only `qualify`. It has no production `stage`, activation, upgrade, delete or rollback command.

The transaction model is monotonic inert immutable release publication. The durable commit authority is the exact immutable release directory itself, not a second PREPARED metadata record.

Frozen publication mechanism identity:
- r0007 source `833123b6a7ad2c61087ee8a86700bb9ad8a46298`;
- payload `c833a385e03d313497f865a669dbce8050fa4b296dc587836dad2fa5d3f560e9`, 414534 bytes, 208 files;
- `materialize_payload.py` Git blob `ece36ad98d4a15442f5f081db76345525fe1b8c1`, identical between installed r0005 and frozen r0007.

Stage qualification r0001 proves eight disposable scenarios:
1. ABSENT → STAGED_EXACT;
2. exact replay → ALREADY_STAGED_EXACT with no publication;
3. foreign/partial destination → fail closed and untouched;
4. prepublication stage residue → RECOVERY_REQUIRED and untouched;
5. materializer publishes durably but caller sees an error → exact release recognized, retained, reconcile required;
6. live boundary drift before mutation → abort before publication;
7. boundary drift after durable publication → exact release retained, activation blocked, reconcile required;
8. exact destination plus orphan stage residue → fail closed/recovery required without deleting either state.

Non-release sentinels for production current, control-current, systemd control units, writer, credential, legacy Hub runtime boundary and Drive state must remain byte-unchanged in every scenario.

D0-02F remains qualification-only:
- `production_stage_cli_exposed=false`;
- `activation_implemented=false`;
- `production_mutation_allowed=false`;
- `drive_content_mutation_allowed=false`;
- `release_deletion_on_uncertainty_allowed=false`;
- `blind_retry_allowed=false`;
- fresh live mutation-boundary revalidation remains mandatory before any future real stage.

## D0-02F stage qualification PASS

Authoritative qualification HEAD `cea4591ed667a0968528758d8509a6cab7f1e6a8`.

Validation:
- Zero-based Core run `35692765529` — SUCCESS, 710/710 tests;
- Operation control r0007 stage gate r0001 run `35692765474` — SUCCESS;
- evidence artifact `10679088044`;
- artifact ZIP SHA-256 `2fa4e7be4640bbb7c5a842cd740381bb975df8e97801513b9474f171c1b639b0`.

Qualified transaction model:
- `MONOTONIC_INERT_IMMUTABLE_RELEASE_PUBLICATION`;
- commit authority = exact immutable r0007 release directory;
- no separate PREPARED metadata record is required for the inert stage itself;
- release deletion after uncertainty is forbidden;
- blind retry is forbidden;
- activation is not implemented by the stage framework;
- production stage CLI is not exposed by the D0-02F qualification tool.

Eight disposable scenarios passed:
1. ABSENT → STAGED_EXACT;
2. exact replay → ALREADY_STAGED_EXACT with no second publication;
3. foreign/partial destination → fail closed untouched;
4. prepublication stage residue → RECOVERY_REQUIRED untouched;
5. durable publication followed by response loss → exact release recognized and retained;
6. runtime boundary drift before mutation → abort before publication;
7. runtime boundary drift after publication → exact release retained, activation blocked, reconcile required;
8. exact destination plus orphan stage residue → fail closed/recovery required without deletion.

The r0007 constrained-candidate lifecycle remains `FROZEN_TRANSITION_GATE_PASS`; D0-02F PASS is release-engineering evidence, not a new frozen-candidate lifecycle state.

## D0-02G production stage preparation

Next work is still qualification-only. It must design the actual authorized production-stage surface around the already-qualified monotonic stage primitive.

Required contract:
- exact r0007 payload/source identity bound before any write;
- fresh live two-pass r0005/legacy-runtime safety observation at the mutation boundary;
- current successor release state classified before any publication;
- only `NOT_STAGED` may call the materializer;
- `STAGED_EXACT` is idempotent no-op;
- residue/foreign/partial states fail closed;
- after materializer uncertainty, exact destination is recognized as durable commit and never deleted/retried blindly;
- post-publication runtime anchors must be re-read and remain unchanged;
- resulting evidence is sanitized and must not expose raw Hub IDs or secrets.

D0-02G does not authorize the real VPS stage. It must not mutate `control-current`, systemd units, writer, credential, legacy Hub state or Google Drive corpus.

## D0-02G — production stage preparation gate r0001

Pre-write authority: `7158004b93e1a2ed79c0ba8232febe2ccd0315fb`; current Core validation and D0-02F stage gate are PASS. Real VPS stage remains forbidden.

New qualification-only production-stage surface:
- `tools/operation_control_r0007_production_stage.py`;
- `tests/core/test_operation_control_r0007_production_stage.py`;
- `.github/workflows/operation-control-r0007-production-stage-prep-r0001.yml`.

The internal future production function is `execute_authorized_stage(...)`; the CLI still exposes only `qualify`. Therefore D0-02G can qualify the real-stage contract without making the real production mutation executable from this development checkpoint.

Authorization is exact and narrow:
- schema `keelaryn.operation-control-r0007-production-stage-authorization.v1`;
- scope `R0007_RELEASE_STAGE_ONLY`;
- exact r0007 candidate/source/tree/payload;
- `production_stage_authorized=true`;
- `activation_authorized=false`;
- Drive, legacy-Hub, writer and credential mutation authorization all false.

Future production execution contract:
1. validate exact authorization before any observation/write;
2. perform fresh two-pass read-only live r0005/legacy-runtime precheck;
3. classify current successor release state before write;
4. reject foreign/partial/residue states without overwrite/delete;
5. delegate exact publication only to the already-qualified monotonic stage primitive;
6. that primitive revalidates payload/filesystem/runtime again at its mutation boundary;
7. after publication or uncertainty, perform a stable two-pass read-only postcheck of all non-release runtime anchors;
8. recognize exact durable release publication instead of blind retry/delete;
9. never authorize activation as part of stage.

Qualification scenarios cover exact authorization, widened-authorization rejection, exact stage, idempotent replay, foreign/partial fail-closed, interrupted residue fail-closed, response loss after durable publication, mutation-boundary drift before publication and runtime drift after publication.

Evidence must be sanitized: raw Hub IDs and credential token material are forbidden. D0-02G itself has `real_vps_stage_performed=false`, `production_stage_cli_exposed=false`, `production_mutation_allowed=false` and `drive_content_mutation_allowed=false`.

## D0-02G production-stage preparation PASS

Authoritative qualification HEAD `d458c351c2e9a8fb0b4efe8f0b6c25aca2689be1`.

Validation:
- Zero-based Core run `35702516892` — SUCCESS, 718/718 tests;
- production-stage-prep gate r0001 run `35702517117` — SUCCESS;
- evidence artifact `10683120485`;
- artifact ZIP SHA-256 `9ddfe98ff081dff4357db45871b4616e61351638c7322f1894aa10039a9ba7bc`.

Qualified production-stage surface:
- internal function `execute_authorized_stage(...)`;
- CLI remains qualification-only and exposes no real production stage command;
- exact authorization scope `R0007_RELEASE_STAGE_ONLY`;
- exact candidate/source/tree/payload bound;
- activation, Drive, legacy-Hub, writer and credential mutation permissions are all false;
- fresh two-pass live r0005/legacy-runtime precheck is mandatory;
- successor release state is classified before any write;
- publication delegates only to the qualified monotonic stage primitive;
- postpublication runtime anchors are read-only reconciled twice;
- exact publication survives response uncertainty without deletion/blind retry;
- evidence is sanitized and rejects raw Hub IDs/token material.

D0-02G performed no real VPS stage and did not authorize production mutation. The r0007 constrained-candidate lifecycle remains `FROZEN_TRANSITION_GATE_PASS`.

## D0-02H — durable authorization provenance

The next layer separates **authorization shape** from **authorization provenance**.

A production executor must never be able to authorize itself merely by calling the authorization-template helper. A future real stage must consume a separately issued immutable authority record.

Required one-shot authorization contract:
- unique `transaction_id`;
- exact candidate `operation-control-r0007-20260921-01`;
- exact source `833123b6a7ad2c61087ee8a86700bb9ad8a46298`;
- exact tree `bbca9e3a17162e12a7a0f649138e8c469518ad2a`;
- exact payload SHA/size/file-count;
- exact scope `R0007_RELEASE_STAGE_ONLY`;
- exact issuing repository checkpoint identity;
- binding to the fresh predecessor-boundary evidence used for the mutation decision;
- `production_stage_authorized=true`;
- activation/Drive/legacy-Hub/writer/credential mutation authorization all false.

Authority must be immutable once issued. Exact replay may recognize the same authority/transaction during reconciliation but must never widen it, mint a replacement silently or convert it into activation authority.

D0-02H is qualification-only. It must design and test issue/validate/reconcile/consume semantics without performing the real VPS release publication.

## D0-02H — stage authorization provenance gate r0001

Pre-write authority: `0c76ee26b0f17004f3658e6918ebc7fcdc7ed4a1`; Core and production-stage-prep qualification are PASS. No real production authorization exists.

New qualification-only issuer/consumer protocol:
- `tools/operation_control_r0007_stage_authority_issue.py` — issuer-side canonical record renderer only;
- `tools/operation_control_r0007_stage_authority.py` — consumer-side Git provenance resolver only;
- `tests/core/test_operation_control_r0007_stage_authority.py`;
- `tests/ci/operation_control_r0007_stage_authority_gate.py`;
- `.github/workflows/operation-control-r0007-stage-authority-gate-r0001.yml`.

Authority path is transaction-bound:
`docs/authorizations/operation-control-r0007-stage/<32-hex-transaction-id>.json`.

A valid future authority requires:
1. fresh sanitized stage-boundary evidence already committed in the issuer checkpoint;
2. authorization commit is a direct child of that checkpoint;
3. authorization commit adds exactly one new canonical authority path and no unrelated mutation;
4. path did not exist in the checkpoint;
5. expected Git blob identity is supplied externally and matches;
6. canonical record binds exact candidate/source/tree/payload, repository/branch/checkpoint, boundary evidence Git blob + SHA-256 and scope `R0007_RELEASE_STAGE_ONLY`;
7. activation/Drive/legacy-Hub/writer/credential mutation permissions are all false.

Consumer returns an opaque `IssuedStageAuthorization`. Direct construction with an arbitrary object is rejected, and `require_issued_authorization(...)` rejects raw dictionaries.

Disposable qualification scenarios:
- exact issue + resolve PASS;
- exact replay PASS;
- same transaction/path substitution FAIL_CLOSED;
- wrong expected authority blob FAIL_CLOSED;
- permission widening FAIL_CLOSED;
- authority commit containing unrelated mutation FAIL_CLOSED;
- boundary-evidence binding substitution FAIL_CLOSED.

D0-02H does not add any real `docs/authorizations/...json` record. The gate explicitly fails if such a record exists. It does not perform VPS staging and does not expose activation authority.

### D0-02H stage-authority gate r0001 failure / r0002 correction

D0-02H r0001 commit `40f1635985380223e61a98b5d4be26ebf8e4b816` introduced the intended issuer/consumer protocol, but the first gate stopped at syntax-check before qualification:
- stage-authority gate r0001 run `35712566897` — FAIL;
- Zero-based Core run `35712566899` — FAIL with exactly one import error; 719 tests were started and all other executed tests passed;
- production-stage-prep, stage gate and bootstrap-prep r0002 remained PASS.

Root cause was source-generation escaping only in `tools/operation_control_r0007_stage_authority_issue.py`:
1. the backslash path guard became an unterminated string;
2. canonical `"\\n"` became a literal line break inside the Python string;
3. `newline="\\n"` became a literal line break inside the call.

No authority/provenance semantics were invalidated and no production action was reached.

Correction policy:
- r0001 remains immutable failed gate evidence;
- issuer escaping is corrected once;
- stage-authority framework/gate revision advances to `operation-control-r0007-stage-authority-gate-r0002`;
- no real `docs/authorizations/...json` record is created;
- no VPS/Drive/legacy-Hub mutation is authorized or performed.

## D0-02H authorization provenance PASS

Authoritative qualification HEAD `d125368e4b9496c7ab18f8909b76d611c7d1c747`.

Validation:
- Zero-based Core run `35717172988` — SUCCESS, 724/724 tests;
- stage-authority gate r0002 run `35717173008` — SUCCESS;
- evidence artifact `10689587185`;
- artifact ZIP SHA-256 `9ec645d7d4abdf33f9d05f2ebd32631d1cc9542f0ae888b4e147f7c120860cf0`.

Qualified provenance model:
- issuer and consumer are separate;
- authority path is transaction-bound under `docs/authorizations/operation-control-r0007-stage/<transaction_id>.json`;
- boundary evidence must already exist in the issuer checkpoint;
- authority commit is a direct child of that checkpoint;
- authority commit adds exactly one new canonical authority path;
- expected Git blob identity is externally supplied and verified;
- same-transaction substitution, wrong blob identity, permission widening, unrelated changes and boundary-binding substitution all fail closed;
- consumer emits opaque `IssuedStageAuthorization`;
- raw dict self-authorization is rejected;
- exact immutable replay is deterministic and does not widen permissions.

No real authorization record exists. No VPS stage, activation, Drive mutation or legacy-Hub mutation was performed. The r0007 constrained-candidate lifecycle remains `FROZEN_TRANSITION_GATE_PASS`.

## D0-02I — real-stage authority/execution preparation

The next layer qualifies the complete one-shot production-stage decision/execution boundary while still remaining disposable-only.

Required future transaction sequence:
1. obtain fresh live read-only r0005/legacy-runtime boundary evidence;
2. durably checkpoint that sanitized evidence;
3. issue one unique stage-only authorization as an isolated Git child commit;
4. resolve exact Git provenance into `IssuedStageAuthorization`;
5. acquire and verify exact frozen r0007 payload before publication;
6. execute only the qualified inert release-stage operation;
7. perform immediate postpublication runtime and staged-release reconcile;
8. record a durable sanitized transaction result/consumption receipt;
9. on interruption, reconcile authority commit, release destination and receipt before any retry.

The D0-02I qualification must prove:
- exact happy path;
- exact replay/idempotent reconciliation;
- authority content/blob substitution fails closed;
- stale or mismatched fresh-boundary evidence fails closed;
- payload mismatch fails before publication;
- conflicting/foreign consumption receipt fails closed;
- response loss after publication recognizes the exact staged release and never mints/retries authority blindly;
- stage authorization never becomes activation authorization;
- r0005→r0007 activation remains a later independent transaction.

D0-02I must not create a real `docs/authorizations/...json` record in the authoritative branch and must not perform real VPS publication.

## D0-02I — one-shot stage execution/recovery gate r0001

Pre-write authority: `5c4b8b679c8a67f41de3b976920608facd4755c3`; Core and stage-authority r0002 are PASS. No real production authorization exists and no real VPS stage is permitted.

New qualification-only execution layer:
- `tools/operation_control_r0007_stage_execution.py`;
- `tests/core/test_operation_control_r0007_stage_execution.py`;
- `.github/workflows/operation-control-r0007-stage-execution-gate-r0001.yml`.

The execution model preserves the layered authorities:
- Git `IssuedStageAuthorization` proves who/what authorized the one-shot stage;
- immutable local PREPARED/COMPLETED witnesses prove which authority transaction the executor used;
- the exact immutable r0007 release directory remains the physical commit authority for whether publication happened.

Witness namespace is flat and transaction-bound:
`<witness-root>/<transaction-id>.PREPARED.json`
`<witness-root>/<transaction-id>.COMPLETED.json`.

Witness files are canonical JSON, private mode 0600 on POSIX, published with O_EXCL + fsync + durable parent publication, and never overwritten.

PREPARED is written only after:
1. resolving an opaque Git-issued authorization;
2. re-reading its authority-bound boundary evidence from the issuer checkpoint;
3. performing a fresh stable live boundary observation;
4. matching the critical live projection to authority-bound evidence;
5. verifying the exact frozen r0007 payload/source/SHA/size/file-count.

COMPLETED is written only after exact staged-release reconciliation and post-stage runtime reconcile.

Disposable qualification r0001 covers nine scenarios:
1. exact happy path → COMPLETED_EXACT;
2. exact replay → IDEMPOTENT_COMPLETED_EXACT with no republication;
3. crash after PREPARED before publication → reconcile required, blind retry forbidden;
4. crash after durable publication before COMPLETED → recover COMPLETED without republication;
5. stale/mismatched live boundary → fail before PREPARED;
6. wrong payload → fail before PREPARED;
7. foreign PREPARED witness → fail closed untouched;
8. exact staged release without matching PREPARED → fail closed/no attribution claim;
9. COMPLETED without PREPARED → fail closed.

D0-02I still exposes only the `qualify` CLI. It creates no real `docs/authorizations/...json`, performs no real VPS publication and grants no activation authority.

## D0-02I one-shot stage execution/recovery PASS

Authoritative qualification HEAD `cb47ac7815da558618408104e4ed3a16d297c2ff`.

Validation:
- Zero-based Core run `35723496514` — SUCCESS, 729/729 tests;
- stage-execution gate r0001 run `35723496551` — SUCCESS;
- evidence artifact `10692333515`;
- artifact ZIP SHA-256 `99f62fc1b575eb8ab52fa9cbfcccddb6e4988d15703ba97313e28b754dfa2587`.

Qualified execution/recovery model:
- Git-resolved `IssuedStageAuthorization` is required;
- authority-bound boundary evidence is re-read and matched against a fresh live runtime projection;
- exact frozen r0007 payload is verified before PREPARED;
- flat immutable transaction-bound PREPARED/COMPLETED witnesses provide execution attribution only;
- exact immutable r0007 release directory remains the physical publication commit authority;
- crash after PREPARED but before publication requires reconcile and forbids blind retry;
- crash after exact publication but before COMPLETED recovers the receipt without republication;
- exact replay is idempotent;
- stale boundary, wrong payload, foreign PREPARED, unattributed staged release and COMPLETED-without-PREPARED all fail closed;
- activation remains unauthorized.

No real `docs/authorizations/...json` record exists, no real VPS stage was performed, and the r0007 constrained-candidate lifecycle remains `FROZEN_TRANSITION_GATE_PASS`.

## D0-02J — concrete real-stage transaction preparation

The next qualification layer must join the already-qualified primitives into the exact future operational transaction without executing it against production.

Required future sequence:
1. fresh read-only VPS boundary capture;
2. sanitize and durably checkpoint that evidence in GitHub;
3. issue exactly one transaction-bound stage authority as an isolated child commit;
4. capture exact authority commit/path/blob identities;
5. acquire/transport the exact frozen r0007 payload to a private VPS input path without publishing it into `/opt/keelaryn/releases`;
6. independently verify payload SHA-256, size, file count and source identity on VPS;
7. resolve the Git authority into `IssuedStageAuthorization`;
8. execute the qualified PREPARED → inert release publication → COMPLETED protocol;
9. post-stage read-only reconcile of staged release and all non-release runtime anchors;
10. durably checkpoint the transaction result and all exact identities.

Qualification must cover interruption after each boundary and prove that recovery always starts from external authority/reconcile rather than blind retry.

D0-02J itself remains disposable-only: no real authority issuance, no production payload transport, no real VPS publication, no activation, no legacy-Hub mutation and no Google Drive mutation.

### Stage-authority disposable Git cleanup stabilization — r0003

On closeout HEAD `ea0e7267565f9b88601c91cb4ce01e45f9112219`, current Core remained PASS (729/729) and stage-execution r0001 remained PASS. Stage-authority r0002 rerun `35724428492` failed only after all six authority regression tests and qualification logic had passed, during `TemporaryDirectory.cleanup()` with `OSError: [Errno 39] Directory not empty`.

This is a disposable Git harness hygiene race, not an authorization/provenance semantic failure.

r0003 stabilization:
- `maintenance.auto=false`;
- `gc.auto=0`;
- `gc.autoPackLimit=0`;
- regression test proves those repository-local settings;
- framework/gate revision advances to `operation-control-r0007-stage-authority-gate-r0003`;
- r0002 remains immutable historical evidence.

No authority schema, Git provenance rule, candidate identity, stage permission or production behavior changes.

D0-02J transport direction is also fixed: do not depend on maintainer workstation/SCP. The future VPS-side acquisition path will fetch the exact frozen source commit from GitHub, verify exact HEAD/tree/clean checkout, rebuild the deterministic payload twice and require byte-identical output matching the frozen SHA/size/file-count before any PREPARED witness or release publication.

## D0-02J — concrete real-stage transaction gate r0001

Pre-write authority: `0005fe9fae42b87879881d0bf3bb57227fba5313`; Core 730/730 PASS, stage-authority r0003 PASS, stage-execution and all current downstream gates PASS. No real production authority/input/stage exists.

New qualification-only transaction orchestrator:
- `tools/operation_control_r0007_real_stage_transaction.py`;
- `tests/core/test_operation_control_r0007_real_stage_transaction.py`;
- `.github/workflows/operation-control-r0007-real-stage-transaction-gate-r0001.yml`.

Autonomous payload acquisition model:
1. VPS-side Git fetch of exact frozen source commit;
2. verify exact HEAD `833123b6a7ad2c61087ee8a86700bb9ad8a46298`;
3. verify exact source tree `bbca9e3a17162e12a7a0f649138e8c469518ad2a`;
4. require clean checkout;
5. run frozen `build_payload.py` twice;
6. require byte-identical builds;
7. require exact payload SHA `c833a385e03d313497f865a669dbce8050fa4b296dc587836dad2fa5d3f560e9`, size 414534, file count 208;
8. verify payload again through the qualified materializer parser;
9. publish bytes only to a private transaction-bound 0600 input path using O_EXCL/fsync semantics.

This removes maintainer-workstation/SCP dependency. Production remote is pinned as `https://github.com/efremov-aleksei-96/keelaryn.git`; the disposable gate uses the checked-out repository as a local stand-in remote while exercising the same exact-SHA Git fetch algorithm.

Transaction-level durable sequence qualified by r0001:
- sanitized boundary evidence checkpoint;
- isolated one-shot Git authority commit;
- exact authority blob capture;
- exact private input acquisition;
- Git authority resolve;
- qualified PREPARED → inert release publication → COMPLETED execution;
- isolated sanitized result checkpoint.

Result checkpoint is transaction-bound, requires the same authority commit/blob and exact source/payload as COMPLETED, never grants activation, and is idempotent if exact. A foreign result path fails closed.

Qualification scenarios:
1. evidence checkpoint → isolated authority PASS;
2. authority branch drift FAIL_CLOSED;
3. autonomous exact acquisition ACQUIRED_EXACT;
4. acquisition replay ALREADY_ACQUIRED_EXACT;
5. foreign private input FAIL_CLOSED_UNTOUCHED;
6. one-shot execution COMPLETED_EXACT;
7. result checkpoint RESULT_CHECKPOINTED_EXACT;
8. result replay RESULT_ALREADY_CHECKPOINTED_EXACT;
9. foreign result checkpoint FAIL_CLOSED;
10. stale live boundary FAIL_BEFORE_PREPARED.

The CLI remains `qualify` only. D0-02J creates no real authority/result record in the authoritative branch, performs no real VPS input acquisition/publication, and keeps activation as a later independent transaction.

### D0-02J real-stage transaction r0001 failure / r0002 wiring correction

On HEAD `87ccc0b01f2b412393860918b123f7ba3ed2ff83`:
- Core run `35744268684` — SUCCESS, 735/735 tests;
- stage-authority r0003, stage-execution, production-stage-prep and stage gate — PASS;
- real-stage-transaction r0001 run `35744268814` — FAIL.

r0001 syntax-check and all 5 real-stage unit regressions passed. The qualification reached the one-shot execution boundary, then rejected the otherwise valid Git-resolved authority with `AUTHORITY_PROVENANCE_REQUIRED`.

Root cause: `operation_control_r0007_real_stage_transaction.py` independently loaded `operation_control_r0007_stage_authority.py` under a second module name. Python therefore created a distinct `IssuedStageAuthorization` class identity from the one already loaded/qualified inside `operation_control_r0007_stage_execution.py`. The execution layer's intentional `isinstance` provenance barrier correctly rejected that foreign class identity.

r0002 changes only wiring:
- load `operation_control_r0007_stage_execution.py` once;
- bind `authority = execution.authority`;
- bind `issuer = execution.issuer`;
- bind `production = execution.production`;
- bind `stage = execution.stage`;
- add a regression test requiring object/class identity across the transaction/execution boundary;
- advance gate revision to `operation-control-r0007-real-stage-transaction-gate-r0002`.

No authority schema, transaction state machine, payload acquisition, witness, result checkpoint, frozen candidate bytes or production permissions change.

