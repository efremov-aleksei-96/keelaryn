# Keelaryn Drive poller — systemd development template

This directory is **development deployment tooling** for the zero-based line. It is not a production release, package, installer, or production qualification artifact.

The template assumes one disposable/test VPS writer and one disposable/test Google identity. Do not point it at the production/personal Hub.

## Expected filesystem layout

```text
/opt/keelaryn/                     exact tested repository checkout
/etc/keelaryn/drive.env            root-owned OAuth/Hub configuration
/run/keelaryn/                     systemd-created runtime directory
```

Both units run as an unprivileged `keelaryn` OS user and read code from `/opt/keelaryn` without modifying it.

## Units

- `keelaryn-drive-bootstrap.service` — explicit one-shot initialize/verify command.
- `keelaryn-drive.service` — long-running polling service.

The continuous unit does **not** bootstrap automatically. Initialization/verification is a separate operator action and a separate failure boundary.

## One-time setup outline

1. Create a dedicated `keelaryn` system user/group with no interactive login.
2. Materialize the exact tested repository commit at `/opt/keelaryn` and make it read-only to the service user except where deployment tooling explicitly requires otherwise.
3. Copy `drive.env.example` to `/etc/keelaryn/drive.env`, populate only disposable/test credentials, set owner `root:root`, mode `0600`.
4. Copy both service files to `/etc/systemd/system/` and run `systemctl daemon-reload`.
5. Initialize or verify the disposable Hub through systemd:

   ```bash
   systemctl start keelaryn-drive-bootstrap.service
   systemctl status keelaryn-drive-bootstrap.service --no-pager
   ```

   Do not source `/etc/keelaryn/drive.env` into a root shell and do not run the poller bootstrap directly as root. The oneshot unit deliberately runs as `User=keelaryn`, lets systemd create `/run/keelaryn` with the expected ownership/mode, and lets systemd read the root-owned environment file without exposing secrets on the command line.
6. Only after disposable live acceptance passes for the same development identity should continuous disposable/VPS testing be enabled:

   ```bash
   systemctl enable --now keelaryn-drive.service
   ```

## Supervisor semantics

`serve` owns a local per-Hub advisory lock for its entire lifetime. A second local `bootstrap`, `once`, or `serve` for the same Hub exits blocked before OAuth/Drive access.

The lock is a **local VPS invariant only**. Two different hosts are not serialized by this mechanism. MVP deployment therefore permits exactly one configured writer host per Hub.

Both units use:

- `User=keelaryn` / `Group=keelaryn`;
- `RuntimeDirectory=keelaryn` with mode `0700`;
- `UMask=0077`;
- `NoNewPrivileges=true`;
- `ProtectSystem=strict`;
- `ProtectHome=true`;
- `PrivateTmp=true`.

The long-running unit additionally uses `Restart=on-failure`, but exit `2` (protocol/configuration block) and `130` are not restarted automatically.

Transport uncertainty is handled inside the poll loop by re-observation on a later iteration; mutation requests are not blindly retried.

## Credential boundary

The env file contains secrets and must never be committed, uploaded as CI evidence, copied into Hub history, or printed in logs. Continuous `serve` requires refresh credentials; a static access token is intentionally rejected.

For the GitHub disposable-live gate, use a **different dedicated Google test identity** that has access only to the disposable acceptance root. The GitHub secrets used by that gate must never grant access to the production/personal Hub.
