#!/usr/bin/env python3
"""Synthetic large owner end-to-end MCP test. Never reads actual project data."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import tempfile

SRC = Path(__file__).resolve().parents[1] / "src"
UID = pwd.getpwnam("nobody").pw_uid
GID = pwd.getpwnam("nobody").pw_gid
SHA = lambda b: hashlib.sha256(b).hexdigest()
ID = lambda n: f"{n:032x}"


def main():
    if os.geteuid() != 0:
        raise RuntimeError("Root required only to prepare disposable nobody-owned fixture")
    with tempfile.TemporaryDirectory(prefix="keelaryn-large-owner-e2e-") as dirname:
        root = Path(dirname)
        root.chmod(0o755)
        config_dir = root / "config"
        config_dir.mkdir(mode=0o700)
        os.chown(config_dir, UID, GID)
        state = root / "state"
        state.mkdir(mode=0o700)
        os.chown(state, UID, GID)
        folder = root / "owner"
        folder.mkdir(mode=0o700)
        os.chown(folder, UID, GID)
        stranger = root / "stranger"
        stranger.mkdir(mode=0o700)
        os.chown(stranger, UID, GID)
        secret = stranger / "NOT_A_SOURCE.md"
        secret.write_text("NEVER EXPOSE OR MODIFY\n")
        os.chown(secret, UID, GID)
        secret.chmod(0o600)
        files = {
            "PROJECT.md": "# Example project\n",
            "STATE.md": "# NEXT: synthetic only\n",
            "MASTERY.csv": "item_id,skill,source\n" +
              "".join(f"TEST-{i:04d},reading,\"synthetic {i:04d}\"\n"
                      for i in range(3500)),
            "JOURNAL.md": ("# Synthetic Armenian lesson :: սա փորձ է ✅\n" * 13000),
        }
        assert len(files["MASTERY.csv"].encode()) > 90 * 1024
        assert 660 * 1024 < len(files["JOURNAL.md"].encode()) < 2 * 1024 * 1024
        for name, content in files.items():
            path = folder / name
            path.write_text(content, encoding="utf-8")
            path.chmod(0o600)
            os.chown(path, UID, GID)
        config = config_dir / "scopes.json"
        config.write_text(json.dumps({
            "schema": "keelarynos_mcp_file_scopes_v1",
            "scopes": {
                "synthetic": {"backend": "workspace", "access": "read-write",
                              "description": "Ephemeral synthetic-only benchmark files"},
                "LargePilot": {
                    "backend": "owner-fs", "owner": "LargePilot",
                    "root": str(folder), "allow": list(files),
                    "access": "read-write", "canonical": False,
                    "snapshot_only": False,
                },
            },
        }), encoding="utf-8")
        config.chmod(0o600)
        os.chown(config, UID, GID)
        env = dict(os.environ, KEELARYN_MCP_MODE="local",
                   KEELARYN_MCP_CONFIG=str(config),
                   KEELARYN_MCP_STATE_DIR=str(state),
                   KEELARYN_MCP_OWNER_FS_TEST="1",
                   KEELARYN_MCP_LARGE_OWNER_PILOT="1",
                   KEELARYN_MCP_BENCHMARK_TOOLS="0",
                   PYTHONDONTWRITEBYTECODE="1")
        def call(name, args, env_override=None):
            message = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": name, "arguments": args}}
            cmd = ["runuser", "-u", "nobody", "--",
                   sys.executable, "-B", str(SRC / "synthetic_stdio.py")]
            p = subprocess.run(cmd, input=json.dumps(message) + "\n",
                               capture_output=True, text=True, timeout=30,
                               env=env_override or env)
            assert p.returncode == 0, p.stderr[-600:]
            res = json.loads(p.stdout)["result"]
            if res.get("isError"):
                return {"error": res["content"][0]["text"]}
            return json.loads(res["content"][0]["text"])
        def request(name, path, **kwargs):
            return {"project": "LargePilot", "path": path, **kwargs}

        preflight = subprocess.run(
            ["runuser", "-u", "nobody", "--", sys.executable, "-B",
             str(SRC / "file_scopes.py"), "--preflight"],
            capture_output=True, text=True, env=env, timeout=25)
        assert preflight.returncode == 0, preflight.stderr
        print("LARGE_PILOT_PREFLIGHT_PASS", flush=True)
        listing = call("list_files", {"project": "LargePilot"})
        assert {x["path"] for x in listing["entries"]} == set(files), listing
        search = call("search_files", {"project": "LargePilot",
                                      "query": "TEST-1077", "limit": 2})
        assert search["matches"][0]["path"] == "MASTERY.csv" and search["matches"][0]["line"] == 1079, search
        large_page = call("read_files", {"project": "LargePilot",
                                        "paths": ["JOURNAL.md"]})
        assert large_page["files"][0]["total_chars"] > 100000
        assert len(large_page["files"][0]["content"]) == 16000
        assert large_page["files"][0]["end_of_file"] is False
        print("LARGE_OWNER_LIST_SEARCH_DEFAULT_READ_PAGE_PASS", flush=True)

        def cli(action, *parts, payload=None):
            p = subprocess.run(
                ["runuser", "-u", "nobody", "--", sys.executable, "-B",
                 str(SRC / "owner_cli.py"), action, *parts],
                input=payload, capture_output=True, text=True, env=env,
                timeout=30)
            try:
                reply = json.loads(p.stdout)
            except ValueError:
                raise AssertionError(p.stderr)
            if p.returncode:
                assert reply.get("status") == "error", reply
            return reply
        cli_list = cli("list", "LargePilot")
        assert cli_list == listing, (cli_list, listing)
        cli_search = cli("search", "LargePilot", "TEST-1077", "2")
        assert cli_search == search and cli_search["matches"][0]["line"] == 1079
        cli_chunk = cli("read", "LargePilot", "JOURNAL.md", "0", "12288")
        remote_chunk = call("owner_read_chunk", request("read", "JOURNAL.md",
                             offset_bytes=0, max_bytes=12288))
        assert cli_chunk == remote_chunk and cli_chunk["returned_bytes"] > 0
        assert cli("search", "LargePilot", "TEST-1077", "21").get("status") == "error"
        assert cli("read", "LargePilot", "../stranger/NOT_A_SOURCE.md").get("status") == "error"
        print("LOCAL_CLI_READ_SEARCH_MCP_PARITY_AND_SCOPE_DENIAL_PASS", flush=True)

        # The feature must fail closed without its separate opt-in.
        noflag = dict(env)
        noflag.pop("KEELARYN_MCP_LARGE_OWNER_PILOT")
        denied = call("owner_read_chunk", request("read", "JOURNAL.md"), noflag)
        assert denied.get("error")
        print("LARGE_OWNER_EXPLICIT_FLAG_PASS", flush=True)

        expected = files["JOURNAL.md"].encode("utf-8")
        cursor = 0
        chunks = []
        while cursor < len(expected):
            data = call("owner_read_chunk",
                        request("read", "JOURNAL.md", offset_bytes=cursor,
                                max_bytes=12288, expected_sha256=SHA(expected)))
            assert not data.get("error"), data
            assert data["offset_bytes"] == cursor and data["sha256"] == SHA(expected)
            assert 0 < data["returned_bytes"] <= 12288
            block = data["content"].encode("utf-8")
            assert len(block) == data["returned_bytes"]
            chunks.append(block)
            cursor = data["next_offset_bytes"]
        assert b"".join(chunks) == expected
        assert data["eof"]
        print("LARGE_UTF8_PAGED_COMPLETE_READ_PASS", len(expected), "bytes", flush=True)
        middle_of_armenian_letter = expected.index("ս".encode("utf-8")) + 1
        bad = call("owner_read_chunk", request("read", "JOURNAL.md",
                         offset_bytes=middle_of_armenian_letter,
                         max_bytes=12288))
        assert bad.get("error"), str(bad)[:200]
        stale = call("owner_read_chunk", request("read", "JOURNAL.md",
                         expected_sha256="0"*64))
        assert stale.get("error"), stale

        master = files["MASTERY.csv"].encode()
        assert call("owner_read_chunk", request("read", "MASTERY.csv",
                    offset_bytes=len(master)-80, max_bytes=12288))["eof"]
        # Replace one bounded row within a >90K synthetic CSV using whole-file CAS.
        before = SHA(master)
        oldrow = 'TEST-1077,reading,"synthetic 1077"\n'
        newrow = 'TEST-1077,reading,"review tomorrow"\n'
        change = request("edit", "MASTERY.csv", request_id=ID(1),
                         action="replace_once", expected_sha256=before,
                         old_text=oldrow, new_text=newrow)
        updated = call("owner_edit_delta", change)
        assert updated["status"] == "committed", updated
        assert (folder/"MASTERY.csv").read_text().count(newrow) == 1
        assert call("owner_edit_delta", change)["status"] == "already_committed"
        assert call("owner_edit_delta", dict(change, request_id=ID(2)))["error"]
        print("LARGE_CSV_EXACT_ROW_CAS_AND_IDEMPOTENCE_PASS", flush=True)

        original = files["JOURNAL.md"].encode()
        block = "\n## TEST EVENT\n- RAW: սա փորձ է\n- SCORE: 1\n"
        write = request("edit", "JOURNAL.md", request_id=ID(3),
                        action="append", expected_sha256=SHA(original),
                        content=block)
        r = call("owner_edit_delta", write)
        assert r["status"] == "committed", r
        assert (folder/"JOURNAL.md").read_text().endswith(block)
        assert call("owner_edit_delta", write)["status"] == "already_committed"
        print("LARGE_JOURNAL_APPEND_CAS_IDEMPOTENCE_PASS", flush=True)

        # Two related files: first owner mutation must remain committed
        # if the second fails; the caller can resume second with an exact SHA.
        step1 = request("edit", "PROJECT.md", request_id=ID(4),
                        action="append", expected_sha256=SHA(files["PROJECT.md"].encode()),
                        content="## Step 1 complete\n")
        step2 = request("edit", "STATE.md", request_id=ID(5),
                        action="replace_once",
                        expected_sha256="0"*64,
                        old_text="NEXT: synthetic only",
                        new_text="NEXT: step 2 confirmed")
        assert call("owner_edit_delta", step1)["status"] == "committed"
        assert call("owner_edit_delta", step2).get("error")
        assert (folder/"PROJECT.md").read_text().endswith("## Step 1 complete\n")
        step2["expected_sha256"] = SHA(files["STATE.md"].encode())
        assert call("owner_edit_delta", step2)["status"] == "committed"
        assert (folder/"STATE.md").read_text() == "# NEXT: step 2 confirmed\n"
        print("MULTI_FILE_EXPLICIT_RECOVERY_SEQUENCE_PASS", flush=True)

        # Cross-owner and sensitive path denials.
        for path in ("../stranger/NOT_A_SOURCE.md", "NOT_A_SOURCE.md",
                     ".keelaryn-g1/.lock"):
            assert call("owner_read_chunk", request("read", path)).get("error")
        assert secret.read_text() == "NEVER EXPOSE OR MODIFY\n"
        print("OWNER_SCOPE_BOUNDARY_PASS", flush=True)

        # A fresh full-reread hash of both synthetic files is a simple,
        # AI-independent last-mile completion witness.
        for name in files:
            blob = (folder / name).read_bytes()
            if name == "MASTERY.csv":
                assert SHA(blob) == updated["sha256"]
            if name == "JOURNAL.md":
                assert SHA(blob) == r["sha256"]
        # Use the same G1 engine in the opposite direction: create a
        # genuinely new committed operation via non-AI CLI, then replay
        # the immutable request through the MCP adapter without duplicating.
        state_after = (folder / "STATE.md").read_bytes()
        replace_cli = request("edit", "STATE.md", request_id=ID(6),
            action="replace", expected_sha256=SHA(state_after),
            content="# NEXT: local CLI can replace without MCP\\n")
        assert cli("mutate", payload=json.dumps(replace_cli))["status"] == "committed"
        assert call("owner_mutate", replace_cli)["status"] == "already_committed"
        assert (folder / "STATE.md").read_text() == "# NEXT: local CLI can replace without MCP\\n"
        journal_after = (folder / "JOURNAL.md").read_bytes()
        append_cli = request("edit", "JOURNAL.md", request_id=ID(7),
            action="append", expected_sha256=SHA(journal_after),
            content="\\n## LOCAL_CLI_EVENT_ONCE\\n")
        assert cli("delta", payload=json.dumps(append_cli))["status"] == "committed"
        assert call("owner_edit_delta", append_cli)["status"] == "already_committed"
        assert (folder / "JOURNAL.md").read_text().count("## LOCAL_CLI_EVENT_ONCE") == 1
        print("LOCAL_CLI_MUTATE_DELTA_MCP_REPLAY_EXACTLY_ONCE_PASS", flush=True)
        print("ALL_LARGE_OWNER_PILOT_TESTS_PASS", flush=True)


if __name__ == "__main__":
    main()
