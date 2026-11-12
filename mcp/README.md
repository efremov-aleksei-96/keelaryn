# Keelaryn MCP — portable component (development only)

**Owner:** Keelaryn Engine, `efremov-aleksei-96/keelaryn`, directory `mcp/`.
**Status (2026-11-12):** configurable paths and a constrained `local-ro` directory backend have been implemented on `dev/mcp-portability` and tested with disposable synthetic data over stdio. This is unqualified development code, not a production deployment or replacement for the running VPS service.
**Canonical component entrypoint:** this README and the source files under `mcp/src/`. No separate STATE/WORKLOG is required.

## Boundaries and purpose

KeelarynOS owns common architecture and information standards. Domain OS/projects own their factual data and canonical sources. This **Keelaryn MCP** component implements bounded file access, not a competing canonical data store or a LifeOS coordinator. The existing Windows-first `manager/` and its `INSTALLATION.json`, Gate Framework, release identities and qualification remain separate and unchanged.

Core interface: five generic MCP tools — `list_files`, `read_files`, `search_files`, `edit_files`, `delete_files`. The current source additionally exposes seven synthetic benchmark/testing tools. The operating model is **standard JSON-RPC MCP over stdio**; a particular AI, Google Drive, VPS provider or tunnel is not mandatory for the protocol itself.

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

The backend supports `list_files`, `read_files` (including existing character paging) and `search_files`. `edit_files` and `delete_files` are denied regardless of arguments. A single document is capped at 64 KiB, reads at 256 KiB total, a directory at 1000 entries, and search at 100 documents. A broader compatibility/security review, independently controlled writers and host-specific permission cases are **not** covered by synthetic testing. The `canonical` flag is operator-declared metadata; it does not itself establish that a local copy is current.

### Latest verified test

GitHub development commit `6bb2b4ca3ca2a92d565f81b016bf870fc45e016f` was read as a pinned source revision on 2026-11-12. All **eight** Python source/test files passed AST parsing. Inside an automatically removed disposable directory, tests run as unprivileged `nobody` returned:

- `LOCAL_STDIO_SYNTHETIC_SMOKE_PASS`: existing synthetic stdio regression.
- `LOCAL_RO_MCP_INTEGRATION_PASS`: actual MCP initialize/discovery, local allowlisted list/read/page/search, and rejection of out-of-scope paths, symlinks, sensitive names, writes, deletions, unsafe file/directory permissions, symlinked roots and a writable registry.

Only synthetic files were involved. Temporary source/test directories were removed. The production systemd service remained active with its prior MainPID `2636967`; no running service, installed Python file, production configuration, user data or credential was changed. This is **not** a clean deployment on an independent machine, exhaustive adversarial testing or proof of conflict-safe writes.

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

## NEXT — exact next task

1. On **`dev/mcp-portability` only**, verify a fresh checkout of the pinned source on a **separate clean Linux environment** under an unprivileged account, running both synthetic test files without secrets or real project data. Prefer an isolated GitHub-hosted Ubuntu runner after checking repository workflow governance; do not require a local PC.
2. Address security gaps found there without enlarging scope: source/config ownership, symlink/path failures, and fail-closed behavior. Keep real project write and delete operations denied until an atomic concurrency mechanism is independently proven.
3. Once the independent test passes, document a minimal systemd install and rollback procedure for an optional tunnel, with a single active tunnel instance per ID. Do **not** deploy, restart or modify the running VPS before an explicit authorized migration.
4. Preserve the single canonical `mcp/README.md` checkpoint and verify every substantive GitHub write by rereading it.

No changes to `main`, `manager/`, `hub/`, real Google Drive files, credentials, running VPS configuration or services are authorized by this development checkpoint.
