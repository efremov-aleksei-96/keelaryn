# Repository model

Keelaryn separates repository source, release/distribution artifacts and installed runtime state.

## Canonical repository

```text
keelaryn/
├── manager/
├── hub/
└── tests/
```

`manager/` is product source. Personal Hub data and machine-local Manager state are never repository source.

## Manager source/install mapping

From Manager 4.8.7 the canonical managed source and installed product use the same physical product paths:

```text
manager/
├── KEELARYN.cmd
├── README_FIRST.md
├── product/
│   ├── install/INSTALLATION.json
│   └── runtime/Keelaryn__Manager.ps1
└── compat/commands/
```

Machine-local installation state is placed under `manager/state/` and is deliberately absent from repository/source artifacts.

Manager UPDATE artifacts retain a narrow transition envelope (`Keelaryn__Manager.ps1`, `_manager_manifest.json`, `_manager_version.txt`) so supported older Manager package validators can enter the canonical runtime safely. Those transport-only paths are never part of `product/install/INSTALLATION.json` and are absent from the final managed installation after update/finalization.

## Distribution

DISTRIBUTION contains the canonical final managed tree plus the layout-root `keelaryn/Keelaryn.cmd`. A fresh canonical installation initializes `manager/state/` on first run; no personal state is packaged.

## Tests

Repository `tests/` owns reusable harness source, disposable work and durable results. Reusable Manager gate source lives under `tests/framework/manager-gate`; generated gate ZIPs use `manager-<version>.zip` for `UNPACK_MANAGER_GATE.cmd`. Personal production Hub data is never Manager development source.
