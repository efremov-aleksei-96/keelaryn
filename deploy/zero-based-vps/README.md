# Zero-based Keelaryn Drive poller — Linux VPS deployment contract

**Status:** development deployment contract only. This does not authorize use against the production/personal Hub.

`deploy/zero-based-vps/` is the **single canonical deployment source** for the zero-based VPS line. Do not maintain a second systemd/deployment template elsewhere in the repository.

The MVP runtime is one long-lived `keelaryn_core.drive_poller serve` process on one Linux VPS. The Drive protocol remains fail-closed if remote state is ambiguous, while `DriveProcessLock` prevents two local runtime processes from owning one Hub concurrently.

## Canonical deployment assets

- `keelaryn-drive.service` — long-running poller;
- `keelaryn-drive-bootstrap.service` — explicit unprivileged bootstrap/verify oneshot;
- `keelaryn-drive.env.example` — secret-free refresh-auth template;
- `build_payload.py` — deterministic exact-source payload builder;
- `materialize_payload.py` — strict payload verifier and immutable release materializer;
- `release_switch.py` — durable, restartable `current` symlink publication/rollback transaction.

## Filesystem contract

```text
/opt/keelaryn/
├── releases/
│   └── <exact-source-commit>/   # manifest-bound read-only release tree
└── current -> releases/<exact-source-commit>

/var/lib/keelaryn/deployment/    # deployment transaction state; owner-only 0700
├── ACTIVE_TRANSACTION.json      # exists only while one switch is active
├── LOCK                         # owner-controlled regular file 0600
├── terminal/                    # immutable ACCEPTED / ROLLED_BACK decisions
└── history/                     # immutable completed transaction records

/etc/keelaryn/
└── drive.env                    # root:root 0600; never stored in Git

/run/keelaryn/                   # systemd RuntimeDirectory, owned by keelaryn
```

A materialized release uses mode `0444` for files and `0555` for directories before it is published under `releases/<exact-source-commit>`. Updating a release means materializing a different exact commit and changing `current` only through `release_switch.py`; never edit or enrich a materialized release in place.

The deployment transaction state is separate from `/run/keelaryn`. `/run/keelaryn` is disposable runtime/process-lock state owned by the service account. `/var/lib/keelaryn/deployment` is durable administrative provenance used to recover a source-publication transaction after an operator/process crash. The switch tool requires its state root, `terminal/`, and `history/` to be real directories owned by the effective deployment user with mode `0700`; its lock is opened without following symlinks and must be a regular owner-controlled `0600` file.

## Service identity

Create a dedicated unprivileged system account and group named `keelaryn`. The service needs network access to Google OAuth/Drive but no elevated Linux capabilities. Both checked-in units clear capability sets, enable systemd sandboxing, and expose only `/run/keelaryn` as an explicit writable runtime path.

The environment file is read by the system manager before dropping privileges. Keep `/etc/keelaryn/drive.env` owned by `root:root` with mode `0600`; the service process does not need filesystem permission to read it directly.

Required variables are shown in `keelaryn-drive.env.example`. Continuous `serve` mode requires refresh credentials; a static access token is intentionally rejected.

`release_switch.py` is an administrative filesystem tool. It does not read OAuth credentials and does not mutate Google Drive or Hub bytes.

## Exact payload provenance

Development CI builds the VPS payload twice from the exact `GITHUB_SHA`, requires byte-identical archives, materializes one copy, validates the materialized runtime without writing bytecode, and emits only compact short-lived evidence. The payload archive itself is not persisted as an ordinary development artifact.

For any deployment, bind **both** identities from approved evidence:

- exact 40-character source commit;
- exact payload SHA-256.

The materializer must be invoked with both expected values:

```bash
python3 materialize_payload.py \
  --payload /path/to/keelaryn-zero.tar.gz \
  --releases-root /opt/keelaryn/releases \
  --expected-source-commit <exact-source-commit> \
  --expected-payload-sha256 <exact-qualified-payload-sha256>
```

It rejects unsafe/non-regular tar members, duplicate/unbound members, manifest/hash/size mismatches, source-commit mismatch, payload-digest mismatch and an already-existing destination. It stages and re-reads all bytes before an atomic directory rename, then publishes the new release read-only. Each materialized release also contains immutable payload identity metadata used by `release_switch.py` to bind the old and new release bytes before changing `current`.

## Validation without modifying release bytes

Do **not** use `compileall` or any command that writes `__pycache__` inside a materialized release. Validate with bytecode writes disabled:

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
python3 -B deploy/zero-based-vps/release_switch.py --help >/dev/null
```

After validation, verify there is still no `__pycache__`, `.pyc` or `.pyo` material in the release. A development-CI PASS is not production qualification; target-host validation is an additional development/deployment evidence class.

## First installation

1. Create the dedicated `keelaryn` system account/group with no interactive login.
2. Create `/opt/keelaryn/releases` and materialize the exact approved payload using the source commit and payload SHA-256 above.
3. Validate the read-only release without writing bytecode.
4. Create `/opt/keelaryn/current` as a **relative** symlink exactly in the form `current -> releases/<exact-source-commit>`.
5. Create `/var/lib/keelaryn/deployment` owned by the administrative deployment identity with mode `0700`.
6. Install `keelaryn-drive.service` and `keelaryn-drive-bootstrap.service` under `/etc/systemd/system/`.
7. Create `/etc/keelaryn/drive.env` from `keelaryn-drive.env.example`, write real values only on the VPS, and set `root:root 0600`.
8. Run `systemctl daemon-reload`.
9. Initialize or verify the **disposable/test Hub** through the unprivileged oneshot:

   ```bash
   systemctl start keelaryn-drive-bootstrap.service
   systemctl status keelaryn-drive-bootstrap.service --no-pager
   ```

   Do not source `/etc/keelaryn/drive.env` into a root shell and **do not run the poller bootstrap directly as root**. Systemd reads the root-owned environment file and then executes the poller as `User=keelaryn`.
10. Only after the applicable disposable live-Drive gate passes for the same development identity may continuous disposable/VPS polling be enabled. Production/personal Hub migration is a later gate.

The first creation of `current` is installation bootstrap, not an update transaction. Every subsequent source identity change uses the durable switch protocol below.

## Runtime behavior

The continuous unit runs:

```text
/usr/bin/python3 -B -m keelaryn_core.drive_poller serve --interval-seconds 30
```

with:

```text
PYTHONPATH=/opt/keelaryn/current/core
PYTHONDONTWRITEBYTECODE=1
KEELARYN_RUNTIME_DIR=/run/keelaryn
```

Systemd owns `/run/keelaryn` with mode `0700`. `DriveProcessLock` places the per-Hub runtime lock there.

`Restart=on-failure` is paired with `RestartPreventExitStatus=2 130`. Exit `2` means Core is protocol/configuration blocked and requires inspection; it MUST NOT become a restart storm. Transport uncertainty inside an already running polling loop is not retried in place; a later top-level iteration re-observes Drive state.

## Durable atomic update transaction

For an approved new exact source/payload identity, first materialize and validate `/opt/keelaryn/releases/<new-commit>` while the existing service continues to use the old immutable release. Then perform the source-publication boundary as follows.

1. Stop the writer and prove it is stopped:

   ```bash
   systemctl stop keelaryn-drive.service
   systemctl is-active --quiet keelaryn-drive.service && exit 1 || true
   ```

2. Create the durable transaction **before** changing `current`:

   ```bash
   python3 -B /opt/keelaryn/current/deploy/zero-based-vps/release_switch.py \
     --install-root /opt/keelaryn \
     --state-root /var/lib/keelaryn/deployment \
     prepare --new-commit <new-commit>
   ```

   `prepare` verifies the exact OLD and NEW materialized release identities and records both in immutable `ACTIVE_TRANSACTION.json`. It fails if `current` is not exactly `releases/<old-commit>` or if another switch is active.

3. Atomically publish NEW:

   ```bash
   python3 -B /opt/keelaryn/current/deploy/zero-based-vps/release_switch.py \
     --install-root /opt/keelaryn \
     --state-root /var/lib/keelaryn/deployment \
     apply
   ```

   `apply` freshly revalidates OLD and NEW immediately before publication, then atomically replaces `current` with the exact relative NEW symlink. A crash after the swap is recovered from the immutable active record plus the observed symlink; there is no mutable progress counter.

4. Start the service from NEW and perform the required post-publication checks:

   ```bash
   systemctl start keelaryn-drive.service
   systemctl status keelaryn-drive.service --no-pager
   ```

   Verify the process/source identity and at least one safe polling observation. Do not accept merely because `systemctl start` returned success.

5. If the deployment passes, publish the immutable terminal decision:

   ```bash
   python3 -B /opt/keelaryn/current/deploy/zero-based-vps/release_switch.py \
     --install-root /opt/keelaryn \
     --state-root /var/lib/keelaryn/deployment \
     accept
   ```

   `accept` requires `current` to be exact NEW and both bound releases to remain exact. It writes an `ACCEPTED` terminal marker before archiving the active transaction record.

The old release directory is retained; acceptance does not delete rollback material. Release retention/deletion policy is outside this MVP transaction.

## Rollback

If publication succeeded but post-publication verification fails, stop the NEW process first:

```bash
systemctl stop keelaryn-drive.service
systemctl is-active --quiet keelaryn-drive.service && exit 1 || true
```

Then rollback using only the already durable transaction authority:

```bash
python3 -B /opt/keelaryn/current/deploy/zero-based-vps/release_switch.py \
  --install-root /opt/keelaryn \
  --state-root /var/lib/keelaryn/deployment \
  rollback
```

Rollback requires the exact bound OLD release and `current` to classify as OLD or NEW. It deliberately does **not** require NEW to remain valid: corruption of NEW may be the reason post-publication verification failed. If OLD is corrupt, `current` is unknown, the terminal decision conflicts, or durable deployment state is ambiguous, rollback fails closed instead of guessing.

After rollback:

```bash
systemctl start keelaryn-drive.service
systemctl status keelaryn-drive.service --no-pager
```

Verify the restored exact source identity and safe polling state. Rollback changes only deployed Core source identity. It MUST NOT attempt to rewrite Drive canonical data. Drive transaction recovery remains governed independently by `MASTER.json`, the active locator, immutable bundle, exact remote state and recovery rules.

## Crash/restart recovery of deployment publication

At any operator restart, inspect the durable transaction before issuing a new deployment:

```bash
python3 -B /opt/keelaryn/current/deploy/zero-based-vps/release_switch.py \
  --install-root /opt/keelaryn \
  --state-root /var/lib/keelaryn/deployment \
  status
```

Interpretation:

- `IDLE` — no active source-publication transaction;
- `PREPARED` — `current` is exact OLD; either continue `apply` or cancel with `rollback`;
- `APPLIED` — `current` is exact NEW; perform/continue post-publication verification, then `accept` or `rollback`;
- `FINALIZE_PENDING` — an immutable terminal decision already exists; repeat the matching `accept` or `rollback` command to finish archival cleanup;
- `BLOCKED` — durable authority and observed `current` disagree or the symlink is unknown; do not perform an ad-hoc `ln`, delete control files, or select a release heuristically.

Crash points after active-record publication, symlink swap, terminal-marker publication, rollback swap and active-record archival are covered by the development fault matrix. A terminal marker binds the SHA-256 of the exact immutable active transaction; an opposite later decision is rejected.

## Security and provenance rules

- Never place OAuth secrets, Hub IDs or environment-file contents in repository commits, CI artifacts, issue/PR text or generic handoffs.
- Do not run development deployment against the production/personal Hub.
- `deploy/zero-based-vps/` is the only deployment source-of-truth for this line.
- Keep release directories manifest-bound and read-only; do not install directly from a moving branch checkout.
- Bind deployment to both exact source commit and exact qualified payload SHA-256.
- Use `release_switch.py` for every update/rollback after first installation; do not use ad-hoc `ln -sfn` for `current`.
- Keep durable deployment transaction state private and separate from service runtime state.
- Do not use `Restart=always`; blocked Core states must remain stopped/observable.
- Do not run multiple writer hosts for the same Hub in MVP.
- A VPS deployment PASS is development evidence until applicable live Drive and later production-specific gates also pass.
