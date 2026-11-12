#!/usr/bin/env python3
"""Isolated MCP benchmark. No arbitrary paths, shell execution or production access."""
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from fs_tools import FILE_TOOLS, FILE_HANDLERS, file_tool

PROTOCOL = "2025-06-18"
ROOT = Path("/var/lib/keelarynos-mcp-benchmark")
WORK = ROOT / "filesystem-benchmark-20261111"
NAMES = tuple(f"sample-{i:02d}.md" for i in range(1, 11))
FILES = {
    f"synthetic_{i:02d}.md": f"# Temporary sample {i:02d}\n" + ("Synthetic test line.\n" * 30)
    for i in range(1, 11)
}

def content(i, stage):
    return (f"# Synthetic benchmark {i:02d}\n"
            f"Stage: {stage}\n" +
            ("Only synthetic sample content for temporary timing.\n" * 45)).encode("utf-8")

def expected(stage):
    return {name: content(i, stage) for i, name in enumerate(NAMES, 1)}

def digest(b):
    return hashlib.sha256(b).hexdigest()

def dirfd():
    root_link = os.lstat(ROOT)
    if stat.S_ISLNK(root_link.st_mode):
        if os.path.realpath(ROOT) != "/var/lib/private/keelarynos-mcp-benchmark":
            raise ValueError("Unexpected systemd StateDirectory link")
    elif not stat.S_ISDIR(root_link.st_mode):
        raise ValueError("Unsafe StateDirectory type")
    root_stat = os.stat(ROOT)
    if not stat.S_ISDIR(root_stat.st_mode) or root_stat.st_uid != os.getuid():
        raise ValueError("Unsafe root directory")
    st = os.lstat(WORK)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise ValueError("Unsafe benchmark directory")
    return os.open(WORK, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

def verify_names(fd):
    if set(os.listdir(fd)) != set(NAMES):
        raise ValueError("Unexpected benchmark directory contents")

def read_bytes(fd, name):
    f = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
    try:
        s = os.fstat(f)
        if not stat.S_ISREG(s.st_mode) or s.st_size > 30000:
            raise ValueError("Unexpected file type or size")
        with os.fdopen(f, "rb", closefd=False) as h:
            b = h.read(30001)
        if len(b) != s.st_size:
            raise ValueError("File changed during read")
        return b
    finally:
        os.close(f)

def snapshot():
    fd = dirfd()
    try:
        verify_names(fd)
        return {name: read_bytes(fd, name) for name in NAMES}
    finally:
        os.close(fd)

def brief(files, stage):
    return {"count": len(files), "bytes": sum(map(len, files.values())),
            "sha256": {name: digest(b) for name, b in files.items()}, "stage": stage}

def create():
    if WORK.exists() or WORK.is_symlink():
        got = snapshot()
        if got == expected("BEFORE"):
            return {"state": "already_created", **brief(got, "BEFORE")}
        raise ValueError("Directory already exists with different contents")
    WORK.mkdir(mode=0o700)
    fd = dirfd()
    try:
        for name, b in expected("BEFORE").items():
            f = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o600, dir_fd=fd)
            with os.fdopen(f, "wb") as out:
                out.write(b)
                out.flush()
                os.fsync(out.fileno())
        os.fsync(fd)
    finally:
        os.close(fd)
    got = snapshot()
    if got != expected("BEFORE"):
        raise ValueError("Creation verification failed")
    return {"state": "created", **brief(got, "BEFORE")}

def read():
    got = snapshot()
    if got not in (expected("BEFORE"), expected("AFTER")):
        raise ValueError("Unexpected file contents")
    stage = "BEFORE" if got == expected("BEFORE") else "AFTER"
    return {"state": "read", **brief(got, stage)}

def edit():
    fd = dirfd()
    try:
        verify_names(fd)
        current = {name: read_bytes(fd, name) for name in NAMES}
        before, after = expected("BEFORE"), expected("AFTER")
        if current == after:
            return {"state": "already_edited", **brief(current, "AFTER")}
        if any(current[name] not in (before[name], after[name]) for name in NAMES):
            raise ValueError("Unexpected file bytes; refusing edit")
        for name in NAMES:
            if current[name] == after[name]:
                continue
            temp = "." + name + ".new"
            f = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o600, dir_fd=fd)
            with os.fdopen(f, "wb") as out:
                out.write(after[name])
                out.flush()
                os.fsync(out.fileno())
            os.replace(temp, name, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        os.close(fd)
    got = snapshot()
    if got != expected("AFTER"):
        raise ValueError("Edit verification failed")
    return {"state": "edited", **brief(got, "AFTER")}

def verify():
    got = snapshot()
    after = expected("AFTER")
    return {"state": "verified", "matches_expected": got == after, **brief(got, "AFTER" if got == after else "MISMATCH")}

def cleanup():
    if not WORK.exists() and not WORK.is_symlink():
        return {"state": "already_removed", "remaining": 0}
    fd = dirfd()
    try:
        verify_names(fd)
        got = {name: read_bytes(fd, name) for name in NAMES}
        before, after = expected("BEFORE"), expected("AFTER")
        if any(got[name] not in (before[name], after[name]) for name in NAMES):
            raise ValueError("Unexpected data; refusing removal")
        for name in NAMES:
            os.unlink(name, dir_fd=fd)
        os.fsync(fd)
    finally:
        os.close(fd)
    WORK.rmdir()
    return {"state": "removed", "removed": 10, "remaining": 0}

FUNCTIONS = {
    "benchmark_create_files": (create, "Create exactly 10 synthetic Markdown files inside a fixed temporary directory."),
    "benchmark_read_files": (read, "Read 10 temporary on-disk Markdown files and return SHA-256 checksums."),
    "benchmark_edit_files": (edit, "Atomically replace the 10 synthetic files if their exact expected bytes match."),
    "benchmark_verify_files": (verify, "Independently read all 10 files and validate SHA-256 against the expected edited content."),
    "benchmark_cleanup_files": (cleanup, "Remove only the 10 known synthetic files and their dedicated temporary directory.")
}

TOOLS = [
    {"name": "read_synthetic_batch", "description": "Return 10 in-memory synthetic Markdown samples; no filesystem access.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "benchmark_echo", "description": "Echo a short non-sensitive test string (at most 80 characters).", "inputSchema": {"type": "object", "properties": {"text": {"type": "string", "maxLength": 80}}, "required": ["text"], "additionalProperties": False}}
] + [
    {"name": name, "description": description, "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}}
    for name, (func, description) in FUNCTIONS.items()
]

TOOLS.extend(FILE_TOOLS)

def handle(msg):
    method = msg.get("method")
    params = msg.get("params") or {}
    if method == "initialize":
        return {"protocolVersion": PROTOCOL, "serverInfo": {"name": "keelarynos-synthetic-benchmark", "version": "0.2.0"}, "capabilities": {"tools": {"listChanged": True}}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "read_synthetic_batch" and not args:
            return {"content": [{"type": "text", "text": json.dumps(FILES, ensure_ascii=False)}]}
        if name == "benchmark_echo" and isinstance(args.get("text"), str) and len(args["text"]) <= 80 and len(args) == 1:
            return {"content": [{"type": "text", "text": args["text"]}]}
        if name in FILE_HANDLERS:
            return file_tool(name, args)
        if name in FUNCTIONS and not args:
            try:
                outcome = FUNCTIONS[name][0]()
                return {"content": [{"type": "text", "text": json.dumps(outcome)}]}
            except Exception as e:
                return {"isError": True, "content": [{"type": "text", "text": type(e).__name__ + ": " + str(e)}]}
        return {"isError": True, "content": [{"type": "text", "text": "Unsupported tool or arguments"}]}
    raise ValueError("Unknown method")

for line in sys.stdin:
    try:
        msg = json.loads(line)
        if not isinstance(msg, dict) or "method" not in msg:
            continue
        if msg["method"].startswith("notifications/") or "id" not in msg:
            continue
        result = handle(msg)
        reply = {"jsonrpc": "2.0", "id": msg["id"], "result": result}
    except Exception:
        reply = {"jsonrpc": "2.0", "id": msg.get("id") if isinstance(msg, dict) else None,
                 "error": {"code": -32603, "message": "Invalid request"}}
    sys.stdout.write(json.dumps(reply, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()
