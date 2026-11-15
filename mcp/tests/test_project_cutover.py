#!/usr/bin/env python3
"""Entire-project staged migration rehearsal: synthetic, never a real cutover.

Source owner remains read-only. Stage EVERY required file, hash-verify before
rename, crash between publish/registry switch, reconcile and flip ONE complete
owner scope, then execute real CAS operations against only the new VPS root.
No Google access, no live service registry, no user-project modification.
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
OWNER = "MigrationSynthetic"
ALLOW = ["PROJECT.md", "STATE.md", "MASTERY.csv", "JOURNAL.md"]
SHA = lambda value: hashlib.sha256(value).hexdigest()


def main():
    if os.geteuid() != 0:
        raise RuntimeError("Root is needed only for fixture setup and simulated cutover")
    with tempfile.TemporaryDirectory(prefix="keelaryn-whole-project-cutover-") as d:
        base = Path(d)
        base.chmod(0o755)
        source = base / "historical-drive-analogue"
        source.mkdir(mode=0o755)
        live = base / "vps-state"
        live.mkdir(mode=0o700)
        os.chown(live, USER.pw_uid, USER.pw_gid)
        stage = live / ".stage-migrationsynthetic"
        stage.mkdir(mode=0o700)
        os.chown(stage, USER.pw_uid, USER.pw_gid)
        target = live / OWNER.lower()
        contents = {
            "PROJECT.md": "# Entire synthetic project\n\nSTATE.md, MASTERY.csv and JOURNAL.md are required.\n",
            "STATE.md": "# Stage: source\nNEXT: verify whole project cutover\n",
            "MASTERY.csv": "item_id,score\n" + "".join(
                f"SYN-{i:05d},{i%4}\n" for i in range(8500)),
            "JOURNAL.md": "# Synthetic Armenian event: սա փորձ է\n" * 17000,
        }
        assert len(contents["MASTERY.csv"].encode()) > 90000
        assert len(contents["JOURNAL.md"].encode()) > 680000
        manifest = {}
        for name, content in contents.items():
            raw = content.encode("utf-8")
            original = source / name
            original.write_bytes(raw)
            original.chmod(0o644)
            manifest[name] = SHA(raw)
            staged = stage / name
            staged.write_bytes(raw)
            staged.chmod(0o600)
            os.chown(staged, USER.pw_uid, USER.pw_gid)
            assert SHA(staged.read_bytes()) == manifest[name]
        assert set(x.name for x in stage.iterdir()) == set(ALLOW)
        assert "STATE.md" in contents["PROJECT.md"]
        assert "MASTERY.csv" in contents["PROJECT.md"]
        assert "JOURNAL.md" in contents["PROJECT.md"]
        print("ENTIRE_PROJECT_INVENTORY_AND_STAGE_HASH_PASS",flush=True)
        # A user may continue to work on the original while staging runs.
        # Detect the stale snapshot and re-stage the changed source BEFORE
        # any publication or active-owner switch. Never silently overwrite
        # the latest source with an older staged copy.
        changed = contents["STATE.md"] + "SYNTHETIC_LATE_SOURCE_EVENT: new evidence\n"
        (source / "STATE.md").write_text(changed, encoding="utf-8")
        assert SHA((source / "STATE.md").read_bytes()) != manifest["STATE.md"]
        assert not target.exists()
        stale = [name for name in ALLOW
                 if SHA((source / name).read_bytes()) != manifest[name]]
        assert stale == ["STATE.md"], stale
        (stage / "STATE.md").write_text(changed, encoding="utf-8")
        os.chown(stage / "STATE.md", USER.pw_uid, USER.pw_gid)
        (stage / "STATE.md").chmod(0o600)
        contents["STATE.md"] = changed
        manifest["STATE.md"] = SHA(changed.encode("utf-8"))
        assert {name: SHA((stage / name).read_bytes()) for name in ALLOW} == manifest
        assert {name: SHA((source / name).read_bytes()) for name in ALLOW} == manifest
        print("CHANGED_SOURCE_REJECTS_STALE_STAGE_AND_RESTAGE_PASS",flush=True)

        config = base / "scopes.json"
        old_scopes = {
            "synthetic": {
                "backend": "workspace", "access": "read-write",
                "description": "Ephemeral synthetic-only benchmark files"},
            "HistoricalSource": {
                "backend": "local-ro", "root": str(source),
                "access": "read-only", "snapshot_only": False,
                "canonical": False, "allow": ALLOW},
        }
        config.write_text(json.dumps({
            "schema": "keelarynos_mcp_file_scopes_v1",
            "scopes": old_scopes}))
        config.chmod(0o644)
        env = dict(os.environ, KEELARYN_MCP_MODE="system",
                   KEELARYN_MCP_ACCESS_MODE="read-only",
                   KEELARYN_MCP_MULTI_CANONICAL="1",
                   KEELARYN_MCP_LARGE_OWNER_PILOT="1",
                   KEELARYN_MCP_CONFIG=str(config),
                   KEELARYN_MCP_STATE_DIR=str(live),
                   KEELARYN_MCP_BENCHMARK_TOOLS="0",
                   PYTHONDONTWRITEBYTECODE="1")
        def user_run(code):
            return subprocess.run(
                ["runuser", "-u", "nobody", "--", sys.executable, "-B",
                 "-c", code, str(SRC)],
                text=True,capture_output=True,env=env,timeout=40)
        # Before publication, the new owner scope cannot be read or written.
        check = user_run("""
import sys
sys.path.insert(0,sys.argv[1])
from file_scopes import get_scope
try:get_scope('MigrationSynthetic')
except ValueError:print('STAGED_NOT_ACTIVE_PASS')
else:raise AssertionError('Stage became a canon prematurely')
""")
        assert check.returncode == 0,check.stderr
        print(check.stdout.strip(),flush=True)

        # Crash after an atomic directory publish, BEFORE registry switch.
        # A new orchestrator must reconcile the already-published files,
        # not create a duplicate or overwrite them.
        p=subprocess.run([sys.executable,"-c",
            "import os,sys;os.replace(sys.argv[1],sys.argv[2]);"
            "os.fsync(os.open(sys.argv[3],os.O_RDONLY|os.O_DIRECTORY));"
            "os._exit(91)",str(stage),str(target),str(live)],
            capture_output=True,timeout=10)
        assert p.returncode==91 and not stage.exists() and target.is_dir()
        assert "MigrationSynthetic" not in json.loads(config.read_text())["scopes"]
        assert {name:SHA((target/name).read_bytes()) for name in ALLOW}==manifest
        # Repeat source reconciliation at the final switch boundary. A real
        # Google writer freeze remains a separate provider-specific gate.
        assert {name:SHA((source/name).read_bytes()) for name in ALLOW}==manifest
        print("POST_DIRECTORY_RENAME_PRE_REGISTRY_CRASH_RECONCILED_PASS",flush=True)

        new_scopes = dict(old_scopes)
        new_scopes[OWNER] = {
            "backend": "owner-fs", "owner": OWNER, "root": str(target),
            "allow": ALLOW, "access": "read-write",
            "canonical": True, "snapshot_only": False,
        }
        new = json.dumps({
            "schema": "keelarynos_mcp_file_scopes_v1",
            "scopes": new_scopes}).encode("utf-8")
        tmp = base / ".scope-switch"
        fd = os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o644)
        with os.fdopen(fd,"wb") as f:
            f.write(new);f.flush();os.fsync(f.fileno())
        os.replace(tmp,config)
        fd=os.open(base,os.O_RDONLY|os.O_DIRECTORY)
        os.fsync(fd);os.close(fd)
        assert json.loads(config.read_text())["scopes"][OWNER]["canonical"] is True
        print("ONE_COMPLETE_OWNER_SCOPE_SWITCH_DURABLE_PASS",flush=True)

        worker=r'''
import hashlib,json,os,sys
sys.path.insert(0,sys.argv[1])
from file_scopes import get_scope
from local_ro import operate as read
from owner_fs import mutate
from owner_large import read_chunk,edit_delta
scope=get_scope("MigrationSynthetic")
assert scope["canonical"] is True and scope["backend"] == "owner-fs"
files=read("list_files",{"path":"","limit":10},scope)["entries"]
assert {x["path"] for x in files} == set(["PROJECT.md","STATE.md","MASTERY.csv","JOURNAL.md"])
data=read_chunk(scope,{"project":"MigrationSynthetic","path":"JOURNAL.md",
                       "max_bytes":12000})
assert data["total_bytes"] > 680000
root=scope["root"]
state=open(root+"/STATE.md","rb").read()
sha=lambda b:hashlib.sha256(b).hexdigest()
args={"project":"MigrationSynthetic","request_id":"f"*32,
      "action":"replace","path":"STATE.md",
      "expected_sha256":sha(state),
      "content":"# Stage: VPS_ONLY_SYNTHETIC_PROJECT\nNEXT: operate without Drive\n"}
changed=mutate(args,scope)
assert changed["status"]=="committed"
assert mutate(args,scope)["status"]=="already_committed"
master=open(root+"/MASTERY.csv","rb").read()
row={"project":"MigrationSynthetic","request_id":"e"*32,
     "action":"replace_once","path":"MASTERY.csv",
     "expected_sha256":sha(master),
     "old_text":"SYN-00420,0\n","new_text":"SYN-00420,3\n"}
updated=edit_delta(scope,row)
assert updated["status"]=="committed"
assert edit_delta(scope,row)["status"]=="already_committed"
assert open(root+"/MASTERY.csv").read().count("SYN-00420,3\n")==1
print("ONE_COMPLETE_PROJECT_VPS_ONLY_CAS_READ_AND_WRITE_PASS")
'''
        done=user_run(worker)
        assert done.returncode==0,done.stderr[-1500:]
        print(done.stdout.strip(),flush=True)
        # The original read-only source is untouched and cannot be mistaken
        # for the mutable VPS owner after activation.
        assert {name:SHA((source/name).read_bytes()) for name in ALLOW}==manifest
        assert (target/"STATE.md").read_text()!=contents["STATE.md"]
        assert (target/"MASTERY.csv").read_text()!=contents["MASTERY.csv"]
        assert len(list(target.iterdir()))==5  # four files and G1 journal
        print("HISTORICAL_SOURCE_UNCHANGED_SINGLE_ACTIVE_WRITER_PASS",flush=True)
        print("ALL_WHOLE_PROJECT_SYNTHETIC_CUTOVER_TESTS_PASS",flush=True)


if __name__=="__main__":
    main()
