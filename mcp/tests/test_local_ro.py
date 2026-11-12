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
    print("LOCAL_RO_MCP_INTEGRATION_PASS")


if __name__ == "__main__":
    main()
