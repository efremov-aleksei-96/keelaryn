# Keelaryn MCP — portable component (development only)

**Owner:** Keelaryn Engine, `efremov-aleksei-96/keelaryn`, directory `mcp/`.
**Status (2026-11-12):** local `stdio`, read-only `local-ro`, bounded directory traversal and symlink-free config/state ancestry are implemented in `dev/mcp-portability`. Direct `benchmark_*` operations now use checked state directory descriptors, with the prior unsafe-create side effect fixed and synthetic tests passed. Source rollback/restore were tested previously. This remains **unqualified development code**, not a production installation or replacement for the running VPS service.
**Canonical component entrypoint:** this README and the source files under `mcp/src/`. No separate STATE/WORKLOG is required.

## Boundaries and purpose

KeelarynOS owns common architecture and information standards. Domain OS/projects own their factual data and canonical sources. This **Keelaryn MCP** component implements bounded file access, not a competing canonical data store or a LifeOS coordinator. The existing Windows-first `manager/` and its `INSTALLATION.json`, Gate Framework, release identities and qualification remain separate and unchanged.

Core interface: five generic MCP tools — `list_files`, `read_files`, `search_files`, `edit_files`, `delete_files`. Seven synthetic/benchmark tools are **opt-in for local mode** and **remain enabled by default for legacy system mode**; both visibility and direct invocation are gated. The operating model is **standard JSON-RPC MCP over stdio**; a particular AI, Google Drive, VPS provider or tunnel is not mandatory for the protocol itself.

The original VPS source was preserved exactly in the first five commits on this branch. Subsequent commits added configurable paths and a **read-only local directory backend** with operator-controlled roots and allowlists. This backend is verified only against synthetic fixtures on the existing VPS OS; no real project data or clean independent Linux host has been tested. Do not infer production readiness from those checks.

## Evidence and source identity (2026-11-12)

Source originals were read from `/usr/local/lib/keelarynos-mcp-benchmark/` on the existing VPS, syntax-checked with Python's AST parser, screened for obvious embedded secrets, and copied byte-for-byte to this branch with individual readback verification **before the later portability edits**. The hashes below identify that baseline, not the revised development code.

| File in `src/` | Original VPS SHA-256 (baseline) |
| --- | --- |
| `synthetic_stdio.py` | `e17ccde486be7e2d6a7d11f5bfbcbaadd7375d3eba16d6ff6e022d659d100f9a` |
| `fs_tools.py` | `c2a7c9aefd57db012e556c2d642532a5910b904108d3abc7ef23cdd1889cf26e` |
| `file_scopes.py` | `592b1db8d75e625fe8506b2ecadd66656b8d6a76fee0783f70531e1e0aadf00b` |
| `drive_live.py` | `baea3f2795d49d3a491a36c470afe71068bf2cc6bdfbe611bd6ec14839621d1d` |
| `preflight.py` | `fcdd3abb3872603efb9b7f2e97768a7da7521cbafd8784ac8855958daa40b9f6` |

The specialized `musiclibrary_ro.py` and binary `tunnel-client` were **not** copied. There are no credentials, project data, Drive snapshots, production configurations or instance state in this component.

A direct stdio probe on the **existing VPS**, with no tunnel and no server file changes, returned MCP initialize, 12 tools and a successful synthetic echo. This proves local protocol invocation there, **not** a clean install on another machine, general offline capability or safe canonical writes.

The running VPS service used `/etc/keelarynos-mcp-benchmark/file-scopes.json` (three scopes: synthetic read/write, MusicLibrary and ArmenianLearning noncanonical pinned read-only snapshots) and `/var/lib/keelarynos-mcp-benchmark/`. An optional Drive live read-only adapter is present in code but no live OAuth/Drive scope is enabled. Production Drive writes are disabled.

## Verified development checkpoint (2026-11-12)

Four modules (`file_scopes.py`, `fs_tools.py`, `preflight.py`, `synthetic_stdio.py`) now support `KEELARYN_MCP_STATE_DIR` and/or `KEELARYN_MCP_CONFIG` with the previous VPS paths as defaults. `KEELARYN_MCP_MODE=system` (default) keeps root-owned scope configuration and existing systemd isolation expectations. `KEELARYN_MCP_MODE=local` requires an unprivileged user, a user-owned configuration without group/other permissions, and a private state root; a one-scope synthetic-only registry is permitted for that mode.

The new `mcp/tests/test_local.py` was run as the unprivileged `nobody` user inside a disposable temporary directory, using the **exact pinned development commit** `fe89365450ab2eac1c5b950575609f6b09d6de23` downloaded from GitHub. It returned `LOCAL_STDIO_SYNTHETIC_SMOKE_PASS`: initialize, tool discovery, synthetic create/read/delete, rejection of stale SHA-256, denied project and traversal path. All six source/test modules passed AST parsing. Temporary test files were removed. The running systemd service and its configuration were not changed. This test was performed on the **existing VPS OS in an isolated directory**, not on another Linux host, and it does not prove race-free concurrent writes or production data safety.

To repeat under an **unprivileged Linux account** with Python 3.12, run `python3 -B mcp/tests/test_local.py` and `python3 -B mcp/tests/test_local_ro.py`. Both tests create and clean synthetic temporary files. Do not run as root.

## Local directory read-only scope — implemented, synthetic-verified

In `KEELARYN_MCP_MODE=local`, an operator-owned scope registry may contain a `local-ro` entry. Example **configuration only** (replace the root with a real directory owned by the unprivileged service user; do not point this at important data before independent validation):

```json
{
  "schema": "keelarynos_mcp_file_scopes_v1",
  "scopes": {
    "synthetic": {
      "backend": "workspace",
      "access": "read-write",
      "description": "Ephemeral synthetic-only benchmark files"
    },
    "NotesPilot": {
      "backend": "local-ro",
      "access": "read-only",
      "snapshot_only": false,
      "canonical": false,
      "root": "/home/USER/keelaryn-pilot",
      "allow": ["docs/", "PROJECT.md"]
    }
  }
}
```

The `synthetic` entry is **still mandatory** under the inherited registry schema and only controls the isolated benchmark workspace; it is **not** access to real projects. No secrets or live folder data are stored in Git.

The MCP caller can select only the preconfigured project and relative paths. A `local-ro` root must be a canonical absolute path owned by the effective unprivileged user, without group/other write access. Config must be owned by that user and private. Ancestors and nested directories are checked; root and child symlinks are rejected using directory descriptors and `O_NOFOLLOW`. Files must be ordinary, single-link, user-owned, non-group/world-writable UTF-8 `.md`, `.csv`, or `.json`. Relative segments use the existing conservative ASCII naming restrictions and additionally reject hidden/sensitive names. Exact files or directory prefixes may be allowlisted; blanket root access is not accepted.

The backend supports `list_files`, `read_files` (including existing character paging) and `search_files`. `edit_files` and `delete_files` are denied regardless of arguments. A single document is capped at 64 KiB, reads at 256 KiB total, and each directory listing at 1000 entries. Search now also has **global** caps of 100 read documents, 100 visited directories and 1000 visited directory entries. When a global search cap is reached, it reports `truncated`; directories exceeding the per-directory limit fail closed. Search traverses open descriptor-relative child directories under a single pinned root descriptor; a multi-file read likewise pins the root. The file reader now compares permissions, owner and link count before/after reading, in addition to size and timestamps.

This protects the tested path boundaries, but **does not create a transactional snapshot** or defend against every in-place rewrite by another process sharing the same user identity. Concurrent writes, mount/bind-mount manipulation, broader adversarial environments, and host-specific permission cases are **not fully qualified**. The `canonical` flag is operator-declared metadata; it does not prove a local copy is current.

### Latest verified test

GitHub development commit `6bb2b4ca3ca2a92d565f81b016bf870fc45e016f` was read as a pinned source revision on 2026-11-12. All **eight** Python source/test files passed AST parsing. Inside an automatically removed disposable directory, tests run as unprivileged `nobody` returned:

- `LOCAL_STDIO_SYNTHETIC_SMOKE_PASS`: existing synthetic stdio regression.
- `LOCAL_RO_MCP_INTEGRATION_PASS`: actual MCP initialize/discovery, local allowlisted list/read/page/search, and rejection of out-of-scope paths, symlinks, sensitive names, writes, deletions, unsafe file/directory permissions, symlinked roots and a writable registry.

Only synthetic files were involved. Temporary source/test directories were removed. The production systemd service remained active with its prior MainPID `2636967`; no running service, installed Python file, production configuration, user data or credential was changed. This is **not** a clean deployment on an independent machine, exhaustive adversarial testing or proof of conflict-safe writes.

### Targeted safety audit — verified 2026-11-12

**Confirmed findings and fixes:**

1. The previous search only limited *read files*; arbitrarily many empty directories or name entries could still be visited. Fixed with global directory/entry budgets in `src/local_ro.py`.
2. The previous search reopened the configured root by pathname for each recursive directory, potentially mixing two distinct same-owner roots if the pathname was replaced while a search ran. Fixed with a root FD pinned for the whole search and parent-FD-relative directory traversal; batched reads now pin their root too.
3. The previous file reader did not compare mode/owner/link-count metadata *after* reading. Now compares them with the initial `fstat` (in addition to length, mtime and ctime). This detects observed changes but is not proof of immutable content under all concurrent writers.

**Adversarial tests** in existing `tests/test_local_ro.py` deterministically replace a file or directory with a symlink at the moment of `open`, and swap the root pathname after initial enumeration. The symlinks fail to open; the pinned-root search ignores the replacement tree. Tests also check read size 64 KiB, batch size 256 KiB, 100-file search cap, 100-directory global cap, 1000-entry global cap, 1000-entry per-directory rejection, allowlist denial, unsafe file/directory/config permissions, no edit/delete, and no changes to the synthetic originals.

**Executed test evidence:** read pinned GitHub commit `61173689e80d22d2ef3782fa88be6743b9646216` into a temporary directory on the **existing VPS**, checked AST parsing of 8 Python files, and ran as unprivileged `nobody`. Both `test_local.py` and `test_local_ro.py` exited 0. Output included `LOCAL_STDIO_SYNTHETIC_SMOKE_PASS`, `LOCAL_RO_ADVERSARIAL_LIMITS_PASS`, `LOCAL_RO_MCP_INTEGRATION_PASS`. Temporary copies were removed. Running service was still `active` at MainPID `2636967`. No installed server files or real user data were modified. **Only these tests are verified**; an independent-host install remains untested and is deferred by operator choice (no additional Linux).

## Minimal target contract (PARTIALLY IMPLEMENTED)

- **Operator-defined paths (implemented for current entrypoints):** `KEELARYN_MCP_CONFIG` selects the scope registry and `KEELARYN_MCP_STATE_DIR` selects the state root, preserving previous VPS absolute paths as defaults. A user-supplied MCP request cannot select its own filesystem root.
- **Two safe ownership profiles (limited implementation):** system installation retains root-owned configuration and systemd sandboxing; local mode requires an unprivileged caller and a private user-owned configuration/state root. Local stdio and `local-ro` were verified only with synthetic fixtures. The validated path boundaries reject unsafe ownership, group/other writes and symlink traversal; further adversarial review remains required.
- **Explicit scopes:** unlisted projects are inaccessible; real sources default to read-only; exact allowed roots and relative paths, file types, maximum read sizes and operation limits are enforced by the server. Do not expose arbitrary command execution or a shell tool.
- **Transport:** direct `stdio` is the baseline. Optional OpenAI Secure MCP Tunnel launches the same Python server as a child process. No public inbound port, database, Docker, web dashboard or second long-lived MCP daemon is required.
- **VPS supervision:** one systemd service, with `DynamicUser`, `StateDirectory`, `ProtectSystem=strict`, `ProtectHome`, `NoNewPrivileges`, `UMask=0077`, and secrets passed via systemd `LoadCredential`. For a stdio tunnel binding, **never run two tunnel-client instances against the same tunnel ID concurrently**.
- **Writes:** creation must fail if a target exists; replacement and deletion require a content/version precondition and an effective *atomic* protection from concurrent writers for that backend. The current check-SHA-then-`os.replace` approach is NOT general compare-and-swap against independent concurrent writers. Multi-file atomicity is not guaranteed. Real canonical sources remain read-only until backend-specific conflict safety and authorized ownership are proven. Google Drive write remains disabled.
- **Offline scope:** local Markdown/CSV/JSON can be worked with without any provider after a separately validated clean install. Cloud-origin content and remote connectors require a network; format portability does not imply an up-to-date local mirror.

## External tunnel is optional, and independently versioned

The installed VPS `tunnel-client` identifies as OpenAI `v0.0.20`, Git commit `c2144b0904980bcbae2636cdca4f4167e9818e0b`. The official release tag points to that commit. The official `tunnel-client-v0.0.20-linux-amd64.zip` was fetched **in memory** and verified against its published SHA-256 `2f06ce5a17425c74a827e7038692936e973ae388e7eec728c40efee1fb5f139d`; its single extracted binary matched the VPS executable byte-for-byte (SHA-256 `447e237f2030a0f0dab908b0a2f61fafce878d7da341f741e79245051319a09e`).

Source: https://github.com/openai/tunnel-client/releases/tag/v0.0.20

Tunnel config includes an OpenAI control-plane runtime credential and tunnel ID, which are **not** part of the MCP repository or standalone local mode. The control plane and ChatGPT connectivity are provider-dependent; the underlying stdio MCP is not. Do not copy a working VPS token or profile when deploying another instance.

## Minimal deployment design

1. Clone or obtain a fixed source revision; use Python 3.12 and stdlib for the file core. No PyPI dependency is needed by the copied Python modules.
2. For local use, pass a user-owned restricted config and state location and launch MCP stdio from the client. The `local-ro` backend is implemented and tested with synthetic directories; no live local canonical scope is authorized or validated.
3. For VPS/ChatGPT, install the verified Python source and a root-owned scope registry, then configure a **single** protected systemd service that supervises the pinned OpenAI tunnel (when required) and its Python child. Provide secrets separately; do not check them into source control.
4. Verify with synthetic data before enabling any real source; do not alter or switch the production VPS until a separate install and rollback have passed.

A fresh Linux installation is accepted only when: stdio initialize/discovery and all five tools work; invalid paths and permissions fail closed; read/write concurrency controls are proven in the allowed scope; source/config/state separation survives restart; systemd privilege restrictions and recovery work; no personal/canonical data are used in mutable tests; Windows Manager identity and behavior are unchanged.

## Local Linux installation, direct stdio and recovery (documented 2026-11-12)

This is an **operator runbook**, not a deployment order. **No additional Linux, Docker, daemon, API key, tunnel, Google Drive, or sudo** is needed for direct local `stdio`. Run as an **unprivileged** user with Python 3.12 and Git; the initial Git clone requires internet, but the copied source and synthetic stdio require none thereafter. Do not run these commands inside the working VPS installation or against real project data.

### 1. Obtain a known source revision

```sh
# Run as your ordinary Linux account; the destination must not already exist.
git clone --single-branch --branch dev/mcp-portability \
  https://github.com/efremov-aleksei-96/keelaryn.git "$HOME/keelaryn"
cd "$HOME/keelaryn"
git rev-parse HEAD                # Record this exact commit for recovery.
python3 --version                 # Target: Python 3.12.
```

Cloning the existing Git repository (not a ZIP or a second repository) retains the development branch's history locally, including prior audited commits. The previous historical audit revision `d23ef959597ba688c5a79b8ac7ac8b08b626566f` **predates the 2026-11-12 symlink-ancestor fix and must not be recommended for active local-mode rollback**. The confirmed hardened **source** checkpoint is `6452bf4412e722e19e0d752cf445b45b5c0aa398` (code and regression tests). If recovery to that exact checkpoint is needed, check `git status --porcelain` is empty and then use `git switch --detach 6452bf4412e722e19e0d752cf445b45b5c0aa398`. **Do not overwrite an existing checkout or user edits.**

### 2. Set up one private, synthetic-only scope

```sh
umask 077
CONF="$HOME/.config/keelaryn-mcp"
STATE="$HOME/.local/share/keelaryn-mcp"
install -d -m 700 "$CONF" "$STATE"
set -C                            # Noclobber: refuse overwriting an existing registry.
cat > "$CONF/file-scopes.json" <<'JSON'
{
  "schema": "keelarynos_mcp_file_scopes_v1",
  "scopes": {
    "synthetic": {
      "backend": "workspace",
      "access": "read-write",
      "description": "Ephemeral synthetic-only benchmark files"
    }
  }
}
JSON
chmod 600 "$CONF/file-scopes.json"
export KEELARYN_MCP_MODE=local
export KEELARYN_MCP_CONFIG="$CONF/file-scopes.json"
export KEELARYN_MCP_STATE_DIR="$STATE"
python3 -B mcp/src/preflight.py
```

Expected preflight line: `SYNTHETIC_MCP_SANDBOX_PREFLIGHT_PASS`. `CONF` and `STATE` must remain user-owned; no group/other access is permitted to state, and the registry is mode 0600. **All parent components of the local config and state paths must be actual directories, not symlinks; config/state parents must be operator-owned and not writable by group/others.** The setup command creates the necessary parent directories before preflight. A noncanonical, symlinked or untrusted parent must produce an error rather than be bypassed with relaxed permissions. `set -C` intentionally refuses to overwrite a registry from a previous interrupted setup: inspect an existing registry before retrying. The `synthetic` scope is deliberately writable **only inside the isolated state workspace**. No live `local-ro` root or canonical project is enabled.

### 3. Test and invoke stdio

```sh
python3 -B mcp/tests/test_local.py
python3 -B mcp/tests/test_local_ro.py
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"manual-probe","version":"1"}}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"list_files","arguments":{"project":"synthetic","path":""}}}' \
  | python3 -B mcp/src/synthetic_stdio.py
```

There should be two JSON-RPC replies, including protocol `2025-06-18` and a synthetic file listing. These tests create and remove **only temporary synthetic fixtures**; do not run as root.

For actual local use, configure an MCP-capable client to **start** `/usr/bin/python3` with arguments `-B /ABSOLUTE/PATH/TO/keelaryn/mcp/src/synthetic_stdio.py`, passing `KEELARYN_MCP_MODE=local`, the absolute `KEELARYN_MCP_CONFIG` path and absolute `KEELARYN_MCP_STATE_DIR` path in its child environment. Use the actual Python path if different. The client owns stdin/stdout: **do not** launch a standalone stdio daemon or expose an HTTP port. The `preflight.py` command runs **before** client startup, not inside the MCP stdio stream.

### 4. Recovery without a new service

Stop/close the MCP client first. Read `git status --porcelain` and `git rev-parse HEAD` in the source directory; do not delete, discard or overwrite unknown changes. Restore a prior known-good checked-out revision only if its commit is locally available and the working tree is clean:

```sh
cd "$HOME/keelaryn"
git status --porcelain
git switch --detach 6452bf4412e722e19e0d752cf445b45b5c0aa398
python3 -B mcp/src/preflight.py
python3 -B mcp/tests/test_local.py
python3 -B mcp/tests/test_local_ro.py
```

The previously prepared private config and state remain **outside Git** and are not reset or erased by a source checkout. If preflight rejects the registry, check its actual owner, permissions and **entire ancestor path** against the synthetic-only JSON and mode requirements above; do not relax permissions or silently replace unknown data. An old revision may be retained for historical comparison but is **not automatically safe for running a newly hardened local deployment**. Never `git reset --hard` or `rm -rf` a user state directory as a generic recovery step. Reopen the client only after tests and preflight pass. If a configuration has been expanded to include real read-only project files, reassess the full allowlist before use.

### Optional systemd **user** service for a future outbound tunnel — not local-only stdio

**Not installed or started. Not needed for standalone MCP.** Below is a *template*, not a drop-in active unit. It presupposes a separately installed verified OpenAI `tunnel-client` binary, a configured `main` stdio channel running the same Python entrypoint, a Tunnel ID, and a revocable **runtime** API key in a private file **outside Git**. The tunnel profile uses official `control_plane.api_key: file:/ABSOLUTE/PRIVATE/PATH/runtime.key`, never a literal key or admin credential. Its `mcp.commands` must contain `channel: main` and an **absolute** command such as `/usr/bin/python3 -B /ABSOLUTE/PATH/TO/keelaryn/mcp/src/synthetic_stdio.py`. The profile needs `config_version: 1` and the operator's actual tunnel ID and endpoint. Official reference: https://github.com/openai/tunnel-client/blob/v0.0.20/docs/configuration.md.

Illustrative `~/.config/systemd/user/keelaryn-mcp-tunnel.service` contents (do **not** create/enable on the working VPS):

```ini
[Unit]
Description=Keelaryn MCP optional outbound tunnel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Environment=KEELARYN_MCP_MODE=local
Environment=KEELARYN_MCP_CONFIG=%h/.config/keelaryn-mcp/file-scopes.json
Environment=KEELARYN_MCP_STATE_DIR=%h/.local/share/keelaryn-mcp
ExecStart=%h/.local/bin/tunnel-client run --profile-file %h/.config/keelaryn-mcp/tunnel-profile.yaml
Restart=on-failure
RestartSec=3
NoNewPrivileges=yes
UMask=0077

[Install]
WantedBy=default.target
```

Substitute actual secure binary/profile locations and validate the profile with the pinned tunnel client's `doctor --profile-file ... --explain` **before** any first activation. This user-unit illustration is different from the existing hardened system-level VPS unit (which uses `DynamicUser` and `LoadCredential`); do not switch that service to this template. User-unit runtime secret reference, service permissions, actual startup and health were **not** tested here. For a future system-level service, retain `DynamicUser`, `StateDirectory`, `LoadCredential` and existing hardened permissions; coordinate the current `synthetic_stdio.py` systemd state-root symlink assumption before changing unit/path names.

**Rollback if later enabled:** stop the optional tunnel unit, make sure there is no second tunnel process using its Tunnel ID, restore the last verified source/profile independently, validate preflight, then start only one instance. Never overlap stdio tunnel clients for one Tunnel ID. Network connectivity to the OpenAI control plane is the optional provider dependency; the core stdio mode stays provider-independent.

### Read-only validation scope

On **2026-11-12**, the operator commands were exercised with a temporary Git checkout of `dev/mcp-portability` at `d23ef959597ba688c5a79b8ac7ac8b08b626566f` and unprivileged `nobody` in a disposable `/tmp` home: `test_local.py` and `test_local_ro.py` passed, `preflight.py` passed, and a piped JSON-RPC initialize + synthetic list returned `RUNBOOK_MANUAL_STDIO_PASS`. A full single-branch clone also confirmed the earlier audited revision is available for offline source rollback. Test directories were removed. The systemd unit was syntax-parsed by `systemd-analyze verify`, which reported the expected missing illustrative tunnel-client executable; it was **not installed, started or authenticated**. The running VPS service kept MainPID `2636967`. No independent Linux deployment, real-data access or production qualification is claimed.

## Configuration ancestry and recovery — targeted verification (2026-11-12)

**Reproduced defect before the fix:** under a disposable unprivileged test account, the original local mode accepted `file-scopes.json` reached through a symlinked parent directory and accepted a state directory created through a symlinked parent (`SYMLINK_CONFIG_PARENT_ACCEPTED=True`, `SYMLINK_STATE_PARENT_ACCEPTED=True`). This contradicted the stated no-symlink boundary. No real source or system service was involved.

**Addressed in development branch only:**

- `src/file_scopes.py` now opens the local registry under a checked operator-owned **directory descriptor**, so symlinks and unsafe permissions in its parent/ancestor path are rejected. The system-mode root-owned registry semantics were left unchanged.
- `src/preflight.py` now creates and verifies the local state root and `workspace` using `O_DIRECTORY|O_NOFOLLOW` and `dir_fd`, rather than recursively creating paths through unchecked parents. The immediate parent must exist and be safe. The system-mode preflight path remains unchanged.
- `src/fs_tools.py` now independently validates the local synthetic workspace's complete ancestor chain before using its file handlers, including if a caller omitted preflight.
- `tests/test_local.py` exercises symlinked registry parent, group/world-writable registry parent, symlinked state parent, symlinked `workspace` and direct MCP calls through a symlinked state parent; expects rejection. The existing `test_local_ro.py` regression suite is retained.

**Tests actually executed:** using a disposable Git checkout at commit `6452bf4412e722e19e0d752cf445b45b5c0aa398` on the **existing VPS** as unprivileged `nobody`, `LOCAL_CONFIG_AND_STATE_PATH_SECURITY_PASS`, `LOCAL_STDIO_SYNTHETIC_SMOKE_PASS`, `LOCAL_RO_ADVERSARIAL_LIMITS_PASS` and `LOCAL_RO_MCP_INTEGRATION_PASS` all completed with zero exit code. A separate disposable **full clone**, switched to historical commit `d23ef959...` and back to `6452bf441...`, ran both historical and hardened synthetic tests, preserved the SHA-256 of its external configuration and left the state workspace intact (`LOCAL_SOURCE_ROLLBACK_AND_RESTORE_PASS`). The historical commit switch was a controlled test **only**, not a recommendation to deploy the older unsafe revision.

The live VPS systemd service remained `active` with MainPID `2636967`. Temporary source and test directories were removed. No changes were made to installed VPS Python, running config, real files, credentials or service state. A different Linux host, filesystem/mount namespaces, trusted checkout protections against other local writers, and actual user data remain **untested**. Symlink-free ancestry is enforced only for the checked local-path operations and does not establish a transactional filesystem snapshot.

## Direct benchmark handlers — verified safety repair (2026-11-12)

**Scope:** only the five `benchmark_*` filesystem handlers in `src/synthetic_stdio.py` when invoked directly over JSON-RPC without `preflight`. `read_synthetic_batch` and `benchmark_echo` are in-memory operations, not state-directory access. No actual project or credential file was used.

**Confirmed before the fix** with the existing development source in a disposable unprivileged fixture:

- `KEELARYN_MCP_STATE_DIR=/.../parent-alias/state`, with `parent-alias` a symlink to another synthetic directory, allowed **all five** benchmark handlers to create, read, edit, verify and remove synthetic files through that link. The local registry itself was private and valid; the bypass came from benchmark path checks, not the generic file handlers.
- A symlink **at the state root** caused `benchmark_create_files` to return an error but nevertheless create the named benchmark directory first (`SYMLINK_ROOT_SIDE_EFFECT=True`), because `WORK.mkdir()` preceded validation.

Both cases were reproduced and cleaned up solely under `/tmp` with an unprivileged test account. These are verified defects, not inferred vulnerabilities of the running systemd service.

**Minimal fix in `src/synthetic_stdio.py`:**

- Added `state_dirfd()`, which validates the entire local state path using the existing `local_ro.open_root` descriptor walker and checks local owner/private permissions **before any filesystem action**. System mode preserves the pre-existing explicitly recognized `DynamicUser` StateDirectory link behavior.
- Added `benchmark_dirfd(parent_fd)` to open only `filesystem-benchmark-20261111` with `O_DIRECTORY|O_NOFOLLOW` and verify directory ownership/private permissions.
- `create()` now checks and creates the benchmark directory **relative to the validated, open parent FD**, then verifies file contents through the same opened directory. A rejected root has **no create side effect**.
- `cleanup()` similarly checks and removes the fixed directory using the pinned parent FD; it checks directory identity before removing the name. All other disk-backed handlers use the guarded `dirfd()`. Existing synthetic file names, deterministic expected contents, public five generic MCP file tools and other project scopes are unchanged.

**Verified regression evidence:** cloned the exact development commit `3220435c750eb3cd57dca20cf95937b1752b718d` to a new, self-cleaning `/tmp` location on the **existing VPS**. The revised `mcp/tests/test_local.py` directly invoked all five benchmark handlers **without running preflight** and verified: legitimate synthetic create/read/edit/verify/cleanup and idempotent operations; all five denied through a symlinked *ancestor*; root-symlink create denied *before* any directory appeared; unsafe root permissions, missing state root, and symlinked benchmark directory denied; exact known synthetic content unchanged on rejected calls. It returned `BENCHMARK_DIRECT_PATH_SECURITY_PASS` and `BENCHMARK_DIRECT_LIFECYCLE_PASS`. Earlier `LOCAL_CONFIG_AND_STATE_PATH_SECURITY_PASS`, `LOCAL_STDIO_SYNTHETIC_SMOKE_PASS`, `LOCAL_RO_ADVERSARIAL_LIMITS_PASS` and `LOCAL_RO_MCP_INTEGRATION_PASS` also passed. Python AST syntax checks passed on edited source and tests, and GitHub writes were individually re-read.

**Limits:** these are targeted unprivileged Linux synthetic checks, not a complete concurrent-writer/mount-namespace threat model. Directory identity checks are not atomic compare-and-swap against another process with the same credentials. The **system** branch's compatibility was reviewed for the original trusted systemd symlink semantics but **not deployed or retested live**. Local/remote real project writes remain disallowed; independent-host acceptance remains deferred by operator choice.

## Tool surface: five generic tools by default locally, seven test tools opt-in (2026-11-12)

**Owner/source:** `src/synthetic_stdio.py` on `dev/mcp-portability`. This is a tool-visibility/authorization policy, not a new project scope or service.

**Confirmed consumers and limits of evidence:**

- The enabled **`MCP → Google Drive backup`** scheduled automation explicitly calls only the existing `mcp__KeelarynOS_MCP_Benchmark__list_files/read_files` generic tools against the synthetic workspace. Its recorded run exists, but task configuration alone does **not** prove which calls actually succeeded on that run. Its prompt does **not** depend on the seven extra benchmark tool names.
- Within the current Git branch, exact references to the seven extras occur in `src/synthetic_stdio.py` and `tests/test_local.py`; the latter needs the five disk-backed benchmark operations for synthetic security regression testing. A bounded code search found no other in-repository consumers.
- The current production VPS systemd unit starts the legacy `tunnel-client` and `synthetic_stdio.py`, whose original source advertises all twelve tools. **Other remote/manual callers cannot be ruled out** from a source scan; runtime invocation logs were not inspected and no behavior was changed there.

**Decision and compatibility:** a normal local read-only MCP does not need benchmark filesystem creation/edit/delete or in-memory echo/batch tests. Hiding their names alone is insufficient: direct requests must also fail. Introduced `KEELARYN_MCP_BENCHMARK_TOOLS` in the **development branch only**, accepting exactly `0` or `1`; any other value is a startup error.

| Mode | Flag unset | Flag `0` | Flag `1` |
| --- | --- | --- | --- |
| `KEELARYN_MCP_MODE=local` | **5 generic tools** | 5 generic tools | 5 generic + 7 benchmark tools |
| `KEELARYN_MCP_MODE=system` | **12 tools** (legacy compatibility) | 5 generic tools | 12 tools |

The seven opt-in tools are `read_synthetic_batch`, `benchmark_echo`, `benchmark_create_files`, `benchmark_read_files`, `benchmark_edit_files`, `benchmark_verify_files`, `benchmark_cleanup_files`. The source uses the same flag for `tools/list` and `tools/call`; disallowed direct calls return an error. The five generic MCP file tools and their existing scope authorization are untouched. This feature flag does **not** permit writes to `local-ro`; benchmark disk operations still touch only their fixed synthetic test directory.

**Verified synthetic-only evidence:** source/test commit `10928b3d2337aa514bd6aa67fa2895b0092f65b2` was cloned into a disposable `/tmp` directory on the existing VPS and run as an unprivileged `nobody`. Outputs included `BENCHMARK_DEFAULT_HIDDEN_AND_DENIED_PASS` (exact five-tool default, denied direct calls and no benchmark file side effect), `BENCHMARK_EXPLICIT_OPT_IN_PASS` (12-tool discovery, in-memory batch and echo), `BENCHMARK_DIRECT_PATH_SECURITY_PASS`, `BENCHMARK_DIRECT_LIFECYCLE_PASS`, `LOCAL_STDIO_SYNTHETIC_SMOKE_PASS`, `LOCAL_RO_ADVERSARIAL_LIMITS_PASS`, `LOCAL_RO_MCP_INTEGRATION_PASS`. An invalid flag failed at startup. A separate **system-mode compatibility** fixture, using only a root-owned *synthetic metadata registry* (no actual credentials or Drive reads), verified 12 tools for the unset/`1` flag and five for `0`: `SYSTEM_LEGACY_BENCHMARK_COMPAT_PASS`. Temporary fixtures and cloned source were removed.

**Not verified:** no live tunnel/runtime switch, no remote consumer end-to-end test, no independent Linux installation, and no guaranteed compatibility with unknown external tools. The *currently running* VPS service retains its original system-mode behavior, binary and settings. The code change is present **only in the development branch**.

## Five generic file tools: schema/runtime alignment (2026-11-12)

**Owner and scope:** `mcp/src/fs_tools.py` and existing `mcp/tests/test_local.py` in `dev/mcp-portability`. The same five names, project allowlists and successful responses remain in use; the running VPS code is unchanged.

**Three reproduced mismatches:** `read_files.offset_chars` lacked the advertised 4,194,304-character maximum; `edit_files.expected_sha256` lacked its required lowercase 64-character hexadecimal pattern; and invalid `read_files` paging arguments reached a synthetic backend before the router rejected them (`INVALID_OFFSET_BACKEND_INVOKED=1`). The shared search schema also omitted the existing NUL restriction.

**Fixes:** public schemas now state the existing maximum relative path length 320 for list/read/edit/delete, the offset limit, the edit SHA pattern, and search NUL prohibition. `_read_pagination` validates all read offsets and character limits before any backend call; `_apply_pagination` centralizes the unchanged output fields and text slicing. All five file-tool schema shapes and required keys are checked in a regression test. Eight malformed paging requests are rejected with **zero** backend calls; a valid paged read preserves content and metadata.

**Evidence:** exact development commit `6de8a2da424e1fd157d05bfdf792a082baaa022e` tested from a self-cleaning `/tmp` clone on the existing VPS as unprivileged `nobody`; `PYTHON_AST_PASS 8`, `MCP_FIVE_TOOL_SCHEMA_RUNTIME_ALIGNMENT_PASS`, `BENCHMARK_DEFAULT_HIDDEN_AND_DENIED_PASS`, `LOCAL_CONFIG_AND_STATE_PATH_SECURITY_PASS`, `BENCHMARK_EXPLICIT_OPT_IN_PASS`, `BENCHMARK_DIRECT_PATH_SECURITY_PASS`, `BENCHMARK_DIRECT_LIFECYCLE_PASS`, `LOCAL_STDIO_SYNTHETIC_SMOKE_PASS`, `LOCAL_RO_ADVERSARIAL_LIMITS_PASS`, `LOCAL_RO_MCP_INTEGRATION_PASS` and `ALL_FILE_TOOL_REGRESSIONS_PASS`. The working VPS remained active at MainPID `2636967`. No real project data, production config, credentials or deployment were changed.

**Limits:** JSON Schema metadata does not itself authorize access. Runtime continues to enforce project scopes, byte-size limits (not identical to schema character limits), relative path depth, file types, SHA checks and read-only boundaries. Tests used Python validators and synthetic fixtures; a separate JSON Schema engine, live Drive and independent-host installation were not qualified.

## Synthetic workspace list/search traversal limits — verified 2026-11-12

**Scope and owner:** `mcp/src/fs_tools.py` (`list_files`, `search_files`) and the **existing** `mcp/tests/test_local.py`; synthetic `workspace` only. No local-ro, credential scope, live Drive adapter, MCP tool names or production unit was modified.

**Reproduced defects before the change:** with 1,300 disposable synthetic Markdown file names, `list_files(limit=1)` returned one result but `os.listdir` read **all 1,300 names** before sorting. With 125 empty synthetic subdirectories, `search_files(query="unmatched", limit=1)` opened **126 directories** while reporting `scanned=0`. The old 200-readable-file limit did not limit directories or other encountered names; a large tree could cause disproportionate CPU/memory/time. Separately, `list_files` previously reported `truncated=true` when its directory merely contained ignored names (no additional visible result). These were resource/metadata defects, **not** observed authorization bypasses.

**Minimal fixes on `dev/mcp-portability`:**

- Shared `_bounded_names(fd)` enumerates at most **1,001 candidate names** using a directory iterator and rejects a directory with **more than 1,000 entries** before sorting or returning a partial result. At most 1,000 names are retained at once per directory. Both generic operations use it. This is fail-closed on a wide directory, not silent omission.
- `list_files` computes valid visible entries within that bounded directory, then applies the existing client `limit` (1–100). `truncated` now indicates **additional visible** results rather than unsupported/hidden names. Its established result keys remain unchanged.
- `search_files` additionally limits a query to **100 visited directories** and **1,000 encountered entries in total**, including non-file/ignored entries. Hitting either global budget sets `truncated=true` and stops traversal. The existing **200 eligible files**, **20 matching-line result maximum**, depth restriction and allowlisted synthetic root remain unchanged.
- No remote calls, changes to real project permissions, destructive production operation or new service were introduced.

**Verification:** read the exact development source at `1bc44446a060a67282eedb5175d2972ec7ae1480` into a self-cleaning temporary checkout on the existing VPS. Python AST parse passed for **eight** source/test files. As unprivileged `nobody`, `test_local.py` and `test_local_ro.py` passed, including new `SYNTHETIC_DIRECTORY_ENUMERATION_BOUNDS_PASS` and `SYNTHETIC_SEARCH_TRAVERSAL_BOUNDS_PASS`. Fixtures covered a 1,001-entry directory (both operations rejected it), exactly 1,000 names (accepted), 125 empty directories (search stopped after at most 100), 12 synthetic folders containing ignored filenames (global entry cap), 205 eligible files (retained 200-file search cap), visibility-aware truncation and a normal matching search. Existing schema, benchmark opt-in, path safety and `local-ro` regressions also passed. Fixtures were removed; running VPS service stayed active at original PID `2636967`.

**Limits:** these are bounded-memory/traversal tests under one unprivileged Linux account, not a proof against all filesystem races, hostile concurrent writers, mount changes, or independent Linux deployment. A directory with over 1,000 entries is intentionally **unsupported** for generic synthetic listing/search. Production VPS source and configuration remain unchanged.

## NEXT — exact next task

1. Resume only from this README and the current `dev/mcp-portability` tip; do not depend on prior conversations. No additional Linux is required.
2. **Only if continuing development:** address the remaining specifically known risk of synthetic `edit_files`/`delete_files` under concurrent same-owner writers. First demonstrate an actual race in disposable synthetic data; patch narrowly only if confirmed, and maintain the rule that no real project scope is writable. Avoid broad reviews and additional state files.
3. Keep `main`, Windows Manager, the running VPS service and source, secrets, user files and Google Drive untouched. Independent-host acceptance and any real project pilot, merge or release require separate authorization; the separate-host test remains deferred by user choice.
4. Save only material verified outcomes and the exact next action in this single README, and read back every significant GitHub change.

No changes to `main`, `manager/`, `hub/`, real Google Drive files, credentials, running VPS configuration or services are authorized by this development checkpoint.
