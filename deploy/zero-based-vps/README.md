# Zero-based Keelaryn Drive poller — Linux VPS deployment contract

**Status:** development deployment contract only. This does not authorize use against the production/personal Hub.

`deploy/zero-based-vps/` is the **single canonical deployment source** for the zero-based VPS line. Do not maintain a second systemd/deployment template elsewhere in the repository.

The MVP runtime is one long-lived `keelaryn_core.drive_poller serve` process on one Linux VPS. The Drive protocol remains fail-closed if remote state is ambiguous, while `DriveProcessLock` prevents two local processes from owning one Hub concurrently.

## Canonical deployment assets

- `keelaryn-drive.service` — long-running poller;
- `keelaryn-drive-bootstrap.service` — explicit unprivileged bootstrap/verify oneshot;
- `keelaryn-drive.env.example` — secret-free refresh-auth template;
- `build_payload.py` — deterministic exact-source payload builder;
- `materialize_payload.py` — strict payload verifier and immutable release materializer.

## Filesystem contract

```text
/opt/keelaryn/
├── releases/
│   └── <exact-source-commit>/   # manifest-bound read-only release tree
└── current -> releases/<exact-source-commit>

/etc/keelaryn/
└── drive.env                    # root:root 0600; never stored in Git

/run/keelaryn/                   # systemd RuntimeDirectory, owned by keelaryn
```

A materialized release uses mode `0444` for files and `0555` for directories before it is published under `releases/<exact-source-commit>`. Updating a release means materializing a different exact commit and atomically changing `current`; never edit or enrich a materialized release in place.

## Service identity

Create a dedicated unprivileged system account and group named `keelaryn`. The service needs network access to Google OAuth/Drive but no elevated Linux capabilities. Both checked-in units clear capability sets, enable systemd sandboxing, and expose only `/run/keelaryn` as an explicit writable runtime path.

The environment file is read by the system manager before dropping privileges. Keep `/etc/keelaryn/drive.env` owned by `root:root` with mode `0600`; the service process does not need filesystem permission to read it directly.

Required variables are shown in `keelaryn-drive.env.example`. Continuous `serve` mode requires refresh credentials; a static access token is intentionally rejected.

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

It rejects unsafe/non-regular tar members, duplicate/unbound members, manifest/hash/size mismatches, source-commit mismatch, payload-digest mismatch and an already-existing destination. It stages and re-reads all bytes before an atomic directory rename, then publishes the new release read-only.

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
```

After validation, verify there is still no `__pycache__`, `.pyc` or `.pyo` material in the release. A development-CI PASS is not production qualification; target-host validation is an additional development/deployment evidence class.

## First installation

1. Create the dedicated `keelaryn` system account/group with no interactive login.
2. Create `/opt/keelaryn/releases` and materialize the exact approved payload using the source commit and payload SHA-256 above.
3. Validate the read-only release without writing bytecode.
4. Create `/opt/keelaryn/current` as a symlink to that exact release directory.
5. Install `keelaryn-drive.service` and `keelaryn-drive-bootstrap.service` under `/etc/systemd/system/`.
6. Create `/etc/keelaryn/drive.env` from `keelaryn-drive.env.example`, write real values only on the VPS, and set `root:root 0600`.
7. Run `systemctl daemon-reload`.
8. Initialize or verify the **disposable/test Hub** through the unprivileged oneshot:

   ```bash
   systemctl start keelaryn-drive-bootstrap.service
   systemctl status keelaryn-drive-bootstrap.service --no-pager
   ```

   Do not source `/etc/keelaryn/drive.env` into a root shell and **do not run the poller bootstrap directly as root**. Systemd reads the root-owned environment file and then executes the poller as `User=keelaryn`.
9. Only after the applicable disposable live-Drive gate passes for the same development identity may continuous disposable/VPS polling be enabled. Production/personal Hub migration is a later gate.

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

Systemd owns `/run/keelaryn` with mode `0700`. `DriveProcessLock` places the per-Hub lock there.

`Restart=on-failure` is paired with `RestartPreventExitStatus=2 130`. Exit `2` means Core is protocol/configuration blocked and requires inspection; it MUST NOT become a restart storm. Transport uncertainty inside an already running polling loop is not retried in place; a later top-level iteration re-observes Drive state.

## Atomic update transaction

For an approved new exact source/payload identity:

1. Materialize `/opt/keelaryn/releases/<new-commit>` from the exact payload without modifying the active release.
2. Validate the new read-only release without bytecode writes.
3. Durably record the currently resolved `/opt/keelaryn/current` target as rollback identity **before** changing the symlink.
4. `systemctl stop keelaryn-drive.service` and verify the service is stopped.
5. Create a temporary symlink pointing to `<new-commit>` and atomically rename it over `/opt/keelaryn/current`.
6. `systemctl start keelaryn-drive.service`.
7. Verify service identity/status and one safe polling observation before accepting the deployment.

Stopping the old process before switching prevents an old process from continuing while filesystem identity changes. Drive transaction recovery and the local process lock remain additional safeguards, not substitutes for the deployment transaction.

The checked-in deployment tooling will own this durable symlink transaction rather than relying on ad-hoc `ln -sfn`; until that transaction tool is qualified, this section is a contract, not permission to deploy production bytes manually.

## Rollback

If the `current` publication succeeded but post-publication verification fails:

1. stop the service;
2. use the durable pre-publication rollback identity to atomically restore `current`;
3. start the service;
4. verify the restored exact release identity/status;
5. preserve evidence from the rejected release and classify the failure before changing product bytes.

Rollback changes only deployed Core source identity. It MUST NOT attempt to rewrite Drive canonical data. Drive transaction recovery remains governed by `MASTER.json`, the active locator, immutable bundle, exact remote state and recovery rules.

## Security and provenance rules

- Never place OAuth secrets, Hub IDs or environment-file contents in repository commits, CI artifacts, issue/PR text or generic handoffs.
- Do not run development deployment against the production/personal Hub.
- `deploy/zero-based-vps/` is the only deployment source-of-truth for this line.
- Keep release directories manifest-bound and read-only; do not install directly from a moving branch checkout.
- Bind deployment to both exact source commit and exact qualified payload SHA-256.
- Do not use `Restart=always`; blocked Core states must remain stopped/observable.
- Do not run multiple writer hosts for the same Hub in MVP.
- A VPS deployment PASS is development evidence until applicable live Drive and later production-specific gates also pass.
