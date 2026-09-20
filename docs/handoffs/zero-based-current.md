# Zero-based Keelaryn — active development handoff

**Status:** volatile sanitized coordination state for `dev/zero-based-keelaryn`. Newer authoritative GitHub/VPS evidence supersedes this file.

## Authoritative development

- Repository: `efremov-aleksei-96/keelaryn`
- Branch: `dev/zero-based-keelaryn`
- Handoff base HEAD: `ad5f12f33eb047f24fd92393fc8ac77c6f616623`
- Base tree: `6a1f455d5e233df3df7563d4b6f8ad86770c5480`
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

- Candidate: `operation-control-r0001-20260920-01`
- Frozen source commit: `98e76ffdcdbac09610f8b9a2b542f7e61e7dba61`
- Frozen source tree: `eabd2a98e9c2d42e81e7f5c04e3f2b90cf900e6a`
- Deterministic VPS payload SHA-256: `b9f4022ddca38435e377ed08662d6cc7930655c828b861cdca980ba87f948c4b`
- Payload size: `340331`
- Payload file count: `188`
- Exact-head Core development validation: PASS, run `35518260534`
- Candidate receipt: `docs/candidates/operation-control-r0001-20260920-01.json`
- State: **FROZEN_NOT_PRODUCTION_QUALIFIED**
- GitHub operation channel: Issue #65

Candidate bytes are immutable. Any later product/control-plane byte change requires a new candidate identity. Development CI evidence does not authorize production bootstrap.

## Operation Control gate r0003

- Frozen candidate: `operation-control-r0001-20260920-01`
- Frozen candidate source: `98e76ffdcdbac09610f8b9a2b542f7e61e7dba61`
- Gate revision: `operation-control-gate-r0003`
- Gate source commit: `5c045556d95fc336467686201930478ab2fabd0e`
- GitHub gate run: `35519565229` — **PASS**
- Gate artifact: `10608062424`, ZIP SHA-256 `b0fbd41fbe1160e6bd1acecc0e807745f988117531297c12431136f6b8a6b825`
- Evidence: `docs/candidates/operation-control-r0001-20260920-01.gate-r0003-evidence.json`
- State: **VPS_QUALIFY_PASS_AWAITING_BOOTSTRAP**
- Production reconcile evidence: `docs/candidates/operation-control-r0001-20260920-01.vps-reconcile-r0003.json`
- Production materialization evidence: `docs/candidates/operation-control-r0001-20260920-01.vps-materialize-r0003.json`
- Production qualification evidence: `docs/candidates/operation-control-r0001-20260920-01.vps-qualify-r0003.json`
- Materialized release: exact frozen source `98e76ffdcdbac09610f8b9a2b542f7e61e7dba61`
- Materialized payload SHA-256: `b9f4022ddca38435e377ed08662d6cc7930655c828b861cdca980ba87f948c4b`
- Sidecar prestate: release `EXACT`; control selector/credential/bootstrap root/receipt/operation units all `ABSENT`
- Production boundary: exact `current=e63f`, Hub cutover `PREPARED`, writer `INACTIVE` before and after
- Qualification mutations: none; production current mutation: false; Hub cutover mutation: false; Drive mutation: false
- Qualification scope: **initial sidecar bootstrap only**

The frozen control-plane candidate is now production-qualified for its initial sidecar bootstrap boundary. This does not authorize production Hub cutover or any Drive mutation. Next permitted action is exactly one sidecar `bootstrap` transaction, followed by immediate read-only reconciliation and end-to-end `RUNTIME_SELFTEST` through GitHub Issue #65.

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

The next boundary is qualification and one-time sidecar bootstrap. The control plane must use its own `/opt/keelaryn/control-current` selector so the currently PREPARED Hub cutover remains bound to production source e63f and `/opt/keelaryn/current` is not changed merely to install remote-control infrastructure.

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

1. Read-only confirm remote branch identity before every development write.
2. Develop Operation Runtime v1 remotely on `dev/zero-based-keelaryn`.
3. Run and diagnose GitHub CI until coherent development PASS.
4. Freeze/materialize/qualify the operation-control framework release according to normal version/candidate discipline; do not change production `/opt/keelaryn/current`.
5. Perform the one-time sidecar bootstrap under `/opt/keelaryn/control-current`, then prove `RUNTIME_SELFTEST` end-to-end through GitHub Issue #65.
6. Reconcile the still-PREPARED production Hub transaction before any later production mutation.
7. Resume production cutover only through the qualified runtime/protocol and transaction-bound finalizers.

If production durable state is found to differ from this handoff, stop and reconcile the authoritative VPS state before any mutation.
