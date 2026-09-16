# Keelaryn Drive poller — systemd development template

This directory is **development deployment tooling** for the zero-based line. It is not a production release, package, installer, or production qualification artifact.

The template assumes one disposable/test VPS writer and one disposable/test Google identity. Do not point it at the production/personal Hub.

## Expected filesystem layout

```text
/opt/keelaryn/                     exact tested repository checkout
/etc/keelaryn/drive.env            root-owned OAuth/Hub configuration
/run/keelaryn/                     systemd-created runtime directory
```

The service runs as an unprivileged `keelaryn` OS user and reads code from `/opt/keelaryn` without modifying it.

## One-time setup outline

1. Create a dedicated `keelaryn` system user/group with no interactive login.
2. Materialize the exact tested repository commit at `/opt/keelaryn` and make it read-only to the service user except where your deployment tooling explicitly requires otherwise.
3. Copy `drive.env.example` to `/etc/keelaryn/drive.env`, populate only disposable/test credentials, set owner `root:root`, mode `0600`.
4. Copy `keelaryn-drive.service` to `/etc/systemd/system/keelaryn-drive.service`.
5. Before enabling continuous service, initialize or verify the disposable Hub once with the exact same checkout and environment:

   ```bash
   set -a
   . /etc/keelaryn/drive.env
   set +a
   PYTHONPATH=/opt/keelaryn/core KEELARYN_RUNTIME_DIR=/run/keelaryn \
     /usr/bin/python3 -m keelaryn_core.drive_poller bootstrap
   ```

6. Only after disposable live acceptance passes for the same development identity should the service be enabled for further disposable/VPS testing.

## Supervisor semantics

`serve` owns a local per-Hub advisory lock for its entire lifetime. A second local `bootstrap`, `once`, or `serve` for the same Hub exits blocked before OAuth/Drive access.

The lock is a **local VPS invariant only**. Two different hosts are not serialized by this mechanism. MVP deployment therefore permits exactly one configured writer host per Hub.

The unit uses:

- `RuntimeDirectory=keelaryn` with mode `0700`;
- `UMask=0077`;
- `NoNewPrivileges=true`;
- `ProtectSystem=strict`;
- `ProtectHome=true`;
- `PrivateTmp=true`;
- `Restart=on-failure`, but exit `2` (protocol/configuration block) and `130` are not restarted automatically.

Transport uncertainty is handled inside the poll loop by re-observation on a later iteration; mutation requests are not blindly retried.

## Credential boundary

The env file contains secrets and must never be committed, uploaded as CI evidence, copied into Hub history, or printed in logs. Continuous `serve` requires refresh credentials; a static access token is intentionally rejected.

For the GitHub disposable-live gate, use a **different dedicated Google test identity** that has access only to the disposable acceptance root. The GitHub secrets used by that gate must never grant access to the production/personal Hub.
