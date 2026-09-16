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

## Development validation

The ordinary zero-based workflow runs compile checks, deterministic model tests, REST-adapter tests, crash matrices and lost-response matrices. These are development evidence only.

Real Google Drive acceptance must use a separate disposable Hub and a separately guarded acceptance path. Never point development acceptance at the production/personal Hub.
