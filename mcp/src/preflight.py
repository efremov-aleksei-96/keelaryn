#!/usr/bin/python3
"""Fail closed when the benchmark service can see private project locations."""
import os
import stat
from pathlib import Path
from local_ro import open_root as open_local_root

mode = os.environ.get("KEELARYN_MCP_MODE", "system")
if mode not in ("system", "local") or (mode == "local" and os.geteuid() == 0):
    raise SystemExit("Invalid MCP operating mode")
raw_state = os.environ.get("KEELARYN_MCP_STATE_DIR", "/var/lib/keelarynos-mcp-benchmark")
state = Path(raw_state)
if mode == "local":
    if not os.path.isabs(raw_state) or os.path.normpath(raw_state) != raw_state or raw_state == "/":
        raise SystemExit("Local state path must be an absolute canonical directory path")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    # Keep descriptor-relative creation under a checked, non-symlink parent.
    # Local deployment creates the parent with install -d; no auto-created
    # unknown ancestors or inherited symlinks are permitted.
    parent_fd = open_local_root({"root": str(state.parent)})
    try:
        try:
            os.mkdir(state.name, mode=0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
        state_fd = os.open(state.name, flags, dir_fd=parent_fd)
        try:
            owner = os.fstat(state_fd)
            if not stat.S_ISDIR(owner.st_mode) or owner.st_uid != os.geteuid() or owner.st_mode & 0o077:
                raise SystemExit("Unsafe local MCP state root")
            try:
                os.mkdir("workspace", mode=0o700, dir_fd=state_fd)
            except FileExistsError:
                pass
            workspace_fd = os.open("workspace", flags, dir_fd=state_fd)
            try:
                st = os.fstat(workspace_fd)
                if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid() or st.st_mode & 0o077:
                    raise SystemExit("Unsafe isolated workspace")
            finally:
                os.close(workspace_fd)
        finally:
            os.close(state_fd)
    finally:
        os.close(parent_fd)
else:
    root = state / "workspace"
    root.mkdir(mode=0o700, exist_ok=True)
    st = os.lstat(root)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid():
        raise SystemExit("Invalid isolated workspace ownership or type")
    if st.st_mode & 0o077:
        raise SystemExit("Workspace accessible by group or others")

hidden = (
    "/home/keelaryn-ops",
    "/root",
    "/run/user/1000",
    "/srv",
    "/mnt",
    "/media",
    "/opt",
    "/var/www",
    "/var/lib/docker",
    "/var/lib/containerd",
)
for path in (hidden if mode == "system" else ()):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    except (FileNotFoundError, PermissionError, NotADirectoryError):
        continue
    else:
        os.close(fd)
        raise SystemExit("Sandbox unexpectedly exposes a protected directory")
print("SYNTHETIC_MCP_SANDBOX_PREFLIGHT_PASS", flush=True)
