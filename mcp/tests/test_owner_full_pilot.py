#!/usr/bin/env python3
"""System-mode synthetic, noncanonical VPS full project pilot test.

No real owner files, no external APIs, no systemd service changes. The root
privilege used here only prepares an isolated temporary DynamicUser-style UID
directory; all file tools execute as nobody.
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
NOBODY = pwd.getpwnam("nobody")
SHA = lambda b: hashlib.sha256(b).hexdigest()
ID = lambda i: f"{i:032x}"
OWNER = "KeelarynFullPilot"
ALLOW = ["PROJECT.md", "STATE.md", "MASTERY.csv", "JOURNAL.md"]


def main():
    if os.geteuid() != 0:
        raise RuntimeError("Isolated fixture requires root setup")
    with tempfile.TemporaryDirectory(prefix="keelaryn-full-pilot-") as d:
        top = Path(d)
        top.chmod(0o755)
        state = top / "service-state"
        state.mkdir(mode=0o700)
        os.chown(state, NOBODY.pw_uid, NOBODY.pw_gid)
        owner_dir = state / "full-pilot"
        owner_dir.mkdir(mode=0o700)
        os.chown(owner_dir, NOBODY.pw_uid, NOBODY.pw_gid)
        journal = ("# Noncanonical synthetic learning session :: սա փորձ է\n" * 14000)
        csv_data = "item_id,score\n" + "".join(
            f"TEST-{i:05d},{i%9}\n" for i in range(8000))
        assert len(journal.encode()) > 680000
        assert len(csv_data.encode()) > 90000
        for name, content in (("PROJECT.md", "# PILOT ONLY\n"),
                              ("MASTERY.csv", csv_data), ("JOURNAL.md", journal)):
            target = owner_dir / name
            target.write_text(content, encoding="utf-8")
            target.chmod(0o600)
            os.chown(target, NOBODY.pw_uid, NOBODY.pw_gid)
        registry = top / "registry.json"
        config = {
            "schema": "keelarynos_mcp_file_scopes_v1",
            "scopes": {
                "synthetic": {
                    "backend": "workspace", "access": "read-write",
                    "description": "Ephemeral synthetic-only benchmark files"},
                OWNER: {
                    "backend": "owner-fs", "owner": OWNER,
                    "root": str(owner_dir), "allow": ALLOW,
                    "access": "read-write", "canonical": False,
                    "snapshot_only": False,
                },
            },
        }
        registry.write_text(json.dumps(config))
        registry.chmod(0o644)
        env = dict(os.environ, KEELARYN_MCP_MODE="system",
                   KEELARYN_MCP_ACCESS_MODE="read-only",
                   KEELARYN_MCP_FULL_PILOT="1",
                   KEELARYN_MCP_LARGE_OWNER_PILOT="1",
                   KEELARYN_MCP_CONFIG=str(registry),
                   KEELARYN_MCP_STATE_DIR=str(state),
                   KEELARYN_MCP_BENCHMARK_TOOLS="0",
                   PYTHONDONTWRITEBYTECODE="1")
        def command(cmd, payload=None, extra=None):
            e=dict(env)
            if extra: e.update(extra)
            return subprocess.run(
                ["runuser", "-u", "nobody", "--", sys.executable, "-B", *cmd],
                input=payload, capture_output=True, text=True, env=e, timeout=40)
        def request(name, args, extra=None):
            data=json.dumps({"jsonrpc":"2.0","id":1,
                             "method":"tools/call",
                             "params":{"name":name,"arguments":args}})+"\n"
            p=command([str(SRC/"synthetic_stdio.py")],data,extra)
            if p.returncode:
                return {"process_exit":p.returncode,"stderr":p.stderr[-300:]}
            obj=json.loads(p.stdout)["result"]
            if obj.get("isError"):
                return {"error":obj["content"][0]["text"]}
            return json.loads(obj["content"][0]["text"])
        def a(path,**kw):return {"project":OWNER,"path":path,**kw}

        preflight=command([str(SRC/"file_scopes.py"),"--preflight"])
        assert preflight.returncode==0,preflight.stderr
        assert request("list_files",{"project":OWNER})["canonical"] is False
        r=request("owner_read_chunk",a("JOURNAL.md",
                  offset_bytes=0,max_bytes=12288))
        assert r["sha256"]==SHA(journal.encode()) and r["returned_bytes"]>0
        assert request("search_files",{"project":OWNER,
                       "query":"PILOT ONLY","limit":4})["matches"][0]["path"]=="PROJECT.md"
        print("SYSTEM_FULL_PILOT_READ_LIST_SEARCH_PASS",flush=True)

        # The normal small owner API creates an absent exact-allowed file.
        create=a("STATE.md",request_id=ID(1),action="create",
                 expected_sha256=None,content="# NEXT: simulate crash\n")
        result=request("owner_mutate",create)
        assert result["status"]=="committed",result
        assert request("owner_mutate",create)["status"]=="already_committed"
        print("SYSTEM_FULL_PILOT_CREATE_AND_REPLAY_PASS",flush=True)

        # A large CSV row gets a unique-text delta CAS with no 100-KB prompt.
        oldrow="TEST-00420,6\n"
        newrow="TEST-00420,8\n"
        edit=a("MASTERY.csv",request_id=ID(2),action="replace_once",
               expected_sha256=SHA(csv_data.encode()),
               old_text=oldrow,new_text=newrow)
        # Crash after intent, before any document write. A different new
        # request cannot pass the pending intent gate.
        p=request("owner_edit_delta",edit,{"KEELARYN_LARGE_TEST_CRASH_AFTER":"intent"})
        assert p.get("process_exit")==81,p
        blocked=request("owner_edit_delta",dict(edit,request_id=ID(3)))
        assert blocked.get("error"),blocked
        assert SHA((owner_dir/"MASTERY.csv").read_bytes())==SHA(csv_data.encode())
        done=request("owner_edit_delta",edit)
        assert done["status"]=="committed",done
        assert request("owner_edit_delta",edit)["status"]=="already_committed"
        print("SYSTEM_LARGE_INTENT_CRASH_AND_SAFE_RESUME_PASS",flush=True)

        # The next file update crashes after atomic document replace; same
        # request ID must detect new SHA and finish receipt without appending
        # the same event twice.
        append="\n## ONE EVENT ONLY\nRAW: սա\n"
        req=a("JOURNAL.md",request_id=ID(4),action="append",
              expected_sha256=SHA(journal.encode()),content=append)
        crash=request("owner_edit_delta",req,{"KEELARYN_LARGE_TEST_CRASH_AFTER":"data"})
        assert crash.get("process_exit")==82,crash
        assert (owner_dir/"JOURNAL.md").read_text().endswith(append)
        resume=request("owner_edit_delta",req)
        assert resume["status"]=="committed",resume
        assert (owner_dir/"JOURNAL.md").read_text().count("## ONE EVENT ONLY")==1
        print("SYSTEM_LARGE_AFTER_DATA_CRASH_EXACTLY_ONCE_PASS",flush=True)

        # A saved committed receipt survives a caller crash after receipt.
        old=SHA((owner_dir/"STATE.md").read_bytes())
        newstate=a("STATE.md",request_id=ID(5),action="replace_once",
                   expected_sha256=old,old_text="simulate crash",
                   new_text="recovered from committed receipt")
        killed=request("owner_edit_delta",newstate,{"KEELARYN_LARGE_TEST_CRASH_AFTER":"receipt"})
        assert killed.get("process_exit")==83,killed
        assert request("owner_edit_delta",newstate)["status"]=="already_committed"
        print("SYSTEM_LARGE_AFTER_RECEIPT_CRASH_REPLAY_PASS",flush=True)

        # Fail closed if its dedicated feature is disabled; never touch live data.
        disabled=dict(env)
        disabled.pop("KEELARYN_MCP_FULL_PILOT")
        p=command([str(SRC/"synthetic_stdio.py")],
                  json.dumps({"jsonrpc":"2.0","id":1,"method":"tools/list",
                              "params":{}})+"\n",
                  {"KEELARYN_MCP_FULL_PILOT":"0"})
        assert p.returncode!=0
        print("SYSTEM_FULL_PILOT_FLAG_OFF_PRESTART_DENIAL_PASS",flush=True)

        # Independent human-compatible local Python reader without the MCP
        # tunnel, Google, network, OpenAI session or other application.
        check_code="""
import os,sys,hashlib
sys.path.insert(0,sys.argv[1])
from file_scopes import get_scope
from owner_large import read_chunk
scope=get_scope('KeelarynFullPilot')
res=read_chunk(scope,{'project':'KeelarynFullPilot','path':'JOURNAL.md'})
assert res['total_bytes'] > 680000
print('SYSTEM_HUMAN_PYTHON_OWNER_READ_PASS')
"""
        direct=command(["-c",check_code,str(SRC)])
        assert direct.returncode==0,direct.stderr
        print(direct.stdout.strip(),flush=True)

        for name in ALLOW:
            assert (owner_dir/name).is_file(),name
        assert (owner_dir/"MASTERY.csv").read_text().count(newrow)==1
        assert (owner_dir/"JOURNAL.md").read_text().count("## ONE EVENT ONLY")==1
        print("ALL_SYSTEM_FULL_PILOT_FIXTURE_TESTS_PASS",flush=True)


if __name__=="__main__":
    main()
