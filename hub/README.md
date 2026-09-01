# Hub runtime boundary

This directory is intentionally not a tracked example Hub.

A real Keelaryn Hub is **instance-owned state**, not product source code. Generate a disposable or new instance with:

```text
..\manager\GENESIS_KEELARYN__HUB.cmd
```

The repository `.gitignore` ignores everything under `hub/` except this README so personal instance state cannot be committed accidentally.

For tests, generate sanitized disposable instances under `tests/work` rather than copying a personal production Hub into the repository.
