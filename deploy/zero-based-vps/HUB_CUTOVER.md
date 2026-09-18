# Zero-based Keelaryn production Hub selector and cutover contract

**Status:** development contract only. This does not authorize production/personal Hub cutover.

This document specifies the exact external selector required by `spec/MIGRATION.md`. Migration data publication and production cutover remain separate transactions.

## 1. Single authoritative selector

The VPS production Hub selector is exactly:

```text
/etc/keelaryn/hub.env
```

It contains exactly one canonical line:

```text
KEELARYN_HUB_ROOT_ID=<exact-google-drive-hub-root-id>
```

The file must be one real regular file, owned by the administrative identity executing cutover, mode `0600`. Its parent directory must be real, owned by that identity, and not group/world-writable. Symlinks, extra assignments, comments inside the installed selector, duplicate lines, whitespace variants and unknown Hub IDs are not accepted by the cutover tool.

`/etc/keelaryn/drive.env` contains Google OAuth credentials only. Hub selection must not be duplicated there or in a checked-in systemd unit.

Both checked-in Drive units load `drive.env` and `hub.env`. Transient Workspace operations must load the same pair. There is no second production Hub-selection convention in the MVP.

Initial installation may create `hub.env` explicitly before any production Hub is active. Every later selector change uses the qualified `hub_cutover.py` transaction; ad-hoc editing or replacement is not an accepted cutover procedure.

## 2. Durable transaction authority

Hub cutover and source-release switching share the existing administrative transaction root:

```text
/var/lib/keelaryn/deployment/
├── ACTIVE_TRANSACTION.json
├── LOCK
├── terminal/
└── history/

/var/lib/keelaryn/mutation-gate/
├── LOCK
└── INHIBIT.json   # only while production Drive mutations are blocked
```

This is deliberate. `release_switch.py` and `hub_cutover.py` use the same `LOCK` and the same `ACTIVE_TRANSACTION.json` name with different strict schemas. Therefore only one release-switch or Hub-cutover transaction may be active at a time. A tool encountering the other transaction schema fails closed rather than guessing ownership.

The state root, `terminal/` and `history/` must be real owner-controlled mode-`0700` directories. `LOCK` must be a regular owner-controlled mode-`0600` file and is opened without following symlinks.

The Hub cutover active record binds:

- one transaction ID;
- exact OLD Hub root ID;
- exact NEW Hub root ID;
- exact qualified source commit supplied to the tool;
- SHA-256 of the exact `hub_cutover.py` bytes executing the transaction.

Terminal authority binds SHA-256 of the exact active transaction and records only `ACCEPTED` or `ROLLED_BACK`. An opposite decision after durable terminal publication is forbidden.

## 3. Transaction boundary

`hub_cutover.py` changes only the selector file. It never mutates Google Drive, either Hub, canonical data, Project state, OAuth credentials or source releases.

`hub_cutover.py accept` is a low-level transaction primitive, not the production operator acceptance path. Production terminal acceptance must be performed only by the transaction-bound post-cutover finalizer described below.

Before `prepare`:

1. the legacy production Hub identity must still be the approved OLD source identity;
2. the new zero-based target must have passed all required construction/acceptance gates;
3. the exact qualified Core/source release must already be active;
4. no release-switch or Hub-cutover transaction may already be active;
5. the writer service must be stopped before `prepare`; `prepare` must obtain the exclusive production mutation gate after all shared mutators have exited.

`prepare` durably publishes a sanitized mutation inhibit before the active Hub transaction. From that point through selector apply, fresh read-only acceptance and terminal verification, poller mutations, Workspace create/update and production-target qualification are blocked before OAuth/Drive access. A successful `apply` means **the durable production selector changed to NEW**. It does not mean cutover acceptance passed.

## 4. Prepare and apply

Use the exact cutover tool from the qualified active release and its exact source commit:

```bash
CUTOVER_TOOL=/opt/keelaryn/current/deploy/zero-based-vps/hub_cutover.py
PRE_APPLY_FINALIZER=/opt/keelaryn/current/tests/live/run_migration_pre_apply_cutover.py
FINALIZER=/opt/keelaryn/current/tests/live/run_migration_post_cutover_acceptance.py
SOURCE_COMMIT=<exact-qualified-40-hex-source-commit>
SELECTOR=/etc/keelaryn/hub.env
STATE=/var/lib/keelaryn/deployment
MUTATION_GATE=/var/lib/keelaryn/mutation-gate
```

Stop and prove the old writer is inactive before `prepare`:

```bash
systemctl stop keelaryn-drive.service
systemctl is-active --quiet keelaryn-drive.service && exit 1 || true
```

Prepare while selector is exact OLD:

```bash
python3 -B "$CUTOVER_TOOL" \
  --selector-path "$SELECTOR" \
  --state-root "$STATE" \
  --mutation-gate-root "$MUTATION_GATE" \
  --source-commit "$SOURCE_COMMIT" \
  prepare <new-hub-root-id>
```

`prepare` first obtains the exclusive mutation gate, proving all gate-participating production mutations have exited, durably publishes `INHIBIT.json`, and only then writes active Hub-selector authority. A crash after inhibit publication but before active authority is restart-recovered by repeating exact `prepare`; a different OLD/NEW/tool identity fails closed.

The active Hub-cutover transaction also records SHA-256 of the exact qualified pre-apply and post-cutover finalizer files from the same release. Both finalizers re-check their own current bytes before live verification and again at commit/recovery boundaries. Finalizer drift therefore blocks selector `apply` or terminal `accept`; rollback remains available through the exact prepared low-level cutover tool so recovery to OLD is not made dependent on finalizer integrity.

Production `prepare` also proves that the executing `hub_cutover.py` is the exact member of the canonical active materialized release, that `/opt/keelaryn/current` is exactly the relative symlink `releases/<source_commit>`, and that the full release passes fresh payload verification. The same active-release assertion is repeated on forward `apply` and terminal `accept`. A drifted `current`, altered release payload or executor outside that release fails closed before forward mutation. Rollback deliberately does not require the active release to remain selected.

Freshly verify the quiesced legacy source and qualified NEW target, then atomically publish NEW **only through the transaction-bound pre-apply finalizer**:

```bash
export KEELARYN_PRODUCTION_CUTOVER_ENABLE=YES
export KEELARYN_HUB_SELECTOR_PATH="$SELECTOR"
export KEELARYN_DEPLOYMENT_STATE_ROOT="$STATE"
export KEELARYN_MUTATION_GATE_ROOT="$MUTATION_GATE"
export KEELARYN_SOURCE_COMMIT="$SOURCE_COMMIT"
export KEELARYN_PRE_APPLY_CUTOVER_RECEIPT=<private-mode-0600-path>
# Also export the exact migration pack/freeze/target-authority/
# qualification-evidence and OAuth bindings from the qualified candidate.

python3 -B "$PRE_APPLY_FINALIZER"
```

The pre-apply finalizer requires exact `PREPARED` transaction + inhibit authority, freshly read-only verifies the qualified NEW target, freshly verifies OLD legacy Drive bytes against the frozen migration source, durably publishes one private transaction-bound pre-apply receipt, revalidates transaction/inhibit identity at the commit boundary, and only then calls the low-level selector `apply` primitive.

The cutover finalizers do **not** require a Git checkout. The clean Git worktree is authoritative at candidate freeze and production-target qualification; after qualification, exact source commit/tree from qualification evidence plus the immutable frozen pack/freeze receipt are the local source-provenance boundary for pre-apply and post-cutover runtime verification.

Raw `hub_cutover.py apply` is intentionally not exposed by the production CLI. A crash or response loss after selector replacement is recovered by re-running the same pre-apply finalizer with the same private receipt: exact `APPLIED` is observed without repeating OAuth/Drive verification or blindly rewriting NEW.

Do **not** start the NEW writer and do **not** invoke low-level terminal `accept` directly after pre-apply PASS.

## 5. Transaction-bound post-cutover acceptance

Production acceptance is performed by the exact finalizer from the qualified active release:

```text
tests/live/run_migration_post_cutover_acceptance.py
```

It requires exact explicit enablement:

```text
KEELARYN_POST_CUTOVER_ACCEPTANCE_ENABLE=YES
```

Required private/local bindings are:

- `KEELARYN_HUB_SELECTOR_PATH`
- `KEELARYN_DEPLOYMENT_STATE_ROOT`
- `KEELARYN_MUTATION_GATE_ROOT`
- `KEELARYN_SOURCE_COMMIT`
- `KEELARYN_POST_CUTOVER_FINALIZATION_RECEIPT`
- `KEELARYN_PRE_APPLY_CUTOVER_RECEIPT`
- `KEELARYN_MIGRATION_PACK_DIR`
- `KEELARYN_MIGRATION_FREEZE_RECEIPT`
- `KEELARYN_MIGRATION_TARGET_AUTHORITY`
- `KEELARYN_MIGRATION_QUALIFICATION_EVIDENCE`
- the Google OAuth environment required by the Drive backend.

The finalization receipt must live in a private owner-controlled mode-`0700` directory. The receipt itself is mode `0600` and remains private.

Run the finalizer while the writer is still stopped and the cutover transaction is exact `APPLIED`:

```bash
python3 -B "$FINALIZER"
```

The finalizer:

1. requires the exact active Hub-cutover transaction, exact NEW selector and exact private pre-apply receipt;
2. requires pre-apply transaction/source/OLD/NEW provenance to bind the same active transaction;
3. runs fresh read-only migration acceptance against the selected NEW Hub and requires it to match the pre-apply target-acceptance digest;
4. freshly re-verifies OLD legacy Drive bytes against the frozen migration source;
5. requires `POST_CUTOVER_READ_ONLY_PASS`, `drive_mutations_performed=false` and `hub_cutover_accept_allowed=true`;
6. durably writes or verifies the private finalization receipt including SHA-256 of the pre-apply receipt;
7. revalidates active transaction and selector identity again at the terminal commit boundary;
8. invokes the low-level terminal `accept` primitive;
9. verifies immutable `ACCEPTED` terminal/history authority;
10. releases the exact bound production mutation inhibit and verifies ordinary `IDLE`;
11. emits only sanitized hashes/identities, never real Hub IDs or private paths.

A fresh successful run returns `PRODUCTION_CUTOVER_ACCEPTED` and terminal outcome `ACCEPTED`.

If process response is lost after durable terminal acceptance, re-run the **same finalizer** with the same qualified release/source identity and the same private receipt. It recovers from terminal/history authority and must not invent a new acceptance transaction. Once terminal `ACCEPTED` exists, rollback is forbidden for that transaction.

Only after finalizer PASS may the NEW writer be started:

```bash
systemctl start keelaryn-drive.service
```

Starting the writer is not a substitute for finalizer PASS.

## 6. Rollback before terminal acceptance

If fresh post-cutover acceptance fails before terminal `ACCEPTED`, keep/prove the NEW writer inactive and run:

```bash
python3 -B "$CUTOVER_TOOL" \
  --selector-path "$SELECTOR" \
  --state-root "$STATE" \
  --mutation-gate-root "$MUTATION_GATE" \
  --source-commit "$SOURCE_COMMIT" \
  rollback
```

If the durable selector is NEW, rollback atomically restores exact OLD using the same replacement protocol. If the selector is already exact OLD after an interrupted rollback, rollback continues idempotently to terminal `ROLLED_BACK`.

Rollback does not copy zero-based bytes into the legacy Hub and does not rewrite either Hub. After selector rollback, the legacy writer may be restarted only after the selector is re-observed as exact OLD.

If the selector is neither exact OLD nor exact NEW, rollback fails closed.

A transaction with durable terminal `ACCEPTED` cannot later be rolled back by `hub_cutover.py`; any future production reversal would require a new separately authorized transaction.

## 7. Status and recovery

`status` returns only non-secret transaction state; it does not print OLD or NEW Hub IDs.

- `IDLE` — no active administrative transaction;
- `INHIBITED_IDLE` — active Hub transaction has settled but the production mutation inhibit remains; only exact finalizer recovery may release an accepted inhibit;
- `PREPARED` — active Hub-cutover transaction and selector is exact OLD;
- `APPLIED` — active Hub-cutover transaction and selector is exact NEW;
- `FINALIZE_PENDING` — immutable terminal decision exists and matching archival cleanup remains;
- `BLOCKED` — durable transaction authority and selector identity disagree or selector state is unknown.

Recovery always re-runs the same logical operation with the same qualified source/tool identity. Never invent a new transaction because a process response was lost.

For `PREPARED` or response loss around selector publication, recovery re-runs the same pre-apply finalizer; raw CLI `apply` does not exist. For `APPLIED` production acceptance, recovery re-runs the transaction-bound post-cutover finalizer, not low-level `accept`. For rollback, recovery re-runs `rollback`. For an accepted finalizer response loss, the private pre-apply/finalization receipts plus terminal/history authority prove the prior decisions without inventing a new transaction.

Fault coverage includes interruption after active-record creation, before/after selector replacement, after private finalization receipt publication, after terminal publication, during rollback replacement and during final history publication.

## 8. Evidence boundary

Private Hub root IDs are necessary local transaction authority but must not be copied into public CI artifacts, GitHub issues/PRs, SOURCE, DISTRIBUTION, UPDATE or AI_CONTEXT.

Public/sanitized qualification evidence may bind:

- exact source commit;
- exact cutover-tool SHA-256;
- SHA-256 of exact active cutover transaction;
- SHA-256 of fresh post-cutover acceptance evidence;
- selector identity hash;
- selector protocol revision/schema;
- terminal outcome;
- PASS/FAIL of disposable switch/rollback rehearsal;
- PASS/FAIL of production-specific acceptance.

The production selector, private finalization receipt and durable transaction files stay private on the target host.

## 9. Qualification sequence

Before production use:

1. deterministic Core/unit/fault tests PASS;
2. transaction-bound finalizer regressions PASS, including stale/mismatched acceptance rejection and terminal response-loss recovery;
3. exact-head VPS payload build/materialization PASS and contains the cutover/finalizer source used for qualification;
4. disposable selector `OLD -> NEW -> ACCEPTED` rehearsal PASS;
5. disposable selector `OLD -> NEW -> OLD/ROLLED_BACK` rehearsal PASS;
6. release-switch versus Hub-cutover mutual-exclusion regression PASS;
7. target-host qualification proves the exact active `current` release, canonical selector/units and secure IDLE shared deployment-state filesystem/ownership/modes;
8. production target construction/qualification PASS with `cutover_authorized=false`;
9. explicit human production cutover approval is obtained;
10. writer is stopped, Hub `prepare` quiesces the mutation gate and publishes the durable inhibit, then selector `apply` completes;
11. transaction-bound fresh post-cutover finalizer verifies `ACCEPTED`, releases the exact inhibit and returns PASS;
12. only then the NEW writer is started and normal production operation resumes.

No development PASS authorizes steps 9-12.
