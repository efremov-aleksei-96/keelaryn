#!/usr/bin/env python3
"""Synthetic root-owned local-ro tests for the system read-only MCP mode.

Run as root on a disposable Linux test host. Source and fixture contents are
synthetic; no real project files, service changes or tunnel operations occur.
"""
import hashlib
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import tempfile

SRC = Path(__file__).resolve().parents[1] / "src"


def main():
    if os.geteuid() != 0:
        raise RuntimeError("System read-only ownership test requires root for fixture setup")
    nobody = pwd.getpwnam("nobody")
    with tempfile.TemporaryDirectory(prefix="keelaryn-mcp-system-ro-") as d:
        root = Path(d)
        root.chmod(0o755)
        docs = root / "public"
        docs.mkdir(mode=0o755)
        sample = docs / "example.md"
        original = "# Synthetic public document\nroot-owned allowlist needle\n"
        sample.write_text(original, encoding="utf-8")
        sample.chmod(0o644)
        home = root / "user"
        home.mkdir(mode=0o700)
        os.chown(home, nobody.pw_uid, nobody.pw_gid)
        registry = root / "scopes.json"
        scope = {
            "schema": "keelarynos_mcp_file_scopes_v1",
            "scopes": {
                "synthetic": {
                    "backend": "workspace", "access": "read-write",
                    "description": "Ephemeral synthetic-only benchmark files",
                },
                "PublicTest": {
                    "backend": "local-ro", "access": "read-only",
                    "snapshot_only": False, "canonical": False,
                    "root": str(docs), "allow": ["example.md"],
                },
            },
        }
        registry.write_text(json.dumps(scope), encoding="utf-8")
        registry.chmod(0o644)
        env = dict(os.environ,
                   KEELARYN_MCP_MODE="system",
                   KEELARYN_MCP_ACCESS_MODE="read-only",
                   KEELARYN_MCP_CONFIG=str(registry),
                   KEELARYN_MCP_STATE_DIR=str(home / "state"),
                   PYTHONDONTWRITEBYTECODE="1")
        command = ["runuser", "-u", "nobody", "--", sys.executable, "-B"]

        def invoke(filename, *args, params=None, override=None):
            custom = dict(env)
            if override:
                for k, value in override.items():
                    if value is None:
                        custom.pop(k, None)
                    else:
                        custom[k] = value
            req = ""
            if params is not None:
                req = json.dumps({"jsonrpc": "2.0", "id": 1, **params}) + "\n"
            return subprocess.run(command + [str(SRC / filename)] + list(args),
                                  env=custom, input=req, text=True,
                                  capture_output=True, timeout=18)

        init = home / "state"
        init.mkdir(mode=0o700)
        os.chown(init, nobody.pw_uid, nobody.pw_gid)
        workspace = init / "workspace"
        workspace.mkdir(mode=0o700)
        os.chown(workspace, nobody.pw_uid, nobody.pw_gid)
        pf = invoke("file_scopes.py", "--preflight")
        assert pf.returncode == 0, pf.stderr[-500:]
        assert "FILE_SCOPES_RO_PREFLIGHT_PASS" in pf.stdout

        def call(name, args):
            response = invoke("synthetic_stdio.py", params={
                "method": "tools/call",
                "params": {"name": name, "arguments": args},
            })
            assert response.returncode == 0, response.stderr[-500:]
            return json.loads(response.stdout)["result"]

        discover = invoke("synthetic_stdio.py", params={
            "method": "tools/list", "params": {},
        })
        assert discover.returncode == 0
        names = {x["name"] for x in json.loads(discover.stdout)["result"]["tools"]}
        assert names == {"list_files", "read_files", "search_files"}
        listing = json.loads(call("list_files", {"project": "PublicTest"})["content"][0]["text"])
        assert listing["entries"][0]["path"] == "example.md"
        assert listing["canonical"] is False
        result = json.loads(call("read_files", {"project": "PublicTest",
                                                 "paths": ["example.md"]})["content"][0]["text"])
        assert result["files"][0]["content"] == original
        assert result["files"][0]["sha256"] == hashlib.sha256(original.encode()).hexdigest()
        hits = json.loads(call("search_files", {"project": "PublicTest",
                                                  "query": "needle"})["content"][0]["text"])
        assert hits["matches"]
        for name, args in [
            ("read_files", {"project": "PublicTest", "paths": ["unknown.md"]}),
            ("read_files", {"project": "PublicTest", "paths": ["../example.md"]}),
            ("list_files", {"project": "Unknown"}),
            ("edit_files", {"project": "PublicTest", "edits": [
                {"path": "example.md", "content": "NO", "expected_sha256": None}]}),
            ("delete_files", {"project": "PublicTest", "files": [
                {"path": "example.md", "expected_sha256": "0" * 64}]}),
            ("benchmark_echo", {"text": "blocked"}),
        ]:
            assert call(name, args).get("isError") is True, (name, args)
        assert sample.read_text(encoding="utf-8") == original
        print("SYSTEM_ROOT_OWNED_LOCAL_RO_READ_AND_DENIAL_PASS")

        # A DynamicUser-owned document must not be accepted as a root-owned source.
        os.chown(sample, nobody.pw_uid, nobody.pw_gid)
        try:
            assert call("read_files", {"project": "PublicTest",
                                       "paths": ["example.md"]}).get("isError") is True
        finally:
            os.chown(sample, 0, 0)
        docs.chmod(0o777)
        try:
            bad = invoke("synthetic_stdio.py")
            assert bad.returncode != 0
        finally:
            docs.chmod(0o755)
        print("SYSTEM_ROOT_OWNERSHIP_AND_PERMISSIONS_ENFORCED_PASS")

        legacy = invoke("synthetic_stdio.py", override={
            "KEELARYN_MCP_ACCESS_MODE": None})
        assert legacy.returncode != 0 and "Local scope requires" in legacy.stderr
        print("SYSTEM_LOCAL_RO_DEFAULT_MODE_FAIL_CLOSED_PASS")


if __name__ == "__main__":
    main()
