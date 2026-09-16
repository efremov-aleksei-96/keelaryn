# Keelaryn Zero-Based Core

This directory contains the zero-based Core implementation. It is development code on `dev/zero-based-keelaryn`; it is not Manager 4.x production code and is not production-qualified.

## Local-filesystem Core

The existing local backend remains available through:

```bash
PYTHONPATH=core python3 -m keelaryn_core.cli --hub <path> bootstrap
PYTHONPATH=core python3 -m keelaryn_core.cli --hub <path> run
PYTHONPATH=core python3 -m keelaryn_core.cli --hub <path> status
```

## Google Drive Core

The Drive runtime is entered through:

```bash
PYTHONPATH=core python3 -m keelaryn_core.drive_poller --hub-root-id <drive-file-id> bootstrap
PYTHONPATH=core python3 -m keelaryn_core.drive_poller --hub-root-id <drive-file-id> once
PYTHONPATH=core python3 -m keelaryn_core.drive_poller --hub-root-id <drive-file-id> serve --interval-seconds 30
```

`KEELARYN_HUB_ROOT_ID` may be used instead of `--hub-root-id`.

### Authentication

Continuous `serve` mode requires refresh credentials supplied only through the process environment:

- `KEELARYN_GOOGLE_CLIENT_ID`
- `KEELARYN_GOOGLE_CLIENT_SECRET`
- `KEELARYN_GOOGLE_REFRESH_TOKEN`

For disposable `bootstrap` or `once` runs, `KEELARYN_GOOGLE_ACCESS_TOKEN` is also accepted. Static access tokens are deliberately rejected for continuous service because they expire.

Credential values must not be committed to Git, written into Hub files, included in qualification artifacts, or printed in normal status output.

### Local single-writer rule

Every Drive CLI command acquires a crash-released local per-Hub lock **before** OAuth/Drive access. A second local `bootstrap`, `once`, or `serve` for the same Hub fails closed rather than racing pre-activation preparation.

Lock files use a SHA-256-derived Hub key, not the Drive Hub ID itself. The runtime directory must be a real private directory owned by the current OS user. It may be set with `KEELARYN_RUNTIME_DIR`; otherwise the poller uses a private XDG runtime subdirectory or a private per-user `/tmp` fallback on POSIX.

This lock serializes one VPS only. MVP deployment therefore requires exactly one writer host for a Hub. Cross-host writer serialization is not claimed by the current protocol.

## Drive service layers

The high-level Drive path is:

```text
DriveHubBootstrap
  -> DrivePollingService
     -> DriveRestartDiscovery / DriveRuntime
     -> DriveTransactionFactory
        -> Ready Change ingestion
        -> immutable DriveTransactionBundle
     -> DriveCoreRunner
     -> terminal READY consumption
     -> locator cleanup
```

Normal canonical readers use `DriveCanonicalReader` and accept data only when the pre/post MASTER observations are both SAFE with the same canonical epoch.

## VPS development deployment

A hardened systemd development template and secret-free environment example live under:

```text
core/deploy/systemd/
```

The template uses an unprivileged `keelaryn` user, private runtime directory, read-only system/home protection, a root-owned environment file, and supervisor restart semantics that do not loop automatically on protocol/configuration exit `2`.

It is for disposable/test deployment only until the live Google Drive gate and later production-specific qualification are complete.

## Development validation

The ordinary zero-based workflow runs compile checks, deterministic model tests, REST-adapter tests, crash matrices, lost-response matrices, process-lock tests and CLI smoke checks. These are development evidence only.

Real Google Drive acceptance must use a separate disposable Hub and a separately guarded acceptance path. Never point development acceptance at the production/personal Hub.
