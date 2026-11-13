#!/usr/bin/env python3
"""Disposable VPS G1 tests: no real owner, no production process, no cloud API."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

SRC = Path(__file__).resolve().parents[1] / "src"
UID = pwd.getpwnam("nobody").pw_uid
GID = pwd.getpwnam("nobody").pw_gid
OWNER = "G1Synthetic"
ALLOW = ["alpha.md", "beta.md", "state.json", "notes.csv"]
SHA = lambda x: hashlib.sha256(x.encode("utf-8")).hexdigest()
ID = lambda x: f"{x:032x}"


def main():
    if os.geteuid() != 0:
        raise RuntimeError("G1 synthetic test needs root only to create a nobody-owned fixture")
    with tempfile.TemporaryDirectory(prefix="keelaryn-g1-owner-") as directory:
        root = Path(directory)
        root.chmod(0o755)
        config = root / "config"
        config.mkdir(mode=0o700)
        os.chown(config, UID, GID)
        owner = root / "owner"
        owner.mkdir(mode=0o700)
        os.chown(owner, UID, GID)
        stranger = root / "other-owner"
        stranger.mkdir(mode=0o700)
        os.chown(stranger, UID, GID)
        sentinel = stranger / "sentinel.md"
        sentinel.write_text("Never write to other owner\n")
        sentinel.chmod(0o600)
        os.chown(sentinel, UID, GID)
        registry = config / "file-scopes.json"
        def scope(root_path):
            return {"backend": "owner-fs", "owner": OWNER, "root": str(root_path),
                    "allow": ALLOW, "access": "read-write", "canonical": False,
                    "snapshot_only": False}
        def write_registry(changes=None):
            data = {"schema": "keelarynos_mcp_file_scopes_v1",
                    "scopes": {"synthetic": {"backend": "workspace",
                               "access": "read-write",
                               "description": "Ephemeral synthetic-only benchmark files"},
                               OWNER: changes or scope(owner)}}
            registry.write_text(json.dumps(data))
            os.chown(registry, UID, GID)
            registry.chmod(0o600)
        write_registry()
        workstate = root / "state"
        workstate.mkdir(mode=0o700)
        os.chown(workstate, UID, GID)
        workspace = workstate / "workspace"
        workspace.mkdir(mode=0o700)
        os.chown(workspace, UID, GID)
        base_env = dict(os.environ, KEELARYN_MCP_MODE="local",
                        KEELARYN_MCP_ACCESS_MODE="default",
                        KEELARYN_MCP_OWNER_FS_TEST="1",
                        KEELARYN_MCP_CONFIG=str(registry),
                        KEELARYN_MCP_STATE_DIR=str(workstate),
                        PYTHONDONTWRITEBYTECODE="1",
                        KEELARYN_MCP_BENCHMARK_TOOLS="0")

        def execute(method, params, env=None, timeout=20):
            merged = dict(base_env)
            if env:
                for k, v in env.items():
                    if v is None:
                        merged.pop(k, None)
                    else:
                        merged[k] = v
            data = json.dumps({"jsonrpc": "2.0", "id": 1,
                               "method": method, "params": params}) + "\n"
            return subprocess.run(
                ["runuser", "-u", "nobody", "--", sys.executable, "-B",
                 str(SRC / "synthetic_stdio.py")],
                text=True, input=data, capture_output=True, env=merged, timeout=timeout)

        def call(name, args, env=None, expect_error=False):
            p = execute("tools/call", {"name": name, "arguments": args}, env=env)
            assert p.returncode == 0, (name, p.returncode, p.stderr[-650:])
            result = json.loads(p.stdout)["result"]
            assert bool(result.get("isError")) == expect_error, (name, args, result)
            if expect_error:
                return result["content"][0]["text"]
            return json.loads(result["content"][0]["text"])

        def mutate(action, idx, path, **kwargs):
            return {"project": OWNER, "request_id": ID(idx), "action": action,
                    "path": path, **kwargs}

        # Explicit gating: production stays on 3 tools, local default on 5;
        # only an opted-in local owner receives the sixth mutation tool.
        result = execute("tools/list", {})
        assert result.returncode == 0, result.stderr[-400:]
        tools = {t["name"] for t in json.loads(result.stdout)["result"]["tools"]}
        assert tools == {"list_files", "read_files", "search_files",
                         "edit_files", "delete_files", "owner_mutate"}
        for key, value in [
            ("KEELARYN_MCP_OWNER_FS_TEST", None),
            ("KEELARYN_MCP_MODE", "system"),
            ("KEELARYN_MCP_ACCESS_MODE", "read-only"),
        ]:
            bad = execute("tools/list", {}, {key: value})
            assert bad.returncode != 0, (key, bad.stdout)
        print("G1_DEFAULT_OFF_LOCAL_ONLY_TOOL_VISIBILITY_PASS")

        a = mutate("create", 1, "alpha.md", content="# First\n", expected_sha256=None)
        created = call("owner_mutate", a)
        assert created["status"] == "committed"
        assert created["sha256"] == SHA("# First\n")
        assert (owner / "alpha.md").read_text() == "# First\n"
        assert (owner / "alpha.md").stat().st_mode & 0o777 == 0o600
        assert call("owner_mutate", a)["status"] == "already_committed"
        bad = dict(a, content="# Other\n")
        call("owner_mutate", bad, expect_error=True)
        assert (owner / "alpha.md").read_text() == "# First\n"
        read = call("read_files", {"project": OWNER, "paths": ["alpha.md"]})
        assert read["files"][0]["content"] == "# First\n"
        assert call("list_files", {"project": OWNER})["entries"][0]["path"] == "alpha.md"
        assert call("search_files", {"project": OWNER, "query": "First"})["matches"]
        print("G1_CREATE_SHA_FSYNC_READBACK_IDEMPOTENT_AND_OWNER_READ_PASS")

        # Both processes race on the same initial SHA: exactly one can win.
        first_sha = SHA("# First\n")
        ra = mutate("replace", 2, "alpha.md",
                    content="# Concurrent A\n", expected_sha256=first_sha)
        rb = mutate("replace", 3, "alpha.md",
                    content="# Concurrent B\n", expected_sha256=first_sha)
        def race(args):
            p = execute("tools/call", {"name": "owner_mutate", "arguments": args})
            assert p.returncode == 0, p.stderr[-500:]
            return json.loads(p.stdout)["result"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(race, [ra, rb]))
        assert sum(not x.get("isError") for x in results) == 1, results
        assert sum(bool(x.get("isError")) for x in results) == 1, results
        winner = ra if not results[0].get("isError") else rb
        winner_content = winner["content"]
        assert (owner / "alpha.md").read_text() == winner_content
        assert call("owner_mutate", winner)["status"] == "already_committed"
        print("G1_CROSS_PROCESS_FLOCK_AND_CAS_WINNER_PASS")

        # Rename moves only the same-root allowed file, no arbitrary targets.
        rename = mutate("rename", 4, "alpha.md",
                        new_path="beta.md", expected_sha256=SHA(winner_content))
        assert call("owner_mutate", rename)["status"] == "committed"
        assert not (owner / "alpha.md").exists()
        assert (owner / "beta.md").read_text() == winner_content
        assert call("owner_mutate", rename)["status"] == "already_committed"
        dele = mutate("delete", 5, "beta.md",
                      expected_sha256=SHA(winner_content))
        assert call("owner_mutate", dele)["status"] == "committed"
        assert not (owner / "beta.md").exists()
        assert call("owner_mutate", dele)["status"] == "already_committed"
        print("G1_SINGLE_ROOT_RENAME_DELETE_AND_REPLAY_PASS")

        # Crash just after durable intent but before data, same ID resumes.
        crash_intent = mutate("create", 6, "state.json",
                              content='{"G1":1}\n', expected_sha256=None)
        p = execute("tools/call", {"name": "owner_mutate",
                                  "arguments": crash_intent},
                    env={"KEELARYN_G1_TEST_CRASH_AFTER": "intent"})
        assert p.returncode == 73
        assert not (owner / "state.json").exists()
        other = mutate("create", 7, "notes.csv",
                       content="a,b\n", expected_sha256=None)
        call("owner_mutate", other, expect_error=True)
        assert call("owner_mutate", crash_intent)["status"] == "committed"
        assert call("owner_mutate", other)["status"] == "committed"
        print("G1_INTENT_CRASH_BLOCKS_OTHERS_AND_SAME_ID_RECOVERS_PASS")

        # Crash after atomic file replace but before receipt: new process
        # recognizes new SHA and does not replay an unsafe second write.
        after_data = mutate("replace", 8, "state.json",
                            content='{"G1":2}\n',
                            expected_sha256=SHA('{"G1":1}\n'))
        p = execute("tools/call", {"name": "owner_mutate",
                                  "arguments": after_data},
                    env={"KEELARYN_G1_TEST_CRASH_AFTER": "data"})
        assert p.returncode == 74
        assert (owner / "state.json").read_text() == '{"G1":2}\n'
        assert call("owner_mutate", after_data)["status"] == "committed"
        after_receipt = mutate("replace", 9, "state.json",
                               content='{"G1":3}\n',
                               expected_sha256=SHA('{"G1":2}\n'))
        p = execute("tools/call", {"name": "owner_mutate",
                                  "arguments": after_receipt},
                    env={"KEELARYN_G1_TEST_CRASH_AFTER": "receipt"})
        assert p.returncode == 75
        assert call("owner_mutate", after_receipt)["status"] == "already_committed"
        print("G1_AFTER_DATA_AND_AFTER_RECEIPT_CRASH_RECOVERY_PASS")

        # Previous receipt is stable even after later legitimate mutation.
        previous = call("owner_mutate", after_data)
        assert previous["status"] == "already_committed"
        assert previous["current_matches"] is False

        # Denied cross-owner/incorrect path, cached legacy writes on the
        # persistent scope, symlink, hardlink, chmod, wrong uid and tampering.
        for bad_action in [
            mutate("create", 10, "../sentinel.md",
                   content="WRONG", expected_sha256=None),
            mutate("create", 10, "/tmp/forbidden.md",
                   content="WRONG", expected_sha256=None),
            mutate("create", 10, "unlisted.md",
                   content="WRONG", expected_sha256=None),
            mutate("create", 10, "notes.csv",
                   content="WRONG", expected_sha256=None),
            mutate("replace", 11, "state.json",
                   content='{"G1":4}', expected_sha256="0"*64),
            mutate("create", 12, "beta.md",
                   content="x" * 65537, expected_sha256=None),
            mutate("create", 13, "alpha.md",
                   content="invalid", expected_sha256="0"*64),
        ]:
            call("owner_mutate", bad_action, expect_error=True)
        call("owner_mutate", dict(a, project="synthetic"), expect_error=True)
        call("edit_files", {"project": OWNER, "edits": [{
            "path": "alpha.md", "content": "bad",
            "expected_sha256": None}]}, expect_error=True)
        call("delete_files", {"project": OWNER, "files": [{
            "path": "state.json", "expected_sha256": SHA('{"G1":3}\n')}]},
            expect_error=True)
        assert sentinel.read_text() == "Never write to other owner\n"
        print("G1_CROSS_OWNER_TRAVERSAL_SIZING_AND_LEGACY_WRITE_DENIAL_PASS")

        # Actual on-disk unsafe path obstacles are not overwritten.
        alpha = owner / "alpha.md"
        alpha.symlink_to(sentinel)
        call("owner_mutate", mutate("create", 14, "alpha.md",
              content="bad", expected_sha256=None), expect_error=True)
        alpha.unlink()
        os.link(sentinel, alpha)
        call("owner_mutate", mutate("replace", 15, "alpha.md",
              content="bad", expected_sha256=SHA(sentinel.read_text())),
              expect_error=True)
        alpha.unlink()
        (owner / "alpha.md").write_text("Mode test\n")
        os.chown(alpha, UID, GID)
        alpha.chmod(0o644)
        call("owner_mutate", mutate("replace", 16, "alpha.md",
              content="bad", expected_sha256=SHA("Mode test\n")),
              expect_error=True)
        alpha.chmod(0o600)
        os.chown(alpha, 0, 0)
        call("owner_mutate", mutate("replace", 17, "alpha.md",
              content="bad", expected_sha256=SHA("Mode test\n")),
              expect_error=True)
        alpha.unlink()
        assert sentinel.read_text() == "Never write to other owner\n"
        owner.chmod(0o777)
        try:
            rejected = execute("tools/call", {"name": "owner_mutate",
                                "arguments": mutate("create", 18, "alpha.md",
                                content="bad", expected_sha256=None)})
            # Unsafe root is denied at registry startup, before any tool call.
            assert rejected.returncode != 0
            assert "Local root ownership or permissions are unsafe" in rejected.stderr
        finally:
            owner.chmod(0o700)
        print("G1_SYMLINK_HARDLINK_OWNER_AND_MODE_REFUSAL_PASS")

        # Simulate disk-full at the mutation stage AFTER the durable intent.
        # Persistent state must be reconcilable by the same id.
        # The patch exists only in an independent nobody subprocess.
        blocked = mutate("replace", 19, "state.json",
                         content='{"G1":4}\n', expected_sha256=SHA('{"G1":3}\n'))
        patch = ("import json,os,sys,errno;"
                 "sys.path.insert(0,os.environ['TEST_SRC']);"
                 "import owner_fs;"
                 "\n"
                 "def fail(*a,**kw): raise OSError(errno.ENOSPC,'synthetic ENOSPC')\n"
                 "owner_fs._apply=fail\n"
                 "print(json.dumps(owner_fs.mutate(json.loads(sys.stdin.read()),"
                 "json.loads(os.environ['TEST_SCOPE']))))")
        patched_env = dict(base_env, TEST_SRC=str(SRC),
                           TEST_SCOPE=json.dumps(scope(owner)))
        p = subprocess.run(["runuser", "-u", "nobody", "--",
                            sys.executable, "-B", "-c", patch],
                           input=json.dumps(blocked), text=True, capture_output=True,
                           env=patched_env, timeout=15)
        assert p.returncode != 0 and "synthetic ENOSPC" in p.stderr, p.stderr[-700:]
        assert (owner / "state.json").read_text() == '{"G1":3}\n'
        call("owner_mutate", mutate("create", 20, "beta.md",
             content="not yet\n", expected_sha256=None), expect_error=True)
        assert call("owner_mutate", blocked)["status"] == "committed"
        print("G1_INJECTED_ENOSPC_INTENT_AND_RETRY_PASS")

        # The owner data persists across subprocesses; journal records are
        # technical recovery metadata, never an editable alternate canon.
        assert call("read_files", {"project": OWNER,
                    "paths": ["state.json"]})["files"][0]["content"] == '{"G1":4}\n'
        assert all(not item.is_symlink() for item in owner.iterdir())
        assert sentinel.read_text() == "Never write to other owner\n"
        print("G1_DISPOSABLE_OWNER_DATA_PERSISTENCE_PASS")

        # An interrupted journal temp entry cannot be mistaken for a durable
        # receipt; refuse to proceed until manual reconciliation.
        orphan = owner / ".keelaryn-g1" / ".tmp-interrupted"
        orphan.write_text("unresolved synthetic")
        os.chown(orphan, UID, GID)
        orphan.chmod(0o600)
        try:
            call("owner_mutate", mutate("create", 21, "beta.md",
                 content="blocked\n", expected_sha256=None), expect_error=True)
        finally:
            orphan.unlink()
        assert not (owner / "beta.md").exists()
        print("G1_ORPHAN_JOURNAL_FAIL_CLOSED_PASS")

        # No project may reuse, be nested in, or overlap this owner root.
        original_registry = registry.read_text()
        try:
            data = json.loads(original_registry)
            other = dict(scope(owner), owner="OtherOwner")
            data["scopes"]["OtherOwner"] = other
            registry.write_text(json.dumps(data))
            denied = execute("tools/list", {})
            assert denied.returncode != 0
            assert "Write owner root overlaps another project scope" in denied.stderr
            inner = owner / "nested"
            inner.mkdir(mode=0o700)
            os.chown(inner, UID, GID)
            data["scopes"]["OtherOwner"]["root"] = str(inner)
            registry.write_text(json.dumps(data))
            denied = execute("tools/list", {})
            assert denied.returncode != 0
            assert "Write owner root overlaps another project scope" in denied.stderr
            inner.rmdir()
            data["scopes"]["OtherOwner"] = {
                "backend": "local-ro", "access": "read-only",
                "snapshot_only": False, "canonical": False,
                "root": str(owner), "allow": ["state.json"],
            }
            registry.write_text(json.dumps(data))
            denied = execute("tools/list", {})
            assert denied.returncode != 0
            assert "Write owner root overlaps another project scope" in denied.stderr
        finally:
            registry.write_text(original_registry)
        print("G1_OVERLAPPING_OWNER_AND_READONLY_SCOPE_DENIAL_PASS")
        print("G1_LIMITS: one-file atomicity only; no real systemd, real project, "
              "restore, power-cut or noncooperative same-UID writer test")


if __name__ == "__main__":
    main()
