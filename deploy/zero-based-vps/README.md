# Zero-based Keelaryn Drive poller — Linux VPS deployment contract

**Status:** development deployment contract only. This does not authorize use against the production/personal Hub.

The MVP runtime is one long-lived `keelaryn_core.drive_poller serve` process on one Linux VPS. The Drive protocol remains fail-closed if remote state is ambiguous, while the local `DriveProcessLock` prevents two processes on the same host from owning one Hub concurrently.

## Filesystem contract

```text
/opt/keelaryn/
├── releases/
│   └── <exact-source-commit>/   # immutable deployed repository tree
└── current -> releases/<exact-source-commit>

/etc/keelaryn/
└── drive.env                    # root:root 0600; never stored in Git

/run/keelaryn/                   # systemd RuntimeDirectory, owned by keelaryn
```

`/opt/keelaryn/releases/<exact-source-commit>` is immutable after validation. Updating a release means publishing a different directory and atomically changing the `current` symlink; never edit the active release in place.

## Service identity

Create a dedicated unprivileged system account and group named `keelaryn`. The service needs network access to Google OAuth/Drive but no elevated Linux capabilities. The checked-in unit deliberately clears Linux capability sets and applies systemd sandboxing.

The environment file is read by the system manager before dropping privileges. Keep `/etc/keelaryn/drive.env` owned by `root:root` with mode `0600`; the service process does not need filesystem permission to read it directly.

Required variables are shown in `keelaryn-drive.env.example`. Continuous `serve` mode requires refresh credentials; a static access token is intentionally rejected by the poller.

## Pre-publication validation for one exact source commit

Before changing `/opt/keelaryn/current`, validate the staged release tree as an unprivileged user:

```bash
cd /opt/keelaryn/releases/<exact-source-commit>
python3 -m compileall -q core
PYTHONPATH=core python3 -m unittest discover -s tests/core -p 'test_*.py' -v
PYTHONPATH=core python3 -m keelaryn_core.drive_poller --help >/dev/null
```

A development-CI PASS is not production qualification. This local validation only proves that the exact staged source tree is internally coherent on the target host.

## First installation

1. Create the `keelaryn` system account/group.
2. Create `/opt/keelaryn/releases/<exact-source-commit>` from the exact qualified source tree; do not regenerate or edit source bytes after validation.
3. Create `/opt/keelaryn/current` as a symlink to that exact release directory.
4. Install `keelaryn-drive.service` as `/etc/systemd/system/keelaryn-drive.service`.
5. Create `/etc/keelaryn/drive.env` from the example, write real values only on the VPS, and set `root:root 0600`.
6. Run `systemctl daemon-reload`.
7. Before enabling continuous polling, perform the separately qualified bootstrap/live-acceptance procedure against a disposable Hub. Production/personal Hub migration is a later gate.

## Runtime behavior

The unit runs:

```text
/usr/bin/python3 -m keelaryn_core.drive_poller serve --interval-seconds 30
```

with:

```text
PYTHONPATH=/opt/keelaryn/current/core
KEELARYN_RUNTIME_DIR=/run/keelaryn
```

Systemd owns `/run/keelaryn` with mode `0700`. `DriveProcessLock` places the per-Hub lock there.

`Restart=on-failure` is paired with `RestartPreventExitStatus=2`. Exit `2` means the Core is blocked/config-invalid and requires inspection; systemd MUST NOT continuously restart it. Transient startup/transport failures may restart subject to the unit start-rate limit. Transport uncertainty inside an already running polling loop is not retried in place; the next top-level iteration re-observes Drive state.

## Atomic update transaction

For an approved new exact source commit:

1. Materialize `/opt/keelaryn/releases/<new-commit>` without modifying the active release.
2. Run the pre-publication validation above against `<new-commit>`.
3. Record the currently resolved `/opt/keelaryn/current` target as rollback identity.
4. `systemctl stop keelaryn-drive.service` and verify the service is stopped.
5. Create a temporary symlink pointing to `<new-commit>` and atomically rename it over `/opt/keelaryn/current`.
6. `systemctl start keelaryn-drive.service`.
7. Verify service status/log output and one safe polling observation before considering the deployment accepted.

Stopping the old process before switching prevents an old process from continuing while the filesystem identity changes. The Drive protocol and local process lock remain additional safeguards, not substitutes for the deployment transaction.

## Rollback

If durable source publication (the `current` symlink swap) succeeded but post-publication verification fails:

1. stop the service;
2. atomically restore `current` to the previously recorded exact release directory;
3. start the service;
4. verify the restored process identity/status;
5. preserve evidence from the rejected release and classify the failure before changing product bytes.

Rollback changes only deployed Core source identity. It MUST NOT attempt to rewrite Drive canonical data. Drive transaction recovery remains governed by `MASTER.json`, the active locator, immutable bundle, exact remote state, and recovery rules.

## Security and provenance rules

- Never place OAuth secrets, Hub IDs, or environment-file contents in repository commits, CI artifacts, issue/PR text, or generic handoffs.
- Do not run development deployment against the production/personal Hub.
- Keep release directories immutable and named by exact source commit.
- Do not install directly from a moving branch checkout.
- Do not use `Restart=always`; blocked Core states must remain stopped/observable.
- Do not run multiple service instances for the same Hub.
- A VPS deployment PASS is development evidence until the applicable live Drive and later production-specific gates also pass.
