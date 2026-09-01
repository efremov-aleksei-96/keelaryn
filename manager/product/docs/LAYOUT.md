# Keelaryn layout

## Canonical installed layout (4.4+)

```text
keelaryn/
├── manager/
├── hub/
└── tests/
```

The same component naming is intended for a future GitHub repository: `manager/`, `hub/`, `tests/`, with optional `docs/` and `tools/`. Directory names are lowercase for cross-platform portability.

## Compatibility

Pre-4.4 sibling directories `Keelaryn__Manager` and `Keelaryn__Hub` are legacy installation-layout names only. They are never defaults for new installations after the migration. Wire-format/package names that contain `Keelaryn__Hub` or `Keelaryn__Manager` remain compatibility contracts until a separate protocol migration.

## Migration safety

`MIGRATE_LAYOUT.cmd` uses copy-and-activate: it closes Obsidian, verifies the canonical baseline, copies Manager and Hub into staging, compares the full Hub tree and managed Manager content, activates `keelaryn/manager` and `keelaryn/hub`, writes a v2 binding, and runs SelfTest plus Doctor from the new Manager. Legacy directories are not deleted.

`FINALIZE_LAYOUT.cmd` is a separate explicit step. It requires a clean Doctor on the canonical installation and archives the legacy directories under `keelaryn/tests/legacy-layout-backup/<timestamp>/` rather than deleting them.

## Tests workspace

Development work under `tests/` uses only role-based directories that have an active purpose:

```text
tests/
├── work/
├── results/
└── legacy-layout-backup/   # on demand only
```

`work/` contains disposable candidate/runtime state. `results/` contains durable gate summaries, benchmark reports and logs. Synthetic fixtures live inside the current worktree instead of a permanent `fixtures/` directory; failed/rejected status is recorded under `results/` instead of a separate `rejected/` tree. `PREPARE_TESTS.cmd` creates/validates the active workspace and leaves pre-existing unclassified entries untouched.
