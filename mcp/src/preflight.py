#!/usr/bin/python3
"""Fail closed when the benchmark service can see private project locations."""
import os
import stat
from pathlib import Path

mode = os.environ.get("KEELARYN_MCP_MODE", "system")
if mode not in ("system", "local") or (mode == "local" and os.geteuid() == 0):
    raise SystemExit("Invalid MCP operating mode")
state = Path(os.environ.get("KEELARYN_MCP_STATE_DIR", "/var/lib/keelarynos-mcp-benchmark"))
if mode == "local":
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    owner = os.lstat(state)
    if not stat.S_ISDIR(owner.st_mode) or owner.st_uid != os.geteuid() or owner.st_mode & 0o077:
        raise SystemExit("Unsafe local MCP state root")
root = state / "workspace"
root.mkdir(mode=0o700, exist_ok=True)
st = os.lstat(root)
if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid():
    raise SystemExit("Invalid isolated workspace ownership or type")
if (st.st_mode & 0o077) != 0:
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
