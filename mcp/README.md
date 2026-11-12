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

## Concurrent synthetic edit/delete — cross-process precondition repair (2026-11-12)

**Scope:** only `mcp/src/fs_tools.py` synthetic workspace `edit_files`/`delete_files` and regression cases in the existing `mcp/tests/test_local.py`; no real project writes, no service installation or configuration change.

**Confirmed before fixing:** using a temporary `nobody`-owned synthetic workspace on the existing VPS, two separate Python processes targeted `race.md` with the **same original SHA-256**. A deterministic pause immediately before the first process's final syscall allowed the second to act:
- **edit/edit:** both clients returned success, but the first overwrite silently discarded the second's completed content (`OLD_EDIT_RACE`, final `first-write`).
- **delete/edit:** another client replaced the file successfully after the first client had rechecked the old hash, yet the first client then unlinked the replacement (`OLD_DELETE_RACE`, final `ABSENT`).
The earlier second hash check did **not** provide atomic compare-and-swap. These are proven cooperative-client lost-update/deletion races, not confirmed damage to real projects.

**Minimal fix:** `edit_files` and `delete_files` acquire Linux `flock(LOCK_EX)` on an already-validated, descriptor-open **synthetic workspace directory** for the entire SHA precondition/read/commit/verification operation, then release the lock and close the FD in `finally`. The existing `_edit_files_locked` and `_delete_files_locked` bodies keep their content/size/path/SHA validation and per-file publication semantics. **No persistent lock file, new directory, daemon or dependency outside the Linux standard library** is needed. The new lock is shared across independent MCP processes opening the same workspace inode.

**Verified after fixing:** cloned development source at commit `523f6fa04ffa6b6ec49cbd8dec585c32dcf223a2` into disposable `/tmp` and ran both existing test scripts as unprivileged `nobody`. The new forked-process barrier test `SYNTHETIC_CONCURRENT_EDIT_DELETE_PRECONDITIONS_PASS` paused one client immediately before replace/unlink while another tried to edit from the same original hash. In both interleavings the contender waited for the directory lock, then failed its stale-SHA check; exactly one operation succeeded, with the expected final content/absence and no leftover temporary files. Also passed `PYTHON_AST_PASS 8`, `MCP_FIVE_TOOL_SCHEMA_RUNTIME_ALIGNMENT_PASS`, `SYNTHETIC_DIRECTORY_ENUMERATION_BOUNDS_PASS`, `SYNTHETIC_SEARCH_TRAVERSAL_BOUNDS_PASS`, `BENCHMARK_DEFAULT_HIDDEN_AND_DENIED_PASS`, `BENCHMARK_EXPLICIT_OPT_IN_PASS`, `BENCHMARK_DIRECT_PATH_SECURITY_PASS`, `BENCHMARK_DIRECT_LIFECYCLE_PASS`, `LOCAL_STDIO_SYNTHETIC_SMOKE_PASS`, `LOCAL_RO_ADVERSARIAL_LIMITS_PASS` and `LOCAL_RO_MCP_INTEGRATION_PASS`. Temporary cloned sources and fixtures were removed; the running service remained active at MainPID `2636967`.

**Boundary and limitations:** `flock` is **cooperative, Linux-specific advisory locking**; a different same-UID process writing directly to files while ignoring the lock, mount manipulation, and malicious directory replacement are **not proven safe**. This is not a filesystem transaction or kernel-enforced conditional replacement. A batch of multiple edits/deletions remains **per-file**, not atomic as a group: later failure may leave earlier files changed. All `local-ro`, credential and Drive project scopes remain read-only. Independent host qualification remains deferred; no new deployment was tested.

## Synthetic partial-batch error transparency (2026-11-12)

**Owner/scope:** `mcp/src/fs_tools.py` and the existing `mcp/tests/test_local.py` on `dev/mcp-portability`. Only synthetic `edit_files`/`delete_files` error reporting changed. No multi-file transaction, rollback, new storage, daemon, dependency or real project write permission was added.

**Confirmed defect before change:** in a disposable unprivileged workspace, force `PermissionError` on the second path (`two.md`) of a file batch *after* `one.md` had committed successfully. For `edit_files`, `one.md` contained new bytes, `two.md` kept its old bytes; for `delete_files`, `one.md` was absent and `two.md` was unchanged. Yet the MCP `tools/call` result was only `isError: true` with plain `PermissionError: synthetic injected second-file failure`. It omitted the already-confirmed change. Both outcomes were checked against actual temporary files (`PARTIAL_BATCH_UNREPORTED_SIDE_EFFECT_REPRODUCED`).

**Minimal implemented behavior:** per-item commit and readback remain unchanged, under the existing cooperative directory lock. After a later error, `PartialBatchError` carries the prior *confirmed-at-operation-time* result objects. The existing `file_tool` returns `isError: true` and one UTF-8 JSON text payload:

- `status: "partial_error"` and `operation` (`edit_files` or `delete_files`);
- `error` (original exception type and bounded message);
- `confirmed_count` and `confirmed_before_failure` (confirmed file results, SHA-256 and action where available);
- `failed_path` and `failed_path_status: "unverified"` (never promise that the failed item was not altered: the error may occur after mutation but before readback);
- `not_attempted_paths` and `atomic_scope: "per-file; not a multi-file transaction"`.

The successful response format and non-partial error format remain unchanged. This JSON-in-text choice uses standard MCP `content` and requires no particular client extension. Consumers must **not** automatically retry an entire failed batch: first verify the affected current files. `confirmed_before_failure` records an earlier result, not a permanent guarantee against later external modifications.

**Verified tests:** source/test commit `57bf053623a201edc5c00388cd451abf59298bc9` cloned to disposable `/tmp` on the existing VPS and run as unprivileged `nobody`. Deterministic injected failure on item two of three in *both* operations checked the MCP `tools/call` response against file bytes, presence/absence and SHA-256; item three was not processed. `SYNTHETIC_PARTIAL_BATCH_ERROR_TRANSPARENCY_PASS` and all prior synthetic benchmarks, local-ro, security, traversal, schema and concurrency tests passed; Python AST parsing and the original live service PID were checked. Temporary source and fixtures removed.

**Unverified:** no general transactional atomicity; `failed_path_status` intentionally remains unknown if publication succeeds but later verification fails. Same-UID writers that ignore advisory locking can still race. No real project data, production service, secrets or independent Linux acceptance were used.

## First actual-public-document local-ro pilot — VERIFIED (2026-11-12)

One-shot, isolated **read-only** pilot was explicitly authorized. Existing VPS, unprivileged `nobody`, standalone `stdio` process; pinned dev source `6b7d9e61c1ebbc7b61811667070c2f7b84e0efbe`. Source document from **main** `b577fa0cc1d760816066ecf3af8afad136564988`: `docs/GITHUB_FIRST_DEVELOPMENT.md`, Git blob `e392c31b13d97af4e34ba903be3a3ba3dab496bc`, **4307 bytes**, SHA-256 `f856bf37cf5a771a3f017d7d622bddc2820df748c8044c6949daa6c923fd592c`.

Created only temporary source checkout, exact-blob-verified public document copy, private local config and synthetic state under one disposable `/tmp/keelaryn-mcp-real-pilot.*` root. `EnginePublicPilot` was `local-ro`, `canonical=false`, `allow=["docs/GITHUB_FIRST_DEVELOPMENT.md"]`; no live source or persistent scope was changed. Both preflights passed. Real JSON-RPC `initialize`/`tools/list` (five generic tools), root/subdirectory listing, full byte-exact `read_files`, character paging and `search_files` (**16 matches**) passed. Unknown scope, excluded paths, traversal, absolute path, edit, delete and excluded listing returned errors. The document remained SHA-identical; separate MCP process exited normally. **Cleanup verified:** no pilot directory remained. Installed service still `active`, PID `2636967`, five original source checksums unchanged. No changes to `main`, working VPS config/service, Windows Manager, Drive or private/canonical data.

**Qualification boundary:** proves one pinned public Markdown file via a temporary local copy, not fresh GitHub syncing, direct access to real canonical user data, remote ChatGPT/tunnel operation, independent-host deployment or general production safety.

## Same-Tunnel-ID conversion plan for the existing ChatGPT app — read-only design (2026-11-12)

**Scope/authority:** USER AUTHORIZED ONLY READ-ONLY INSPECTION, SYNTHETIC TESTS AND THIS README CHECKPOINT. No production source/profile/unit, secrets, ChatGPT app, automation, Windows Manager, Drive, `main`, or real project was changed. Keep this under Keelaryn Engine `mcp/`, not the general KeelarynOS rules.

**Confirmed current baseline:** `dev/mcp-portability` HEAD before documenting `8b6a86460815679d3962c1b609b9f3ab9abb2ccc`, installed service `keelarynos-mcp-benchmark.service` active with MainPID `2636967`. Systemd: `DynamicUser=yes`, `User=keelarynos-mcp-benchmark`, `ProtectHome=yes`, `ProtectSystem=strict`, `NoNewPrivileges=yes`, `PrivateTmp=yes`, `StateDirectory=keelarynos-mcp-benchmark`, `LoadCredential` present, **two `ExecStartPre` checks**, `MemoryMax=infinity`. One tunnel-client `--profile-file` references a local **JSON** profile (`config_version=1`) with one `mcp.commands` **main stdio** binding, a configured Tunnel ID and a runtime key **reference**, not an inline value. The existing root-owned file-scopes registry has **three** scopes: synthetic workspace and two `credentials` read-only noncanonical snapshots; no `local-ro` or `drive-live`. No secret or Tunnel ID value was disclosed.

**Key constraints established from actual source:**
- `KEELARYN_MCP_MODE=system` currently **rejects** `backend=local-ro` in `file_scopes.py`; `local-ro` is only qualified in `local` mode on an operator-owned directory. `ProtectHome=yes` and preflight's hidden path checks also block naïve exposure of canonical local files. It is unsafe to deploy the dev files as-is and simply add arbitrary real roots.
- `KEELARYN_MCP_BENCHMARK_TOOLS=0` leaves **five** generic tools and permits **synthetic `edit_files`**; it is not a read-only switch. Production read-only must expose only `list_files`, `read_files`, `search_files` and **reject direct calls** to all write and benchmark names, including cached legacy tool calls.
- The active daily scheduled automation **`MCP → Google Drive backup`** calls the existing app's `list_files/read_files` for `synthetic` exclusively. A read-only cutover can preserve those two operations (without synthetic writes) without changing that automation; removing the synthetic read scope would break it and requires a separate choice.
- The current ChatGPT app is connected and successfully returned a synthetic `list_files` result during this review. Its app-specific permission is **Allow all actions**. Treat this as a risk if any real source is exposed; server-side allowlist and write denial are mandatory regardless of app permission. OpenAI notes that published MCP app tools/schemas can be **frozen** and may need an authorized refresh: https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt.
- The installed `tunnel-client` is the previously pinned v0.0.20. Its official instructions prohibit **any overlap** of two stdio tunnel processes sharing the same Tunnel ID, even during rolling restarts: https://github.com/openai/tunnel-client/blob/v0.0.20/docs/configuration.md. Same Tunnel ID and the existing ChatGPT app identity **can be retained by replacing the one current child behind an orderly stop/start**, not by running a parallel client.

**Synthetic-only evidence on the same VPS (temporary clone + isolated files; all removed):**
1. `SYSTEM_MODE_LEGACY_COMPAT_PASS`: current dev source in `system` mode, with root-owned *synthetic* credentials metadata, publishes 12 original tool names, reads the fake snapshot, and refuses editing the fake read-only scope.
2. `SYSTEM_FLAG_ZERO_WRITE_STILL_POSSIBLE_PASS`: flag `KEELARYN_MCP_BENCHMARK_TOOLS=0` advertises five tools yet an explicit synthetic edit succeeds. This **proves** the access-mode gap.
3. `SYSTEM_LOCAL_RO_REJECTED_BY_CURRENT_VALIDATOR_PASS`: adding synthetic `local-ro` to system-mode config causes startup rejection as designed.
4. **Disposable prototype only**, not committed: in a temporary checkout, an opt-in `KEELARYN_MCP_ACCESS_MODE=read-only` gate at `stdio` advertisement and direct dispatch produced `TEMP_OVERLAY_SYSTEM_READ_ONLY_MODE_PASS tools=3`, `TEMP_OVERLAY_EXISTING_SNAPSHOT_READ_PASS`, `TEMP_OVERLAY_AUTOMATION_SYNTHETIC_LIST_PASS`, `TEMP_OVERLAY_DIRECT_WRITES_AND_BENCHMARK_DENIED_PASS`. No production/read-only capability was implemented in the GitHub branch by this experiment.
5. The real working service stayed active with unchanged MainPID and installed source hashes. No new tunnel was started.

**Earlier conversion plan (read-only source item now completed in dev; other steps remain pending):**
1. **DONE in dev only:** added default-off `KEELARYN_MCP_ACCESS_MODE=read-only`, exactly three advertised read tools, direct write/benchmark denial and independent file-backend denial. Preserved legacy system defaults and synthetic `list/read` for the existing backup automation. This is not deployed.
2. For an initial compatibility cutover, reuse the **current system-mode root-owned registry, existing synthetic read-only use and pinned credentials snapshots**. This qualifies connectivity and backward-compatible reads, **not** live canonical truth. Do not recategorize the old snapshots as canonical.
3. Before any real source: name its Domain OS/project owner, original storage and freshness contract. For **local canonical files**, review a least-privilege read-only bind/ownership/path arrangement under `DynamicUser` and preflight, and implement explicit system-mode scope support only if the original can be safely accessed without ownership change or broad unmasking. For **live Drive**, the existing read-only `drive-live` adapter would need separately authorized limited credentials and allowlist; this requires network and is not offline. For **Windows Hub**, VPS currently has no authorized canonical file transport. Never copy private canonical data into the public repository or label a stale snapshot live.
4. Stage immutable pinned source and a reversible service/profile update plan **outside** the active installed path. Preserve original five file hashes, profile/unit/registry and verified return route as protected originals. The updated service must still supervise **one** tunnel-client with the **same** Tunnel ID/runtime key reference and `main` stdio channel, and retain both pre-start checks and systemd isolation. Avoid copying secrets or introducing a second plugin/tunnel/VPS.
5. Qualify offline in disposable synthetic conditions: exact 3-tool discovery, read/search on permitted snapshot and synthetic read for automation, direct denial of old write/benchmark calls, unknown scope/path denial, SHA integrity, restarted stdio compatibility, config ownership and error handling; rehearse code/profile rollback **without starting another tunnel**. Check resource limits (`MemoryMax` currently unlimited) before larger sources.
6. **Separate explicit production-switch approval required.** At that point, record a safe cutover window; STOP the single existing service, atomically switch its pinned Python command + relevant preflight paths/config (do not overwrite original source), then START only one service. No overlapping Tunnel ID. Verify readiness and a live ChatGPT `list/read/search` call, then read-only denial and automation compatibility. Refresh frozen ChatGPT action schemas only with authorized app-management access; if not possible, keep old schemas callable only as **server-side errors** until another reviewed solution. In-flight requests may fail during the stop/start; never assume automatic replay.
7. **Rollback:** stop failed new service; restore exact original profile/unit/registry/source refs from protected originals, `daemon-reload` if unit changed, start **one** original service under the same Tunnel ID, confirm live ChatGPT synthetic read and service health. No destructive `git reset --hard`, blanket file removal, or overlapping tunnel.

**Remaining gates:** the default-off read-only code and tests are now committed and synthetically verified in dev (details below), **not installed**; source-specific permissions/freshness not chosen; existing ChatGPT app tool-refresh ability unverified; memory cap/target preflight unqualified; production stop/start **NOT AUTHORIZED**. The backup automation must keep its synthetic reads; actual scheduled execution after cutover is not yet verified. Existing VPS and tunnel can be reused without another server or key; short downtime and network dependency remain possible. Do not claim conversion complete before the remaining gates.

## Default-off read-only MCP access mode — IMPLEMENTED IN DEV (2026-11-12)

**Owner and exact source:** `mcp/src/file_scopes.py`, `fs_tools.py`, `synthetic_stdio.py`; regression added only to existing `mcp/tests/test_local.py`. Development source/test checkpoint `dd5f86d7642b259886aeed2af08d1cb4384afb8a` on `dev/mcp-portability`. No systemd, tunnel, configured scope, ChatGPT plugin, automation, private document or production Python source was changed.

**Contract:** `KEELARYN_MCP_ACCESS_MODE` accepts precisely `default` (also when absent) or `read-only`; an unknown value fails startup. `default` retains existing mode-sensitive benchmark behavior: system-mode discovers twelve tools, local-mode five when the benchmark flag is absent. `read-only` advertises **exactly three** tools, `list_files`, `read_files`, `search_files`, irrespective of `KEELARYN_MCP_BENCHMARK_TOOLS=0|1`. Before dispatch, the stdio handler rejects every cached direct `edit_files`, `delete_files` and benchmark tool call. `fs_tools._route_file_tool` independently rejects edit/delete in read-only mode before backend access, including the otherwise writable `synthetic` project. The server-side scopes, original registry, permissions, read limits and JSON-RPC success fields are unchanged.

**Tested on existing VPS, isolated temporary source only:** as `nobody`, pinned Python 3.12 source compiled by AST (8 scripts); existing `test_local.py` and `test_local_ro.py` passed, including `READ_ONLY_THREE_TOOL_DISCOVERY_PASS`, `READ_ONLY_SYNTHETIC_AUTOMATION_READ_PASS`, `READ_ONLY_CACHED_WRITE_AND_BENCHMARK_DENIAL_PASS`, `READ_ONLY_INVALID_MODE_FAIL_CLOSED_PASS`, schema, symlink, limits, concurrency, batch-error and baseline benchmark regressions. Additional disposable root-owned *synthetic system registry* + non-sensitive fake credential confirmed `SYSTEM_RO_EXACT_THREE_TOOLS_PASS`, `SYSTEM_RO_SYNTHETIC_AUTOMATION_LIST_READ_PASS`, `SYSTEM_RO_SNAPSHOT_READ_PASS`, `SYSTEM_RO_CACHED_WRITE_BENCHMARK_DENIED_PASS`, `SYSTEM_LEGACY_DEFAULT_COMPAT_12_TOOLS_PASS`, `SYSTEM_LEGACY_BENCHMARK_SUPPRESSION_PASS`, `SYSTEM_UNRECOGNIZED_ACCESS_MODE_FAIL_CLOSED_PASS`. A separate synthetic `local-ro` scope verified read-only listing, reading/search and denial of edit/unknown paths (`LOCAL_RO_ACCESS_MODE_LIST_READ_SEARCH_PASS`, `LOCAL_RO_ACCESS_MODE_WRITE_UNLISTED_DENIAL_PASS`). All cloned fixtures were disposable; no working tunnel started or service restarted.

**Proof boundary:** preserves the existing automation's *required read calls*, not evidence of the future scheduled run. The installed VPS continues using **old code** and its original twelve-tool system interface. Neither local-ro under `system` nor live canonical project access was enabled; app-side frozen/cached tool definitions were not refreshed. Real data access, installation and a cutover with the same Tunnel ID still require separate approval.

## Existing ChatGPT personal MCP plugin: tool-refresh investigation (2026-11-12)

**Read-only inspection only; no ChatGPT/plugin/VPS mutation.** The connected app is the *owned private personal App-backed plugin* `plugin_asdk_app_6af3289514588191b95be7a163122467`, internal app `asdk_app_6af3289514588191b95be7a163122467`, package `dev-6af3289514588191b95be7a163122467`, visible name `KeelarynOS MCP Benchmark`. Current release `PluginRelease_e0e207f83fb8819184376d5de7ebd97a`, version `1.0.0`, created 2026-11-10; scope `USER`, `PRIVATE`. Its manifest `.codex-plugin/plugin.json` references `.app.json`; neither exposed an editable MCP tool-scan definition. Twelve legacy tool names are still registered in ChatGPT. Plugin-specific ChatGPT permission is **Allow all actions** (higher risk; not changed).

**Verified capability:** plugin metadata, current files, release history and archive-update capability are accessible under the existing owner identity. The generic `update_plugin` action explicitly **preserves App bindings and MCP configuration**; it is **not a documented rescan/refresh action** and was NOT invoked. No explicit read-only `refresh MCP tools` action is exposed by available connected tools. The current OpenAI Help Center https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt documents in-place MCP tool refresh by **Business / Enterprise-Edu workspace admins**; it does not establish an equivalent control for this private `USER` plugin. Exact personal UI refresh support therefore remains **unverified**, not categorically impossible.

**Operational consequence:** ChatGPT may retain the original frozen twelve-tool snapshot after future server cutover. `dev/mcp-portability` already gates the new read-only mode at **both** `tools/list` and direct `tools/call` / file router; old write/benchmark names can appear yet must return `isError` without effects. The existing automated `MCP → Google Drive backup` remains enabled and its saved prompt explicitly uses only `list_files/read_files` for synthetic workspace; their names and inputs are unchanged. Runtime success of the automation *after* a future cutover is **not yet verified**. A changed app/package identity, deleted tool or changed schema could disrupt it; do **not** recreate the plugin or change its release/permission as an attempted refresh.

**Post-switch verification gate (NOT AUTHORIZED NOW):** under an independently approved single-Tunnel-ID stop/switch/start, verify actual ChatGPT `list_files/read_files/search_files`, confirmed denial of direct stale write/benchmark calls, exact synthetic backup-list/read compatibility, and installed tool visibility. If legacy names remain visible but fail safely, record UI limitation; do not claim successful refresh or expose private canonical data without approval. Do not start overlapping tunnels.

## Personal-plugin tool refresh: user-reported action and subsequent observation (2026-11-12)

The operator reported **already pressing the tool-refresh control** for the connected existing ChatGPT MCP app. This is a user report of the UI action, **not** independent verification of that UI control's exact name or platform-side completion. Immediately afterward, the connected `KeelarynOS MCP Benchmark` `list_files(project="synthetic")` returned successfully and the ChatGPT tool registry exposed the original **12** MCP tools. Personal plugin metadata still showed release `PluginRelease_e0e207f83fb8819184376d5de7ebd97a`, version `1.0.0`. **No active MCP source or tool surface was changed on the VPS**, so twelve published names are expected. This does not demonstrate that a future post-cutover refresh will successfully remove old names. Do not repeat refresh merely to check it now.

## Same-Tunnel-ID cutover and rollback staging rehearsal — verified 2026-11-12

**Authorization boundary:** preparation and disposable synthetic rehearsal only. No change to active `keelarynos-mcp-benchmark.service`, its systemd unit, profile, key/Tunnel ID, permanent registry, ChatGPT application, existing automation, real data, `main`, or Windows Manager. GitHub branch under test: pinned `dev/mcp-portability` commit `f4b93d15331c835329e19d7f74d73b634f33cd19`.

**Verified operating layout (source metadata and no credentials disclosed):**
- Service `active`, stable MainPID `2636967`, `DynamicUser=yes`, `ProtectHome=yes`, `ProtectSystem=strict`, `NoNewPrivileges=yes`, `PrivateTmp=yes`, `Restart=always`, two `ExecStartPre` checks (sandbox and scopes), five `LoadCredential` directives. `MemoryMax=infinity`, so no finite systemd memory cap was proven.
- The **existing** tunnel-client v`0.0.20` is executed directly from `/usr/local/lib/keelarynos-mcp-benchmark/tunnel-client` and is **inside the installed source directory**. The unchanged profile starts `python3 /usr/local/lib/keelarynos-mcp-benchmark/synthetic_stdio.py` on `main`. No additional tunnel or new plugin required. Its Go stdio child uses `exec.Command` without overriding `Cmd.Env`, which normally inherits the parent systemd environment (pinned code: https://github.com/openai/tunnel-client/blob/v0.0.20/pkg/mcpclient/stdio_command.go). **Runtime inheritance through the live tunnel was not exercised.**
- Installed directory also includes `musiclibrary_ro.py`, `__pycache__` and all six original Python scripts, **not just** the five previously pinned core script hashes. Replacing it with the GitHub `mcp/src` directory alone would **delete the live tunnel binary and this extra module**. Original directory occupies **25,987,972 bytes**, filesystem had **53,675,593,728 free bytes**. Any candidate must be assembled from a **complete copy of the installed directory** and then overlaid with the pinned development `mcp/src/*.py`. Verify the original tunnel-client, `musiclibrary_ro.py` and other retained items are byte-identical in the candidate. No new permanent copies were created in this session.

**Disposable switch/restore rehearsal, existing VPS:** a pinned `dev` clone and a **complete temporary copy** of the installed directory were prepared under `/tmp`; the candidate received only development `*.py` overlays. Passed `STAGED_FULL_DIRECTORY_PRESERVES_TUNNEL_BINARY_AND_LEGACY_MODULE_PASS`, Python AST parsing on **7** staged modules, and `FULL_DIRECTORY_RENAME_CUTOVER_REHEARSAL_PASS` using successive renames under a **temporary path**, not the installed path. A separate `nobody` system-mode stdio child with *fake root-owned scope metadata, fake credential and synthetic workspace* passed `file_scopes.py --preflight`, three-tool discovery, synthetic backup `list/read/search`, fake snapshot read, and direct `edit/delete/benchmark` denials (`STAGED_FULL_SLOT_SYSTEM_READ_ONLY_AND_AUTOMATION_READ_PASS`). The temporary candidate was renamed away and the exact original directory restored: **all original top-level file SHA-256 checksums matched** (`COMPLETE_ORIGINAL_DIRECTORY_RESTORED_SHA256_PASS`, `ROLLBACK_PRESERVES_TUNNEL_BINARY_AND_EXTRA_MODULE_PASS`). All temporary folders removed, installed hashes unchanged, live PID unchanged, connected ChatGPT `list_files(synthetic)` still responded. No separate tunnel-client process was started.

**Important qualification:** the original installed `file_scopes.py` uses fixed local source/credential locations instead of the new env-configurable registry, so an initial fake-registry rehearsal of its snapshot-reading path was **not applicable**. The exact old source's hashes and the still-running legacy service were verified instead. This does not prove systemd start/stop, live credential mounting, tunnel reconnection, preflight under its real mount isolation, actual ChatGPT tool refresh, or successful production rollback after a real cutover.

### Exact production cutover procedure — DOCUMENTATION ONLY, NOT AUTHORIZED

1. **Precondition:** separate express approval, a maintenance window avoiding the daily synthetic backup, clean pinned Git revision `f4b93d15331c835329e19d7f74d73b634f33cd19`, sufficient free space, verified current service health and original top-level SHA-256. Confirm no existing destination collision or previously installed read-only drop-in. Do **not** connect private canonical sources in this cutover; retain the existing three scopes and snapshot truth labels.
2. **Stage without touching the live path:** prepare a root-owned sibling candidate directory under `/usr/local/lib` by `cp -a` of the **entire** current `keelarynos-mcp-benchmark/` directory; overlay only the pinned GitHub `mcp/src/*.py`. Verify original `tunnel-client` remains executable and SHA-identical, `musiclibrary_ro.py` unchanged, Python source syntax, file ownership/permissions and read-only synthetic regression. Protect the original by an exact separate rollback directory name; do not overwrite it.
3. **Stage the only systemd policy change** in a checked drop-in, e.g. `/etc/systemd/system/keelarynos-mcp-benchmark.service.d/90-keelaryn-read-only.conf` containing `[Service]` and `Environment=KEELARYN_MCP_ACCESS_MODE=read-only`. Preserve the existing `PYTHONDONTWRITEBYTECODE`, unit sandbox, both preflight checks, LoadCredential references, unchanged tunnel profile, main channel, Tunnel ID and runtime key. Confirm this drop-in does **not** already exist. Do not apply or reload now.
4. **Controlled single-instance switch after authorization:** `systemctl stop keelarynos-mcp-benchmark.service` and verify the tunnel process is gone. While stopped, rename the original full directory to the protected rollback name, rename the prepared sibling candidate into the **identical original path**, install only the new drop-in, then `systemctl daemon-reload` and `systemctl start keelarynos-mcp-benchmark.service`. This sequence uses two separate same-filesystem renames while service is stopped, **not an atomic two-directory transaction**. Never allow two clients with one Tunnel ID to overlap.
5. **Go/no-go tests:** `systemctl is-active`, both original `ExecStartPre` checks, exactly three tools advertised by the new MCP child, live ChatGPT `list_files/read_files/search_files`, direct rejection of cached `edit_files/delete_files/benchmark_*` with **zero side effects**, existing synthetic `list/read` for the scheduled backup, and unchanged credential snapshot integrity. Only after the new server is healthy, use the already available ChatGPT `Refresh tools` UI **once**, if needed. Actual scheduled backup success must still be confirmed separately, without duplicating Drive output.
6. **Rollback if any gate fails:** `systemctl stop` the new single instance; move the new full directory aside to a distinct failure-review name, rename the protected exact original directory back to the fixed installed path, remove **only** the newly introduced read-only drop-in (or restore the pre-existing file if one was already present), run `systemctl daemon-reload`, then `systemctl start` the original service. Verify original hashes, original twelve-tool legacy behavior, ChatGPT synthetic read, and service health. Do not delete the preserved originals, change scope data or start a second tunnel. Avoid blind repeated restart after an uncertain outcome.

**Scope still excluded:** neither live `local-ro` canonical data in `system` mode nor live Drive canonical access is qualified. `local-ro` remains limited to operator-owned `local` mode. This first cutover would change the tool surface, not establish production access to KeelarynOS private sources.

## Final read-only systemd pre-cutover inspection — 2026-11-12

**Scope:** operator requested inspection, **no installation, systemctl change, reload, stop/start, secret reading or service modification**. This checkpoint only updates the existing GitHub README on `dev/mcp-portability`. The tested candidate source prior to this documentation commit is `a01531217612096edd7d864189ceec12b5f6fad5`; `main` remains `b577fa0cc1d760816066ecf3af8afad136564988`. No new tunnel or real canonical file was connected.

**Exact observed service state, on existing VPS:**
- `keelarynos-mcp-benchmark.service` **active/running**, MainPID `2636967`, `NRestarts=0`, enabled, `NeedDaemonReload=no`. One running `tunnel-client` process detected, **inside this unit**; no other such executable process found, though PID enumeration does **not** prove global Tunnel-ID uniqueness outside this host.
- `DynamicUser=yes`, `User=keelarynos-mcp-benchmark`, `ProtectSystem=strict`, `ProtectHome=yes`, `PrivateTmp=yes`, `NoNewPrivileges=yes`, `UMask=0077`, `StateDirectory=keelarynos-mcp-benchmark`, `StateDirectoryMode=0700`. StateDirectory path is the **expected systemd private-directory symlink**. Five `LoadCredential` directives, two `ExecStartPre` scripts, one `ExecStart`. Existing Environment keys: only `PYTHONDONTWRITEBYTECODE`; no `KEELARYN_MCP_ACCESS_MODE` set and no `UnsetEnvironment` directive.
- Main fragment regular root-owned `0644`, SHA-256 `f5dc401d79b7bd2f54fa550bd5d27a3d5300804ed00d8bcaf598d81127e7a90b`. **Zero** current systemd drop-ins. The proposed drop-in path `/etc/systemd/system/keelarynos-mcp-benchmark.service.d/90-keelaryn-read-only.conf`, its parent, and proposed sibling stage/rollback paths `/usr/local/lib/keelarynos-mcp-benchmark.stage-readonly` and `/usr/local/lib/keelarynos-mcp-benchmark.rollback-original` **do not currently exist**. This is a point-in-time collision check, not a reservation: re-check just before any future write.
- Installed source directory and `/usr/local/lib` parent root-owned `0755`, same filesystem; service executable and both preflight scripts still resolve under the installed source path. Source directory uses **25,987,972 bytes**; filesystem free **53,675,511,808 bytes**. Current command was run with UID 0, but future production changes still require separate user authorization.
- The existing **root-owned `0644` scope registry** at `/etc/keelarynos-mcp-benchmark/file-scopes.json` had SHA-256 `cb14330bec369994cc2fdd033f4d7096fb5fcbe86e9cfe9967a811050b331fbf`, expected `keelarynos_mcp_file_scopes_v1` schema, three scopes: **one synthetic workspace and two pinned credential snapshots**; **no `local-ro` or live Drive**. Only structural metadata was reported; secrets, actual credential bytes and Tunnel ID values were not printed.
- Installed complete top level: `drive_live.py`, `file_scopes.py`, `fs_tools.py`, `musiclibrary_ro.py`, `preflight.py`, `synthetic_stdio.py`, `tunnel-client`, plus derived `__pycache__` directory. SHA-256 of preserved non-core items: `musiclibrary_ro.py` = `bd7665a6cc4b696c0ee37d73b15633666c19f3d3cc3af6cb9bc08929445d7c3c`; `tunnel-client` = `447e237f2030a0f0dab908b0a2f61fafce878d7da341f741e79245051319a09e`. Core five originals remain the baseline values in the earlier evidence table, unchanged. Preserve **all seven original top-level files** and source directory layout for rollback; never replace the folder using the GitHub `src/` contents alone.
- **Resource guardrails not yet production-qualified:** `MemoryCurrent=22,044,672` bytes, observed `MemoryPeak=23,638,016` bytes, but **`MemoryMax=infinity`, `MemoryHigh=infinity`, CPUQuota infinite**, `TasksMax=4600` (`TasksCurrent=10`), `LimitNOFILE=524288`. Current consumption does not bound the worst-case. Set a finite, justified limit only through a separately tested/approved configuration change; do not invent a number from this single observation.
- Existing ChatGPT-connected `list_files(synthetic)` succeeded during this inspection. The previously recorded daily `MCP → Google Drive backup` depends on `list_files/read_files`, but an attempt to re-read its schedule through the connected automation action returned `NOT_FOUND`; **current next-run timing was not independently verified**. Avoid a maintenance overlap only after checking the automation's actual schedule. No task was modified.

**Exact permission/installation conditions for a later, separately authorized cutover (NOT DONE):**
1. Confirm one explicit authorization and a maintenance window; **verify** the active automation is not running/near due, with no queued requests that must be preserved. Re-read unit, profile and registry metadata and original hashes; ensure the same Tunnel ID is still associated only with this service on this host, with no overlapping client during switching.
2. Re-check **all three** proposed destination collisions and ensure same-filesystem renames. Stage a **complete** root-owned copy of the installed source, overlay the pinned development Python files, preserving `tunnel-client`, `musiclibrary_ro.py`, other original contents and permission bits. Verify hashes, Python AST and the synthetic read-only tests; ensure no copied stale `__pycache__` masks new source (handle only disposable candidate cache, never destroy the original). Preserve the exact original directory under a protected rollback name.
3. After explicit approval, **stop the single** service and verify its tunnel process is gone; only then perform original→rollback, candidate→installed-path renames, install the new *non-conflicting* drop-in `[Service]\nEnvironment=KEELARYN_MCP_ACCESS_MODE=read-only`, `daemon-reload` and `start`. Keep old profile/Tunnel ID/key refs, `ExecStartPre`, DynamicUser and all original scopes unchanged. The rename pair is **not one atomic transaction**; examine actual paths before recovery after interruption.
4. **Mandatory post-start go/no-go:** stable service and exactly one tunnel-client; two preflights succeed **inside real systemd isolation**; the child has the read-only environment and shows exactly three `list_files/read_files/search_files` tools; calls from existing ChatGPT app succeed on allowed synthetic and pinned snapshot scopes; old cached `edit/delete/benchmark` calls all return errors without effects; synthetic `list/read` behavior remains compatible with the automation. Only after child readiness, refresh ChatGPT tool definitions if needed and then verify; do not run duplicate scheduled exports. Real private/canonical scopes and new user data are **excluded**.
5. **Rollback trigger:** any failed preflight, missing three tools, unintended write, incorrect snapshot/read result, tunnel reconnect failure, unreadable existing scope, incompatible automation, or uncertain source/credential configuration. Stop the new service; confirm no child/tunnel remains; determine which two rename steps actually completed; restore the original full directory to the identical installed path. Remove only the **new** drop-in (if present), `daemon-reload`, start just the original service, verify its seven hashes, legacy twelve-tool interface, connected synthetic read and service health. Never start a second client with the same Tunnel ID, never blindly repeat operations after uncertain outcome, and retain failed candidate for investigation until a safe decision.

**Decision:** systemd path/permission/collision and preservation prerequisites are satisfactory **at inspection time**. Production readiness is **not established**: no real stop/start, live child environment, runtime resource maximum, post-cutover ChatGPT refresh or automation run is verified. No service change is authorized by this inspection.

## Existing same-Tunnel-ID production cutover — VERIFIED 2026-11-12

**Authorized production operation completed**, with the explicit restriction to **existing synthetic workspace + pinned noncanonical credential snapshots only**. No new private/canonical project scope, new tunnel or app, new credential, new host, Drive write, Windows Manager change, other service change or `main` change. Exact tested source is pinned Git commit `43f869324ef14e62e912d8b25648d4c7823f29ea` from `dev/mcp-portability`; this documentation commit does not modify installed source code.

**Preflight:** full seven original installed-file SHA-256 matched the previous README; root-owned registry SHA-256 remained `cb14330bec369994cc2fdd033f4d7096fb5fcbe86e9cfe9967a811050b331fbf`; original systemd unit had no drop-in and no pending reload; no collision with the chosen stage, rollback or failure-review names. The existing ChatGPT `list_files(synthetic)` responded. The enabled `MCP → Google Drive backup` automation's next scheduled run was **2026-11-13 04:00 Asia/Yerevan** (last run recorded 2026-11-12 00:42:42 UTC), outside the cutover window. This check did not prove no manually triggered task was queued. Only one `tunnel-client` process was detected on the VPS.

**Staging:** root-owned sibling `/usr/local/lib/keelarynos-mcp-benchmark.stage-readonly` was made from an **entire copy** of the existing installed directory, then only the pinned `mcp/src/*.py` development files were overlaid. The old tunnel-client v0.0.20, `musiclibrary_ro.py` and inherited file permissions were retained. Staged Python AST parse passed (7 files), all `test_local.py` and `test_local_ro.py` synthetic/adversarial regressions passed as `nobody`, and staged `*.py` bytes exactly matched the pinned Git checkout. An initial test attempt could not traverse its temporary root (mode 0700); this was corrected **only in the disposable test checkout** and tests reran successfully. No code change was needed.

**Actual controlled cutover:** intentionally stopped the **one** `keelarynos-mcp-benchmark.service` and verified the old tunnel exited; renamed the **entire** original installation to `/usr/local/lib/keelarynos-mcp-benchmark.rollback-original`, moved the staged candidate to the unchanged installed path, and added only `/etc/systemd/system/keelarynos-mcp-benchmark.service.d/90-keelaryn-read-only.conf`:

```ini
[Service]
Environment=KEELARYN_MCP_ACCESS_MODE=read-only
```

Then `systemctl daemon-reload` and `systemctl start` the **same** service. Original tunnel profile, Tunnel ID, secret references, root registry, main unit, service identity and all other services were not edited. Controlled host script provided a **failure-path rollback** (stop, restore the protected original directory, remove only the new drop-in, reload/start) for any failing host gate; none triggered.

**Post-start evidence:** `ActiveState=active`, `SubState=running`, stable MainPID **2708803**, `NRestarts=0`, one `tunnel-client` process matching MainPID, applied read-only environment and drop-in, `NeedDaemonReload=no`. systemd start completed its configured ExecStartPre chain (a subsequent systemctl query surfaced one last recorded successful ExecStartPre result). The original unit fragment SHA-256 `f5dc401d79b7bd2f54fa550bd5d27a3d5300804ed00d8bcaf598d81127e7a90b` and original scope registry SHA-256 were unchanged. **All seven original files are retained with exact matching SHA-256** in the protected `.rollback-original` directory; the new installed tunnel-client and `musiclibrary_ro.py` match original hashes. Staging and failure-review directories absent; the probe synthetic file was not created. Observed current service memory `23,580,672` bytes, while `MemoryMax` remains unlimited.

**Real ChatGPT verification:** through the **existing connected KeelarynOS MCP Benchmark app / same tunnel**, `list_files(synthetic)` and `search_files(synthetic)` succeeded; `list_files(ArmenianLearning)` exposed only the two already configured **pinned noncanonical snapshot metadata** entries; `read_files(ArmenianLearning, ["STATE.md"], max_chars=64)` returned 64 characters, SHA-256 metadata, `snapshot_only=true`, `canonical=false`. No private canonical/live source was added or exposed. Cached direct calls to `benchmark_echo`, `edit_files` and `delete_files` all failed specifically with **`Read-only MCP mode forbids this tool`**, and `list_files` of an unknown scope failed with `Project scope is not allowed`. The synthetic workspace remained empty and the attempted probe path remained absent. These observations substantiate the **server-side denial even while ChatGPT may still list 12 frozen tool names**. The active server's code has three-tool `tools/list` in read-only mode; a post-cutover app-side refresh to make only three visible **was not performed here**.

**Production status/limits:** **same-ID cutover succeeded, no rollback was needed**. This qualifies the installed read-only MCP for existing synthetic reads and legacy pinned snapshots, **not** for fresh/canonical project data, independent-host Linux, remote real file writes, perfect concurrency, or full workload/resource safety. The scheduled backup automation's actual next run, upcoming 2026-11-13 04:00 Asia/Yerevan, was **not executed or duplicated** during the switch; its success after cutover is unverified. Existing `MemoryMax=infinity` remains an explicit risk for larger/future sources. Keep the rollback directory untouched until both ChatGPT tool-visibility review and normal automation follow-up are satisfied.

## Existing ChatGPT app tool refresh — VERIFIED (2026-11-12)

The user reported clicking **Refresh tools** in the existing `KeelarynOS MCP Benchmark` app **after** the same-Tunnel-ID read-only cutover. Subsequent ChatGPT tool registry inspection confirmed **exactly three** exposed MCP tools: `list_files`, `read_files` and `search_files`. The former `edit_files`, `delete_files` and seven benchmark tools were **not** present in the accessible tool registry; this is direct evidence that the previously frozen 12-tool presentation has been refreshed. It does not by itself prove any hidden cache in other clients. No new app, release or tunnel was created by this verification.

Actual calls using the refreshed existing connection: `list_files(project="synthetic")` succeeded with an empty workspace; `search_files(project="synthetic", query="__post_refresh_no_match__")` succeeded with zero matches. Read-only `read_files` and the stale write/benchmark command refusal were already verified through ChatGPT **immediately before the refresh**, while the same server process was running. Do not invoke any obsolete write command just to test the new tool visibility. The VPS service remained `active/running`, MainPID `2708803`, `NRestarts=0`, `NeedDaemonReload=no`. The exact protected original installation still exists under `/usr/local/lib/keelarynos-mcp-benchmark.rollback-original`; read-only systemd drop-in remains present. No service, app, schedule, permission, profile, secret, private canonical scope or Windows Manager change was performed during this verification; only this README is updated.

**Qualification:** publishing the three tools is now complete. The first **normal scheduled run after cutover** of the enabled `MCP → Google Drive backup` task was still pending at the time of this checkpoint; most recently observed schedule: **2026-11-13 04:00 Asia/Yerevan**. Its post-cutover execution and backup result remain unverified. The service still has no private canonical live source, and `MemoryMax` remains `infinity`.

## Root-owned system local-ro development and first public-source qualification — 2026-11-13

**Operator choice:** skip the post-cutover `MCP → Google Drive backup` automation verification and continue toward a real read-only file source. **No automation was edited, paused, deleted, triggered, or checked further for the purpose of this step**. Its post-cutover output remains **unverified**; do not silently mark it successful. This instruction does not authorize a new private canonical scope or a production restart.

**Selected harmless pilot:** public Keelaryn **Engine** source `docs/GITHUB_FIRST_DEVELOPMENT.md` at `main` commit `b577fa0cc1d760816066ecf3af8afad136564988` (Git blob `e392c31b13d97af4e34ba903be3a3ba3dab496bc`). Exactly **4,307 bytes**, SHA-256 `f856bf37cf5a771a3f017d7d622bddc2820df748c8044c6949daa6c923fd592c`. It is **not** a private KeelarynOS/LifeOS document. A local pinned copy has `canonical=false`; GitHub remains the authoritative owner and a new GitHub revision will **not** automatically appear in a pinned local copy. Do not confuse a local offline-readable format with a synchronized canonical source.

**Implementation (dev only):** `mcp/src/local_ro.py` now selects a **root-owned source tree** only under the combined `KEELARYN_MCP_MODE=system` + `KEELARYN_MCP_ACCESS_MODE=read-only` condition; the prior user-owned behavior remains for unprivileged local mode. `mcp/src/file_scopes.py` accepts the exact six-field `local-ro` registry entry under that same combination and rejects it in legacy system default mode. Existing no-symlink, owner/mode, file-size, traversal and allowlist checks and stdio three-tool write denial are retained. A single focused `mcp/tests/test_system_ro.py` regression covers root-owned fixture reading and discovery, denied cached writes, wrong owner, unsafe mode, and default-off rejection.

**Evidence on existing VPS in disposable roots only:** Python AST and all three smoke/regression test scripts passed: `test_system_ro.py` as root (it invokes the child as `nobody`), `test_local.py` and `test_local_ro.py` as `nobody`. A separate real *public* file from the pinned `main` Git tree was read/search/listed by a temporary root-owned system read-only scope, matching the exact GitHub bytes and SHA-256; direct delete/traversal calls were rejected and the source was unchanged. Temporary fixtures and Git checkouts were removed. **No production registry, credential, copy, systemd drop-in, service, tunnel, ChatGPT app, private real data or `main` was changed.** Installed service remained `active`, PID `2708803`. The protected original pre-cutover installation remains required for fallback.

**Risk boundary:** the tested source is publicly readable root-owned content, not a proof of safety for arbitrary private files. Explicit `allow` paths, root-owned `local-ro` tree, exact system read-only mode, `DynamicUser` visibility and the target unit's existing sandbox all need to be rechecked before any production scope change. No live GitHub sync is implemented, and no new private local or Drive data is approved.

## NEXT — exact next task

1. **Separate approval before any service change:** stage an isolated, *pinned noncanonical* public Engine document under a root-owned allowlisted local source directory, add only that one read-only project scope to the existing registry, and perform a controlled one-service same-Tunnel-ID cutover/rollback after revalidating the current hashes, service and previous protected rollback directory. Preserve exactly the existing three read tools and never overwrite the original. Do not imply that the public local snapshot updates from GitHub automatically.
2. Once this public-source method is proven through the real connected ChatGPT app, select **one actual canonical KeelarynOS/Domain OS file** by owner and obtain separate permission to expose it; evaluate file freshness, privacy and systemd path visibility first. No broad or recursive real-data access by default.
3. Do not resume automation auditing without a new user request. The existing automation stays unchanged; do not claim its next run was verified. Keep `main`, Windows Manager, credential refs, other services and private project data unchanged.
