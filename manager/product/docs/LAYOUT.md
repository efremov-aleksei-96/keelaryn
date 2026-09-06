# Keelaryn layout

Canonical local layout:

```text
keelaryn/
├── Keelaryn.cmd
├── manager/
├── hub/
└── tests/
```

Directory names are lowercase. Legacy `Keelaryn__*`, `Core__*` and prefixed filesystem names are compatibility/migration names only.

## Manager physical layout

Manager 4.8.7 finalizes physical organization:

```text
manager/
├── KEELARYN.cmd
├── README_FIRST.md
├── product/
│   ├── install/
│   │   └── INSTALLATION.json
│   ├── runtime/
│   │   └── Keelaryn__Manager.ps1
│   ├── tools/
│   ├── docs/
│   ├── governance/
│   ├── migrations/
│   └── starter/
├── compat/
│   └── commands/
└── state/
    ├── baseline/
    │   └── Keelaryn__Hub_CURRENT.zip
    ├── inbox/
    ├── logs/
    ├── history/
    ├── releases/
    ├── work/
    ├── binding.json
    └── layout.json
```

`binding.json` and CURRENT exist only when applicable. `state/` is machine-local runtime state, not repository source. It is physically separated rather than hidden in the Manager root.

Historical root command aliases and the root runtime bootstrap are transition artifacts, not the canonical layout. The 4.7.2-compatible UPDATE envelope may temporarily materialize them during installation; the 4.8.7 filesystem-finalization transaction removes them, validates the canonical `state/` paths, and restarts the runtime before the update command completes.

## Legacy layout migration

Advanced > Migrate canonical layout handles older pre-`keelaryn/{manager,hub,tests}` installations. Manager filesystem state finalization is a separate 4.8.7 transaction and does not mutate Hub portable source.

## Tests workspace

`tests/work/` is disposable candidate/runtime state. `tests/results/` contains durable gate summaries, benchmark reports and logs.

### 4.8.7 legacy-parent log handoff

The 4.7.2 -> 4.8.7 self-update crosses a live legacy parent process. Phase 1 moves the canonical log tree to `state/logs` but temporarily recreates an empty hidden root `_logs` directory so the waiting 4.7.2 parent can write its final completion record after the new runtime returns. The next independent 4.8.7 invocation merges that handoff log into `state/logs`, removes root `_logs`, and clears `legacy_log_handoff_pending` in `state/layout.json`. This handoff is transition-only and is not part of the final filesystem contract.
Distribution-only provenance is physically organized under `product/install/DISTRIBUTION_MANIFEST.json`. It is not canonical managed source and does not appear as a separate Manager-root object after extraction.
