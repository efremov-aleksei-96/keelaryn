#!/usr/bin/python3
"""Fail closed when the benchmark service can see private project locations."""
import os
import stat
from pathlib import Path

root = Path("/var/lib/keelarynos-mcp-benchmark/workspace")
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
for path in hidden:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    except (FileNotFoundError, PermissionError, NotADirectoryError):
        continue
    else:
        os.close(fd)
        raise SystemExit("Sandbox unexpectedly exposes a protected directory")
print("SYNTHETIC_MCP_SANDBOX_PREFLIGHT_PASS", flush=True)
