# Zero-based Keelaryn Drive poller — Linux VPS deployment contract

**Status:** development deployment contract only. This does not authorize use against the production/personal Hub.

`deploy/zero-based-vps/` is the **single canonical deployment source** for the zero-based VPS line. Do not maintain a second systemd/deployment template elsewhere in the repository.

The MVP runtime is one long-lived `keelaryn_core.drive_poller serve` process on one Linux VPS. Drive state remains fail-closed if remote state is ambiguous, and `DriveProcessLock` prevents two local Core runtime processes from owning one Hub concurrently. Workspace commands are separate short-lived semantic-work operations over `work/projects/`; they do not acquire the Core process lock and may run while the poller is active.

## Canonical deployment assets

- `keelaryn-drive.service` — long-running poller;
- `keelaryn-drive-bootstrap.service` — explicit unprivileged bootstrap/verify oneshot;
- `keelaryn-drive.env.example` — OAuth refresh-auth template only;
- `keelaryn-hub.env.example` — single Hub-selector template only;
- `build_payload.py` — deterministic exact-source payload builder;
- `materialize_payload.py` — strict payload verifier and immutable release materializer;
- `release_switch.py` — durable restartable `current` source publication/rollback transaction;
- `hub_cutover.py` — durable restartable production Hub-selector cutover/rollback transaction;
- `HUB_CUTOVER.md` — exact production selector and cutover contract.

The Workspace executable surface is part of the immutable Core payload:

```text
python3 -B -m keelaryn_core.workspace_cli
```

It is intentionally not a second daemon.

## Filesystem contract

```text
/opt/keelaryn/
├── releases/
│   └── <exact-source-commit>/   # manifest-bound read-only release tree
└── current -> releases/<exact-source-commit>

/var/lib/keelaryn/deployment/    # shared durable admin transaction state; owner-only 0700
├── ACTIVE_TRANSACTION.json      # at most one release-switch OR Hub-cutover transaction
├── LOCK                         # regular owner-controlled 0600
├── terminal/
└── history/

/etc/keelaryn/
├── drive.env                    # root:root 0600; OAuth credentials only
└── hub.env                      # root:root 0600; single KEELARYN_HUB_ROOT_ID selector

/run/keelaryn/                   # disposable systemd runtime directory
```

A materialized release uses mode `0444` for files and `0555` for directories. Updating a release means materializing a different exact commit and changing `current` only through `release_switch.py`; never edit or enrich a materialized release in place.

Deployment transaction state is separate from `/run/keelaryn`. `/run/keelaryn` is disposable process-lock state. `/var/lib/keelaryn/deployment` is durable administrative publication/cutover provenance. `release_switch.py` and `hub_cutover.py` deliberately share its `LOCK` and `ACTIVE_TRANSACTION.json`, so a source switch and Hub cutover cannot be active concurrently. The state root, `terminal/`, and `history/` must be real directories owned by the effective administrative identity with mode `0700`; the lock is opened without following symlinks and must be a regular owner-controlled `0600` file.

## Service identity, credentials and selector

Create a dedicated unprivileged `keelaryn` system account/group. The checked-in units clear Linux capabilities, use systemd sandboxing and expose only `/run/keelaryn` as an explicit writable runtime path.

Keep both `/etc/keelaryn/drive.env` and `/etc/keelaryn/hub.env` owned by `root:root` with mode `0600`. Systemd reads them before dropping privileges; the service process does not need filesystem permission to read either file directly.

`drive.env` contains only Google OAuth refresh credentials. `hub.env` contains exactly one authoritative selector assignment:

```text
KEELARYN_HUB_ROOT_ID=<exact-approved-drive-hub-root-id>
```

Do not duplicate `KEELARYN_HUB_ROOT_ID` in `drive.env`, units, shell profiles or Workspace wrappers. After initial installation, change `hub.env` only through the qualified `hub_cutover.py` transaction.

Do not `source` either root-owned environment file into an interactive shell merely to run Workspace commands. Use the transient-systemd pattern below so the service manager reads both files and launches the short-lived command as the unprivileged `keelaryn` identity.

`release_switch.py` and `hub_cutover.py` are administrative filesystem tools. Neither reads OAuth credentials or mutates Google Drive/Hub bytes.

## Exact payload provenance

Development CI builds the VPS payload twice from exact `GITHUB_SHA`, requires byte-identical archives, materializes one copy, validates it without writing bytecode, and emits only compact short-lived evidence. The payload archive itself is not retained as an ordinary development artifact.

Every deployment binds both:

- exact 40-character source commit;
- exact payload SHA-256.

Materialize with both expected identities:

```bash
python3 materialize_payload.py \
  --payload /path/to/keelaryn-zero.tar.gz \
  --releases-root /opt/keelaryn/releases \
  --expected-source-commit <exact-source-commit> \
  --expected-payload-sha256 <exact-qualified-payload-sha256>
```

The materializer rejects unsafe/non-regular tar members, duplicate or unbound members, manifest/hash/size mismatches, source mismatch, payload-digest mismatch and an already-existing release destination. It stages and re-reads all bytes before atomic publication, then makes the release read-only. Materialized payload identity is revalidated by `release_switch.py` before source publication.

## Validation without modifying release bytes

Do **not** use compile commands that write `__pycache__` inside a materialized release. Validate with bytecode writes disabled:

```bash
cd /opt/keelaryn/releases/<exact-source-commit>
export PYTHONDONTWRITEBYTECODE=1

python3 -B - <<'PY'
from pathlib import Path
for path in sorted(Path('.').rglob('*.py')):
    compile(path.read_bytes(), str(path), 'exec')
PY

PYTHONPATH=core python3 -B -m unittest discover -s tests/core -p 'test_*.py' -v
PYTHONPATH=core python3 -B -m keelaryn_core.drive_poller --help >/dev/null
PYTHONPATH=core python3 -B -m keelaryn_core.workspace_cli --help >/dev/null
python3 -B deploy/zero-based-vps/release_switch.py --help >/dev/null
python3 -B deploy/zero-based-vps/hub_cutover.py --help >/dev/null
```

After validation there must still be no `__pycache__`, `.pyc` or `.pyo` material in the release. A development-CI PASS is not production qualification; target-host validation is a separate evidence class.

## First installation

1. Create the dedicated `keelaryn` account/group with no interactive login.
2. Create `/opt/keelaryn/releases` and materialize the exact approved payload using both qualified identities.
3. Validate the read-only release without bytecode writes.
4. Create `/opt/keelaryn/current` as a **relative** symlink exactly `current -> releases/<exact-source-commit>`.
5. Create `/var/lib/keelaryn/deployment` for the administrative deployment identity with mode `0700`.
6. Install both checked-in systemd units under `/etc/systemd/system/`.
7. Create `/etc/keelaryn/drive.env` from its example and set `root:root 0600`.
8. Create `/etc/keelaryn/hub.env` from its example, replace the placeholder with the exact approved disposable/test Hub ID, and set `root:root 0600`.
9. Run `systemctl daemon-reload`.
10. Initialize or verify the **disposable/test Hub** through the unprivileged oneshot:

   ```bash
   systemctl start keelaryn-drive-bootstrap.service
   systemctl status keelaryn-drive-bootstrap.service --no-pager
   ```

   Do not source the secret env file into a root shell and **do not run the poller bootstrap directly as root**.
11. Continuous disposable/VPS polling is enabled only after the applicable live-Drive gate passes. Production/personal Hub migration is a later gate.

The initial creation of `current` and initial selector file are installation bootstrap. Every later source identity change uses `release_switch.py`; every later Hub-selector change uses `hub_cutover.py`.

## Runtime behavior

The continuous unit runs:

```text
/usr/bin/python3 -B -m keelaryn_core.drive_poller serve --interval-seconds 30
```

with both root-owned EnvironmentFiles plus:

```text
PYTHONPATH=/opt/keelaryn/current/core
PYTHONDONTWRITEBYTECODE=1
KEELARYN_RUNTIME_DIR=/run/keelaryn
```

`Restart=on-failure` is paired with `RestartPreventExitStatus=2 130`. Exit `2` means Core is protocol/configuration blocked and MUST NOT become a restart storm. Transport uncertainty is not blindly retried inside a mutation; a later top-level iteration re-observes Drive state.

## Workspace operations on the VPS

Workspace commands operate only on semantic Project work state. They do not publish canonical data and do not use the Core process lock. One active writer per Project remains the MVP rule; do not intentionally run simultaneous mutating Workspace commands for the same Project.

Every transient Workspace command must load the same credentials and Hub selector as the poller.

Run read-only list/read commands through a transient oneshot:

```bash
systemd-run --quiet --wait --collect --pipe \
  --unit=keelaryn-workspace-list \
  --property=User=keelaryn \
  --property=Group=keelaryn \
  --property=EnvironmentFile=/etc/keelaryn/drive.env \
  --property=EnvironmentFile=/etc/keelaryn/hub.env \
  --property=Environment=PYTHONPATH=/opt/keelaryn/current/core \
  --property=Environment=PYTHONDONTWRITEBYTECODE=1 \
  /usr/bin/python3 -B -m keelaryn_core.workspace_cli list
```

For one Project:

```bash
systemd-run --quiet --wait --collect --pipe \
  --unit=keelaryn-workspace-read \
  --property=User=keelaryn \
  --property=Group=keelaryn \
  --property=EnvironmentFile=/etc/keelaryn/drive.env \
  --property=EnvironmentFile=/etc/keelaryn/hub.env \
  --property=Environment=PYTHONPATH=/opt/keelaryn/current/core \
  --property=Environment=PYTHONDONTWRITEBYTECODE=1 \
  /usr/bin/python3 -B -m keelaryn_core.workspace_cli read <project_id>
```

For `create` or `update`, write the intended exact UTF-8 STATE bytes to a temporary file readable by `keelaryn` but not world-readable. Do not place OAuth material in that file. Example administrative preparation:

```bash
install -o keelaryn -g keelaryn -m 0600 /path/to/STATE.md /run/keelaryn/workspace-state.md
```

Then create:

```bash
systemd-run --quiet --wait --collect --pipe \
  --unit=keelaryn-workspace-create \
  --property=User=keelaryn \
  --property=Group=keelaryn \
  --property=EnvironmentFile=/etc/keelaryn/drive.env \
  --property=EnvironmentFile=/etc/keelaryn/hub.env \
  --property=Environment=PYTHONPATH=/opt/keelaryn/current/core \
  --property=Environment=PYTHONDONTWRITEBYTECODE=1 \
  /usr/bin/python3 -B -m keelaryn_core.workspace_cli \
  create <project_id> --state-file /run/keelaryn/workspace-state.md
```

Or update:

```bash
systemd-run --quiet --wait --collect --pipe \
  --unit=keelaryn-workspace-update \
  --property=User=keelaryn \
  --property=Group=keelaryn \
  --property=EnvironmentFile=/etc/keelaryn/drive.env \
  --property=EnvironmentFile=/etc/keelaryn/hub.env \
  --property=Environment=PYTHONPATH=/opt/keelaryn/current/core \
  --property=Environment=PYTHONDONTWRITEBYTECODE=1 \
  /usr/bin/python3 -B -m keelaryn_core.workspace_cli \
  update <project_id> <update_id> --state-file /run/keelaryn/workspace-state.md
```

After the command returns, remove the temporary semantic input:

```bash
rm -f /run/keelaryn/workspace-state.md
```

The CLI emits JSON only and intentionally omits internal Drive IDs. Exit `2` is a protocol/configuration block. Exit `3` means the remote mutation result is uncertain and the caller must re-observe/repeat the same logical operation; do not invent a new Project or update identity merely because the response was lost.

## Durable Hub selector cutover

The exact migration cutover protocol is defined in `HUB_CUTOVER.md`. In summary:

- production cutover changes only `/etc/keelaryn/hub.env`;
- `hub_cutover.py` shares `/var/lib/keelaryn/deployment/LOCK` and `ACTIVE_TRANSACTION.json` with `release_switch.py`, preventing concurrent source and Hub-selection transactions;
- `prepare` durably records exact OLD/NEW Hub identities before mutation;
- the writer must be stopped and proven inactive before `apply`;
- `apply` atomically replaces the selector and a restart re-observes OLD/NEW rather than trusting process-local progress;
- post-cutover read-only acceptance is external to the selector tool;
- `accept` terminally records PASS only when NEW remains exact;
- `rollback` atomically restores OLD and never copies or rewrites Hub data;
- a selector outside exact OLD/NEW blocks fail-closed.

Do not perform a real production cutover merely because development selector tests pass.

## Durable atomic source update transaction

A source-publication transaction is executed by **one immutable tool identity from start to terminal completion**. NEW bytes must never take over their own deployment transaction after `current` changes.

First materialize and validate `/opt/keelaryn/releases/<new-commit>`. Before `prepare`, capture the exact OLD release and its switch tool:

```bash
OLD_RELEASE="$(readlink -f /opt/keelaryn/current)"
SWITCH_TOOL="$OLD_RELEASE/deploy/zero-based-vps/release_switch.py"
test -f "$SWITCH_TOOL"
```

Keep using that exact `$SWITCH_TOOL` for `prepare`, `apply`, `status`, `accept` and `rollback` until the transaction is terminal and `status` is `IDLE`. `release_switch.py` enforces this itself: while an active transaction exists, a tool launched from NEW or any unrelated release is rejected fail-closed.

1. Stop the old writer and prove it is stopped:

   ```bash
   systemctl stop keelaryn-drive.service
   systemctl is-active --quiet keelaryn-drive.service && exit 1 || true
   ```

2. Publish durable transaction authority before changing `current`:

   ```bash
   python3 -B "$SWITCH_TOOL" \
     --install-root /opt/keelaryn \
     --state-root /var/lib/keelaryn/deployment \
     prepare --new-commit <new-commit>
   ```

   `prepare` verifies exact OLD and NEW materialized release identities and writes immutable `ACTIVE_TRANSACTION.json` before any symlink mutation.

3. Atomically publish NEW using the same OLD tool:

   ```bash
   python3 -B "$SWITCH_TOOL" \
     --install-root /opt/keelaryn \
     --state-root /var/lib/keelaryn/deployment \
     apply
   ```

   `apply` freshly revalidates both releases, then atomically replaces `current` with exact NEW. A crash after swap is recovered from durable transaction authority plus observed symlink state; no mutable progress counter is trusted.

4. Start NEW and perform post-publication verification:

   ```bash
   systemctl start keelaryn-drive.service
   systemctl status keelaryn-drive.service --no-pager
   ```

   Verify exact process/source identity and at least one safe polling observation. `systemctl start` success alone is insufficient.

5. On PASS, use the still-pinned OLD tool to publish terminal acceptance:

   ```bash
   python3 -B "$SWITCH_TOOL" \
     --install-root /opt/keelaryn \
     --state-root /var/lib/keelaryn/deployment \
     accept
   ```

`accept` requires exact NEW `current`, exact bound release identities, then writes an immutable ACCEPTED marker before archival cleanup. OLD is retained as rollback/provenance material; release retention is outside this MVP transaction.

## Source rollback

If post-publication verification fails, stop NEW first:

```bash
systemctl stop keelaryn-drive.service
systemctl is-active --quiet keelaryn-drive.service && exit 1 || true
```

Then use the exact same captured OLD tool:

```bash
python3 -B "$SWITCH_TOOL" \
  --install-root /opt/keelaryn \
  --state-root /var/lib/keelaryn/deployment \
  rollback
```

Rollback uses the durable pre-publication authority to **atomically restore `current`** to exact OLD. It deliberately does not require NEW to remain valid: NEW corruption may be the reason verification failed. Exact OLD must remain valid. If OLD is corrupt, `current` is UNKNOWN, terminal authority conflicts, or durable state is ambiguous, rollback fails closed instead of guessing.

After rollback, start the restored service and verify its exact source identity and safe polling state. Rollback changes only deployed Core source identity and **MUST NOT attempt to rewrite Drive canonical data**.

## Crash/restart recovery

Do not choose a release-switch executor from `current` after a source-switch crash: `current` may already be NEW while the active transaction remains bound to OLD.

If the shell that captured `$SWITCH_TOOL` was lost, recover the exact OLD commit from owner-only durable authority:

```bash
OLD_COMMIT="$(python3 -B - <<'PY'
import json
from pathlib import Path
p = Path('/var/lib/keelaryn/deployment/ACTIVE_TRANSACTION.json')
value = json.loads(p.read_text(encoding='utf-8'))
print(value['old']['source_commit'])
PY
)"
SWITCH_TOOL="/opt/keelaryn/releases/$OLD_COMMIT/deploy/zero-based-vps/release_switch.py"
test -f "$SWITCH_TOOL"
```

Then inspect source-switch state with that OLD tool:

```bash
python3 -B "$SWITCH_TOOL" \
  --install-root /opt/keelaryn \
  --state-root /var/lib/keelaryn/deployment \
  status
```

Release-switch status meanings:

- `IDLE` — no active administrative transaction; the tool from current release is authoritative for the next transaction;
- `PREPARED` — `current` is exact OLD; continue `apply` or finish as rollback;
- `APPLIED` — `current` is exact NEW; continue post-check then `accept` or `rollback` using OLD tool;
- `FINALIZE_PENDING` — immutable terminal decision already exists; repeat matching `accept` or `rollback` using OLD tool to finish archival cleanup;
- `BLOCKED` — durable authority and observed `current` disagree or the symlink is UNKNOWN; do not use ad-hoc `ln`, delete control files, or select a release heuristically.

Hub-cutover recovery uses the same durable-state principles but its strict schema is different; use `hub_cutover.py status` as documented in `HUB_CUTOVER.md`. Encountering the other transaction schema is a fail-closed signal, not permission to overwrite `ACTIVE_TRANSACTION.json`.

Crash points after active-record creation, selector/symlink swap, terminal-marker creation, rollback swap and active-record archival are covered by development fault tests. Terminal authority binds SHA-256 of the exact active transaction and prevents a later opposite decision.

## Security and provenance rules

- Never place OAuth secrets, Hub IDs or installed environment-file contents in repository commits, CI artifacts, issue/PR text or generic handoffs.
- Do not run development deployment or cutover against the production/personal Hub.
- `deploy/zero-based-vps/` is the only deployment source-of-truth for this line.
- Keep release directories manifest-bound/read-only; never install from a moving branch checkout.
- Bind deployment to exact source commit and exact qualified payload SHA-256.
- Keep `/etc/keelaryn/hub.env` as the only production Hub selector; do not duplicate its value elsewhere.
- Use `hub_cutover.py` for every selector change after initial installation; do not edit/replace `hub.env` ad hoc.
- Capture and pin the OLD `release_switch.py` before source `prepare`; one source transaction never changes executor identity midway.
- Use `release_switch.py` for every source update/rollback after first installation; do not use ad-hoc `ln -sfn` for `current`.
- Never run source switching and Hub cutover concurrently; shared durable transaction authority enforces this fail-closed.
- Keep durable deployment state private and separate from service runtime state.
- Do not use `Restart=always`; blocked Core states must remain stopped/observable.
- MVP allows only one Core writer host per Hub and one active semantic writer per Project.
- A VPS deployment/cutover PASS is development evidence until applicable live Drive and later production-specific gates also pass.
