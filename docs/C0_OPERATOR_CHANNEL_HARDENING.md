# C0 OperatorChannel hardening

Status: IN PROGRESS

## Goal

Routine autonomous development must not require Gateway to log in as root.

Target:

```text
ChatGPT
→ Gateway
→ keelaryn-vps-ops
→ SSH as keelaryn-ops
→ unprivileged routine development
```

A separate root/admin channel remains temporarily available for exceptional host administration until the non-root path is proven.

## Why not reuse the existing `keelaryn` account

The current `keelaryn` account is a service identity:

- UID 996;
- home `/nonexistent`;
- shell `/usr/sbin/nologin`;
- password locked.

It remains a service account and is not converted into an operator login.

## SSH prestate

Observed effective SSH policy:

- `PubkeyAuthentication yes`;
- `PasswordAuthentication no`;
- `KbdInteractiveAuthentication no`;
- `PermitRootLogin without-password`;
- authorized keys use normal per-user `.ssh/authorized_keys`.

Root currently has two authorized keys:

1. maintainer key fingerprint `SHA256:rcBMGtftkOpueFZrjd1gk9GKT335RaSP83ajS1E2EvE`;
2. existing Gateway root identity fingerprint `SHA256:5IBhCk6xyeiYb1Hj+JSbZj4Z2G5oOW4lud2w+5popNQ`.

## New Gateway identity

Created endpointless/key-first Gateway server:

- name: `keelaryn-vps-ops`;
- ID: `srv_01M3A22AVW9ZVAEBPPYHQ2DJCN`;
- SSH username: `keelaryn-ops`;
- status: `awaiting_endpoint`;
- Gateway identity: `sid_01M3A22DVSHRZ7HPQJY6CJ35FR`;
- public-key fingerprint: `SHA256:7H0JSU59UMcYvTUsZAiUK3b7pa6fF8UU+C/peYO4R0M`.

The endpoint is intentionally not assigned until the account/key exists on the VPS.

## Privilege policy

Initial `keelaryn-ops` gets **no sudo**.

This is deliberate. Routine source checkout, tests, builds, logs under owned development directories and network diagnostics do not require root.

Privileged host mutations remain exceptional and use the existing root admin channel until evidence justifies a narrowly bounded sudo surface.

Do not grant `systemctl`, shell, filesystem utilities or ALL via broad passwordless sudo merely to make routine development convenient.

## Next transaction

1. Create `keelaryn-ops` as a locked-password login account with home and `/bin/bash`.
2. Install the new Gateway public key only for that user.
3. Verify exact fingerprint and account metadata.
4. Assign endpoint `138.124.242.44:22` to the pending Gateway server with independently verified ED25519 host fingerprint `SHA256:P1+i/M2gFIZHMiaN+gJ0rv0Bpp96wv1ICjM90sRQ4zw`.
5. Verify non-root Gateway execution.
6. Keep root Gateway untouched until a later independent decision.


## Non-root Gateway verification result

Gateway key authentication is **verified** for `keelaryn-vps-ops`.

All three VPS host-key algorithms were independently read through the already-trusted root channel and pinned exactly:

- RSA: `SHA256:ZVwLKEE+YKp7mJ9Yy0UuJJT8y0d/Kh9F2MiyIbZgdVc`;
- ECDSA: `SHA256:MTcvSxd3RyQ0PzS72EN0W1/rnXPoQvFqBVUa04eqLSU`;
- ED25519: `SHA256:P1+i/M2gFIZHMiaN+gJ0rv0Bpp96wv1ICjM90sRQ4zw`.

Verification job `job_01M3A8K3WHJ1SBPTXW9NNEYP5J` succeeded.

However, the current Gateway remote execution layer is unusable through this non-root identity:

- SSH journal repeatedly records `Accepted publickey` and an opened PAM session for `keelaryn-ops`;
- root-side `runuser -u keelaryn-ops` successfully launches `whoami`, `id` and `bash`;
- Gateway `execute_command` exits 125 before useful output;
- Gateway `execute_argv` reports that the remote argv helper stopped before launching the target;
- `list_available_shells`, `file.stat` and `file.read` fail through the same profile.

Therefore the blocker is classified as **Gateway non-root remote-helper/tooling behavior**, not a Linux account/SSH-key problem.

Disposition:

- do not grant broad sudo merely to satisfy the plugin;
- do not build another custom relay;
- keep `keelaryn-vps-ops` and its key for future retest;
- continue current development through the existing root Gateway channel as a temporary tool-specific exception;
- Keelaryn product architecture remains independent of Gateway.
