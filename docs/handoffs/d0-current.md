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


## D0-02K — fresh real VPS pre-apply reconcile PASS

Fresh control-channel selftest:
- request `50000000000000000000000000000003`;
- request comment `5780183513`;
- terminal status comment `5780188716`;
- exact installed r0005 source `08f2e211f53764590f6ff0f05f86b2de62c14418`;
- `SUCCEEDED / READ_ONLY / PASS`;
- timestamp `2026-09-22T16:31:38Z`.

The first real reconcile attempt exposed a development-only Python 3.12 dynamic-import defect before boundary completion. That defect was fixed on `1908cf3d86c2ce6b2e75425826fc2b46bc489781`, covered by a real `@dataclass` regression, then checkpointed on `8594750510bd2698013382f5ace44e2243273442`. Exact-head Core run `35760845995` passed.

The corrected root-only two-pass VPS reconcile returned PASS. Durable stage-boundary evidence is `docs/evidence/R0007_STAGE_BOUNDARY_20260922T173715Z.json`.

Fresh boundary:
- production source exact `e63f371d14eb9b6069cb2f1b5fad5f4b68a49d4f`;
- control source exact r0005 `08f2e211f53764590f6ff0f05f86b2de62c14418`;
- control payload exact: SHA `6272afbe918d33c29a3f72354baca9e781b3960b3f0f465e1598b5bbc794a7e7`, 365052 bytes, 190 files;
- operation agent and transport active/enabled with exact r0005 unit bytes;
- writer `INACTIVE / MainPID 0`;
- legacy Hub `PREPARED`, transaction `61a2bfb65c9a47d088a76eee0df89d14`, selector `OLD`;
- mutation inhibit present and authority-matching;
- credential SHA exact and bootstrap receipt exact;
- r0007 snapshot unit absent;
- production mutations false;
- Drive mutations false.

The reconcile implementation also fail-closed validates canonical credential actor/status-actor fields, exact legacy cutover tool/finalizer bytes, exact transaction SHA and OLD/NEW selector identities before returning this sanitized result. Raw Hub IDs and credential material are not stored.

### Next permitted objective

**D0-02L — issue one real r0007 stage-only Git authorization.**

This must be an isolated Git child commit bound to this exact boundary-evidence checkpoint. Do not combine authority issuance with VPS payload acquisition or release publication. Activation, legacy-Hub mutation, writer mutation, credential mutation and Drive mutation remain forbidden.

## D0-02L — real r0007 release-stage authority issued

Issuer checkpoint:
- commit `82b1a0107a7f7a01b674265d19e7ad0da93bab8d`;
- Zero-based Core run `35766748442` PASS;
- bootstrap-prep r0002, stage-authority r0003, stage-execution, real-stage-transaction r0002, stage gate and production-stage-prep all PASS.

Issued transaction:
- transaction ID `e7869ce5efd9d63da191e30f7c4e2c2b`;
- authority commit `b821bd44c82e853b7464664087d11cb39644d0df`;
- authority parent / issuer checkpoint `82b1a0107a7f7a01b674265d19e7ad0da93bab8d`;
- authority path `docs/authorizations/operation-control-r0007-stage/e7869ce5efd9d63da191e30f7c4e2c2b.json`;
- authority Git blob `7bbb3196e1318bf808f40b2d89928a45ad2ee44a`;
- authority SHA-256 `002c725f8ddcd5ad1a579116d37ec4aad58521356bf11e57103f0babe81527f8`;
- scope `R0007_RELEASE_STAGE_ONLY`.

Bound fresh stage boundary:
- evidence path `docs/evidence/R0007_STAGE_BOUNDARY_20260922T173715Z.json`;
- evidence Git blob `b91d6f11101aabf9beac1d180a29249fb4515449`;
- evidence SHA-256 `582970cacfa3e2e740379e7c4c9017037324a16a5c731b31246819e3df7f57f5`;
- observed at `2026-09-22T17:37:15Z`.

Read-only post-write verification proved the authority commit has exactly one file diff: one added canonical authorization JSON. The bound evidence blob is byte-identical in issuer parent and authority commit.

Authorized:
- inert r0007 release staging only.

Explicitly not authorized:
- activation;
- Drive content mutation;
- legacy Hub mutation;
- writer mutation;
- credential mutation.

No VPS payload input was acquired and no release was published during D0-02L.

### Next objective — D0-02M

Acquire the exact frozen r0007 payload into the **private transaction-bound VPS input path only**.

Before the write:
1. resolve the exact issued Git authority above;
2. fresh read-only reconcile the private input path and live runtime boundary;
3. if input is already exact, do not rewrite it;
4. if input is foreign/partial, fail closed;
5. only when absent and all authority/boundary identities are exact, perform autonomous exact acquisition.

Acquisition contract:
- fetch exact frozen source `833123b6a7ad2c61087ee8a86700bb9ad8a46298`;
- require source tree `bbca9e3a17162e12a7a0f649138e8c469518ad2a`;
- require clean checkout;
- deterministic build twice, byte-identical;
- payload SHA-256 `c833a385e03d313497f865a669dbce8050fa4b296dc587836dad2fa5d3f560e9`;
- payload size `414534`;
- file count `208`;
- publish only to transaction-bound `0600` private input with O_EXCL/fsync semantics.

D0-02M must not publish into `/opt/keelaryn/releases`, create stage PREPARED/COMPLETED witnesses, activate r0007, mutate legacy Hub/writer/credential, or mutate Drive.

## D0-02M — operational private-input surface

Post-issuance checkpoint `b0fb9cd8f56c7c6fe8508e1fdb76cad6eeada077` passed Zero-based Core run `35767460526`.

The real authority makes older D0-02H/I/J pre-issuance workflows intentionally inapplicable: their first assertions require that no real authority record exist. Current post-issuance safety is therefore carried by Core plus the dedicated D0-02M gate rather than interpreting those expected historical failures as authority defects.

New operational tool:
- `tools/operation_control_r0007_private_input.py`;
- gate `operation-control-r0007-private-input-gate-r0001`;
- transaction fixed to `e7869ce5efd9d63da191e30f7c4e2c2b`;
- authority commit/path/blob/SHA fixed to the already issued D0-02L record;
- default private root `/var/lib/keelaryn/operation-control/r0007-stage-input`;
- CLI surface exactly `reconcile` and `acquire`.

The tool requires:
1. exact local HEAD and authoritative branch ref equal an explicit expected checkpoint;
2. live GitHub branch tip equal the same checkpoint;
3. Git-resolved immutable authority provenance;
4. fresh two-pass real VPS runtime boundary equal the qualified exact runtime boundary;
5. read-only private-input reconcile before any acquisition;
6. exact frozen source fetch/tree/clean checkout;
7. deterministic payload build twice and exact SHA/size/count/materializer verification;
8. a second Git authority + branch + VPS runtime revalidation at the mutation boundary;
9. secure current-user-owned private input root mode 0700;
10. one transaction-bound mode-0600 O_EXCL/fsync publication and immediate exact postverify.

`reconcile` does not create the input root when absent.

`acquire` has no release-publication, stage-witness or activation command/surface. It cannot mutate legacy Hub, writer, credential or Drive.

No real VPS private input was acquired in this development commit.

### D0-02M CLI location hardening

On predecessor HEAD `69c167ddb5576a0941fe9dc43adb78dbe2e7ecca`:
- Zero-based Core run `35768695386` PASS;
- private-input gate r0001 run `35768695814` PASS, 9/9 regressions;
- bootstrap-prep r0002, production-stage-prep and stage gate PASS.

The operational private-input CLI is now intentionally narrower:
- operator cannot override the private input root;
- canonical root is always `/var/lib/keelaryn/operation-control/r0007-stage-input`;
- operator cannot redirect tool output to an arbitrary filesystem path;
- output is stdout only;
- library-level `input_root` parameters remain solely for disposable regression tests;
- CLI commands remain exactly `reconcile` and `acquire`.

The next real action is **read-only reconcile only**. It must not be combined with `acquire`.

### D0-02M harness correction after self-derived branch tip

HEAD `a8058d9fbbba0ef8bcdbeeadc49ffa0bbd1fe8cd` reached the intended production fail-closed branch-drift path. Both the dedicated private-input gate and full Core suite failed only because one regression still matched the obsolete text `branch tip`; the implementation now reports `local HEAD, authoritative branch and live remote branch differ`.

This checkpoint changes only that test expectation and state metadata. No production/private-input/VPS mutation is performed.

### D0-02M self-locating production CLI

A real read-only reconcile on `d3eebd7c25ae49e7e9500f7d19834342985c14f0` failed closed with `REPOSITORY_INVALID` even though the surrounding shell had successfully executed Git commands against the same disposable checkout. No mutation occurred.

The production CLI now removes the last path argument:
- no `--repository-root`;
- repository root is `Path(__file__).resolve().parents[1]`;
- no `--expected-branch-tip`;
- no `--input-root`;
- no `--output`;
- CLI surface is only `reconcile` or `acquire`.

Therefore the next VPS wrapper only needs to fetch/checkout exact HEAD and execute:
`python3 -B tools/operation_control_r0007_private_input.py reconcile`.

### D0-02M issued-record projection correction

The first real self-locating VPS reconcile reached Git-resolved authority validation and failed closed with `AUTHORITY_IDENTITY_MISMATCH` on `transaction_id`. This was a D0-02M wrapper defect, not authority corruption.

`authority.require_issued_authorization(issued)` intentionally returns a production-stage authorization projection and therefore omits `transaction_id`. The wrapper now:
1. calls `require_issued_authorization(issued)` only to validate provenance/type;
2. reads the immutable complete authority from `issued.record`;
3. compares transaction/source/payload/scope/safety flags against that full record.

A regression explicitly proves the wrapper does not depend on the projected return object for transaction identity.

The failed VPS reconcile performed zero private-input/release/Drive/activation mutation.

### D0-02M live private-input prestate PASS

Real VPS read-only reconcile on exact HEAD `2b6a92587a07b7f7529207c88dee07fbc0ba0048` completed successfully.

Verified:
- transaction `e7869ce5efd9d63da191e30f7c4e2c2b`;
- authority commit `b821bd44c82e853b7464664087d11cb39644d0df`;
- authority blob `7bbb3196e1318bf808f40b2d89928a45ad2ee44a`;
- authority SHA-256 `002c725f8ddcd5ad1a579116d37ec4aad58521356bf11e57103f0babe81527f8`;
- branch tip exact `2b6a92587a07b7f7529207c88dee07fbc0ba0048`;
- control source remains r0005 `08f2e211f53764590f6ff0f05f86b2de62c14418`;
- production source remains `e63f371d14eb9b6069cb2f1b5fad5f4b68a49d4f`;
- legacy Hub remains `PREPARED`, selector `OLD`;
- writer remains `INACTIVE/MainPID=0`;
- r0007 snapshot unit remains absent;
- canonical private-input root is absent.

The reconcile performed zero private-input/root/release/witness/activation/Hub/writer/credential/Drive mutation.

Sanitized evidence: `docs/evidence/R0007_PRIVATE_INPUT_RECONCILE_20260922.json`.

Next transaction: one private-input `acquire` only. It may create the canonical private root and exact transaction-bound payload, but must not perform release publication, stage witnesses or activation.

### D0-02M real private-input acquire PASS

Real VPS `acquire` completed successfully from exact checkpoint `4888cd7002c2f5522f10c87d509c1b319d72ad46`.

Durable private input:
- root `/var/lib/keelaryn/operation-control/r0007-stage-input` created;
- transaction payload `e7869ce5efd9d63da191e30f7c4e2c2b.r0007.tar.gz`;
- state `INPUT_EXACT / ACQUIRED_EXACT`;
- source `833123b6a7ad2c61087ee8a86700bb9ad8a46298`;
- payload SHA-256 `c833a385e03d313497f865a669dbce8050fa4b296dc587836dad2fa5d3f560e9`;
- payload size `414534`;
- file count `208`.

The acquire transaction revalidated the exact authority and live boundary before publication and immediately postverified the written input.

Mutation scope was exactly limited to private input:
- private input: true;
- private input root created: true;
- release publication: false;
- stage witness: false;
- activation: false;
- legacy Hub/writer/credential: false;
- Drive: false.

Sanitized evidence: `docs/evidence/R0007_PRIVATE_INPUT_ACQUIRE_20260922.json`.

Next lifecycle step is D0-02N: prepare/qualify the inert release-publication transaction. Release publication is a separate production-filesystem mutation and is not performed by this checkpoint.

### D0-02N operational stage runtime

D0-02M private input is already exact and durably checkpointed. Review confirmed that the lower-level stage implementation is qualified but all existing CLIs expose only `qualify`.

This revision adds `tools/operation_control_r0007_stage_runtime.py` as the narrow real-host surface:
- commands only `reconcile` and `stage`;
- no repository/input/release/witness/output path overrides;
- self-locates the exact Git checkout;
- reuses the issued-authority resolver and exact live-boundary verifier;
- verifies the canonical acquired input before any stage work;
- loads the exact frozen r0007 materializer, never a mutable development materializer;
- release root fixed to `/opt/keelaryn/releases`;
- witness root fixed to `/var/lib/keelaryn/operation-control/r0007-stage-witness`;
- read-only reconcile never creates the witness root;
- stage revalidates Git/authority/runtime/input at the mutation boundary;
- witness root creation is owner-only 0700;
- execution delegates to the already-qualified monotonic `execute_once` PREPARED -> immutable release -> COMPLETED protocol;
- activation/Hub/writer/credential/Drive mutation surfaces do not exist;
- a stage failure reports release/witness outcome as unknown and requires reconcile rather than falsely claiming zero mutation.

The old private-input gate is also made lifecycle-aware by removing its obsolete requirement that the current objective still be D0-02M.

Next action after green CI is one real read-only stage-runtime `reconcile` only.

### D0-02N stage-runtime gate harness correction

On HEAD `efa6e2a1fca33bb7c7e0f34e66913e21df19d75b`:
- Core PASS;
- private-input gate PASS;
- production-stage-prep PASS;
- bootstrap-prep r0002 PASS;
- stage gate PASS;
- stage-runtime authority/evidence checks PASS;
- stage-runtime syntax PASS;
- stage-runtime regressions 11/11 PASS.

The stage-runtime gate failed only because its static source check required the literal private-input path to appear in the wrapper. The wrapper intentionally binds `DEFAULT_INPUT_ROOT = private_input.DEFAULT_INPUT_ROOT` so there is a single canonical path definition. The gate now verifies that inheritance instead of requiring duplicated configuration.

No production mutation is performed by this harness-only correction.

### D0-02N single execution/authority module graph correction

The first real stage-runtime read-only reconcile on `2fbda345919b6f0fcf8a3509b042c42f9b7c008b` failed closed with `AUTHORITY_PROVENANCE_REQUIRED` before any release/witness mutation.

Root cause: the wrapper loaded `operation_control_r0007_stage_execution.py` a second time. The private-input path already reaches `real_stage_transaction.execution`, whose source explicitly requires reuse of one trusted execution/authority module graph because Python class identity differs across duplicate importlib loads.

The wrapper now sets:
- `transaction = private_input.transaction`;
- `execution = transaction.execution`;
- `stage = execution.stage`.

A regression requires object identity between runtime execution, transaction execution and their authority modules. No production mutation is performed by this correction.

### D0-02N live stage prestate PASS

Real VPS stage-runtime `reconcile` on exact HEAD `84d352abefef2f301604951d6067a876ee8e7b8a` completed successfully.

Verified:
- exact issued authority/provenance;
- transaction-bound private input `INPUT_EXACT`;
- payload source `833123b6a7ad2c61087ee8a86700bb9ad8a46298`;
- payload SHA-256 `c833a385e03d313497f865a669dbce8050fa4b296dc587836dad2fa5d3f560e9`;
- payload size `414534`, file count `208`;
- runtime boundary remains production source `e63f371d...`, control source r0005, legacy Hub PREPARED/OLD, writer INACTIVE, r0007 snapshot unit absent;
- stage execution state `NEW`;
- release state `NOT_STAGED`;
- PREPARED/COMPLETED witnesses absent;
- canonical witness root absent.

The reconcile performed zero witness-root/release/witness/activation/Hub/writer/credential/Drive mutation.

Sanitized evidence: `docs/evidence/R0007_STAGE_RUNTIME_RECONCILE_20260923.json`.

Next transaction is one inert `stage` invocation only. It may create the witness root, PREPARED/COMPLETED immutable witnesses and the exact immutable r0007 release directory. It must not change `/opt/keelaryn/current` or any runtime/Hub/Drive state. After any interruption, reconcile before retry.

### D0-02N real inert stage COMPLETED_EXACT

The real VPS `stage` invocation from exact HEAD `6d35f444074ea094259a9d8a8569c31f4a3df42c` completed terminally.

Durable result:
- canonical witness root created;
- immutable PREPARED witness committed;
- exact immutable r0007 release published at `/opt/keelaryn/releases/833123b6a7ad2c61087ee8a86700bb9ad8a46298`;
- immutable COMPLETED witness committed;
- post-reconcile `PASS`;
- execution `COMPLETED_EXACT`;
- release `STAGED_EXACT`;
- prepared SHA-256 `ca6af6239a042d96b2e3d2c3c600aba9d2f931eb4e54a82b5b0f1711c418341e`.

The transaction did **not** activate r0007 or change `/opt/keelaryn/current`. Legacy Hub, writer, credential and Drive were not mutated.

Sanitized evidence: `docs/evidence/R0007_STAGE_RUNTIME_COMPLETED_20260923.json`.

Next lifecycle step is D0-02O: one fresh read-only post-stage reconcile and inspection of the existing activation/update protocol. No activation is authorized by this checkpoint.

### D0-02O post-stage reconcile PASS

Real VPS read-only post-stage reconcile on exact HEAD `e287d4bfd2b8432a620e8737da3f5d78a58b2196` completed successfully.

Verified:
- private input remains `INPUT_EXACT`;
- stage witnesses are present and exact;
- execution remains `COMPLETED_EXACT`;
- release remains `STAGED_EXACT`;
- control source remains predecessor r0005 `08f2e211f53764590f6ff0f05f86b2de62c14418`;
- production source remains `e63f371d14eb9b6069cb2f1b5fad5f4b68a49d4f`;
- legacy Hub remains PREPARED/OLD;
- writer remains INACTIVE/MainPID=0;
- r0007 snapshot unit remains absent.

No witness/release/activation/Hub/writer/credential/Drive mutation occurred.

Sanitized evidence: `docs/evidence/R0007_POST_STAGE_RECONCILE_20260923.json`.

The next lifecycle step is D0-02P control-update preparation. The existing qualified D0 update protocol is `deploy/zero-based-vps/operation_control_d0_update.py`; it updates only the control plane (`control-current` plus control units/services), leaves production `current` unchanged, protects credential identity, and has rollback/recovery semantics. No control update is authorized by this checkpoint.

### D0-02P narrow control-update runtime

Post-stage state is exact and r0007 is inertly staged. Review confirmed that the frozen `operation_control_d0_update.py` protocol is the correct r0005 -> r0007 control transition: it preserves production `current`, switches only `control-current` plus exact control unit bytes, restarts the persistent control services, checks stability, preserves credential identity, and has transactional rollback/recovery.

The generic updater CLI is not used directly in production because it exposes path and identity overrides.

This revision adds `tools/operation_control_r0007_control_update_runtime.py`:
- commands only `reconcile` and `update`;
- self-locates the current dev checkout and proves live branch identity;
- resolves the exact issued stage authority;
- verifies immutable stage PREPARED/COMPLETED witnesses independently of current control boundary;
- verifies exact installed r0005 and staged r0007 release identities with the frozen materializer;
- loads the mutation engine from the verified staged r0007 release itself;
- fixes install/unit/credential/operation/transport/update roots to canonical VPS paths;
- fixes old/new source and payload identities;
- requires production `current` to remain exact `e63f...`;
- requires exact credential SHA;
- requires operation runtime and transport inbox idle;
- classifies control state as `OLD_EXACT` or `NEW_EXACT`;
- classifies transaction state as `NEW`, recoverable PREPARED states, `COMPLETED_EXACT`, `ROLLED_BACK_EXACT`, or fail-closed;
- never creates update-root during `reconcile`;
- on update failure reports mutation/credential outcome unknown and requires read-only reconcile before any retry;
- has no Hub or Drive mutation surface.

Next action after green CI is one real VPS `reconcile` only.

### D0-02P frozen sibling import correction

The first real control-update-runtime read-only reconcile on `ed87796a79e67168b1f9083295f31f2a6d2afc09` failed before control-state classification and before any write.

Observed exception: frozen `operation_control_plane_update.py` could not resolve its canonical sibling import `materialize_payload`.

Root cause: the verified staged updater was loaded through `importlib`, so Python did not automatically place its frozen `deploy/zero-based-vps` directory on `sys.path`.

The runtime loader now:
- verifies the staged r0007 release first;
- explicitly loads the exact staged sibling `materialize_payload.py` under the canonical module name;
- temporarily prepends only the verified frozen deploy directory while loading the updater;
- refuses to let a cached dev `materialize_payload` satisfy the frozen dependency;
- restores prior `sys.path` and prior canonical module binding after import;
- converts import failures to structured `FROZEN_UPDATER_IMPORT_FAILED` fail-closed output.

Regressions cover cached-module shadowing, frozen sibling selection, namespace restoration and structured import failure.

No control-current/systemd/service/credential/Hub/Drive/production-current mutation occurred.

### D0-02P live control-update prestate PASS

Real VPS `control-update-runtime reconcile` on exact HEAD `9709b513d104daf984fc012c4825f2559d7cc460` completed successfully.

Verified:
- stage transaction `e7869ce5efd9d63da191e30f7c4e2c2b` remains exact and completed;
- staged r0007 release remains exact;
- installed predecessor r0005 release remains exact;
- `control-current` + installed control units classify `OLD_EXACT`;
- D0 control-update transaction ID `4832c22f208742c3cf5a8e32a79fbf92bfb037acd81f21d1331904cb54f68073`;
- control-update state `NEW`;
- control-update root absent;
- production `current` remains `releases/e63f371d14eb9b6069cb2f1b5fad5f4b68a49d4f`;
- credential SHA remains exact;
- operation runtime and transport inbox passed idle checks.

The reconcile performed zero control-update/production-current/Hub/credential/Drive mutation.

Sanitized evidence: `docs/evidence/R0007_CONTROL_UPDATE_RECONCILE_20260923.json`.

Next transaction is one r0005 -> r0007 control update invocation only. It may create D0 update PREPARED/COMPLETED records, replace exact control unit bytes, switch only `control-current`, and restart the persistent control services under the frozen transactional updater. Production `current`, legacy Hub, credential contents and Drive remain outside the allowed mutation set. After any interruption or uncertain result, reconcile before retry.

### D0-02Q DEVELOPMENT_STATE mutation flag correction

HEAD `32c115735b0835d30e8f6bc74d4553d6234c1d10` has a valid live control-update prestate and a green control-update-runtime gate. Zero-based Core rejected only the checkpoint metadata because D0 requires `next_objective.production_mutation_allowed=false` unconditionally.

This revision changes only that metadata flag back to `false`.

This does **not** revoke or weaken the separately qualified r0005 -> r0007 control-update protocol. Production mutation authority is carried by the transaction-specific protocol/evidence and must never be inferred from the generic D0 objective metadata.

No VPS mutation occurs in this correction.

### D0-02Q control update ROLLED_BACK_EXACT

The first real r0005 -> r0007 D0 control update failed when systemd could not start `keelaryn-operation-transport.service`.

The frozen updater reported exact rollback. Mandatory post-failure read-only reconcile on exact HEAD `0680919dc54699880e5fcd91ec2994f280b7e16e` proved:
- control boundary `OLD_EXACT`;
- transaction `4832c22f208742c3cf5a8e32a79fbf92bfb037acd81f21d1331904cb54f68073` is `ROLLED_BACK_EXACT`;
- update root is present;
- r0005 release remains exact;
- r0007 staged release/witnesses remain exact;
- production `current` remains `releases/e63f371d14eb9b6069cb2f1b5fad5f4b68a49d4f`;
- credential remains exact;
- Hub/Drive were not mutated.

Sanitized evidence: `docs/evidence/R0007_CONTROL_UPDATE_ROLLED_BACK_20260923.json`.

This transaction is terminal and must never be retried. Next objective is read-only failure diagnosis. If a correction changes frozen successor product bytes or transition behavior, create a new successor candidate/transaction rather than altering or replaying r0007.

### D0-02R exact failure diagnosis and successor fix

VPS journal proves the failed r0007 control switch reached successor transport startup, which exited with `ERROR: operation relay source_commit mismatch`; rollback then restored r0005 transport successfully.

Static analysis proves:
- r0005/r0007 transport unit bytes are identical;
- r0005/r0007 agent unit bytes are identical;
- the transport root/outbox is durable and shared across control releases;
- terminal relay files remain in outbox after publication;
- r0007 `GitHubOperationTransport._publish_statuses()` fatally rejects every relay whose `source_commit` differs from the running release.

Therefore r0007 has a product-level upgrade-compatibility defect. It remains frozen/rejected and transaction `4832c22f...` remains terminal `ROLLED_BACK_EXACT`.

Development fix:
- historical predecessor relay is tolerated only when it is terminal **and** private transport state proves the exact status body SHA-256 was already published;
- it is never republished/adopted as successor output;
- mismatched nonterminal relay fails closed;
- mismatched terminal relay without publication proof fails closed;
- publication digest conflict fails closed.

Regression coverage is added for all three transition cases.

Durable diagnosis: `docs/evidence/R0007_CONTROL_UPDATE_FAILURE_DIAGNOSIS_20260923.json`.

Next objective is D0-02S: qualify this fix and freeze a **new successor candidate/version** with a new production transaction identity. Do not alter or retry r0007.

### D0-02S r0008 successor candidate frozen

Frozen candidate:
- `operation-control-r0008-20260923-01`;
- source `20727893662cde92998d88ecdca730b69633eaaa`;
- source tree `c68bfe3dab53206439d1c42634f5c5ac602fb09c`;
- payload SHA-256 `bc74c0e5b7eba90465fb8d59c5bb9a619ebc1f2c737c06fbf357ae062c5b374d`;
- payload size `428403`;
- file count `217`;
- source Core run `35826924330`: 781 tests PASS;
- deterministic r0005 -> r0008 control-update digest `83e20aeecd4ecd7a8288816065fa700ab3e99b8017177df215e18e03695d4e58`.

The frozen source is the parent commit. This revision adds only candidate receipt and qualification tooling; it does not alter frozen product bytes.

New qualification:
- candidate gate rebuilds/materializes exact frozen r0008 and runs full frozen Core/security validation;
- transition gate retains the six r0007-era success/rollback/recovery cases, retargeted to r0008;
- seventh scenario `shared_outbox_upgrade` recreates the real failure condition: an exact already-published terminal r0005 relay remains in the shared durable outbox when r0008 transport starts. r0008 must start successfully and must not create/update/re-adopt that predecessor publication.

r0007 remains immutable rejected evidence; transaction `4832c22f...` remains terminal `ROLLED_BACK_EXACT` and is never reused.

### D0-02S r0008 gate harness candidate-name correction

The first r0008 candidate/transition gate runs failed before frozen-source checkout because generated qualification files referenced `operation-control-r0008-20260921-01` while the immutable receipt is correctly `operation-control-r0008-20260923-01`.

This revision changes only that qualification metadata string in the r0008 candidate gate, transition gate and transition harness. Frozen source/tree/payload bytes are unchanged.

### D0-02S r0008 candidate + transition qualification PASS

Artifacts reviewed and durably copied into repository:
- candidate gate run `35828006786` PASS; artifact digest `70831d0ac95213ac8fc9c39c73358c7a233e7da9e2efaf0f99c1abe9a452d9d4`;
- transition gate run `35828006771` PASS; artifact digest `ded3a9442770be5ca283a5039c24b65247f443971561dc42bec1d1222dfb4988`.

Transition evidence has seven scenarios. The new `shared_outbox_upgrade` scenario proves:
- predecessor r0005 terminal relay remains in the shared durable outbox;
- r0008 successor startup probe passes;
- predecessor status is not created/updated/republished by r0008.

No production or Drive mutation occurred.

Next objective D0-02T: create and qualify r0008-specific production-prep/private-input/stage surfaces with new transaction roots/identities. r0007 staged/private-input/witness state remains immutable and must not be overwritten.

### D0-02S transition evidence copy correction

The first repository copy of the already-PASS r0008 transition artifact accidentally serialized the nested `scenarios` object as empty. This was a checkpoint serialization defect only.

This revision replaces that file with the complete canonical artifact content, including all seven scenarios and the exact `shared_outbox_upgrade` result. Candidate bytes, gate runs and production state are unchanged.

### D0-02T r0008 production-prep framework

Added an isolated r0008 staging/authority framework, derived from the qualified r0007 framework but rebound to:
- candidate `operation-control-r0008-20260923-01`;
- source `20727893662cde92998d88ecdca730b69633eaaa`;
- tree `c68bfe3dab53206439d1c42634f5c5ac602fb09c`;
- payload `bc74c0e5b7eba90465fb8d59c5bb9a619ebc1f2c737c06fbf357ae062c5b374d`, size 428403, files 217;
- r0008 schemas/scope/authority root.

New tools:
- `operation_control_r0008_vps.py`;
- `operation_control_r0008_stage.py`;
- `operation_control_r0008_production_stage.py`;
- `operation_control_r0008_stage_authority.py`;
- `operation_control_r0008_stage_authority_issue.py`;
- `operation_control_r0008_stage_execution.py`;
- `operation_control_r0008_real_stage_transaction.py`.

The r0008 authority directory is intentionally still absent. No authority has been issued. No private-input/stage-runtime binding is created yet, because those must bind the exact Git provenance of the authority issued only after a fresh live VPS boundary reconcile.

The consolidated production-prep gate proves candidate binding, namespace isolation from r0007, protocol regressions, and authority absence. r0007 authority/private-input/stage witnesses remain immutable.

Next after green CI: one read-only r0008 live-boundary reconcile. No VPS mutation.

### D0-02T r0008 production-prep gate harness correction

First prep gate run `35831437056` passed candidate identity and authority-absence checks. The seven r0008 modules compiled without a syntax error, but `python -m py_compile` wrote `__pycache__`; the subsequent clean-worktree assertion failed.

This changes only the gate compile method to residue-free built-in `compile()`.

No r0008 framework/product bytes changed. No authority/VPS/Drive mutation occurred.

### D0-02T historical-boundary compatibility correction

The second r0008 production-prep run reached candidate/authority-absence/compile/namespace checks and then failed in the cloned VPS-prep regression.

Root cause:
- r0008 candidate/authority namespace was correctly retargeted;
- but the current durable production-boundary evidence is still an r0007 stage-boundary record, and legacy D0 evidence still names `r0007_snapshot_unit`;
- these are historical provenance inputs, not r0007 authority reuse.

Correction:
- r0008 VPS prep accepts exact canonical `keelaryn.operation-control-r0007-stage-boundary-evidence.v1` as the current recorded boundary input;
- legacy D0 evidence continues to read `r0007_snapshot_unit`;
- r0008 candidate/source/payload/authority root/scope remain strictly r0008;
- DEVELOPMENT_STATE now records r0007 as `REJECTED_AFTER_CONTROL_UPDATE_ROLLBACK_EXACT / FORBIDDEN`;
- r0008 is added as `FROZEN_CANDIDATE_AND_TRANSITION_GATE_PASS`.

Also restored `last_coherent_ci.conclusion=PASS` per validator contract. No authority/VPS/Drive mutation.

### D0-02T r0008 lifecycle-token normalization

Prep gate run `35832182708` passed candidate, authority-absence, compile and namespace checks. VPS-prep tests then found only that DEVELOPMENT_STATE used `FROZEN_CANDIDATE_AND_TRANSITION_GATE_PASS` while the existing qualified prep contract requires canonical token `FROZEN_TRANSITION_GATE_PASS`.

This revision changes only that state token. No framework/product/authority/VPS/Drive mutation.

### D0-02T retired r0007 test expectation correction

On HEAD `ec70efb1959462cb1e87f9c2331b681312e13974`, r0008 production-prep gate run `35832395232` passed completely.

Zero-based Core failed only because two old `test_operation_control_r0007_vps.py` tests still expected the repository's current r0007 disposition to be `FROZEN_TRANSITION_GATE_PASS`. The real r0007 production transaction is terminal `ROLLED_BACK_EXACT`, so current DEVELOPMENT_STATE correctly marks r0007 `REJECTED_AFTER_CONTROL_UPDATE_ROLLBACK_EXACT / FORBIDDEN`.

Regression correction:
- current repository state explicitly tests that r0007 prep fails closed;
- historical legacy-evidence parser compatibility uses an isolated synthetic fixture with r0007 temporarily marked pre-rejection qualified.

No r0007 runtime/tool behavior changed. No r0008 framework/product/authority/VPS/Drive mutation.

### D0-02T fresh r0008 live boundary PASS

Exact-head read-only VPS reconcile on `c81affd43ec6cff3801be8e8e35de6670df6bc4b` passed.

Verified:
- control source remains exact r0005 `08f2e211...`;
- production source remains `e63f371d...`;
- both persistent operation-control services are ACTIVE/enabled with exact release bytes;
- legacy Hub remains `PREPARED / OLD` under `RUNTIME_SAFETY_ONLY`;
- mutation inhibit authority remains exact;
- writer remains INACTIVE/MainPID=0;
- credential remains exact;
- r0008 snapshot unit is ABSENT;
- production/Drive mutations are false.

Sanitized evidence: `docs/evidence/R0008_LIVE_BOUNDARY_RECONCILE_20260923.json`.

No r0008 authority has been issued. Next objective is bootstrap-input qualification only, still without VPS mutation.

### D0-02U r0008 disposable bootstrap qualification PASS

Real VPS `operation_control_r0008_vps.py qualify` on exact HEAD `a04a478c6165362ba2368667a322bf419df1dee0` completed successfully.

Verified:
- exact frozen source/tree/payload;
- deterministic rebuild and disposable materialization;
- target-host validation;
- D0 installed-unit and snapshot-unit policy validation;
- remote allowlist exactly `PRODUCTION_SNAPSHOT`, `RUNTIME_SELFTEST`;
- zero remote mutation handlers;
- production/Drive mutation permission false.

The qualification's `recorded_live_boundary` still resolves historical canonical r0007 stage-boundary evidence. That remains valid compatibility provenance for disposable qualification, but it is not accepted as new r0008 production authority input.

Durable qualification: `docs/evidence/R0008_BOOTSTRAP_INPUT_QUALIFICATION_20260923.json`.

Added `tools/operation_control_r0008_boundary_capture.py`: a read-only primitive that performs r0008 reconcile, requires exact live service/runtime anchors, emits the exact r0008 stage-boundary evidence schema with a fresh UTC timestamp, and validates it through the r0008 authority contract before output.

No r0008 authority, VPS mutation or Drive mutation is part of this checkpoint.

### D0-02V canonical r0008 authority boundary PASS

Real VPS boundary capture from exact HEAD `db323f41c393de0692431e1fda4b4353d8d52cd7` emitted canonical `keelaryn.operation-control-r0008-stage-boundary-evidence.v1`.

Observed at `2026-09-23T09:27:08Z`:
- production source `e63f371d14eb9b6069cb2f1b5fad5f4b68a49d4f`;
- control source exact r0005 `08f2e211f53764590f6ff0f05f86b2de62c14418`;
- legacy Hub `PREPARED / OLD`;
- writer `INACTIVE_MAINPID_0`;
- mutation inhibit authority exact;
- credential SHA exact;
- production and Drive mutations false.

The **exact captured JSON bytes** are committed as `docs/evidence/R0008_STAGE_BOUNDARY_20260923T092708Z.json`, and DEVELOPMENT_STATE.production_boundary now references this r0008 authority-grade evidence.

No r0008 stage authority has been issued yet. Next objective is one separate GitHub-only release-stage authorization transaction, followed by exact read-back provenance verification before any VPS private-input/stage work.

### D0-02W r0008 authority-prep compatibility correction

After committing the canonical r0008 stage boundary, the r0008 production-prep gate failed before its regressions for one mechanical reason: it still expected exactly seven `operation_control_r0008_*.py` tools, while the newly qualified read-only boundary-capture primitive is the eighth.

The r0008 VPS-prep provenance parser also still accepted only historical r0007 stage-boundary schema.

This revision:
- changes the prep-gate namespace count from 7 to 8;
- accepts exact canonical r0008 stage-boundary evidence in addition to historical r0007 evidence;
- keeps exact canonical byte/shape/identity checks unchanged;
- does not issue authority and performs no VPS/Drive mutation.

### D0-02W retired r0007 fixture correction after r0008 boundary promotion

After DEVELOPMENT_STATE.production_boundary correctly moved to canonical r0008 boundary evidence, Core exposed three stale r0007 VPS-prep tests that still treated the current production boundary as an r0007 historical fixture.

The failures were test-only:
- current rejected-r0007 disposition test;
- r0007 stage-boundary identity-drift test;
- r0007 noncanonical-stage-boundary test.

All three now explicitly select preserved historical `R0007_STAGE_BOUNDARY_20260922T173715Z.json` inside disposable fixtures. r0007 runtime/parser bytes are unchanged and remain rejected provenance.

r0008 production-prep and boundary-capture gates were already PASS. No authority/VPS/Drive mutation occurs in this correction.

### D0-02X post-authority lifecycle fixture correction

Exact-head qualification after adding r0008 private-input/stage-runtime tooling exposed only lifecycle/test issues:
- the private-input synthetic authority fixture still named `operation-control-r0008-20260921-01` instead of the issued candidate `operation-control-r0008-20260923-01`;
- boundary-capture and production-prep gates still required r0008 authority absence, invalid after isolated issuance.

This revision changes no product/runtime or authority bytes. It corrects the synthetic fixture and makes both historical prep gates verify the one exact canonical stage-only r0008 authority instead of requiring absence.

The r0008 stage-runtime gate was already PASS. No VPS/Drive mutation occurs.

### D0-02X production-prep explicit toolset correction

The post-authority r0008 private-input, stage-runtime and boundary-capture gates are PASS. Production-prep failed only because it glob-counted all `operation_control_r0008_*.py` tools and therefore treated independently qualified private-input/stage-runtime tooling as unexpected.

Production-prep now validates an explicit seven-tool prep framework instead of a global namespace count. No product/runtime/authority/VPS/Drive mutation occurs.

### D0-02Y r0008 private-input clean prestate PASS

Real VPS read-only `operation_control_r0008_private_input.py reconcile` on exact branch tip `c2fcaf269f2d40454c0781a96545b072d782cb81` returned the clean prestate required before acquisition.

Verified:
- transaction `a6383609e9a6442ad86445ba62baff93` and issued authority commit/blob/SHA are exact;
- private input root is absent: `INPUT_ROOT_ABSENT`;
- expected input filename is `a6383609e9a6442ad86445ba62baff93.r0008.tar.gz`;
- production source remains `e63f371d14eb9b6069cb2f1b5fad5f4b68a49d4f`;
- installed control source remains r0005 `08f2e211f53764590f6ff0f05f86b2de62c14418`;
- legacy Hub remains `PREPARED / OLD`;
- writer is `INACTIVE / MainPID=0`;
- r0008 snapshot unit is absent;
- private-input/root creation/release publication/stage witness/activation/legacy-Hub/writer/credential/Drive mutation flags are all false.

Sanitized durable evidence: `docs/evidence/R0008_PRIVATE_INPUT_RECONCILE_20260923.json`.

The reconcile output did not contain its own UTC observation timestamp, so this checkpoint intentionally does not invent one.

Next transaction is exactly one r0008 private-input `acquire` invocation. It may create the isolated private-input root and publish only the transaction-bound r0008 input after its built-in Git/authority/live-boundary revalidation. It must not stage, activate, mutate the legacy Hub, writer, credential, production current, or Drive. After any result or interruption, reconcile before any retry or stage action.

### D0-02Z r0008 private input acquired and post-verified

One real VPS private-input `acquire` transaction on exact branch tip `67c30798d915765349b1f4f5270fb82974cbddc8` completed successfully for authority transaction `a6383609e9a6442ad86445ba62baff93`.

Acquire result:
- input root was created;
- transaction-bound file `a6383609e9a6442ad86445ba62baff93.r0008.tar.gz` reconciled as `INPUT_EXACT / ACQUIRED_EXACT`;
- identity is exact frozen r0008 source `20727893662cde92998d88ecdca730b69633eaaa`, payload SHA-256 `bc74c0e5b7eba90465fb8d59c5bb9a619ebc1f2c737c06fbf357ae062c5b374d`, size `428403`, file count `217`;
- the only reported mutation was isolated private-input/root creation;
- release publication, stage witness, activation, legacy Hub, writer, credential and Drive mutations were false.

Mandatory independent post-acquire read-only reconcile then returned the same `INPUT_EXACT` identity with all mutation flags false. Live safety boundary remained r0005 control source, production source `e63f371d...`, legacy Hub `PREPARED / OLD`, writer inactive/MainPID=0 and r0008 snapshot unit absent.

Durable evidence: `docs/evidence/R0008_PRIVATE_INPUT_ACQUIRED_20260923.json`.

Neither tool output emitted a UTC observation timestamp; none is invented here.

Next objective is one read-only r0008 stage-runtime `reconcile` only. Expected clean stage prestate: `NEW / NOT_STAGED`, `prepared=false`, `completed=false`, witness root absent. Do not run `stage` until that prestate is separately verified and checkpointed.

### D0-03A r0008 clean stage prestate PASS

Real VPS read-only `operation_control_r0008_stage_runtime.py reconcile` on exact branch tip `5153a1b9210e565521c9752973b204d988d96cf8` returned the required clean prestate before release staging.

Verified:
- transaction `a6383609e9a6442ad86445ba62baff93` and issued authority remain exact;
- private input remains `INPUT_EXACT` with frozen source `20727893662cde92998d88ecdca730b69633eaaa`, payload SHA-256 `bc74c0e5b7eba90465fb8d59c5bb9a619ebc1f2c737c06fbf357ae062c5b374d`, size `428403`, file count `217`;
- stage execution state is `NEW`;
- release state is `NOT_STAGED`;
- `prepared=false`, `completed=false`;
- witness root is `ABSENT`;
- production source remains `e63f371d14eb9b6069cb2f1b5fad5f4b68a49d4f`;
- control source remains exact r0005 `08f2e211f53764590f6ff0f05f86b2de62c14418`;
- legacy Hub remains `PREPARED / OLD`;
- writer remains inactive/MainPID=0;
- witness-root creation, release publication, stage-witness, activation, legacy-Hub, writer, credential and Drive mutation flags are all false.

Sanitized durable evidence: `docs/evidence/R0008_STAGE_PRESTATE_20260923.json`.

The reconcile output contained no UTC observation timestamp, so none is invented.

Next transaction is exactly one r0008 stage-runtime `stage` invocation. Its implementation performs a second Git/authority/runtime/private-input revalidation immediately before mutation. It may create the isolated witness root and publish only the exact frozen r0008 release under the already-issued `R0008_RELEASE_STAGE_ONLY` authority. Activation, legacy Hub, writer, credential, production-current selector and Drive remain outside the allowed mutation set. After any outcome or interruption, reconcile before any retry or later action.

### D0-03B r0008 stage completed and post-verified

One real VPS r0008 stage-runtime `stage` transaction on exact branch tip `00fb90a9e9ab05bf655f8f0afad251d70d6480da` completed successfully for authority transaction `a6383609e9a6442ad86445ba62baff93`.

Stage result:
- prestate was `NEW / NOT_STAGED`;
- execution completed `COMPLETED_EXACT`;
- release is `STAGED_EXACT`;
- prepared witness SHA-256 is `c89be4c90ffde0c4ec6e6d3d9ce5348faf213f7a41a93dd4b9f7fe94c9f6f582`;
- release publication and isolated stage-witness/root creation occurred;
- `blind_retry_allowed=false`, `exact_replay=false`, release deletion forbidden;
- activation was not authorized or performed;
- legacy Hub, writer, credential and Drive mutations were false.

Mandatory independent post-stage read-only reconcile then proved:
- execution remains `COMPLETED_EXACT`;
- release remains `STAGED_EXACT`;
- witness root is `PRESENT`;
- private input remains `INPUT_EXACT`;
- witness records production and Drive mutations as false;
- the reconcile itself performed no release/witness/activation/Hub/writer/credential/Drive mutation.

Durable evidence: `docs/evidence/R0008_STAGE_COMPLETED_20260923.json`.

Neither tool output emitted a UTC observation timestamp; none is invented.

The r0008 stage transaction is complete and MUST NOT be replayed. The next engineering objective is an r0008-specific control-update runtime/gate. The old r0007 control-update runtime is candidate-bound to rejected r0007 and cannot be reused for the real switch. First build/qualify the r0008 runtime and perform a separate real-VPS read-only control-update prestate reconcile. Production `current`, legacy Hub, credential and Drive remain outside allowed mutation scope.

### D0-03B r0008 control-update runtime implementation

This successor adds an r0008-specific production control-update runtime derived from the previously qualified r0007 state machine but rebound to the accepted r0008 candidate and completed r0008 stage authority.

New development surfaces:
- `tools/operation_control_r0008_control_update_runtime.py`;
- `tests/core/test_operation_control_r0008_control_update_runtime.py`;
- `.github/workflows/operation-control-r0008-control-update-runtime-gate-r0001.yml`.

The runtime is fixed to:
- predecessor r0005 source `08f2e211f53764590f6ff0f05f86b2de62c14418`, payload `6272afbe918d33c29a3f72354baca9e781b3960b3f0f465e1598b5bbc794a7e7`;
- successor r0008 source `20727893662cde92998d88ecdca730b69633eaaa`, payload `bc74c0e5b7eba90465fb8d59c5bb9a619ebc1f2c737c06fbf357ae062c5b374d`, size `428403`, files `217`;
- r0008 stage witness root and exact issued r0008 authority graph;
- canonical deterministic control-update transaction `83e20aeecd4ecd7a8288816065fa700ab3e99b8017177df215e18e03695d4e58`.

The runtime exposes only `reconcile` and `update`. It verifies exact old/new releases, exact r0008 stage witnesses, production-current identity, credential identity, idle operation/transport boundaries, read-only remote agent contract, systemd unit policy and exact control-boundary classification. A newly added transaction-ID assertion fails closed if the frozen updater derives anything other than the candidate receipt's canonical r0008 control-update identity.

The dedicated gate binds the runtime to the durable r0008 staged-release evidence and immutable candidate receipt, rejects stale r0007 successor identities, runs targeted regressions and proves the CLI/path/mutation surface remains narrow.

No real VPS/control/production/Hub/credential/Drive mutation is performed by this development commit.

Next: require exact-head Core + r0008 control-update-runtime gate PASS, then perform one real VPS `reconcile` only. Do not run `update` yet.

### D0-03C r0008 control-update clean prestate PASS

Real VPS read-only `operation_control_r0008_control_update_runtime.py reconcile` on exact branch tip `acb60bda9f7d81480b983495d3b7d627dd4332bf` returned the required clean prestate before the control-plane switch.

Verified:
- current control boundary is exact predecessor r0005: `OLD_EXACT`;
- old release is exact r0005 source `08f2e211f53764590f6ff0f05f86b2de62c14418`, payload `6272afbe918d33c29a3f72354baca9e781b3960b3f0f465e1598b5bbc794a7e7`;
- new staged release is exact r0008 source `20727893662cde92998d88ecdca730b69633eaaa`, payload `bc74c0e5b7eba90465fb8d59c5bb9a619ebc1f2c737c06fbf357ae062c5b374d`, size `428403`, files `217`;
- r0008 stage witness remains `STAGED_EXACT` with post-reconcile PASS;
- production current remains `releases/e63f371d14eb9b6069cb2f1b5fad5f4b68a49d4f`;
- credential SHA-256 remains `7002ed72a223dd7fc860451c53a4ec8f264d14f7144000559a295522b7cbe928`;
- canonical r0008 control-update transaction is `83e20aeecd4ecd7a8288816065fa700ab3e99b8017177df215e18e03695d4e58`;
- that transaction is `NEW`;
- update root is `PRESENT`, which is compatible with retained terminal history from the rejected r0007 transaction;
- control-update, production-current, legacy-Hub, credential and Drive mutation flags are all false.

Sanitized durable evidence: `docs/evidence/R0008_CONTROL_UPDATE_PRESTATE_20260924.json`.

The reconcile output contained no UTC observation timestamp, so none is invented.

Next transaction is exactly one r0008 control-update `update` invocation after this checkpoint itself passes exact-head CI. The qualified updater may switch only the D0 control plane from exact r0005 to exact r0008, including transaction authority, `control-current`, exact control-unit bytes and service restart/stability checks. Production `current`, legacy Hub, credential contents and Drive remain immutable boundaries. After any result or interruption, reconcile before any retry.

### D0-03D r0008 control update ROLLED_BACK_EXACT

The one permitted real r0005 -> r0008 D0 control update for transaction `83e20aeecd4ecd7a8288816065fa700ab3e99b8017177df215e18e03695d4e58` failed during successor service verification.

Observed failure:
- frozen updater reached `_verify_services()`;
- `active_probe(STATIC_UNIT)` called the legacy `systemctl is-active --quiet` wrapper for `keelaryn-production-snapshot@.service`;
- the wrapper returned a code outside its accepted inactive set and raised `ControlPlaneUpdateError: systemctl active-state probe failed`;
- the frozen updater then reported `D0 control update failed and rolled back exactly`.

Mandatory independent post-failure read-only reconcile on exact branch tip `4248a73be3f46329ad7dfc8d53cdb89d0cb65837` proved:
- control boundary `OLD_EXACT`;
- canonical r0008 control-update transaction is terminal `ROLLED_BACK_EXACT`;
- update root remains present;
- r0005 predecessor release remains exact;
- r0008 staged release and stage witness remain exact;
- production current remains `releases/e63f371d14eb9b6069cb2f1b5fad5f4b68a49d4f`;
- credential SHA remains exact;
- legacy Hub and Drive were not mutated.

Durable evidence: `docs/evidence/R0008_CONTROL_UPDATE_ROLLED_BACK_20260924.json`.

This transaction is terminal and MUST NOT be retried. r0008 is now rejected after exact rollback. The next objective is read-only diagnosis of the systemd static template-unit probe: capture the exact `systemctl is-active` return code/stdout/stderr and `systemctl show` state for `keelaryn-production-snapshot@.service` without changing any unit or runtime state. A fix, if required, must be frozen as a new successor candidate/version with a new control-update transaction identity.

### D0-03D rollback lifecycle fixture correction

Exact-head Core on the r0008 rollback checkpoint ran 866 tests and failed only two historical bootstrap-prep tests. Both called `operation_control_r0008_vps._recorded_boundary()` against the current authoritative DEVELOPMENT_STATE, where r0008 is now correctly terminal `REJECTED_AFTER_CONTROL_UPDATE_ROLLBACK_EXACT`. The production helper correctly failed closed with `r0008 transition qualification is not durably PASS`.

This checkpoint changes tests only:
- historical positive bootstrap-prep fixtures explicitly restore the historical `FROZEN_TRANSITION_GATE_PASS` lifecycle state inside a disposable repository fixture;
- the former current-state positive test now uses that historical fixture;
- a new regression asserts that the actual current rejected r0008 DEVELOPMENT_STATE is rejected by the retired bootstrap-prep path.

No r0008 product/runtime/candidate bytes are modified. The terminal rollback disposition and retry prohibition remain unchanged.

The first systemd diagnostic command also accidentally passed a literal backslash in the unit name (`keelaryn-production-snapshot\@.service`), so its rc=1/not-found output is not evidence for the original updater defect. The next VPS action remains read-only and must probe the exact frozen constant `keelaryn-production-snapshot@.service`.

### D0-03E r0008 systemd template-probe defect confirmed

Read-only diagnosis on exact rollback-safe state confirmed the r0008 control-update failure mechanism.

Environment:
- Ubuntu 24.04 systemd `255 (255.4-1ubuntu8.17)`;
- exact unit `keelaryn-production-snapshot@.service`;
- staged unit file present with SHA-256 `9a967b1571cebd48f8248ed5e572ccb6448d20d0ff0368f543c4e91fd45466b6`;
- `systemd-analyze verify` returns rc=0.

Observed bare-template behavior:
- `systemctl is-active --quiet keelaryn-production-snapshot@.service` -> rc=1;
- verbose `systemctl is-active` -> rc=1 with `neither a valid invocation ID nor unit name`;
- the updater's generic `_is_active()` accepts only rc 0/3/4 and therefore raises `systemctl active-state probe failed`.

This precisely matches the r0008 failure stack:
`operation_control_d0_update._verify_services -> active_probe(STATIC_UNIT) -> operation_control_plane_update._is_active`.

The staged template itself is valid; the defect is querying active-state on an uninstantiated bare systemd template as if it were a concrete service unit. The correct successor fix must be template-specific and fail closed. Do **not** globally reinterpret rc=1 as inactive, because that would weaken error detection for ordinary services.

After exact rollback, the installed successor template is absent as expected on r0005; this is not evidence of a missing staged file or rollback defect.

Durable evidence: `docs/evidence/R0008_SYSTEMD_TEMPLATE_DIAGNOSIS_20260924.json`.

The terminal r0008 transaction remains non-retryable. Next engineering objective is a new successor candidate/version with a template-appropriate inactivity verification, regression coverage for the observed systemd semantics, and a new control-update transaction identity.

### D0-03E r0009 successor fix implementation

A minimal successor fix is implemented in development only; frozen r0008 remains immutable and terminal-rejected.

Product change:
- generic `legacy._is_active()` is unchanged;
- persistent operation-control services continue to use the generic `active_probe`;
- the static snapshot template now uses a separate `template_active_probe`;
- its production default calls `systemctl list-units --type=service --state=active --no-legend --plain keelaryn-production-snapshot@*.service`;
- nonzero systemctl status or stderr fails closed;
- any returned active template instance blocks the control update;
- no active instances is the required outside-request state.

This avoids asking `systemctl is-active` for the uninstantiated bare template `keelaryn-production-snapshot@.service`, which Ubuntu 24.04 systemd 255.4 rejects with rc=1.

Regression coverage now proves:
- no-active-instance output is accepted;
- an active instantiated snapshot unit is detected;
- systemctl probe failure remains fatal;
- the generic active probe is never called with the bare template;
- an active template instance blocks successor verification.

No candidate receipt or authority is issued in this commit and no VPS/Drive mutation occurs. Next require exact-head Core/deterministic payload PASS; only then freeze a new r0009 candidate/version with new source/payload and control-update transaction identity.

### D0-03F r0009 candidate freeze

Frozen successor candidate issued:

- candidate: `operation-control-r0009-20260924-01`;
- frozen source: `e42a4f156abb048f5c8f0bd1884fcae51674a55f`;
- source tree: `4eccddde06351d91e9bb2dcffa37e77344651621`;
- payload SHA-256: `8592a314b084a2a1ccc1608168b3c0776cccb1277ffc049f42f3efd5291d4876`;
- payload size: `442514`;
- file count: `227`;
- source Core run: `35918927163`, 872 tests PASS;
- payload artifact: `10775714106`, ZIP SHA-256 `38cf9b06d1eb2edee742937ff73e2d16be7f0faee3c36126859f8ad34cf1c4d2`;
- deterministic r0005 -> r0009 control-update transaction: `24e9df7d9d305450acd11a8dc8f638769ad87444a9b5d16c8befed76a89c52ce`.

The frozen source is the parent commit; this freeze commit contains qualification metadata/harness/workflows only and does not alter product bytes.

New qualification:
- `operation-control-r0009-gate-r0001` rebuilds the frozen payload twice, runs the full frozen Core suite, verifies cross-user relay DAC, materialization, target-host validation, D0 control validation and the explicit template-probe fix contract;
- `operation-control-r0009-transition-gate-r0001` runs eight disposable transition/recovery scenarios;
- the transition harness universally fails if the generic active probe is ever called for the bare snapshot template;
- the eighth scenario forces an active snapshot instance and requires fail-closed exact rollback;
- the existing shared-outbox predecessor-relay scenario remains required.

r0007 and r0008 remain immutable terminal rejected evidence. No VPS, production current, Hub, credential or Drive mutation occurs during freeze.

### D0-03G r0009 candidate qualification checkpoint

Frozen `operation-control-r0009-20260924-01` is now durably recorded as `FROZEN_TRANSITION_GATE_PASS`.

Exact qualified identities:
- source `e42a4f156abb048f5c8f0bd1884fcae51674a55f`;
- tree `4eccddde06351d91e9bb2dcffa37e77344651621`;
- payload SHA-256 `8592a314b084a2a1ccc1608168b3c0776cccb1277ffc049f42f3efd5291d4876`;
- payload size `442514`;
- file count `227`;
- deterministic r0005 -> r0009 control-update transaction `24e9df7d9d305450acd11a8dc8f638769ad87444a9b5d16c8befed76a89c52ce`.

Qualification:
- candidate gate run `35960522322` PASS, artifact `10791109816`;
- transition gate run `35960522374` PASS, artifact `10792505159`;
- exact-head Core run `35960522210` PASS;
- transition qualification passed eight disposable scenarios, including active snapshot-template instance fail-closed exact rollback and shared-outbox predecessor-relay compatibility.

No production VPS, production current, Hub, credential or Drive mutation occurred.

Durable evidence: `docs/evidence/R0009_QUALIFICATION_20260924.json`.

Next objective is a **new r0009 production-prep chain**. Reuse of r0007/r0008 stage authority, witness roots, private-input transaction identity or control-update transaction identity is forbidden. First build and qualify r0009-specific read-only preparation/reconcile tooling in CI; only then obtain a fresh real-VPS read-only boundary before issuing any new stage authority.

### D0-03G isolated r0009 production-prep framework

Added seven r0009-only prep/qualification tools and six targeted regression modules, plus `operation-control-r0009-production-prep-gate-r0001`.

The framework is fixed to `operation-control-r0009-20260924-01`, source `e42a4f156abb048f5c8f0bd1884fcae51674a55f`, payload `8592a314b084a2a1ccc1608168b3c0776cccb1277ffc049f42f3efd5291d4876`, and future control-update transaction `24e9df7d9d305450acd11a8dc8f638769ad87444a9b5d16c8befed76a89c52ce`. It also requires the exact r0009 systemd template-probe defect-fix contract.

Current production-boundary state still cites canonical r0008 stage-boundary evidence after the exact r0008 rollback. r0009 therefore accepts r0007/r0008 stage-boundary schemas strictly as predecessor provenance while emitting only r0009 schemas and using only the r0009 authority namespace.

No r0009 authority is issued in this commit. r0007/r0008 authorities and transaction state are read-only historical evidence and are not imported or reused.

Next: require exact-head Core and r0009 production-prep gate PASS, then run one fresh real-VPS read-only r0009 reconcile. Canonical r0009 boundary capture remains a separate later transaction.

### D0-03G r0009 production-prep gate harness correction

The first r0009 production-prep gate run `35963547025` failed at its syntax-check step after:
- exact frozen r0009 candidate validation PASS;
- confirmation that no r0009 stage authority exists PASS.

The Python modules produced no syntax traceback. The failure came from `python -m py_compile` creating unignored `__pycache__/*.pyc` files, after which the gate's own `git status --porcelain` cleanliness assertion failed.

This correction changes **only** the workflow harness: the seven r0009 prep modules are now syntax-checked using Python's in-memory `compile()` over source text. No product/runtime/test file is changed. Exact-head Core run `35963546919` on the framework commit is PASS.

Next: require the corrected r0009 production-prep gate and exact-head Core to PASS. Only then perform one real-VPS read-only r0009 reconcile.

### D0-03H fresh r0009 live boundary reconcile PASS

After exact-head qualification of the corrected r0009 production-prep framework, one real VPS **read-only** `operation_control_r0009_vps.py reconcile` was executed on branch tip `c02b4bb308be131aded9f99a748c297869aff0f6`.

Verified live boundary:
- predecessor control candidate is `operation-control-r0005-20260921-01`;
- control source `08f2e211f53764590f6ff0f05f86b2de62c14418` and its 190-file payload are exact;
- production source remains `e63f371d14eb9b6069cb2f1b5fad5f4b68a49d4f`;
- operation agent and transport are ACTIVE, enabled and byte-exact to the predecessor release;
- writer is exact `INACTIVE / MainPID=0`;
- legacy Hub remains `PREPARED / OLD` with mutation-inhibit authority matching;
- credential SHA-256 remains exact;
- r0009 snapshot unit is `ABSENT`;
- `production_authorized=false`;
- production and Drive mutation flags are false.

Sanitized durable evidence: `docs/evidence/R0009_LIVE_BOUNDARY_RECONCILE_20260924.json`.

The reconcile emitted no timestamp, so this checkpoint does **not** replace the canonical timestamped `production_boundary` record in DEVELOPMENT_STATE. The next isolated development transaction is to add and qualify canonical r0009 boundary capture. Stage authority, private input and release staging remain forbidden until that boundary is captured and durably accepted.

### D0-03H r0009 canonical boundary-capture tooling

Added the pre-authority r0009 canonical boundary-capture surface:
- `tools/operation_control_r0009_boundary_capture.py`;
- `tests/core/test_operation_control_r0009_boundary_capture.py`;
- `.github/workflows/operation-control-r0009-boundary-capture-gate-r0001.yml`.

The implementation follows the original pre-authority r0008 boundary-capture model:
1. invoke only the qualified r0009 `vps.reconcile()` read-only boundary;
2. require exact candidate, no production authorization, no production/Drive mutation, legacy-Hub scope `RUNTIME_SAFETY_ONLY`, r0009 snapshot unit absent, writer inactive, and both persistent control units active/enabled/byte-exact;
3. add a UTC timestamp locally;
4. construct `keelaryn.operation-control-r0009-stage-boundary-evidence.v1`;
5. pass the result through the r0009 stage-authority boundary validator;
6. print canonical JSON only.

The dedicated gate requires that `docs/authorizations/operation-control-r0009-stage` is still absent, while retained r0007/r0008 authority roots remain historical evidence. It syntax-checks without residue, runs targeted regressions and rejects any write-capable surface.

No r0009 authority is issued and no VPS/Drive mutation occurs in this commit.

Next: require exact-head Core + boundary-capture gate PASS, then execute one real-VPS read-only `capture` and durably record its exact timestamped JSON before authority issuance.

### D0-03I canonical r0009 stage boundary committed

The real VPS read-only r0009 boundary capture emitted canonical authority-grade evidence observed at `2026-09-24T07:10:01Z`.

Committed evidence:
`docs/evidence/R0009_STAGE_BOUNDARY_20260924T071001Z.json`

Exact boundary:
- schema `keelaryn.operation-control-r0009-stage-boundary-evidence.v1`;
- conclusion `PASS`;
- production source `e63f371d14eb9b6069cb2f1b5fad5f4b68a49d4f`;
- control source `08f2e211f53764590f6ff0f05f86b2de62c14418`;
- legacy Hub `PREPARED / OLD`, transaction `61a2bfb65c9a47d088a76eee0df89d14`;
- writer `INACTIVE_MAINPID_0`;
- mutation-inhibit authority matches;
- credential SHA-256 `7002ed72a223dd7fc860451c53a4ec8f264d14f7144000559a295522b7cbe928`;
- legacy-Hub authority scope `RUNTIME_SAFETY_ONLY`;
- production and Drive mutation flags false.

This exact evidence now replaces the older r0008 boundary pointer in DEVELOPMENT_STATE as the current timestamped production boundary. It does not authorize staging or any production mutation.

Next objective: issue exactly one GitHub-only r0009 release-stage authority bound to this evidence after exact-head Core + r0009 prep + r0009 boundary gates PASS. VPS must remain untouched during authority issuance.

### D0-03I boundary checkpoint compatibility correction

The canonical r0009 boundary checkpoint exposed two expected lifecycle-qualification mismatches:

1. r0009 production-prep gate run `35968348607` passed candidate validation, authority absence and syntax checks, then failed because it still expected seven `operation_control_r0009_*.py` files. Boundary capture is now the eighth qualified prep tool.
2. Zero-based Core run `35968348460` ran 921 tests and failed only four retired r0008 bootstrap-prep tests. Those tests cloned the **current** DEVELOPMENT_STATE production-boundary pointer, which is now correctly r0009 schema, so the retired r0008 parser failed closed before reaching the historical assertions.

This correction is qualification/test-only:
- r0009 prep gate expects eight tools and syntax-checks `operation_control_r0009_boundary_capture.py`;
- historical r0008 fixtures explicitly pin `docs/evidence/R0008_STAGE_BOUNDARY_20260923T092708Z.json`;
- the r0008 rejected-lifecycle test uses that historical boundary while retaining the current rejected r0008 lifecycle token, so it continues testing the intended fail-closed reason.

No r0008/r0009 runtime tool, frozen candidate, VPS, authority, Hub, credential or Drive state is changed.

Next: require exact-head Core + r0009 prep gate + r0009 boundary gate PASS. Only then issue one GitHub-only r0009 release-stage authority.

### D0-03J r0009 stage authority provenance checkpoint

Exactly one r0009 release-stage authority has been issued and independently read back.

Authority:
- commit `f2dd7b8875d423a197c27642f8c4b1db8bbcf786`;
- transaction `92aea51ee7f80a8e8b84fffa9315bf9e`;
- path `docs/authorizations/operation-control-r0009-stage/92aea51ee7f80a8e8b84fffa9315bf9e.json`;
- Git blob `f903c62370dc27e3fb0264c56e6fc76e56f3afa3`;
- canonical SHA-256 `56c16168d4ad473757342251c2791fd148ef578630136f7626226425257b4919`;
- scope `R0009_RELEASE_STAGE_ONLY`.

Issuer checkpoint `86aa3a92f860d9ab96ad54c6d75f9adbcf723026` passed:
- Zero-based Core `35968684813`, 921 tests PASS;
- r0009 production-prep gate `35968684863` PASS;
- r0009 boundary-capture gate `35968684721` PASS.

The authority is bound to canonical boundary `docs/evidence/R0009_STAGE_BOUNDARY_20260924T071001Z.json`, blob `0d29ddb050143b953157e961e40d6c63d75df916`, SHA-256 `d6ea834ff31d9a5269cee573009c256f6871e437ba5635c8d047602d8b1f0117`.

Authorization permits release staging only. Activation, Drive, legacy Hub, writer and credential mutation remain explicitly denied. The issuance commit changed exactly one file. No VPS or Drive mutation occurred.

Next: build and qualify r0009-only private-input and stage-runtime tooling bound to this exact authority commit/blob/SHA/transaction. Do not reuse r0007/r0008 private roots or witnesses, and do not acquire/stage in the same transaction as tooling creation.

### D0-03J r0009 post-authority gate alignment

After the exact r0009 authority was issued and checkpointed, the two pre-authority qualification gates behaved fail-closed as designed:
- production-prep run `35969310183` passed candidate validation and failed only at `authority has not been issued`;
- boundary-capture run `35969310171` failed only at the equivalent pre-authority assertion;
- exact-head Core `35969310230` passed 921 tests.

This revision changes only those workflow lifecycle expectations. Both gates now require:
- exactly one r0009 authority JSON;
- transaction `92aea51ee7f80a8e8b84fffa9315bf9e`;
- canonical SHA-256 `56c16168d4ad473757342251c2791fd148ef578630136f7626226425257b4919`;
- exact candidate/source/payload/stage-only deny flags;
- issuer checkpoint `86aa3a92f860d9ab96ad54c6d75f9adbcf723026`;
- exact boundary blob/SHA provenance.

The production-prep artifact now records `r0009_authority_issued=true` and points next to private-input/stage-runtime qualification.

No runtime, frozen candidate or authority bytes change. No VPS/Drive mutation occurs.

Next: require exact-head Core + both aligned r0009 gates PASS. Only then create r0009 private-input/stage-runtime tooling in a separate transaction.
