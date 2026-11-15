#!/usr/bin/env python3
"""Disposable owner-history integration test: 300+ writes, crash recovery.

Runs only on synthetic temp data. It never enables migration or writes to any
real project. No network, ChatGPT, Google Drive, systemd or secrets.
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
USER = pwd.getpwnam("nobody")
SHA = lambda data: hashlib.sha256(data.encode("utf-8")).hexdigest()
ID = lambda i: f"{i:032x}"


def main():
    assert os.geteuid() == 0
    with tempfile.TemporaryDirectory(prefix="keelaryn-history-fixture-") as directory:
        top = Path(directory)
        top.chmod(0o755)
        root = top / "historysynthetic"
        root.mkdir(mode=0o700)
        os.chown(root, USER.pw_uid, USER.pw_gid)
        state = root / "STATE.md"
        state.write_text("v=0\n")
        state.chmod(0o600)
        os.chown(state, USER.pw_uid, USER.pw_gid)
        env = dict(os.environ, KEELARYN_MCP_MODE="local",
                   KEELARYN_MCP_ACCESS_MODE="default",
                   KEELARYN_MCP_OWNER_FS_TEST="1",
                   KEELARYN_MCP_LARGE_OWNER_PILOT="1",
                   PYTHONDONTWRITEBYTECODE="1")
        code = r'''
import hashlib,json,os,sys
sys.path.insert(0,sys.argv[1])
import owner_fs,owner_large
root=sys.argv[2]
owner="HistorySynthetic"
scope={"backend":"owner-fs","owner":owner,"root":root,"access":"read-write",
       "allow":["STATE.md"],"canonical":False,"snapshot_only":False}
sha=lambda t:hashlib.sha256(t.encode()).hexdigest()
id=lambda n:f"{n:032x}"
cmd=sys.argv[3]
if cmd == "batch":
 start,stop=map(int,sys.argv[4:6])
 for i in range(start,stop+1):
  args={"project":owner,"request_id":id(i),"action":"replace",
        "path":"STATE.md","expected_sha256":sha(f"v={i-1}\n"),
        "content":f"v={i}\n"}
  res=owner_fs.mutate(args,scope)
  assert res["status"]=="committed" and res["verified_readback"],(i,res)
 print("BATCH_PASS",start,stop)
elif cmd == "single":
 i=int(sys.argv[4])
 args={"project":owner,"request_id":id(i),"action":"replace",
       "path":"STATE.md","expected_sha256":sha(f"v={i-1}\n"),
       "content":f"v={i}\n"}
 res=owner_fs.mutate(args,scope)
 assert res["status"]=="committed"
 print("SINGLE_PASS",i)
elif cmd == "old":
 index=int(sys.argv[4])
 args={"project":owner,"request_id":id(index),"action":"replace",
       "path":"STATE.md","expected_sha256":sha(f"v={index-1}\n"),
       "content":f"v={index}\n"}
 res=owner_fs.mutate(args,scope)
 assert res["status"]=="already_committed" and res["current_matches"] is False
 print("OLD_ID_REPLAY_SAFE",index)
elif cmd == "different":
 args={"project":owner,"request_id":id(1),"action":"replace",
       "path":"STATE.md","expected_sha256":sha("v=0\n"),
       "content":"MALICIOUS DIFFERENT PAYLOAD\n"}
 try:owner_fs.mutate(args,scope)
 except ValueError as e:
  assert "Idempotency ID reused" in str(e),str(e)
 else:raise AssertionError("Old request ID reused with changed payload")
 print("OLD_ID_DIFFERENT_PAYLOAD_DENIED")
elif cmd == "delete_recreate":
 old=open(os.path.join(root,"STATE.md")).read()
 delete_args={"project":owner,"request_id":id(326),"action":"delete",
              "path":"STATE.md","expected_sha256":sha(old)}
 deleted=owner_fs.mutate(delete_args,scope)
 assert deleted["status"]=="committed" and not os.path.exists(os.path.join(root,"STATE.md"))
 created=owner_fs.mutate({"project":owner,"request_id":id(327),"action":"create",
                         "path":"STATE.md","expected_sha256":None,"content":"v=327\n"},scope)
 assert created["status"]=="committed"
 print("DELETE_AND_RECREATE_RECEIPTS_PASS")
elif cmd == "large":
 old=open(os.path.join(root,"STATE.md")).read()
 args={"project":owner,"request_id":id(999),"action":"append",
       "path":"STATE.md","expected_sha256":sha(old),
       "content":"legacy G1 history works with large delta\n"}
 res=owner_large.edit_delta(scope,args)
 assert res["status"]=="committed" and res["verified_readback"]
 print("LARGE_DELTA_CROSS_HISTORY_PASS")
elif cmd == "invalid":
 before=open(os.path.join(root,"STATE.md"),"rb").read()
 args={"project":owner,"request_id":id(600),"action":"replace",
       "path":"STATE.md","expected_sha256":hashlib.sha256(before).hexdigest(),
       "content":"BAD\n"}
 try:owner_fs.mutate(args,scope)
 except ValueError as e:
  assert "history" in str(e).lower()
 else:raise AssertionError("Corrupt archive accepted")
 assert open(os.path.join(root,"STATE.md"),"rb").read()==before
 print("HISTORY_CORRUPTION_FAIL_CLOSED")
else:raise RuntimeError(cmd)
'''
        def run(cmd, *args, crash=None):
            subenv = dict(env)
            if crash:
                subenv["KEELARYN_HISTORY_TEST_CRASH_AFTER"] = crash
            return subprocess.run([
                "runuser", "-u", "nobody", "--", sys.executable, "-B",
                "-c", code, str(SRC), str(root), cmd, *map(str, args)],
                text=True, capture_output=True, timeout=100, env=subenv)
        p = run("batch", 1, 128)
        assert p.returncode == 0, p.stderr[-1000:]
        print("G1_128_INITIAL_WRITES_PASS", flush=True)
        p = run("single", 129, crash="publish")
        assert p.returncode == 91, (p.returncode, p.stderr)
        assert state.read_text() == "v=128\n"
        journal = root / ".keelaryn-g1"
        assert (journal / "history-000001.json").is_file()
        assert len(list(journal.glob("[0-9]*.json"))) == 128
        print("G1_CRASH_AFTER_ARCHIVE_PUBLISH_DETECTED", flush=True)
        p = run("single", 129)
        assert p.returncode == 0, p.stderr[-1000:]
        assert state.read_text() == "v=129\n"
        assert len(list(journal.glob("[0-9]*.json"))) < 128
        print("G1_ARCHIVE_PUBLISH_RECOVERY_PASS", flush=True)

        # Archived requests are never forgotten (including after later edits).
        assert run("old", 1).returncode == 0
        assert run("different").returncode == 0
        print("G1_ARCHIVED_IDEMPOTENCE_AND_REUSE_DENIAL_PASS", flush=True)

        # Next 64-ish calls fill active records again.
        p = run("batch", 130, 192)
        assert p.returncode == 0, p.stderr[-1000:]
        p = run("single", 193, crash="first_unlink")
        assert p.returncode == 92, (p.returncode, p.stderr)
        assert state.read_text() == "v=192\n"
        p = run("single", 193)
        assert p.returncode == 0, p.stderr[-1000:]
        print("G1_CRASH_AFTER_FIRST_UNLINK_RECOVERY_PASS", flush=True)

        # Multiple rotations interleave with the same G1 identity space.
        p = run("batch", 194, 325)
        assert p.returncode == 0, p.stderr[-1000:]
        assert state.read_text() == "v=325\n"
        assert run("old", 1).returncode == 0
        assert run("old", 129).returncode == 0
        p = run("large")
        assert p.returncode == 0, p.stderr[-1000:]
        assert state.read_text().endswith("legacy G1 history works with large delta\n")
        print("G1_325_WRITES_AND_LARGE_DELTA_PASS", flush=True)
        p = run("delete_recreate")
        assert p.returncode == 0, p.stderr[-1000:]
        p = run("batch", 328, 520)
        assert p.returncode == 0, p.stderr[-1000:]
        assert state.read_text() == "v=520\n"
        print("G1_520_WRITES_WITH_DELETE_AND_RECREATE_PASS", flush=True)

        archives = sorted(journal.glob("history-*.json"))
        assert archives
        all_archived = {}
        for f in archives:
            obj = json.loads(f.read_text())
            assert obj["schema"] == "keelaryn-g1-history-v1"
            for req, item in obj["receipts"].items():
                assert req not in all_archived
                all_archived[req] = item
        assert len(all_archived) > 128
        assert all_archived[ID(326)]["action"] == "delete"
        assert all_archived[ID(326)]["new_sha256"] is None
        assert all_archived[ID(327)]["action"] == "create"
        assert len(list(journal.glob("[0-9]*.json"))) <= 128
        print("G1_ARCHIVE_BOUNDED_ACTIVE_RECEIPTS_PASS",
              len(all_archived), len(archives), flush=True)

        # No fallback to accepting an unknown archive as empty history.
        archive = archives[0]
        original = archive.read_bytes()
        archive.write_bytes(b"corrupt")
        try:
            p = run("invalid")
            assert p.returncode == 0, p.stderr[-1000:]
        finally:
            archive.write_bytes(original)
        assert run("old", 1).returncode == 0
        print("G1_CORRUPT_ARCHIVE_FAIL_CLOSED_AND_RESTORE_PASS", flush=True)
        print("ALL_HISTORY_ROTATION_TESTS_PASS", flush=True)


if __name__ == "__main__":
    main()
