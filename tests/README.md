# Tests

Local development uses two role-based directories:

- `work/` — disposable candidate trees, generated fixtures, fault-injection targets and benchmark runtimes;
- `results/` — durable summaries/transcripts when local evidence needs to be retained.

Both are ignored by Git except for their boundary README files. Do not commit real Hub checkpoints or instance-specific transports.

The installed Manager can initialize the local layout with `manager/PREPARE_TESTS.cmd`.
