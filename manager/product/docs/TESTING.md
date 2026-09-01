# Keelaryn development tests workspace

The canonical local development root is `keelaryn/tests`. It is intentionally small and role-based:

```text
tests/
├── work/
├── results/
└── legacy-layout-backup/   # only when legacy layout finalization actually needs it
```

`work/` is disposable. Candidate packs, temporary Hub copies, generated fixtures, fault-injection targets and benchmark runtimes belong under `work/manager-<version>/`. A completed worktree may be deleted after the candidate has either been promoted and rebuilt from production or formally rejected with its durable evidence preserved.

`results/` is durable. Every Windows gate writes its summary, transcript and raw Doctor benchmark reports under `results/manager-<version>/`. A failed/rejected candidate is represented by the result status and retained evidence; there is no separate `rejected/` directory.

Persistent `fixtures/` are not created by default. Synthetic fixtures are generated inside the active worktree so they cannot silently become stale. Add a shared fixture directory only when a future test genuinely needs a versioned, reusable corpus.

`legacy-layout-backup/` is reserved for `FINALIZE_LAYOUT.cmd` and is not created by ordinary development tests.

Run `PREPARE_TESTS.cmd` from the installed canonical Manager to create/validate `work/` and `results/` and write `tests/WORKSPACE.json`. Existing unclassified top-level entries are reported but never moved or deleted automatically.
