# Zero-based Keelaryn — active development handoff

**Status:** volatile sanitized coordination state for `dev/zero-based-keelaryn`. Newer authoritative GitHub/VPS evidence supersedes this file.

## Authoritative development

- Repository: `efremov-aleksei-96/keelaryn`
- Branch: `dev/zero-based-keelaryn`
- Handoff base HEAD: `819dcbd11b531180763ddcf55d2273a8b6da1c5e`
- Base tree: `7e00fadba2aff9b40a941f68175af7275f208413`
- Development branch is unqualified by definition.
- Exact e63f source bytes currently materialized on production remain the production source authority; later development commits do not silently replace them.

## Closed source-release switch

Production source publication from OLD `3d3ea4a28aafd5915aed278307313c4b5ecaaf5e` to NEW `e63f371d14eb9b6069cb2f1b5fad5f4b68a49d4f` is terminally accepted.

Last confirmed boundary:

- release-switch status: `IDLE`
- terminal outcome: `ACCEPTED`
- current source: exact `e63f371d14eb9b6069cb2f1b5fad5f4b68a49d4f`
- NEW payload SHA-256: `e01763c03c94ef960187ad990c5fb5de91db3b0f956503bc04569c256b9e8bca`
- NEW payload size: `316120`
- NEW file count: `175`
- source transaction history identity: exact
- source active transaction: absent
- source mutation inhibit: absent

Do not rerun the completed source-switch transaction.

## r0072 frozen migration authority

- Candidate: `migration-r0072-20260919-01`
- Frozen candidate source commit: `001b7a655a5a0fb638e16acd056af3b94426a666`
- Frozen candidate source tree: `2138816f61f705cee83ae838783bb28cf4a8566c`
- Pack SHA-256: `82eda038bb2c424d44137e3bfa8174778ab8a24d49bcca253430cc1aea2bc21b`
- Freeze receipt SHA-256: `d469b6b5f20196445111da5b354284338ec4b3c9c4245d395e95b97115f1ff39`
- Production target authority SHA-256: `5ef842af448bbfba606abd4565c13f2c9a059a480ad0ad81cf9d688abe5fab10`
- Production qualification evidence SHA-256: `5fda3af50ab1e9f9fb2d53a93d163f97a2842383b1b0d6d2c635c49df0cc2346`
- Production target qualification: definitive PASS, `cutover_authorized=false`
- Frozen legacy migration-source identity SHA-256: `40907275bba002f58120cef28d8bf2c0950f6d69057075dbb632154075b21eb9`

Do not rerun definitive r0072 target qualification.

## Frozen Operation Control candidate

- Candidate: `operation-control-r0002-20260920-01`
- Frozen source commit: `a368cc85e799842a00c5c1c496614437aa7064f2`
- Frozen source tree: `7fc44142c83a4f9af3079ee9f801dfa232f38f98`
- Deterministic VPS payload SHA-256: `47f99b459a8582ff9bf20756ff4b088d083f66af5cdaf34b7ead4f7c8dafbb3b`
- Payload size: `342556`
- Payload file count: `188`
- Exact-head Core development validation: **PASS**, run `35530177965` (609 deterministic tests plus all payload/surface/rehearsal steps)
- Development payload artifact: `10611112366`, ZIP SHA-256 `b130e30302a78492ba958db678512cdd58c83797ca30aa427e4569cadadf0dfa`
- Candidate receipt: `docs/candidates/operation-control-r0002-20260920-01.json`
- State: **REJECTED_BEFORE_VPS_MATERIALIZATION**
- GitHub operation channel: Issue #65
- Rejection evidence: `docs/candidates/operation-control-r0002-20260920-01.rejection.json`

Candidate bytes remain immutable historical provenance. Focused post-gate review found a public-status-publication identity defect, so r0002 must not be reconciled/materialized/qualified/bootstraped on production. The rejected r0001 release already materialized on the VPS also remains historical provenance only.

## Operation Control r0002 gate r0004

- Frozen candidate: `operation-control-r0002-20260920-01`
- Frozen candidate source: `a368cc85e799842a00c5c1c496614437aa7064f2`
- Gate revision: `operation-control-gate-r0004`
- Qualification driver: `tools/operation_control_r0002_vps.py`
- Workflow: `.github/workflows/operation-control-r0002-gate.yml`
- GitHub gate run: `35531369705` — **PASS**
- Gate artifact: `10611566039`, ZIP SHA-256 `dcd4661c92167489c0dbdc2209ddfde151102364799a05bbe400dbd79ebac69d`
- Evidence: `docs/candidates/operation-control-r0002-20260920-01.gate-r0004-evidence.json`
- Historical state: **GATE_PASS**; candidate subsequently **REJECTED_BEFORE_VPS_MATERIALIZATION**
- r0002 release is not yet materialized on production.
- Rejected r0001 release remains historical provenance only and is explicitly validated by the r0002 VPS driver.
- Initial r0002 qualification requires `control-current`, credential, bootstrap root/receipt, and operation units all exact `ABSENT`.

Gate r0004 passed exact frozen-r0002 deterministic rebuild/selftest, but a later focused security review rejected r0002 before any r0002 VPS reconcile/materialization. Its gate evidence is historical only and no longer authorizes production use.

## Operation Control gate r0003

- Frozen candidate: `operation-control-r0001-20260920-01`
- Frozen candidate source: `98e76ffdcdbac09610f8b9a2b542f7e61e7dba61`
- Gate revision: `operation-control-gate-r0003`
- Gate source commit: `5c045556d95fc336467686201930478ab2fabd0e`
- GitHub gate run: `35519565229` — **PASS**
- Gate artifact: `10608062424`, ZIP SHA-256 `b0fbd41fbe1160e6bd1acecc0e807745f988117531297c12431136f6b8a6b825`
- Evidence: `docs/candidates/operation-control-r0001-20260920-01.gate-r0003-evidence.json`
- Historical state before rejection: **VPS_QUALIFY_PASS**; candidate subsequently **REJECTED_BEFORE_BOOTSTRAP**
- Production reconcile evidence: `docs/candidates/operation-control-r0001-20260920-01.vps-reconcile-r0003.json`
- Production materialization evidence: `docs/candidates/operation-control-r0001-20260920-01.vps-materialize-r0003.json`
- Production qualification evidence: `docs/candidates/operation-control-r0001-20260920-01.vps-qualify-r0003.json`
- Materialized release: exact frozen source `98e76ffdcdbac09610f8b9a2b542f7e61e7dba61`
- Materialized payload SHA-256: `b9f4022ddca38435e377ed08662d6cc7930655c828b861cdca980ba87f948c4b`
- Sidecar prestate: release `EXACT`; control selector/credential/bootstrap root/receipt/operation units all `ABSENT`
- Production boundary: exact `current=e63f`, Hub cutover `PREPARED`, writer `INACTIVE` before and after
- Qualification mutations: none; production current mutation: false; Hub cutover mutation: false; Drive mutation: false
- Qualification scope: **initial sidecar bootstrap only**

This r0001 qualification evidence is historical only. Post-qualification review rejected r0001 before bootstrap, so its prior qualification does not authorize any bootstrap action. Current work proceeds only from frozen r0002 after a new r0002-specific gate/production qualification cycle.

## Operation Control r0001 rejection

Frozen candidate `operation-control-r0001-20260920-01` is **REJECTED_BEFORE_BOOTSTRAP**.
The immutable release already materialized on the VPS is retained as rejected
provenance and must not be bootstrapped.

Post-qualification review found a bootstrap transaction blocker: a partially successful
`systemctl enable --now` could fail before the unit was added to the rollback list, and
the exception path used unchecked raw systemctl calls. That could leave an operation
service active after a reported bootstrap failure. The candidate also allowed its
nominal preflight to create private directories. No r0001 bootstrap was attempted;
`control-current`, credential, bootstrap receipt, and operation units remain absent at
the last authoritative VPS observation.

Successor development fixes rollback accounting/verification, makes preflight truly
read-only, uses exclusive no-overwrite publication, pins transaction-owned objects with
Linux `O_PATH|O_NOFOLLOW` descriptors through commit/rollback, fails closed on ambiguous
directory ownership, and decouples agent liveness from transport with `Wants=`.
Those successor bytes passed coherent exact-head development CI and are now frozen as
`operation-control-r0002-20260920-01`.

## Operation Control r0002 rejection

Frozen candidate `operation-control-r0002-20260920-01` is **REJECTED_BEFORE_VPS_MATERIALIZATION**.

Focused post-gate review found that response-loss recovery for GitHub status publication selected pre-existing status comments by request ID without binding them to the transport's publisher identity. Because Issue #65 is in a public repository, an unrelated commenter could pre-create a matching status marker/request ID and be adopted as publication state, causing false provenance or a persistent PATCH failure/transport restart loop. No r0002 VPS reconcile, materialization, qualification or bootstrap was attempted.

Successor development binds remote status recovery and create/update responses to an explicit status-publisher actor, uses a dedicated private operation-control credential directory, writes bootstrap files directly with exclusive no-overwrite final-path creation so a crash cannot strand an untracked token-bearing temp file, and makes systemd active-state probing fail closed on unclassified errors. A new candidate identity is required after coherent development PASS.

## Frozen Operation Control candidate r0003

- Candidate: `operation-control-r0003-20260920-01`
- Frozen source commit: `18885db5baa479fde080568b116ff32c0fead07a`
- Frozen source tree: `b77fe079e1ee55f1b9be20d6363ae8c063a8664e`
- Deterministic VPS payload SHA-256: `80050c8adda76080b91b5d71dd3ce75a6463ef189850e74dd144ff882035fee8`
- Payload size: `348890`
- Payload file count: `188`
- Exact-head development validation: **PASS**, run `35534261802`, 622 deterministic tests plus all CLI/payload/rehearsal steps
- Development payload artifact: `10612487237`, ZIP SHA-256 `1338c51d104c573fc258fff6820f818685352efc003ba773514a25d4853095d6`
- Candidate receipt: `docs/candidates/operation-control-r0003-20260920-01.json`
- Gate revision: `operation-control-gate-r0005`
- State: **REJECTED_AFTER_BOOTSTRAP_COMMIT_BEFORE_RUNTIME_ACCEPTANCE**
- GitHub operation channel: Issue #65
- Gate run: `35534742741` — **PASS**
- Gate artifact: `10612094272`, ZIP SHA-256 `022b010fb30739daf09f756166cb7733c6f9f3df17a4ffbf340d5c2404796c14`
- Gate evidence: `docs/candidates/operation-control-r0003-20260920-01.gate-r0005-evidence.json`

Focused post-PASS review found no successor product blocker. It did identify a gate-framework incompatibility in the historical r0002 driver: that driver still targeted the shared `/etc/keelaryn` credential directory and did not pass the now-required exact status-publisher actor. r0005 is therefore a new gate-framework revision, not a product-byte change. It binds qualification to frozen r0003, uses `/etc/keelaryn/operation-control`, passes the exact status actor, requires the rejected r0002 release to remain absent, and exposes transaction-safe bootstrap resume semantics for a previously reconciled interrupted bootstrap.

Candidate bytes are immutable from this issuance point. Development may continue only through a new successor candidate if frozen product bytes need to change.

### r0003 production read-only reconcile

Production read-only reconcile completed **PASS** against gate r0005.

- Evidence: `docs/candidates/operation-control-r0003-20260920-01.vps-reconcile-r0005.json`
- production current: exact `e63f371d14eb9b6069cb2f1b5fad5f4b68a49d4f`
- Hub cutover: `PREPARED`
- writer: `INACTIVE`
- r0001 rejected materialized release: exact historical provenance
- r0002 rejected release: `ABSENT`
- r0003 release: `ABSENT`
- `control-current`: `ABSENT`
- operation credential: `ABSENT`
- bootstrap root / transaction / receipt: all `ABSENT`
- operation-control units: both `ABSENT`
- persistent mutations: none
- Drive mutations: none

The before/after production boundary was identical.

### r0003 production materialization

Exact frozen r0003 materialization completed **PASS**.

- Evidence: `docs/candidates/operation-control-r0003-20260920-01.vps-materialize-r0005.json`
- Materialized source: `18885db5baa479fde080568b116ff32c0fead07a`
- Payload SHA-256: `80050c8adda76080b91b5d71dd3ce75a6463ef189850e74dd144ff882035fee8`
- Payload size: `348890`
- File count: `188`
- Python files compiled: `173`
- Release exact after validation: true
- production current mutation: false
- Hub cutover mutation: false
- Drive mutation: false
- post-materialization r0003 release: `EXACT`
- r0002 release: `ABSENT`
- `control-current`, credential, bootstrap root/transaction/receipt and both operation units: all `ABSENT`
- production boundary before/after: exact `e63f`, Hub `PREPARED`, writer `INACTIVE`

### r0003 production qualification

Read-only production qualification completed **PASS**.

- Evidence: `docs/candidates/operation-control-r0003-20260920-01.vps-qualify-r0005.json`
- exact materialized source/tree/payload: verified
- release remained exact: true
- Python files compiled: `173`
- r0001 rejected materialized predecessor: exact historical provenance
- r0002 rejected release: `ABSENT`
- `control-current`, credential, bootstrap root/transaction/receipt and both operation units: all `ABSENT`
- production boundary before/after: exact `e63f`, Hub `PREPARED`, writer `INACTIVE`
- persistent mutations: none
- production current mutation: false
- Hub cutover mutation: false
- Drive mutation: false
- post-qualification reconcile: unchanged

r0003 production qualification was valid for the attempted one-time sidecar bootstrap, but the candidate is now rejected after production bootstrap exposed a product defect. No Hub selector apply or mutation of `/opt/keelaryn/current` was authorized or performed.

### r0003 bootstrap failure and rejection

The bootstrap transaction committed its sidecar material, but the control plane did **not** become durably usable.

- Failure evidence: `docs/candidates/operation-control-r0003-20260920-01.bootstrap-failure-r0005.json`
- Rejection evidence: `docs/candidates/operation-control-r0003-20260920-01.rejection.json`
- r0003 release: `EXACT`
- `control-current`: `EXACT`
- credential: `PRESENT`
- bootstrap root / transaction / receipt: `PRESENT / PRESENT_SINGLE / PRESENT`
- both unit files: `EXACT`
- transport service: `failed`, enabled, `NRestarts=2`, `226/NAMESPACE`
- agent service: `failed`, enabled, `NRestarts=5`
- production boundary remains exact `e63f`, Hub `PREPARED`, writer `INACTIVE`
- production current mutation: false
- Hub cutover mutation: false
- Drive mutation: false
- Issue #65 remained empty

Confirmed blocker: the transport unit specifies `InaccessiblePaths=/run/keelaryn`; the qualified production host has no such path, so systemd fails namespace setup before the Python transport starts. The agent then fails because its transport inbox is unavailable. A second product defect is exposed by the same incident: bootstrap uses immediate `is-active` probes and can publish a completed receipt before a shortly-after-start sandbox failure becomes observable.

The token's validity is **unknown**, not failed: transport never reached the GitHub API. Do not retry r0003 bootstrap and do not edit the credential manually. Candidate r0003 is immutable rejected provenance.

Gate r0005 passed exact frozen-r0003 driver selftest and deterministic payload rebuild. This is gate qualification only, not production qualification. The next permitted boundary is a **read-only VPS reconcile**. It must prove the production `e63f` / Hub `PREPARED` / writer `INACTIVE` boundary is unchanged, rejected r0001 remains exact historical provenance, rejected r0002 was never materialized, and the r0003 sidecar prestate is safe before any materialization.

### Successor operation-control development after r0003 rejection

Exact-head development commit `047566c560dd79ca9efeeedf348468faba41e684`
completed Zero-based Core validation run `35536851066` **PASS**: 626 deterministic
tests, all CLI/rehearsal steps, deterministic payload materialization and target-host
validation passed. That commit fixes the missing `/run/keelaryn` systemd sandbox
dependency, adds a bootstrap stability/restart window before receipt publication, and
keeps the agent idle rather than exiting while the transport relay is not yet present.

The next development commit adds a product-shipped rejected-install recovery surface.
Recovery must retain the immutable r0003 release, prove the exact bootstrap
transaction by binding the credential hash to the transaction marker and receipt,
publish durable recovery PREPARED authority before any deletion, support restart-safe
partial cleanup, disable units before deleting their bytes, and preserve the production
`e63f + PREPARED + writer INACTIVE` boundary. Runtime state directories are deliberately
not deleted by this recovery transaction.

## Frozen Operation Control candidate r0004

- Candidate: `operation-control-r0004-20260920-01`
- Frozen product source: `819dcbd11b531180763ddcf55d2273a8b6da1c5e`
- Frozen source tree: `7e00fadba2aff9b40a941f68175af7275f208413`
- Deterministic VPS payload SHA-256: `d814b27f4fe7fa9ceb5271002fa17044f427cda1a58f4e554e5168f1a8b5aa89`
- Payload size: `361869`
- Payload file count: `190`
- Exact-head development validation: **PASS**, run `35538811327`, 640 deterministic tests plus all CLI/payload/rehearsal/target-host steps
- Development payload artifact: `10613144170`, ZIP SHA-256 `603fa307c1ce3478549a8c2c151140e2a05405cb665b27d3a909eb460b2348b1`
- Gate revision: `operation-control-gate-r0006`
- Qualification driver: `tools/operation_control_r0004_vps.py`
- Workflow: `.github/workflows/operation-control-r0004-gate.yml`
- State: **REJECTED_AFTER_BOOTSTRAP_ROLLBACK_BEFORE_RUNTIME_ACCEPTANCE**
- Gate run: `35539222639` — **PASS**
- Frozen focused regressions: `55` tests — **PASS**
- Gate artifact: `10613827353`, ZIP SHA-256 `9cddb43ae4df352f26b042503f94ea96f578e56be3adc94e8951dcf8647d4624`
- Gate evidence: `docs/candidates/operation-control-r0004-20260920-01.gate-r0006-evidence.json`
- GitHub operation channel: Issue #65

r0004 is the immutable successor to rejected r0003. Its product bytes add exact rejected-r0003 recovery, retain the rejected r0003 release as provenance, remove only transaction-owned sidecar bytes and the production-observed empty r0003 runtime directories, bind PREPARED recovery authority to exact filesystem paths, and fail closed on foreign runtime material. The r0003 credential is deleted as part of recovery and is not reused.

Bootstrap hardening requires systemd `Type=notify`: transport sends `READY=1` only after the supplied token authenticates as the exact status actor and the first live read of Issue #65 succeeds. Bootstrap then verifies stable service liveness/restart counts before writing its receipt. GitHub write permission remains a separate runtime acceptance property to be proved by the later Issue #65 `RUNTIME_SELFTEST`.

Production read-only runtime reconciliation before freeze proved the rejected r0003 runtime state is exact and disposable: `/var/lib/keelaryn-operation-transport` is empty mode 0700 under the keelaryn service identity; `/var/lib/keelaryn/operations` is empty root:root mode 0700; and `/var/lib/keelaryn/operation-control` contains only empty root-owned 0700 `processed/` and `rejected/`. No operation/user payload exists in those directories.

Candidate bytes are immutable from this issuance point. Gate/framework/evidence fixes may receive a later gate revision, but any frozen product-byte change requires a new operation-control candidate.

Gate r0006 passed; r0004 then completed production recovery, materialization and read-only qualification. Its first bootstrap attempt is rejected: transport authenticated the exact GitHub actor and completed the first live Issue #65 poll, but the capability-free root agent could not traverse the transport-owned 0700 relay and exited with permission denied before runtime acceptance. Bootstrap rollback removed transaction-owned unit/config/control-current material and wrote no bootstrap receipt, while systemd-created runtime directories remain as exact residue. r0004 must not be bootstrapped again.

## r0004 bootstrap rejection and successor development

- Rejection evidence: `docs/candidates/operation-control-r0004-20260920-01.rejection.json`
- Product blocker: cross-user relay DAC contract.
- Transport startup: **PASS** — authenticated `efremov-aleksei-96`, first Issue #65 poll succeeded.
- Agent startup: **FAIL** — permission denied on `/var/lib/keelaryn-operation-transport/inbox`.
- Bootstrap receipt: absent; runtime selftest: not attempted; Issue #65 status comments: none.
- Rollback removed credential, control-current and both installed operation unit files; services are inactive/not-found.
- Exact runtime residue remains: transport `inbox/outbox/state`, empty operation root, and operation-control `processed/rejected/LOCK`.
- Rejected r0004 release remains immutable provenance.

Successor development uses group-mediated DAC without restoring broad root capabilities: transport root `0750`, relay directories `0770`, relay files `0640`; both services use group `keelaryn`, while agent remains `User=root` with empty `CapabilityBoundingSet`. `RestrictSUIDSGID=true` remains enabled and the relay has no SGID dependency. Recovery gains a separate durable r0004 failed-bootstrap runtime-residue transaction with exact shape validation, PREPARED-before-delete authority, restart-safe partial cleanup and retained rejected release.

## Frozen Operation Control candidate r0005

- Candidate: `operation-control-r0005-20260921-01`
- Frozen product source: `08f2e211f53764590f6ff0f05f86b2de62c14418`
- Frozen source tree: `8b73bb1e19f554099c81374cb957c588f479d666`
- Deterministic VPS payload SHA-256: `6272afbe918d33c29a3f72354baca9e781b3960b3f0f465e1598b5bbc794a7e7`
- Payload size: `365052`
- Payload file count: `190`
- Exact-head Core validation: **PASS**, run `35564099444`, 643 deterministic tests plus cross-user DAC, CLI, rehearsal, deterministic payload/materialization and target-host validation
- Windows migration validation: **PASS**, run `35564099442`
- Development payload artifact: `10623295924`, ZIP SHA-256 `ed9cfe449d58f23094deb9647c5f12aff9299d8b3113615ad0caca5e7c45e1fd`
- Gate revision: `operation-control-gate-r0008`
- Qualification driver: `tools/operation_control_r0005_vps.py`
- Workflow: `.github/workflows/operation-control-r0005-gate.yml`
- State: **FROZEN_NOT_PRODUCTION_QUALIFIED — r0007 gate harness failed; r0008 pending**
- GitHub operation channel: Issue #65

The cross-user relay defect exposed by rejected r0004 is covered by an actual disposable Linux user boundary: transport runs as a non-root UID, agent retains UID 0 but all capability sets are zero, both share only the keelaryn GID, request/status files are mode 0640, relay directories are 0770, and terminal publication succeeds. `RestrictSUIDSGID=true` remains enabled; no SGID bit is required. The CI-only relay harness lives under `tests/ci` and is excluded from production payload bytes.

r0005 preserves the exact historical r0003 recovery authority:
- PREPARED SHA-256: `1a254b06fe3167e0b437b93606a37df14285e8ba3a167947824fc0b684a4468b`
- COMPLETED SHA-256: `eef349e2f6d7f12047212e221003341129294d44f5dc669f1579a4d13fb1bca4`

Before r0005 materialization, the r0005 driver requires a separate rejected-r0004 failed-bootstrap runtime-residue recovery transaction. It may remove only the exact production-observed r0004 runtime residue, must retain the immutable r0004 release, must coexist with and preserve the historical r0003 authority files, and must preserve the `e63f + PREPARED + writer INACTIVE` production boundary.

Candidate product bytes are immutable from this issuance point. A gate/evidence-only correction may receive a later gate revision, but any change to frozen product bytes requires a new candidate.

### r0007 gate execution failure

Gate r0007 run `35564710697` is preserved as failed qualification evidence. Driver SelfTest, exact frozen source/tree checkout and 58 focused frozen operation-control tests all passed. The cross-user step failed before invoking the frozen product because the shell referenced `FROZEN_COMMIT` without defining it in that step. Classification: **GATE_HARNESS**, not product failure. Frozen r0005 product bytes remain immutable and unchanged.

Gate r0008 changes only gate tooling/evidence: it binds the cross-user step to exact frozen source `08f2e211f53764590f6ff0f05f86b2de62c14418`. The historical r0007 workflow remains available only by manual dispatch and no longer runs automatically on successor gate metadata commits.

## Current production Hub-cutover transaction

The production Hub cutover has been prepared but the selector has **not** been applied.

Last confirmed durable boundary:

- framework source: exact production `e63f371d14eb9b6069cb2f1b5fad5f4b68a49d4f`
- cutover status: `PREPARED`
- transaction ID: `61a2bfb65c9a47d088a76eee0df89d14`
- active transaction SHA-256: `1d243586556019e132c454ebc8ccc252b755e5b43421434a6ff1eaf1c166ea34`
- active transaction: present, private mode 0600
- mutation inhibit: present, mode 0640, exact-bound to the active transaction
- writer service: inactive, MainPID 0
- selector: exact OLD, unchanged
- OLD selector identity SHA-256: `15370553b6732a11d4e0a9a8a02066c1c089d8b0f443001cc39fe39b201c8444`
- qualified NEW target identity SHA-256: `dffc1b46b44d951b498ee7d781f6b992f0dc6356cfb38eebadbee792a847db39`
- active runtime credential: unchanged; SHA-256 `8eb2e646c9215ff2261489369fe2866b19730255edb203cae0e4e2214721b682`
- staged qualification credential: exact private staged copy; SHA-256 `24f562a3eb5d4ea93a24162e8a65d182cc2ab4c4298f70da7866c446cc7018ed`
- credential activation: not performed
- pre-apply receipt: absent at last confirmed boundary
- post-cutover finalization receipt: absent at last confirmed boundary
- Drive mutations after PREPARED: none

Do not restart the writer, rerun `prepare`, manually edit the selector, activate the staged credential, or invoke raw selector apply.

## Last attempted read-only recovery

A read-only pre-apply input recovery failed while trying to recover the raw legacy migration-source Drive ID by scanning local candidate files for a token whose SHA-256 matched the frozen source identity.

Observed result:

`migration_source_private_binding=NOT_UNIQUE:0`

Classification: **read-only locator/evidence-wrapper defect**, not product failure, not r0072 failure, and not Hub-cutover transaction failure. The raw legacy Drive ID is not required to exist in local candidate files.

The failure occurred before pre-apply receipt publication or selector mutation. The previously confirmed PREPARED transaction remains the recovery anchor.

## Immediate engineering goal before production selector apply

The active first priority is the durable remote-autonomous operation control plane. GitHub Issue **#65, Keelaryn VPS Operation Control**, is the dedicated request/status channel. Development already includes Operation Runtime, the allowlisted network-isolated agent, and the narrow GitHub Issues transport.

r0003 remains immutable rejected provenance. Successor development is complete and frozen as r0004. The next production mutation is **not** materialization or bootstrap: after gate r0006 PASS and a fresh read-only VPS reconcile, run the r0004 driver's separate `recover-r0003` transaction. It must remove only the exact rejected sidecar/empty runtime state already observed on production, retain the r0003 release, preserve `/opt/keelaryn/current`, and leave durable COMPLETED recovery authority. Only then may r0004 materialization proceed.

Successor development after the r0002 rejection also hardens durable initialization and crash/replay recovery:
immutable terminal result authority can repair a state/handoff publication gap without
rerunning work; an agent restart terminalizes any surviving nonterminal operation as
`INTERRUPTED` (or `RECOVERY_REQUIRED` after an ambiguous mutation boundary); and
conflicting reuse of an already-processed request ID is quarantined rather than causing
a restart loop. Pre-state initialization orphans can be reclaimed only when no durable
authority exists and only exact runtime-generated state-staging filenames are present;
request archive directory boundaries are fsynced; and crash-torn trailing progress
fragments no longer poison status recovery. The bootstrap now carries a durable private
transaction-directory identity before any credential/unit publication, so a SIGKILL can
be resumed only under the exact source/payload/configuration/credential hash; partial
regular files are repairable only while operation-control units are inactive, an exact
completed receipt replay is read-only, and ambiguous material remains fail-closed.
The earlier 620-test run failure was a regression-harness Path-concatenation typo, not a
product failure; that typo was removed. Successor CI run `35534113522` then executed 622
deterministic tests: the new bootstrap crash-recovery regression passed, while exactly two
runtime/agent initialization-recovery tests failed from one newly introduced recognizer
defect — the raw-string staging regexp used doubled backslashes and therefore rejected the
legitimate `.state.json.new-<pid>-<32hex>` form. No other deterministic failure was reported.
The recognizer escape is corrected in the successor commit; bytes remain unqualified until
that exact HEAD completes coherent CI PASS.

The overall objective remains a durable **Operation Runtime v1** so long-running and mutation-capable operations do not depend on ChatGPT streaming, PowerShell, SSH session lifetime or one conversation's memory.

Required v1 capabilities:

- server-side durable operation directory and state machine;
- sanitized append-only progress journal with heartbeat;
- detached execution suitable for systemd/transient service operation;
- `status` and `watch` CLI surfaces;
- explicit mutation states and recovery-required semantics;
- hard timeouts/stall detection without blind mutation retry;
- durable result/evidence files;
- automatic sanitized handoff/checkpoint generation;
- regression coverage;
- inclusion in deterministic VPS payload and target-host CLI validation.

Existing `core/keelaryn_core/gate_progress.py` is reusable infrastructure and should be extended/composed rather than replaced casually.

## Remote-autonomous working rule

Normal development from this point is GitHub-first and should be performed by ChatGPT directly on `dev/zero-based-keelaryn`, with GitHub Actions used for disposable validation and diagnosis. Connected Google Drive may be used directly when authoritative Drive evidence is needed.

The maintainer should be asked to execute a local/VPS command only when evidence or a state transition inherently depends on the actual production VPS/workstation and no connected execution path is available. Keep such requests to one coherent action.

## Next permitted sequence

1. Run and review Source/Full Gate `operation-control-gate-r0008` against immutable frozen r0005.
2. If gate r0008 PASS, fresh production read-only reconcile must prove: production `e63f + PREPARED + writer INACTIVE`; rejected r0004 release exact; r0004 transaction-owned sidecar absent; exact known runtime residue present; historical r0003 recovery authority hashes unchanged.
3. Run `recover-r0004` as one separate production mutation and read-only verify durable COMPLETED failed-bootstrap authority plus preserved r0003 authority.
4. Materialize exact frozen r0005 as a separate production transaction.
5. Run read-only production qualification.
6. Bootstrap r0005 as a separate transaction with explicit token input; do not inherit any rejected-candidate credential.
7. Prove end-to-end `RUNTIME_SELFTEST` through Issue #65, including actual status comment write permission.
8. Only after runtime acceptance reconcile the still-PREPARED Hub transaction before any Hub selector mutation.

Do not retry r0004 bootstrap. Do not rerun r0007 automatically. If any durable state differs, stop and reconcile before mutation.

## 2026-09-21 autonomous remote-operation continuation

This section supersedes older development-next-step text above when the two conflict.
Always reconcile the authoritative remote branch before any write.

### Development authority at section creation

- Repository: `efremov-aleksei-96/keelaryn`
- Branch: `dev/zero-based-keelaryn`
- Pre-write authoritative HEAD: `b914812fe9d2c02185ebe12197128613d4075815`
- The commit containing this section is the immediate successor development commit; after opening a new chat, read the branch HEAD rather than assuming the pre-write SHA is still current.
- Branch remains explicitly **unqualified development**.

### Production boundary — do not infer newer state without VPS evidence

Last durable production facts carried forward:

- production `/opt/keelaryn/current`: exact `e63f371d14eb9b6069cb2f1b5fad5f4b68a49d4f`
- Hub cutover transaction: exact `PREPARED`, transaction `61a2bfb65c9a47d088a76eee0df89d14`
- ACTIVE_TRANSACTION SHA-256: `1d243586556019e132c454ebc8ccc252b755e5b43421434a6ff1eaf1c166ea34`
- selector remains OLD; writer remains inactive; mutation inhibit remains present/exact
- installed Operation Control remains immutable r0005 source `08f2e211f53764590f6ff0f05f86b2de62c14418`
- no development commit in this continuation has mutated VPS production, Hub selector, Drive content or r0005
- frozen r0072 migration candidate remains authoritative; do not rerun definitive qualification
- legacy migration-source raw identity is private; only its approved SHA-256 `40907275bba002f58120cef28d8bf2c0950f6d69057075dbb632154075b21eb9` may appear in public/sanitized evidence

### Remote-operation successor development

Goal: remove routine manual SSH/PowerShell from production administration. One bootstrap/update action may still be required to move installed r0005 to the first mutation-capable successor; after that, Hub stages should be driven through strict GitHub Operation Control.

Development history:

- `a6f92aa492b79cbc64baa5ef106d31021f2e792d`: fixed the first HUB_PRE_APPLY handler defect; Core run `35580495127` PASS.
- `c064bc67767ca4f25d36c4c7bb93529ecc6d5fd8`: added root-private exact mutation preauthorization; Core run `35581062210` PASS.
- `b914812fe9d2c02185ebe12197128613d4075815`: added transactional control-plane updater and updater tests.
  - Migration Windows run `35581631951`: PASS.
  - Core run `35581632045`: FAIL in one rollback regression only.
  - Failure classification: **TEST_HARNESS**. The injected agent-start failure repeated during rollback, intentionally making exact rollback impossible; product correctly failed closed with read-only reconciliation required.
- Focused review after that run found two real updater hardening requirements:
  1. after transport/agent stop and immediately before first successor publication, freshly revalidate inbox/runtime and exact predecessor production/control/unit/credential boundaries;
  2. rollback must prove successor persistent services are stopped before restoring predecessor bytes.
- The immediate successor commit containing this handoff implements those hardenings and changes the regression injection to a one-shot successor-start failure.

### Current safety model

- `HUB_PRE_APPLY` is mutation-capable and requires a private mode-0600 preauthorization profile.
- GitHub/transport cannot choose raw command, filesystem path, Drive ID, target identity or transaction identity.
- Preauthorization binds the exact successor control source, operation/profile token and already-durable Hub/migration authorities.
- Agent is network-isolated; transport is unprivileged/network-capable.
- Hub pre-apply worker is a fixed static oneshot and must not be persistently enabled.
- Any ambiguity at/after `COMMITTING` requires read-only reconciliation; never blindly repeat the mutation.
- Control-plane updater must preserve the existing GitHub credential byte-for-byte and must not mutate production `current`, Hub selector or migration state.

### Next goal after restoring context

1. Read authoritative `dev/zero-based-keelaryn` HEAD and CI associated with the commit containing this section.
2. If CI fails, classify product vs harness before changing bytes.
3. Reach coherent development PASS for the transactional updater.
4. Add/build a sanitized deterministic preauthorization-profile generator so the maintainer never handles a raw Drive ID or long VPS parameter list.
5. Freeze a new immutable Operation Control successor candidate only after coherent PASS; then run candidate gate/production-specific qualification.
6. Perform at most one minimal manual r0005 -> successor installation/update action.
7. Thereafter submit `HUB_PRE_APPLY` remotely, reconcile APPLIED, then separately implement/qualify and invoke post-cutover acceptance and writer-start operations.

Never resurrect the previously supplied large manual HUB PRE-APPLY PowerShell block.

### 2026-09-21 crash-safe successor activation

Pre-write authority: `2791192bdcb581b585e7143801d459d99f911c51`.
The successor commit containing this section changes control update recovery and mutation activation:

- PREPARED + exact OLD can resume even if a crash already stopped persistent operation services.
- PREPARED + exact NEW is recovery-terminalized by quiescing/restarting/stability-checking exact successor bytes; publication is not replayed.
- mixed/unknown boundaries remain read-only-reconcile only.
- rollback overwrites state only after proving every mutable object is exact OLD/NEW transaction-owned.
- `hub-pre-apply-profile.json` is no longer sufficient to authorize mutation.
- a root-private `hub-pre-apply-activation.json` binds successor source, profile SHA-256, update transaction and COMPLETED authority hash.
- activation is published only after durable control-update COMPLETED; agent and worker both require it.
- if only activation publication is interrupted after COMPLETED, replay may restore that exact activation without repeating the update.

Before any later write, reconcile the authoritative branch HEAD and its CI. Production remains untouched by this development commit.

### 2026-09-21 initial-authority ordering and crash regressions

Pre-write authority: `3bfc31e86e440377db66a3e7f27d0621b95a4e9b`.
Core run `35590413595` executed 656 deterministic tests; 655 passed and the only failure proved a product transaction-order defect: the updater created `operation-control-updates/` before the initial pending-request/runtime preflight.

The successor commit containing this section moves all first-time update-root/transaction creation until after initial runtime, inbox, OLD live-boundary, active-service and enabled-service validation. Existing durable PREPARED authorities remain readable for crash recovery without requiring predecessor services to have remained active.

Permanent regressions now cover:

- pending transport request before first update: zero update transaction material;
- PREPARED + OLD_EXACT with persistent services already stopped: safe resume to exact successor;
- PREPARED + NEW_EXACT with services inactive: terminalize/stability-check without republishing qualified bytes;
- PREPARED + mixed/unknown bytes: fail closed with no overwrite, no terminal and no activation.

After context loss, read authoritative branch HEAD and its CI before any write. Production/VPS/Hub/Drive remain untouched by this development work.

### 2026-09-21 activation-to-COMPLETED authority binding

Pre-write authority: `40f84f491ebaede105aa6f310d1aa3d7a971263b`; Core run `35590802866` PASS.

The successor commit containing this section makes `HUB_PRE_APPLY` activation depend on the durable control-update terminal authority itself. Agent and worker resolve `operation-control-updates/<activation transaction>/COMPLETED.json` and require exact owner/mode, canonical schema/keys, success semantics, transaction identity and the SHA-256 recorded by activation. Tampered/missing/replaced terminal authority blocks mutation before worker execution. No new transport parameter or write permission is introduced.

Production/VPS/Hub/Drive remain unchanged. Reconcile authoritative branch HEAD and CI before any later write.

### 2026-09-21 reusable successor upgrade engine

Pre-write authority: `5ef961c5ce0c136757026477c2f2579be07b0870`; Core run `35591236803` PASS.

The successor commit containing this section adds `deploy/zero-based-vps/operation_control_successor_upgrade.py` as a reusable engine; it does **not** freeze or issue a successor candidate.

Design:

- a later frozen wrapper supplies exact predecessor/successor source/tree/payload identities and the migration-source identity hash;
- source is fetched by exact commit and tree, payload is rebuilt twice and must be byte-identical to the frozen payload identity;
- an existing materialized successor is accepted only after exact release verification;
- the production `current` release and Hub cutover must still be exact PREPARED;
- r0072 pack/freeze/target/qualification/credential authorities are re-read privately and cross-bound;
- legacy source is resolved only through exact-case logical Drive path `My Laptop/0__Core/keelaryn/hub`, then its opaque ID hash must equal the frozen migration-source identity and the live source set is freshly verified against `MIGRATION_SOURCE`;
- the raw Drive ID exists only in process/private profile bytes and is never returned in sanitized result;
- a candidate-side private profile is create-once/verify-exact and by itself does not authorize mutation;
- only the exact successor release's transactional updater may install the profile and publish activation after COMPLETED.

Next: wait for coherent Core/Windows development PASS, then focused review this engine and add the frozen candidate wrapper/gate only after the successor source bytes are ready. Production/VPS/Hub/Drive remain unchanged.

### 2026-09-21 successor engine authority hardening

Pre-write authority: `e14312818a868e673a2df49f14df004f48f80b90`.
Migration Windows run `35591683874` PASS. Core run `35591683870` failed before executing the new engine tests because the dynamic test loader omitted `sys.modules` registration required by Python 3.12 dataclass processing; this is classified **TEST_HARNESS**, while the other 660 tests passed.

The successor commit containing this section:

- fixes the dynamic test loader registration;
- stabilizes production PREPARED authority with two status observations and two exact ACTIVE_TRANSACTION reads, requiring identical status, bytes, parsed authority and production-current symlink;
- parses target authority and target qualification using strict duplicate-key rejection, exact schema/key sets and canonical JSON bytes;
- requires qualification `cutover_authorized=false`;
- publishes the private staged profile through same-directory create-once staging, file fsync, no-replace publication and directory fsync;
- adds regressions for noncanonical/extra target-authority JSON, PREPARED authority drift and create-once private profile publication.

Production/VPS/Hub/Drive remain unchanged. Before any later write, reconcile authoritative branch HEAD and CI.

### 2026-09-21 library-only validator contract and early successor preflight

Pre-write authority: `a019d7f1ce7ac51399e1ed7cc0a20accc713c54d`.
Core run `35592117877` passed deterministic tests, relay, all CLI smokes and Hub rehearsal, then failed only in deterministic payload proof because `target_host_validate.py` treated the library-only successor upgrade engine as a CLI surface and invoked `py_compile` inside the immutable materialized release. This is classified **DEVELOPMENT_VALIDATOR_CONTRACT**; release determinism itself had already passed.

The successor commit containing this section:

- removes `operation_control_successor_upgrade.py` from target-host CLI surfaces; the workflow still compiles it before materialization, and target-host validation still read-only compiles every Python source with built-in `compile()` without bytecode writes;
- adds a regression proving the upgrade engine remains a library-only surface;
- adds an early read-only successor-upgrade preflight before source fetch/materialization or Drive work;
- the preflight requires production writer exact `inactive/MainPID=0`, canonical `control-current -> releases/<old source>`, exact predecessor transport/agent unit bytes, and absence of successor worker/profile/activation;
- this fail-fast layer does not replace the transactional updater's fresh commit-boundary validation.

Production/VPS/Hub/Drive remain unchanged. Reconcile authoritative branch HEAD and CI before any later write.

### 2026-09-21 r0006 candidate freeze

Development-coherent source before issuance:

- source commit: `b371a9b9f28fe668cc8073019a3d5f352f9d9bf3`
- source tree: `1e3a80f76283fb0800bb6e9d09202f6ab6755c5b`
- deterministic payload SHA-256: `0d2201e94a75f8622b40118d93b9eee9064ebe6650d3140e73997aed92c8c3cd`
- payload size: `393732`
- file count: `199`
- Core run `35592732039`: SUCCESS, 672 tests PASS
- Hub rehearsal artifact `10635575175`, ZIP SHA-256 `df8a4089ef87c1c65fbe4a1ec3655d51ead98f4d76bcf63fd82b55c839bfcbe7`
- VPS payload artifact `10635425517`, ZIP SHA-256 `73ee1e20e5d29554c9f6746538ab1cf2a1244434929c8c0b5d8c9ee3d037d628`

The commit containing this section **issues and freezes** `operation-control-r0006-20260921-01`. Candidate product bytes are the exact earlier source commit above and are immutable from this point. This issuance commit contains only qualification/provenance tooling; changing those files does not change frozen r0006 product bytes.

New production driver: `tools/operation_control_r0006_vps.py`.

- `reconcile`: read-only exact production/r0005/r0072 boundary reconciliation.
- `qualify`: read-only production qualification; rebuilds exact frozen source/payload and invokes frozen engine boundary verification without Drive mutation.
- `upgrade`: re-runs qualification first, then freshly fetches the same frozen source and invokes its exact transactional successor engine. It is the intended single short manual r0005 -> r0006 transition command after gate/production acceptance.
- driver pins PREPARED transaction identity/SHA, OLD/NEW selector identity hashes and all critical r0072 authority/credential hashes.
- raw Drive IDs are never emitted in sanitized driver results.

Initial candidate gate revision: `operation-control-gate-r0009`, workflow `.github/workflows/operation-control-r0006-gate-r0009.yml`.

No production/VPS/Hub/Drive mutation was performed by candidate issuance. Next: read the automatic r0009 gate result. Do not alter frozen product bytes; if product bytes must change, issue r0007. If only gate/evidence must change, issue a new gate revision for the same r0006 candidate.

### 2026-09-21 r0006 gate r0010 after r0009 harness failure

Authoritative pre-write HEAD: `3e41e00da1f9eafb259c35eca4298b373c66da06`.

r0009 run `35593516119` is preserved as **GATE_HARNESS** failure. Exact frozen r0006 source/tree/payload were unchanged. The following passed before the failed step: qualification-driver selftest, exact frozen checkout, 86 focused operation tests, 12 target-host tests, capability-free cross-user relay DAC, and deterministic frozen payload rebuild.

The failing run block contained unescaped shell grouping parentheses in a `find` command. Bash rejected the complete `Materialize and validate frozen r0006 release` block at parse time, so neither materialization nor target-host validation from that block is claimed as executed. Product bytes were not implicated.

The commit containing this section issues gate revision `operation-control-gate-r0010` only. Frozen candidate remains exactly `operation-control-r0006-20260921-01` at source `b371a9b9f28fe668cc8073019a3d5f352f9d9bf3`. r0010 replaces the invalid shell residue scan with a read-only Python filesystem scan; no frozen product, production driver, production/VPS/Hub/Drive state is changed.

Next: read automatic r0010 gate result. If r0010 fails, classify before any change; do not alter frozen r0006 product bytes unless a genuine product defect is proven.

### 2026-09-21 r0006 gate r0011 production-driver filesystem contract

Pre-write authority: `23c8b12dd781db0d6afda73f9ce416bfbf10855b`.

r0010 run `35593775552` completed SUCCESS. Evidence artifact `10635907150` ZIP SHA-256 is `8abd4a4e04e5acc48d3516f609c1a1b6e444037bb718213e34185ed8766d787a`. r0010 proved the exact frozen r0006 product bytes, focused tests, relay DAC, deterministic rebuild, materialization and target-host validation.

A subsequent production-readiness review found a **qualification-driver-only** filesystem contract defect: the candidate-specific r0006 driver used the private-output mode-0600 validator for `qualification-input/pack/PACK_MANIFEST.json` and `qualification-input/pack/authority/MIGRATION_SOURCE.json`. Those two files are immutable pack inputs, not private credential/authority outputs; the frozen product engine itself correctly verifies pack semantics/content without requiring mode 0600.

The commit containing this section issues gate revision `operation-control-gate-r0011` only. Frozen r0006 product source remains exactly `b371a9b9f28fe668cc8073019a3d5f352f9d9bf3`. Driver semantics are now:

- private freeze/target/qualification/credential files: root-owned regular exact mode 0600;
- immutable pack manifest/source manifest: root-owned regular non-symlink, not group/world writable, plus exact pinned SHA/pack verification;
- symlink or group/world-writable pack inputs fail closed.

r0011 adds an explicit gate regression for this distinction and reruns the complete frozen r0006 gate. No production/VPS/Hub/Drive mutation occurred. Do not run production `qualify` until r0011 is PASS.

### 2026-09-21 r0006 gate r0012 after production read-only reconcile

Authoritative pre-write HEAD: `eb2c4f65990150b00e1f35711e10f553e40364b9`.

r0011 run `35594376690` completed SUCCESS. Its evidence artifact is `10636186650`, ZIP SHA-256 `49960baf1384b6544a1de7a4a83ea3fd3572e15191be87709dbcc56215a2c498`, evidence JSON SHA-256 `83882dcbd87563a2b55f835bd338f9b8ccb8f729a4ec63eb7b5f5a37448c2eed`.

The first production-specific command under r0011 ran `reconcile` only and failed closed with `ERROR: r0072 pack manifest cannot be inspected`. `qualify` never started and no production/control/Hub/Drive mutation occurred.

Exact frozen source review proved this was a **PRODUCTION_QUALIFICATION_DRIVER** defect, not r0072/product state:

- frozen migration contract defines `MIGRATION_PACK_NAME = "MIGRATION_PACK.json"`;
- `MigrationPack.pack_sha256` is SHA-256 of the canonical `MIGRATION_PACK.json` bytes;
- there is no `PACK_MANIFEST.json` contract and no embedded `pack_sha256` field.

The commit containing this section issues gate revision `operation-control-gate-r0012` only. Frozen r0006 product remains exact source `b371a9b9f28fe668cc8073019a3d5f352f9d9bf3`.

r0012 driver now reads `qualification-input/pack/MIGRATION_PACK.json` as an immutable pack file and requires its raw-byte SHA-256 to equal the pinned r0072 pack SHA. The gate regression constructs an r0072-like filesystem with the real filename/layout, proves successful `_migration_anchor()`, then proves a legacy/wrong `PACK_MANIFEST.json` path is rejected.

Do not rerun production qualification until r0012 PASS. Production state remains PREPARED/r0005 with writer off; no durable production mutation was attempted by the failed r0011 reconcile.

### 2026-09-21 r0006 production qualification PASS

Production-specific read-only execution under gate revision `operation-control-gate-r0012` completed successfully.

Observed:

- `reconcile`: PASS;
- `qualify`: PASS;
- candidate: `operation-control-r0006-20260921-01`;
- frozen product source/tree: `b371a9b9f28fe668cc8073019a3d5f352f9d9bf3` / `1e3a80f76283fb0800bb6e9d09202f6ab6755c5b`;
- payload: SHA-256 `0d2201e94a75f8622b40118d93b9eee9064ebe6650d3140e73997aed92c8c3cd`, size `393732`, files `199`;
- control boundary: exact r0005 predecessor; successor worker/profile/activation absent;
- production Hub transaction remains exact PREPARED `61a2bfb65c9a47d088a76eee0df89d14`;
- writer remains exact `INACTIVE_MAINPID_0`;
- all pinned r0072 authority/credential/source hashes match;
- production boundary before qualification equals production boundary after qualification;
- persistent mutations: false;
- Drive mutations: false.

Production qualification evidence is stored in `docs/candidates/operation-control-r0006-20260921-01.production-r0012-pass.json`.

The candidate is now production-qualified for the next action reported by the driver: `UPGRADE`. The control-plane upgrade has **not** been executed. Treat it as a separate human-approved production mutation transaction. Before that mutation, reconcile authoritative GitHub state and use the exact r0012 driver; after any interruption, reconcile production before considering retry.

### 2026-09-21 r0006 gate r0013 after first upgrade attempt

Authoritative pre-write HEAD: `b4ef7b10d9a0a83f1f370a8fceff37829c6586a1`.

The first r0012 production `upgrade` attempt did **not** enter the transactional updater. Frozen engine sequencing proves the successor release was materialized first, then profile construction failed while resolving the legacy Drive source. Post-failure read-only reconcile proved:

- `control-current` remains exact r0005;
- successor worker/profile/activation are absent;
- operation-control update root is absent/empty;
- production Hub remains PREPARED and writer remains inactive;
- no Drive mutation occurred.

Read-only Drive diagnosis found the exact legacy `hub` by its frozen identity SHA-256 and confirmed the logical chain `My Laptop -> 0__Core -> keelaryn -> hub`. The root cause is namespace topology: `My Laptop` is a parentless Google Drive **Computers** root, not a child of ordinary My Drive alias `root`. Raw Drive IDs are not stored in repository evidence.

A later diagnostic command imported `materialize_payload.py` directly from the immutable release without Python `-B`, creating exactly one extra directory/file:

- `deploy/zero-based-vps/__pycache__` mode 0755;
- `deploy/zero-based-vps/__pycache__/materialize_payload.cpython-312.pyc` mode 0644.

No expected file/directory is missing, release identity remains exact, root mode is 0555 and there are no symlinks. This is classified **DIAGNOSTIC_INDUCED_RELEASE_CONTAMINATION**, not product/materialization failure.

The commit containing this section issues gate revision `operation-control-gate-r0013` only; frozen r0006 product bytes remain source `b371a9b9f28fe668cc8073019a3d5f352f9d9bf3`.

r0013 production-driver changes:

- a strict candidate-side Drive adapter performs one global read-only exact-name folder search for parentless `My Laptop` and exposes only that item as the frozen resolver's synthetic `root` child;
- all later path traversal remains the frozen exact-case resolver and ends with the frozen source-root identity SHA plus complete two-pass `MIGRATION_SOURCE` verification;
- production `qualify` now performs this live Drive source probe, so resolver/source failures cannot first appear during mutation;
- `upgrade` injects the same adapter into the frozen engine through its existing `drive_factory` seam;
- new `repair-release` is a separate production mutation surface. It rebuilds/materializes an exact disposable reference, permits only the exact proven diagnostic residue, removes only those two objects, then requires full byte/mode equality to the reference. It does not alter control-current/Hub/Drive.

Do not run repair or upgrade until r0013 gate PASS and a fresh production read-only r0013 `reconcile + qualify` PASS. Cleanup and upgrade remain separate transaction boundaries.

