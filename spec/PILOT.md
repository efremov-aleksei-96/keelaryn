# Limited Real-Hub Subset Pilot

This document defines the MVP pilot boundary for testing zero-based Keelaryn with a deliberately limited copy of real Hub material.

## Purpose

The pilot proves that exact bytes selected from a read-only copy of an existing Hub can be moved through the zero-based publication protocol into a fresh disposable Google Drive Hub without exposing private payload bytes to GitHub, CI artifacts or repository history.

The pilot is development evidence. It is not production migration and does not authorize mutation of the production/personal Hub.

## Source boundary

The source Hub is never a write target for pilot tooling.

The pilot starts from a local copy or other independently disposable copy of the source material. Selection is explicit through `PILOT_SOURCE.json`; there is no recursive implicit import.

`PILOT_SOURCE.json` uses schema `keelaryn.pilot-source.v1` and contains:

- one `pilot_id`;
- 1..32 explicit entries;
- each entry binds one relative source path to one canonical-root target name.

MVP pilot targets are canonical-root files only. Nested canonical paths are deliberately not supported by the pilot importer.

The pack builder rejects symlinks/reparse-style paths, non-regular files, traversal, duplicate source/target identities, files larger than 16 MiB and packs larger than 32 MiB.

## Private pack

`python -m keelaryn_core.pilot_cli pack-build` creates a new immutable private pack:

```text
<pack>/
├── PILOT_PACK.json
└── files/
    ├── import-001.bin
    └── ...
```

`PILOT_PACK.json` uses schema `keelaryn.pilot-pack.v1` and binds every payload by operation ID, source path, target, exact SHA-256 and byte length.

The pack directory is private test material. It must not be committed, uploaded as a GitHub Actions artifact, placed in SOURCE/DISTRIBUTION/UPDATE/AI_CONTEXT, or treated as generic fixture data.

`pack-build` and `pack-verify` emit only a sanitized summary: schema, pilot ID, pack SHA-256, file count and total bytes. Source paths, canonical target names and payload contents are intentionally absent from normal CLI output.

## Target boundary

The importer may target only a fresh disposable zero-based Hub. It requires:

- one valid zero-based Hub structure;
- clean READY/SAFE `MASTER.json` at canonical epoch 0 before Ready Change preparation;
- empty `canonical/`;
- no unrelated material in Reconciliation changes/postcheck areas;
- no active transaction belonging to another change.

The production/personal Hub is never a pilot import target.

## Publication path

The importer does not write canonical bytes directly. It converts the verified private pack into the ordinary protocol:

```text
verified private pack
  -> Reconciliation changes/<pilot_id>/prepared
  -> exact CHANGE.json
  -> READY.json published last
  -> DriveTransactionFactory
  -> DrivePollingService / DriveCoreRunner
  -> deterministic postcheck
  -> COMMITTED or mandatory rollback
  -> Ready consumption / locator cleanup
  -> clean READY
```

Every imported operation is `ADD` because the disposable pilot Hub starts with an empty canonical directory.

The deterministic pilot postcheck emits PASS only when the canonical directory exactly equals the verified private pack by names, byte lengths and SHA-256 fingerprints. Any mismatch yields FAIL and therefore mandatory rollback through the normal Core path.

## Restart and uncertainty

Pilot preparation uses deterministic names and exact byte verification so lost responses can be resolved by re-observation.

Once Core authority exists, restart uses the normal active locator and immutable transaction bundle. A temporary zero-`MASTER.json` state during a copy-on-write MASTER transition is treated as a recoverable Core gap, never as a fresh Hub bootstrap opportunity.

A completed pilot is idempotent: rerunning the same exact pack against the same completed disposable Hub returns the same terminal evidence without publishing another canonical epoch.

## Evidence

Successful pilot evidence is sanitized and contains only:

- schema `keelaryn.pilot-import-evidence.v1`;
- pilot ID;
- private pack SHA-256;
- file count and total byte count;
- terminal outcome (`COMMITTED` or `ROLLED_BACK`);
- final canonical epoch.

Private source paths, canonical target names, Drive object IDs and payload bytes are not part of public/development evidence.

## CLI

Build and verify locally without Google credentials:

```bash
PYTHONPATH=core python3 -m keelaryn_core.pilot_cli pack-build \
  --source-root <read-only-copy-root> \
  --source-manifest <PILOT_SOURCE.json> \
  --output-dir <new-private-pack-dir>

PYTHONPATH=core python3 -m keelaryn_core.pilot_cli pack-verify \
  --pack-dir <private-pack-dir>
```

Import into one exact disposable Drive Hub using the same environment-only OAuth contract as the other Drive CLIs:

```bash
PYTHONPATH=core python3 -m keelaryn_core.pilot_cli import \
  --pack-dir <private-pack-dir> \
  --hub-root-id <disposable-drive-hub-id>
```

The pilot CLI is included in exact-head VPS payload qualification, but private pilot packs are never included in that payload.
