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

The caller owns service stop/start and read-only production acceptance.

Before `prepare`:

1. the legacy production Hub identity must still be the approved OLD source identity;
2. the new zero-based target must have passed all required construction/acceptance gates;
3. the exact qualified Core/source release must already be active;
4. no release-switch or Hub-cutover transaction may already be active;
5. the writer service must be stopped and proven inactive before selector `apply`.

A successful `apply` means **the durable production selector changed to NEW**. It does not mean cutover acceptance passed.

## 4. Commands

Use the exact cutover tool from the qualified active release and its exact source commit:

```bash
CUTOVER_TOOL=/opt/keelaryn/current/deploy/zero-based-vps/hub_cutover.py
SOURCE_COMMIT=<exact-qualified-40-hex-source-commit>
SELECTOR=/etc/keelaryn/hub.env
STATE=/var/lib/keelaryn/deployment
```

Prepare while selector is exact OLD:

```bash
python3 -B "$CUTOVER_TOOL" \
  --selector-path "$SELECTOR" \
  --state-root "$STATE" \
  --source-commit "$SOURCE_COMMIT" \
  prepare <new-hub-root-id>
```

`prepare` writes durable authority before selector mutation.

Stop and prove the old writer is inactive before `apply`:

```bash
systemctl stop keelaryn-drive.service
systemctl is-active --quiet keelaryn-drive.service && exit 1 || true
```

Atomically publish NEW:

```bash
python3 -B "$CUTOVER_TOOL" \
  --selector-path "$SELECTOR" \
  --state-root "$STATE" \
  --source-commit "$SOURCE_COMMIT" \
  apply
```

`apply` re-observes exact OLD at the durable commit boundary, writes a mode-`0600` temporary selector in the same directory, fsyncs it, atomically replaces `hub.env`, fsyncs the parent directory, then requires exact NEW bytes on re-observation.

A crash or response loss after replacement is recovered by observation: the next `status` reports `APPLIED` when NEW is exact. The tool must not blindly write NEW again.

Start the writer and run the required read-only post-cutover acceptance against the selected NEW Hub. Starting the service successfully is not sufficient acceptance by itself.

On PASS:

```bash
python3 -B "$CUTOVER_TOOL" \
  --selector-path "$SELECTOR" \
  --state-root "$STATE" \
  --source-commit "$SOURCE_COMMIT" \
  accept
```

`accept` requires exact NEW, publishes immutable terminal `ACCEPTED`, then archives the exact active transaction. A crash after terminal creation cannot later become rollback.

## 5. Rollback

If post-cutover verification fails, first stop and prove the NEW writer is inactive. Then run:

```bash
python3 -B "$CUTOVER_TOOL" \
  --selector-path "$SELECTOR" \
  --state-root "$STATE" \
  --source-commit "$SOURCE_COMMIT" \
  rollback
```

If the durable selector is NEW, rollback atomically restores exact OLD using the same replacement protocol. If the selector is already exact OLD after an interrupted rollback, rollback continues idempotently to terminal `ROLLED_BACK`.

Rollback does not copy zero-based bytes into the legacy Hub and does not rewrite either Hub. After selector rollback, the legacy writer may be restarted only after the selector is re-observed as exact OLD.

If the selector is neither exact OLD nor exact NEW, rollback fails closed.

## 6. Status and recovery

`status` returns only non-secret transaction state; it does not print OLD or NEW Hub IDs.

- `IDLE` — no active administrative transaction;
- `PREPARED` — active Hub-cutover transaction and selector is exact OLD;
- `APPLIED` — active Hub-cutover transaction and selector is exact NEW;
- `FINALIZE_PENDING` — immutable terminal decision exists and matching archival cleanup remains;
- `BLOCKED` — durable transaction authority and selector identity disagree or selector state is unknown.

Recovery always re-runs the same logical command with the same qualified tool/source identity. Never invent a new transaction because a process response was lost.

Fault coverage includes interruption after active-record creation, before/after selector replacement, after terminal publication, during rollback replacement and during final history publication.

## 7. Evidence boundary

Private Hub root IDs are necessary local transaction authority but must not be copied into public CI artifacts, GitHub issues/PRs, SOURCE, DISTRIBUTION, UPDATE or AI_CONTEXT.

Public/sanitized qualification evidence may bind:

- exact source commit;
- exact cutover-tool SHA-256;
- transaction/evidence identity where safe;
- selector protocol revision/schema;
- terminal outcome;
- PASS/FAIL of disposable switch/rollback rehearsal;
- PASS/FAIL of production-specific acceptance.

The production selector file and durable transaction files stay private on the target host.

## 8. Qualification sequence

Before production use:

1. deterministic unit/fault tests PASS;
2. exact-head VPS payload build/materialization PASS and contains `hub_cutover.py`;
3. disposable selector `OLD -> NEW -> ACCEPTED` rehearsal PASS;
4. disposable selector `OLD -> NEW -> OLD/ROLLED_BACK` rehearsal PASS;
5. release-switch versus Hub-cutover mutual-exclusion regression PASS;
6. target-host filesystem/ownership/mode checks PASS;
7. production target construction and read-only acceptance PASS;
8. explicit human production cutover approval is obtained.

No development PASS authorizes step 8.
