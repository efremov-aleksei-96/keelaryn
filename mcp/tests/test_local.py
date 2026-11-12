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


def benchmark_direct_cases(root, config, env):
    """All benchmark_* calls, without preflight, use only synthetic fixtures."""
    parent = root / "benchmark-actual-parent"
    parent.mkdir(mode=0o700)
    state = parent / "state"
    state.mkdir(mode=0o700)
    benchmark_env = dict(env, KEELARYN_MCP_BENCHMARK_TOOLS="1")
    actual_env = dict(benchmark_env, KEELARYN_MCP_STATE_DIR=str(state))
    alias = root / "benchmark-parent-alias"
    alias.symlink_to(parent, target_is_directory=True)
    alias_env = dict(benchmark_env, KEELARYN_MCP_STATE_DIR=str(alias / "state"))
    root_alias = root / "benchmark-root-alias"
    root_alias.symlink_to(state, target_is_directory=True)
    root_alias_env = dict(benchmark_env, KEELARYN_MCP_STATE_DIR=str(root_alias))
    work = state / "filesystem-benchmark-20261111"

    def invoke(which, environment):
        request = json.dumps({
            "jsonrpc": "2.0", "id": 55, "method": "tools/call",
            "params": {"name": which, "arguments": {}},
        }) + "\n"
        response = run([str(SRC / "synthetic_stdio.py")], environment, request)
        messages = [json.loads(line) for line in response.stdout.splitlines()]
        assert len(messages) == 1, response.stderr
        return messages[0]["result"]

    def accepted(which, environment):
        result = invoke(which, environment)
        assert not result.get("isError"), (which, result)
        return json.loads(result["content"][0]["text"])

    def denied(which, environment):
        result = invoke(which, environment)
        assert result.get("isError") is True, (which, result)

    # Opt-in must restore all seven historical tools and their handlers.
    inputs = [
        ("tools/list", {}),
        ("tools/call", {"name": "benchmark_echo", "arguments": {"text": "synthetic-ok"}}),
        ("tools/call", {"name": "read_synthetic_batch", "arguments": {}}),
    ]
    request = "".join(json.dumps({"jsonrpc": "2.0", "id": i, "method": m, "params": p}) + "\n"
                      for i, (m, p) in enumerate(inputs, 1))
    outputs = run([str(SRC / "synthetic_stdio.py")], actual_env, request)
    replies = [json.loads(line) for line in outputs.stdout.splitlines()]
    assert len(replies) == 3, outputs.stderr
    names = {t["name"] for t in replies[0]["result"]["tools"]}
    extras = {"benchmark_create_files", "benchmark_read_files", "benchmark_edit_files",
              "benchmark_verify_files", "benchmark_cleanup_files",
              "benchmark_echo", "read_synthetic_batch"}
    assert len(names) == 12 and extras <= names, names
    assert replies[1]["result"]["content"][0]["text"] == "synthetic-ok"
    assert len(json.loads(replies[2]["result"]["content"][0]["text"])) == 10
    print("BENCHMARK_EXPLICIT_OPT_IN_PASS")

    operations = (
        "benchmark_create_files",
        "benchmark_read_files",
        "benchmark_edit_files",
        "benchmark_verify_files",
        "benchmark_cleanup_files",
    )
    # No preflight is called: the benchmark handlers independently
    # enforce the same local state-root path constraints. The historical
    # root-link bug created a directory *before* returning an error.
    denied(operations[0], alias_env)
    denied(operations[0], root_alias_env)
    assert not work.exists(), "Rejected create left a benchmark directory"
    assert accepted(operations[0], actual_env)["state"] == "created"
    assert accepted(operations[0], actual_env)["state"] == "already_created"
    assert accepted(operations[1], actual_env)["state"] == "read"
    assert accepted(operations[2], actual_env)["state"] == "edited"
    assert accepted(operations[2], actual_env)["state"] == "already_edited"
    assert accepted(operations[3], actual_env)["matches_expected"] is True
    preserved = {p.name: p.read_bytes() for p in work.iterdir()}
    assert len(preserved) == 10

    # The vulnerable version accepted all these calls via a symlinked
    # parent. No operation may now read or modify the target directory.
    for which in operations:
        denied(which, alias_env)
    assert {p.name: p.read_bytes() for p in work.iterdir()} == preserved

    # Previously 'create' reported error but still created this directory
    # through a symlink at the state root before calling dirfd().
    denied(operations[0], root_alias_env)
    assert {p.name: p.read_bytes() for p in work.iterdir()} == preserved

    # An unsafe state mode is rejected even without preflight.
    state.chmod(0o777)
    try:
        for which in operations:
            denied(which, actual_env)
        assert {p.name: p.read_bytes() for p in work.iterdir()} == preserved
    finally:
        state.chmod(0o700)

    assert accepted(operations[4], actual_env)["state"] == "removed"
    assert accepted(operations[4], actual_env)["state"] == "already_removed"
    assert not work.exists()

    # No state directory may be created implicitly by benchmark_create.
    missing = root / "missing-benchmark-state"
    denied(operations[0], dict(benchmark_env, KEELARYN_MCP_STATE_DIR=str(missing)))
    assert not missing.exists()

    # A named benchmark directory symlink cannot redirect any tool.
    external = root / "benchmark-external-synthetic"
    external.mkdir(mode=0o700)
    sentinel = external / "sentinel.md"
    sentinel.write_text("synthetic sentinel\n", encoding="utf-8")
    work.symlink_to(external, target_is_directory=True)
    try:
        for which in operations:
            denied(which, actual_env)
        assert sentinel.read_text(encoding="utf-8") == "synthetic sentinel\n"
        assert work.is_symlink()
    finally:
        work.unlink()

    print("BENCHMARK_DIRECT_PATH_SECURITY_PASS")
    print("BENCHMARK_DIRECT_LIFECYCLE_PASS")


def schema_runtime_cases(env):
    """Check all five public schemas and validate paging before backend I/O."""
    code = '''
import fs_tools
tools = {item["name"]: item["inputSchema"] for item in fs_tools.FILE_TOOLS}
names = {"list_files", "read_files", "search_files", "edit_files", "delete_files"}
assert set(tools) == names
assert all(schema["additionalProperties"] is False for schema in tools.values())
assert tools["list_files"]["properties"]["path"]["maxLength"] == 320
assert tools["list_files"]["properties"]["limit"]["maximum"] == 100
rp = tools["read_files"]["properties"]
assert tools["read_files"]["required"] == ["paths"]
assert rp["paths"]["maxItems"] == 20 and rp["paths"]["items"]["maxLength"] == 320
assert rp["offset_chars"]["maximum"] == 4194304
assert rp["max_chars"]["maximum"] == 16384
sp = tools["search_files"]["properties"]
assert tools["search_files"]["required"] == ["query"]
assert sp["limit"]["maximum"] == 20 and "pattern" in sp["query"]
ep = tools["edit_files"]["properties"]["edits"]["items"]
dp = tools["delete_files"]["properties"]["files"]["items"]
assert tools["edit_files"]["required"] == ["edits"]
assert tools["delete_files"]["required"] == ["files"]
assert ep["properties"]["path"]["maxLength"] == 320
assert dp["properties"]["path"]["maxLength"] == 320
assert ep["properties"]["expected_sha256"]["pattern"] == "^[0-9a-f]{64}$"
assert dp["properties"]["expected_sha256"]["pattern"] == "^[0-9a-f]{64}$"
assert ep["additionalProperties"] is False and dp["additionalProperties"] is False
for required in ("path", "content", "expected_sha256"):
    assert required in ep["required"]
for required in ("path", "expected_sha256"):
    assert required in dp["required"]

calls = []
def dummy_handler(args):
    calls.append(args)
    return {"files": [{"path": "sample.md", "content": "synthetic text", "sha256": "0" * 64}]}
fs_tools.FILE_HANDLERS["read_files"] = dummy_handler
bad = [
    {"offset_chars": -1}, {"offset_chars": 4194305},
    {"offset_chars": True}, {"offset_chars": "0"},
    {"max_chars": 0}, {"max_chars": 16385},
    {"max_chars": False}, {"max_chars": "5"},
]
for invalid in bad:
    try:
        fs_tools._route_file_tool("read_files", {"paths": ["sample.md"], **invalid})
        raise AssertionError("Malformed paging was accepted")
    except ValueError:
        pass
assert not calls, "Invalid paging reached backend despite rejection"
valid = fs_tools._route_file_tool(
    "read_files", {"paths": ["sample.md"], "offset_chars": 2, "max_chars": 5}
)
assert len(calls) == 1
doc = valid["files"][0]
assert doc["content"] == "nthet" and doc["next_offset_chars"] == 7
assert doc["total_chars"] == len("synthetic text")
assert fs_tools.file_tool("read_files", {"project": "Unknown", "paths": ["sample.md"]})["isError"]
assert fs_tools.file_tool("edit_files", {"project": "Unknown", "edits": []})["isError"]
assert fs_tools.file_tool("delete_files", {"project": "Unknown", "files": []})["isError"]
print("MCP_FIVE_TOOL_SCHEMA_RUNTIME_ALIGNMENT_PASS")
'''
    response = run(["-c", code], dict(env, PYTHONPATH=str(SRC)))
    assert "MCP_FIVE_TOOL_SCHEMA_RUNTIME_ALIGNMENT_PASS" in response.stdout
    print("MCP_FIVE_TOOL_SCHEMA_RUNTIME_ALIGNMENT_PASS")


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
        schema_runtime_cases(env)
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
            ("tools/call", {"name": "benchmark_create_files", "arguments": {}}),
            ("tools/call", {"name": "benchmark_echo", "arguments": {"text": "disabled"}}),
            ("tools/call", {"name": "read_synthetic_batch", "arguments": {}}),
        ]
        request = "".join(json.dumps({"jsonrpc": "2.0", "id": i, "method": m, "params": p}) + "\n" for i, (m, p) in enumerate(actions, 1))
        output = run([str(SRC / "synthetic_stdio.py")], env, request)
        messages = [json.loads(line) for line in output.stdout.splitlines()]
        assert len(messages) == len(actions), (len(messages), output.stderr)
        assert messages[0]["result"]["protocolVersion"] == "2025-06-18"
        tools = {t["name"] for t in messages[1]["result"]["tools"]}
        assert tools == {"list_files", "read_files", "search_files", "edit_files", "delete_files"}, tools
        assert tool_result(messages[2])["returned"] == 0
        assert tool_result(messages[3])["count"] == 1
        assert tool_result(messages[4])["files"][0]["sha256"] == digest
        for idx in (5, 6, 7, 9, 10, 11):
            assert messages[idx]["result"]["isError"] is True, messages[idx]
        assert tool_result(messages[8])["count"] == 1
        assert not (state / "filesystem-benchmark-20261111").exists()
        print("BENCHMARK_DEFAULT_HIDDEN_AND_DENIED_PASS")
        invalid = dict(env, KEELARYN_MCP_BENCHMARK_TOOLS="invalid")
        rejected = subprocess.run([sys.executable, "-B", str(SRC / "synthetic_stdio.py")],
                                  input="", capture_output=True, text=True, env=invalid, timeout=15)
        assert rejected.returncode != 0, "Invalid benchmark opt-in accepted"
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
        benchmark_direct_cases(root, config, env)
    print("LOCAL_STDIO_SYNTHETIC_SMOKE_PASS")


if __name__ == "__main__":
    main()
