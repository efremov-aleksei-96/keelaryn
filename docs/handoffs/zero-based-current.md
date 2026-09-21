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

Successor development uses group-mediated DAC without restoring broad root capabilities: transport root `0750`, relay directories `2770`, relay files `0660`; both services use group `keelaryn`, while agent remains `User=root` with empty `CapabilityBoundingSet`. Recovery gains a separate durable r0004 failed-bootstrap runtime-residue transaction with exact shape validation, PREPARED-before-delete authority, restart-safe partial cleanup and retained rejected release.

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

1. Read-only confirm authoritative GitHub identity before every repository write.
2. Validate successor relay DAC and exact r0004 failed-bootstrap residue recovery on GitHub.
3. Do not retry r0004 bootstrap.
4. After coherent successor development PASS, freeze a new operation-control candidate; r0004 remains immutable rejected provenance.
5. Source/Full Gate the successor candidate.
6. Fresh production read-only reconcile must prove r0004 transaction sidecar remains absent, rejected r0004 release is exact, and only the known runtime residue remains.
7. Run the dedicated failed-bootstrap runtime-residue cleanup as one separate production transaction and verify durable COMPLETED authority.
8. Materialize, qualify and bootstrap the successor as separate boundaries.
9. Prove `RUNTIME_SELFTEST` end-to-end through Issue #65.
10. Reconcile the still-PREPARED production Hub transaction before any later Hub mutation.

If production durable state differs, stop and reconcile before mutation.
