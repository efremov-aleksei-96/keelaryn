#!/usr/bin/env python3
"""Synthetic-only smoke test for Keelaryn MCP local stdio; no real project access."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"


def run(argv, env, stdin=None):
    return subprocess.run(
        [sys.executable, "-B", *argv],
        input=stdin, text=True, capture_output=True, check=True,
        env=env, timeout=20,
    )


def tool_result(msg):
    result = msg["result"]
    if result.get("isError"):
        return None
    return json.loads(result["content"][0]["text"])


def main():
    if os.geteuid() == 0:
        raise RuntimeError("Local-mode smoke test must run as an unprivileged user")
    with tempfile.TemporaryDirectory(prefix="keelaryn-mcp-synthetic-") as directory:
        root = Path(directory)
        state = root / "state"
        config = root / "scopes.json"
        config.write_text(json.dumps({
            "schema": "keelarynos_mcp_file_scopes_v1",
            "scopes": {
                "synthetic": {
                    "backend": "workspace",
                    "access": "read-write",
                    "description": "Ephemeral synthetic-only benchmark files",
                },
            },
        }), encoding="utf-8")
        config.chmod(0o600)
        env = dict(os.environ)
        env.update({
            "KEELARYN_MCP_MODE": "local",
            "KEELARYN_MCP_CONFIG": str(config),
            "KEELARYN_MCP_STATE_DIR": str(state),
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        preflight = run([str(SRC / "preflight.py")], env)
        assert "SYNTHETIC_MCP_SANDBOX_PREFLIGHT_PASS" in preflight.stdout
        payload = "Hello from disposable synthetic workspace.\n"
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        actions = [
            ("initialize", {"protocolVersion": "2025-06-18", "clientInfo": {"name": "smoke", "version": "1"}, "capabilities": {}}),
            ("tools/list", {}),
            ("tools/call", {"name": "list_files", "arguments": {"project": "synthetic", "path": ""}}),
            ("tools/call", {"name": "edit_files", "arguments": {"project": "synthetic", "edits": [{"path": "sample.md", "content": payload, "expected_sha256": None}]}}),
            ("tools/call", {"name": "read_files", "arguments": {"project": "synthetic", "paths": ["sample.md"]}}),
            ("tools/call", {"name": "edit_files", "arguments": {"project": "synthetic", "edits": [{"path": "sample.md", "content": "stale", "expected_sha256": "0" * 64}]}}),
            ("tools/call", {"name": "read_files", "arguments": {"project": "not-authorized", "paths": ["sample.md"]}}),
            ("tools/call", {"name": "read_files", "arguments": {"project": "synthetic", "paths": ["../escape.md"]}}),
            ("tools/call", {"name": "delete_files", "arguments": {"project": "synthetic", "files": [{"path": "sample.md", "expected_sha256": digest}]}}),
        ]
        request = "".join(json.dumps({"jsonrpc": "2.0", "id": i, "method": m, "params": p}) + "\n" for i, (m, p) in enumerate(actions, 1))
        output = run([str(SRC / "synthetic_stdio.py")], env, request)
        messages = [json.loads(line) for line in output.stdout.splitlines()]
        assert len(messages) == len(actions), (len(messages), output.stderr)
        assert messages[0]["result"]["protocolVersion"] == "2025-06-18"
        tools = {t["name"] for t in messages[1]["result"]["tools"]}
        assert {"list_files", "read_files", "search_files", "edit_files", "delete_files"} <= tools
        assert tool_result(messages[2])["returned"] == 0
        assert tool_result(messages[3])["count"] == 1
        assert tool_result(messages[4])["files"][0]["sha256"] == digest
        for idx in (5, 6, 7):
            assert messages[idx]["result"]["isError"] is True, messages[idx]
        assert tool_result(messages[8])["count"] == 1
        assert not (state / "workspace" / "sample.md").exists()
        assert not (root / "escape.md").exists()

        # A private final registry file is insufficient when an ancestor is
        # a symlink or writable by other users.
        secure_dir = root / "secure-config"
        secure_dir.mkdir(mode=0o700)
        registry = secure_dir / "file-scopes.json"
        registry.write_bytes(config.read_bytes())
        registry.chmod(0o600)
        config_link = root / "config-link"
        config_link.symlink_to(secure_dir, target_is_directory=True)
        bad_config_env = dict(env, KEELARYN_MCP_CONFIG=str(config_link / registry.name))
        proc = subprocess.run(
            [sys.executable, "-B", str(SRC / "file_scopes.py"), "--preflight"],
            env=bad_config_env, capture_output=True, text=True, timeout=15)
        assert proc.returncode != 0, "Symlinked config ancestor accepted"

        secure_dir.chmod(0o777)
        try:
            bad_config_env = dict(env, KEELARYN_MCP_CONFIG=str(registry))
            proc = subprocess.run(
                [sys.executable, "-B", str(SRC / "file_scopes.py"), "--preflight"],
                env=bad_config_env, capture_output=True, text=True, timeout=15)
            assert proc.returncode != 0, "Writable config parent accepted"
        finally:
            secure_dir.chmod(0o700)

        # Local preflight must not create a state directory through a parent
        # symlink, even if the eventual directory would be privately owned.
        real_parent = root / "real-state-parent"
        real_parent.mkdir(mode=0o700)
        state_link = root / "state-parent-link"
        state_link.symlink_to(real_parent, target_is_directory=True)
        bad_state_env = dict(env, KEELARYN_MCP_STATE_DIR=str(state_link / "new-state"))
        proc = subprocess.run(
            [sys.executable, "-B", str(SRC / "preflight.py")],
            env=bad_state_env, capture_output=True, text=True, timeout=15)
        assert proc.returncode != 0, "Symlinked state ancestor accepted"
        assert not (real_parent / "new-state").exists()

        # A symlink in the workspace location must never be accepted.
        alternate = root / "alternate-state"
        alternate.mkdir(mode=0o700)
        (alternate / "workspace").symlink_to(state / "workspace", target_is_directory=True)
        bad_workspace_env = dict(env, KEELARYN_MCP_STATE_DIR=str(alternate))
        proc = subprocess.run(
            [sys.executable, "-B", str(SRC / "preflight.py")],
            env=bad_workspace_env, capture_output=True, text=True, timeout=15)
        assert proc.returncode != 0, "Symlinked workspace accepted"

        # The server-side synthetic file tools must independently reject
        # a symlinked state ancestor, even if a client skipped preflight.
        alias = root / "runtime-state-link"
        alias.symlink_to(state, target_is_directory=True)
        runtime_env = dict(env, KEELARYN_MCP_STATE_DIR=str(alias))
        request = json.dumps({
            "jsonrpc": "2.0", "id": 20, "method": "tools/call",
            "params": {"name": "list_files", "arguments": {"project": "synthetic", "path": ""}},
        }) + "\n"
        response = run([str(SRC / "synthetic_stdio.py")], runtime_env, request)
        replies = [json.loads(line) for line in response.stdout.splitlines()]
        assert len(replies) == 1 and replies[0]["result"].get("isError") is True
        print("LOCAL_CONFIG_AND_STATE_PATH_SECURITY_PASS")
    print("LOCAL_STDIO_SYNTHETIC_SMOKE_PASS")


if __name__ == "__main__":
    main()
