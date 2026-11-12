#!/usr/bin/env python3
"""Synthetic local read-only MCP integration and safety tests; no production data."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"


def call_stdio(env, requests):
    incoming = "".join(json.dumps({"jsonrpc": "2.0", "id": i, "method": method, "params": params}) + "\n"
                       for i, (method, params) in enumerate(requests, 1))
    p = subprocess.run([sys.executable, "-B", str(SRC / "synthetic_stdio.py")],
                       input=incoming, capture_output=True, text=True, env=env, timeout=25)
    if p.returncode:
        raise AssertionError("MCP startup failed: " + p.stderr[:300])
    replies = [json.loads(x) for x in p.stdout.splitlines()]
    assert len(replies) == len(requests), (len(replies), p.stderr)
    return replies


def data(reply):
    result = reply["result"]
    if result.get("isError"):
        return None
    return json.loads(result["content"][0]["text"])


def fail(reply):
    assert reply["result"].get("isError") is True, reply


def security_cases(top, docs, scope, env):
    """Targeted synthetic directory-replacement races and resource limits."""
    import shutil
    sys.path.insert(0, str(SRC))
    import local_ro

    notes = docs / "notes"
    outside = docs / "elsewhere.md"

    # Deterministically swap the named file for a symlink at the actual open().
    # The open file descriptor must never dereference the symlink.
    original_open = local_ro.os.open
    before_file = notes / "public.md"
    saved = notes / "saved.md"
    swapped = False

    def swap_file(name, flags, *args, **kwargs):
        nonlocal swapped
        if name == "public.md" and "dir_fd" in kwargs and not swapped:
            swapped = True
            before_file.rename(saved)
            before_file.symlink_to(outside)
        return original_open(name, flags, *args, **kwargs)

    local_ro.os.open = swap_file
    try:
        try:
            local_ro._read_files(scope, ["notes/public.md"])
            raise AssertionError("Symlink substitution was followed")
        except OSError:
            pass
        assert swapped
    finally:
        local_ro.os.open = original_open
        before_file.unlink()
        saved.rename(before_file)

    # Directory substitution must also fail with O_DIRECTORY|O_NOFOLLOW.
    original_open = local_ro.os.open
    moved = docs / "savednotes"
    swapped = False

    def swap_directory(name, flags, *args, **kwargs):
        nonlocal swapped
        if name == "notes" and "dir_fd" in kwargs and not swapped:
            swapped = True
            notes.rename(moved)
            notes.symlink_to(moved, target_is_directory=True)
        return original_open(name, flags, *args, **kwargs)

    local_ro.os.open = swap_directory
    try:
        try:
            local_ro._read_files(scope, ["notes/public.md"])
            raise AssertionError("Directory substitution was followed")
        except OSError:
            pass
        assert swapped
    finally:
        local_ro.os.open = original_open
        notes.unlink()
        moved.rename(notes)

    # Search must use the same pinned root FD even if its pathname is
    # replaced by another user-owned directory after the root is enumerated.
    original_entries = local_ro._directory_entries
    previous_root = top / "renamed-source"
    swapped = False

    def swap_root(fd):
        nonlocal swapped
        names = original_entries(fd)
        if not swapped:
            swapped = True
            docs.rename(previous_root)
            docs.mkdir(mode=0o700)
            (docs / "notes").mkdir(mode=0o700)
            (docs / "notes" / "injected.md").write_text("injected data", encoding="utf-8")
        return names

    local_ro._directory_entries = swap_root
    try:
        result = local_ro._search(scope, "injected", 20)
        assert not result["matches"], result
        assert swapped
    finally:
        local_ro._directory_entries = original_entries
        shutil.rmtree(docs)
        previous_root.rename(docs)

    # File size and aggregate read budget: reject before returning contents.
    oversize = notes / "oversize.md"
    oversize.write_bytes(b"x" * (local_ro.MAX_FILE + 1))
    try:
        try:
            local_ro._read_files(scope, ["notes/oversize.md"])
            raise AssertionError("Oversize document accepted")
        except ValueError:
            pass
        assert "oversize.md" not in {x["path"].split("/")[-1]
                                     for x in local_ro._list(scope, "notes", 100)["entries"]}
    finally:
        oversize.unlink()

    batch = [notes / ("batch%02d.md" % i) for i in range(5)]
    for file in batch:
        file.write_bytes(b"x" * 62000)
    try:
        try:
            local_ro._read_files(scope, ["notes/" + f.name for f in batch])
            raise AssertionError("Aggregate read size exceeded")
        except ValueError:
            pass
    finally:
        for file in batch:
            file.unlink()

    # Search file budget stays at 100; no silent full-tree scan.
    many_files = [notes / ("scan%03d.md" % i) for i in range(110)]
    for file in many_files:
        file.write_text("no-match\n", encoding="utf-8")
    try:
        r = local_ro._search(scope, "absent-value", 20)
        assert r["truncated"] and r["scanned"] == local_ro.MAX_SEARCH_FILES, r
    finally:
        for file in many_files:
            file.unlink()

    # New global directory budget: trees of empty directories cannot
    # consume unbounded CPU when no documents are present.
    many_dirs = [notes / ("d%03d" % i) for i in range(120)]
    for d in many_dirs:
        d.mkdir()
    try:
        r = local_ro._search(scope, "absent-value", 20)
        assert r["truncated"] and r["visited_directories"] == local_ro.MAX_SEARCH_DIRECTORIES, r
    finally:
        for d in many_dirs:
            d.rmdir()

    # New global entry budget also limits trees with few readable documents.
    groups = [notes / "alpha", notes / "beta"]
    for d in groups:
        d.mkdir()
    try:
        for d in groups:
            for i in range(550):
                (d / (".ignored%04d" % i)).touch()
        r = local_ro._search(scope, "absent-value", 20)
        assert r["truncated"] and r["visited_entries"] == local_ro.MAX_SEARCH_ENTRIES, r
    finally:
        for d in groups:
            shutil.rmtree(d)

    # Per-directory 1,000-entry cap must fail closed on a larger directory.
    excessive = [notes / ("item%04d.md" % i) for i in range(1001)]
    for file in excessive:
        file.touch()
    try:
        try:
            local_ro._list(scope, "notes", 100)
            raise AssertionError("Large directory was accepted")
        except ValueError:
            pass
    finally:
        for file in excessive:
            file.unlink()

    # No writes, even if the caller supplies a valid path or synthetic hash.
    for operation in ("edit_files", "delete_files"):
        try:
            local_ro.operate(operation, {}, scope)
            raise AssertionError("Write operation allowed")
        except ValueError:
            pass
    assert outside.read_text(encoding="utf-8") == "outside scope"
    assert (notes / "public.md").read_text(encoding="utf-8") == "needle first\nsecond line\n"
    print("LOCAL_RO_ADVERSARIAL_LIMITS_PASS")


def main():
    if os.geteuid() == 0:
        raise RuntimeError("Run as unprivileged user")
    with tempfile.TemporaryDirectory(prefix="keelaryn-mcp-local-ro-") as temp:
        top = Path(temp)
        docs = top / "owned-docs"
        docs.mkdir(mode=0o700)
        (docs / "notes").mkdir(mode=0o700)
        (docs / "notes" / "public.md").write_text("needle first\nsecond line\n", encoding="utf-8")
        (docs / "notes" / "other.csv").write_text("header,needle\n", encoding="utf-8")
        (docs / "notes" / "secret.md").write_text("SHOULD_NOT_BE_SEEN", encoding="utf-8")
        (docs / "elsewhere.md").write_text("outside scope", encoding="utf-8")
        (docs / "notes" / "ref.md").symlink_to(docs / "elsewhere.md")
        (docs / "alias").symlink_to(docs / "notes", target_is_directory=True)
        state = top / "state"
        cfg = top / "scopes.json"
        scopes = {"schema": "keelarynos_mcp_file_scopes_v1", "scopes": {
            "synthetic": {"backend": "workspace", "access": "read-write",
                          "description": "Ephemeral synthetic-only benchmark files"},
            "LocalDemo": {"backend": "local-ro", "access": "read-only",
                          "snapshot_only": False, "canonical": False,
                          "root": str(docs), "allow": ["notes/"]}}}
        cfg.write_text(json.dumps(scopes), encoding="utf-8")
        cfg.chmod(0o600)
        env = dict(os.environ, KEELARYN_MCP_MODE="local",
                   KEELARYN_MCP_CONFIG=str(cfg), KEELARYN_MCP_STATE_DIR=str(state),
                   PYTHONDONTWRITEBYTECODE="1")
        preflight = subprocess.run([sys.executable, "-B", str(SRC / "preflight.py")],
                                   env=env, capture_output=True, text=True, timeout=15)
        assert preflight.returncode == 0, preflight.stderr
        req = [
            ("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "local-ro-smoke", "version": "1"}}),
            ("tools/list", {}),
            ("tools/call", {"name": "list_files", "arguments": {"project": "LocalDemo", "path": ""}}),
            ("tools/call", {"name": "list_files", "arguments": {"project": "LocalDemo", "path": "notes"}}),
            ("tools/call", {"name": "read_files", "arguments": {"project": "LocalDemo", "paths": ["notes/public.md"], "offset_chars": 7, "max_chars": 5}}),
            ("tools/call", {"name": "search_files", "arguments": {"project": "LocalDemo", "query": "needle"}}),
            ("tools/call", {"name": "read_files", "arguments": {"project": "LocalDemo", "paths": ["elsewhere.md"]}}),
            ("tools/call", {"name": "read_files", "arguments": {"project": "LocalDemo", "paths": ["notes/ref.md"]}}),
            ("tools/call", {"name": "list_files", "arguments": {"project": "LocalDemo", "path": "alias"}}),
            ("tools/call", {"name": "read_files", "arguments": {"project": "LocalDemo", "paths": ["notes/secret.md"]}}),
            ("tools/call", {"name": "read_files", "arguments": {"project": "LocalDemo", "paths": ["../elsewhere.md"]}}),
            ("tools/call", {"name": "read_files", "arguments": {"project": "Unknown", "paths": ["notes/public.md"]}}),
            ("tools/call", {"name": "edit_files", "arguments": {"project": "LocalDemo", "edits": [{"path": "notes/public.md", "content": "changed", "expected_sha256": "0" * 64}]}}),
            ("tools/call", {"name": "delete_files", "arguments": {"project": "LocalDemo", "files": [{"path": "notes/public.md", "expected_sha256": "0" * 64}]}}),
        ]
        results = call_stdio(env, req)
        assert results[0]["result"]["protocolVersion"] == "2025-06-18"
        assert {t["name"] for t in results[1]["result"]["tools"]} >= {"list_files", "read_files", "search_files", "edit_files", "delete_files"}
        assert {x["path"] for x in data(results[2])["entries"]} == {"notes"}
        assert {x["path"] for x in data(results[3])["entries"]} == {"notes/public.md", "notes/other.csv"}
        p = data(results[4])["files"][0]
        assert p["content"] == "first" and p["total_chars"] == len("needle first\nsecond line\n")
        assert {x["path"] for x in data(results[5])["matches"]} == {"notes/public.md", "notes/other.csv"}
        for r in results[6:]:
            fail(r)
        assert (docs / "notes" / "public.md").read_text() == "needle first\nsecond line\n"
        file = docs / "notes" / "public.md"
        file.chmod(0o666)
        fail(call_stdio(env, [("tools/call", {"name": "read_files", "arguments": {"project": "LocalDemo", "paths": ["notes/public.md"]}})])[0])
        file.chmod(0o644)
        (docs / "notes").chmod(0o777)
        fail(call_stdio(env, [("tools/call", {"name": "read_files", "arguments": {"project": "LocalDemo", "paths": ["notes/public.md"]}})])[0])
        (docs / "notes").chmod(0o700)
        bad = top / "root-link"
        bad.symlink_to(docs, target_is_directory=True)
        scopes["scopes"]["LocalDemo"]["root"] = str(bad)
        cfg.write_text(json.dumps(scopes), encoding="utf-8")
        p = subprocess.run([sys.executable, "-B", str(SRC / "synthetic_stdio.py")],
                           env=env, input="", capture_output=True, text=True, timeout=10)
        assert p.returncode != 0
        scopes["scopes"]["LocalDemo"]["root"] = str(docs)
        cfg.write_text(json.dumps(scopes), encoding="utf-8")
        cfg.chmod(0o666)
        p = subprocess.run([sys.executable, "-B", str(SRC / "synthetic_stdio.py")],
                           env=env, input="", capture_output=True, text=True, timeout=10)
        assert p.returncode != 0
        assert (docs / "notes" / "public.md").read_text() == "needle first\nsecond line\n"
        cfg.chmod(0o600)
        security_cases(top, docs, scopes["scopes"]["LocalDemo"], env)
    print("LOCAL_RO_MCP_INTEGRATION_PASS")


if __name__ == "__main__":
    main()
