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

## Limited real-Hub subset pilot

The pilot path is deliberately private and disposable. It never writes the production/personal Hub and never uploads selected source bytes to GitHub or CI artifacts.

Build and verify one immutable private pack from an explicit allowlist over a read-only local copy:

```bash
PYTHONPATH=core python3 -m keelaryn_core.pilot_cli pack-build \
  --source-root <read-only-copy-root> \
  --source-manifest <PILOT_SOURCE.json> \
  --output-dir <new-private-pack-dir>

PYTHONPATH=core python3 -m keelaryn_core.pilot_cli pack-verify \
  --pack-dir <private-pack-dir>
```

Import the verified pack into one exact fresh disposable Drive Hub:

```bash
PYTHONPATH=core python3 -m keelaryn_core.pilot_cli import \
  --pack-dir <private-pack-dir> \
  --hub-root-id <disposable-drive-hub-id>
```

Normal pilot CLI output is sanitized: it contains hashes/counts/outcomes rather than private payload bytes or source/target names. The complete protocol and privacy boundary are defined in `spec/PILOT.md`.

## VPS development deployment

The **single canonical** VPS deployment source, including hardened systemd units, secret-free environment template, deterministic payload builder/materializer and rollout/rollback contract, lives under:

```text
deploy/zero-based-vps/
```

Materialized releases are bound to exact source commit + payload SHA-256 and are published read-only. Do not maintain a second deployment template under `core/` or elsewhere.

This deployment tooling is for disposable/test deployment until the live Google Drive gate and later production-specific qualification are complete.

## Development validation

The ordinary zero-based workflow runs compile checks, deterministic model tests, REST-adapter tests, crash matrices, lost-response matrices, process-lock tests, deployment-contract tests and CLI smoke checks. It also builds the VPS payload twice for the exact `GITHUB_SHA`, proves byte identity, materializes it against the same source/payload identity, validates the read-only runtime without bytecode writes and emits compact short-lived evidence. These are development evidence only.

Real Google Drive acceptance must use a separate disposable Hub and a separately guarded acceptance path. Never point development acceptance at the production/personal Hub.
