#!/usr/bin/env python3
"""G2 VPS test: encrypted, consistent G1 owner data, journal and isolated restore.

All crypto, data and keys are synthetic and disposable; no Google, no VPS
service change, no production account. Run as root for nobody-owned fixtures.
"""
import os
from pathlib import Path
import pwd
import subprocess
import sys
import tempfile

SRC = Path(__file__).resolve().parents[1] / "src"
G2 = Path(__file__).with_name("g2_synthetic_backup.py")
USER = pwd.getpwnam("nobody")

CHILD = r'''
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, os.environ["G2_TEST_SRC"])
sys.path.insert(0, os.environ["G2_TEST_BACKUP_DIR"])
import owner_fs
import g2_synthetic_backup as backup

root = Path(os.environ["G2_TEST_ROOT"])
repo = root / "repository"
owner = root / "owner"
restore_parent = root / "restore-parent"
other = root / "other"
passphrase = os.environ["G2_TEST_PASSPHRASE"]
OWNER = "G2Synthetic"
ALLOW = ["PROJECT.md", "STATE.json", "DATA.csv"]
SCOPE = {"backend": "owner-fs", "owner": OWNER, "root": str(owner),
         "allow": ALLOW, "access": "read-write", "canonical": False,
         "snapshot_only": False}
os.umask(0o077)
sha = lambda b: hashlib.sha256(b).hexdigest()
digest = lambda s: sha(s.encode("utf-8"))
counter = 0

def edit(action, path, **kwargs):
    global counter
    counter += 1
    args = dict(project=OWNER, request_id=f"{counter:032x}",
                action=action, path=path, **kwargs)
    result = owner_fs.mutate(args, SCOPE)
    assert result["status"] == "committed" and result["verified_readback"]
    return args

v1_project = "# Synthetic project\nNEXT: R1\n"
v2_project = "# Synthetic project\nNEXT: R2\n"
v1_state = '{"cursor":"R1","synthetic":true}\n'
v2_state = '{"cursor":"R2","synthetic":true}\n'
first_project = edit("create", "PROJECT.md", content=v1_project, expected_sha256=None)
first_state = edit("create", "STATE.json", content=v1_state, expected_sha256=None)
csv = edit("create", "DATA.csv", content="id,value\n1,alpha\n", expected_sha256=None)
assert (owner / ".keelaryn-g1/.lock").exists()

v1 = backup.make_snapshot(owner, repo, OWNER, "v0001", ALLOW, passphrase)
assert v1["entry_count"] == 6  # 3 owner files + 3 G1 committed receipts
snapshot1 = (repo / "v0001.kg2").read_bytes()
assert not any(phrase in snapshot1 for phrase in
               (v1_project.encode(), v1_state.encode(), b"request_id", b"alpha"))
assert snapshot1.startswith(backup.MAGIC)
assert backup.list_versions(repo) == ["v0001.kg2"]
print("G2_V1_ENCRYPTED_SNAPSHOT_CONSISTENT_G1_JOURNAL_PASS")

last_project = edit("replace", "PROJECT.md", content=v2_project,
                    expected_sha256=digest(v1_project))
last_state = edit("replace", "STATE.json", content=v2_state,
                  expected_sha256=digest(v1_state))
v2 = backup.make_snapshot(owner, repo, OWNER, "v0002", ALLOW, passphrase)
assert v2["entry_count"] == 8
snapshot2 = (repo / "v0002.kg2").read_bytes()
assert snapshot1 != snapshot2
assert backup.list_versions(repo) == ["v0001.kg2", "v0002.kg2"]
try:
    backup.make_snapshot(owner, repo, OWNER, "v0001", ALLOW, passphrase)
except ValueError as e:
    assert "already published" in str(e)
else:
    raise AssertionError("Overwrote existing backup version")
assert (repo / "v0001.kg2").read_bytes() == snapshot1
print("G2_V2_VERSIONED_NO_CLOBBER_AND_PREVIOUS_VERSION_PRESERVED_PASS")

# A genuine G1 intent must refuse a coherent snapshot; never capture a
# document updated without its paired durable commit receipt.
pending_id = "f"*32
pending = owner / ".keelaryn-g1" / (pending_id + ".json")
pending.write_text(json.dumps({
    "request_id": pending_id, "status": "intent",
    "fingerprint": "0"*64, "path": "PROJECT.md"}))
pending.chmod(0o600)
try:
    try:
        backup.make_snapshot(owner, repo, OWNER, "v0003", ALLOW, passphrase)
    except ValueError as e:
        assert "Pending/invalid" in str(e)
    else:
        raise AssertionError("Pending G1 intent was snapshotted")
finally:
    pending.unlink()
assert not (repo / "v0003.kg2").exists()
orphan = owner / ".keelaryn-g1/.tmp-interrupted"
orphan.write_text("synthetic orphan")
orphan.chmod(0o600)
try:
    try: backup.make_snapshot(owner, repo, OWNER, "v0003", ALLOW, passphrase)
    except ValueError as e: assert "Unresolved" in str(e)
    else: raise AssertionError("Orphan journal temp was snapshotted")
finally:
    orphan.unlink()
print("G2_INCOMPLETE_G1_INTENT_AND_ORPHAN_JOURNAL_DENIED_PASS")

# Restore with a fresh standalone Python interpreter. -I isolates the module
# search path; the script imports NO owner_fs/file_scopes/MCP, Google or ChatGPT.
def offline(version, path, phrase=passphrase, expected_owner=OWNER, success=True):
    env = dict(os.environ, G2_EXPECTED_SYNTHETIC_OWNER=expected_owner)
    call = [sys.executable, "-I", os.environ["G2_TEST_G2_SCRIPT"],
            "restore", str(repo), version, str(path)]
    run = subprocess.run(call, input=phrase+"\n", text=True,
                         capture_output=True, timeout=40, env=env)
    if success:
        assert run.returncode == 0, (run.stderr, run.stdout)
        result = json.loads(run.stdout)
        assert result["owner"] == OWNER and result["version"] == version
        return result
    assert run.returncode != 0 and not path.exists(), (run.stdout, run.stderr)
    return run

restored2 = restore_parent / "v2-clean"
v2_result = offline("v0002", restored2)
restored1 = restore_parent / "v1-clean"
v1_result = offline("v0001", restored1)

def tree_bytes(root):
    out = {}
    for item in root.rglob("*"):
        if item.is_file() and item.name != ".lock":
            assert not item.is_symlink()
            out[str(item.relative_to(root))] = item.read_bytes()
    return out

v2_bytes = tree_bytes(owner)
assert tree_bytes(restored2) == v2_bytes
assert restored2.joinpath("PROJECT.md").read_text() == v2_project
assert restored2.joinpath("STATE.json").read_text() == v2_state
assert restored1.joinpath("PROJECT.md").read_text() == v1_project
assert restored1.joinpath("STATE.json").read_text() == v1_state
assert restored1.joinpath("PROJECT.md").read_bytes() != restored2.joinpath("PROJECT.md").read_bytes()
assert len(tree_bytes(restored1)) == 6
assert len(tree_bytes(restored2)) == 8
assert v2_result["sha256"] == {n:sha(b) for n,b in tree_bytes(restored2).items()}
assert v1_result["sha256"] == {n:sha(b) for n,b in tree_bytes(restored1).items()}
assert all((p.stat().st_mode & 0o777) == 0o600 for p in restored2.rglob("*") if p.is_file())
assert restored2.stat().st_mode & 0o777 == 0o700
assert (restored2 / ".keelaryn-g1").stat().st_mode & 0o777 == 0o700
assert (restored2 / ".keelaryn-g1/.lock").is_file()
assert not (restored2 / ".keelaryn-g1/.lock").read_bytes()
print("G2_OFFLINE_RESTORE_BOTH_VERSIONS_ALL_SHA_AND_NEXT_PASS")

# Verify original G1 *same* request-ID is still idempotent on the restored
# journal and local files. No privileged process or remote connector.
scope_new = dict(SCOPE, root=str(restored2))
scope_old = dict(SCOPE, root=str(restored1))
r = owner_fs.mutate(last_state, scope_new)
assert r["status"] == "already_committed" and r["current_matches"] is True
r = owner_fs.mutate(first_project, scope_old)
assert r["status"] == "already_committed" and r["current_matches"] is True
assert restored2.joinpath("STATE.json").read_text() == v2_state
print("G2_RESTORED_G1_RECEIPT_REPLAY_IDEMPOTENCE_PASS")

# The credentials are not persisted with the ciphertext. Wrong/missing key,
# tampered encrypted versions and wrong owner fail *before* writing any dest.
offline("v0002", restore_parent / "no-key", "", success=False)
offline("v0002", restore_parent / "bad-key", "wrong-but-longer-than-sixteen", success=False)
offline("v0002", restore_parent / "wrong-owner", passphrase, "OtherOwner", success=False)
tampered = bytearray(snapshot2)
tampered[-1] ^= 0x40
v3_path = repo / "v0003.kg2"
v3_path.write_bytes(tampered)
v3_path.chmod(0o600)
offline("v0003", restore_parent / "tampered", success=False)
v3_path.write_bytes(snapshot2[:25])
offline("v0003", restore_parent / "truncated", success=False)
v3_path.unlink()
print("G2_MISSING_WRONG_KEY_TAMPER_TRUNCATE_AND_WRONG_OWNER_FAIL_CLOSED_PASS")

# No overwrite of a valid existing owner, even if caller proposes same name.
before = tree_bytes(restored2)
try:
    backup.restore_snapshot(repo, "v0002", restored2, OWNER, passphrase)
except ValueError as e:
    assert "existing" in str(e)
else:
    raise AssertionError("Restore clobbered existing owner")
assert tree_bytes(restored2) == before
print("G2_NONEMPTY_DESTINATION_NEVER_OVERWRITTEN_PASS")

# Abrupt termination after encrypted tmp file fsync but before publication
# leaves no new advertised version. Previous snapshots remain exact.
pid = os.fork()
if pid == 0:
    backup.make_snapshot(owner, repo, OWNER, "v0004", ALLOW, passphrase,
                         interrupt_before_publish=True)
    os._exit(99)
_, status = os.waitpid(pid, 0)
assert os.WIFEXITED(status) and os.WEXITSTATUS(status) == 81
assert not (repo / "v0004.kg2").exists()
assert backup.list_versions(repo) == ["v0001.kg2", "v0002.kg2"]
assert (repo / "v0001.kg2").read_bytes() == snapshot1
assert (repo / "v0002.kg2").read_bytes() == snapshot2
pending_files = [x for x in repo.iterdir() if x.name.startswith(".pending-")]
assert len(pending_files) == 1
pending_files[0].unlink()  # synthetic cleanup only; never automate deleting real backups
assert backup.list_versions(repo) == ["v0001.kg2", "v0002.kg2"]
print("G2_INTERRUPTED_BACKUP_UNPUBLISHED_AND_OLDER_SNAPSHOTS_INTACT_PASS")

# Distinct unrelated synthetic owner remained pristine for the whole test.
assert other.joinpath("SENTINEL.md").read_text() == "Other owner is never copied\n"
assert "SENTINEL.md" not in tree_bytes(restored2)
print("G2_OTHER_OWNER_NOT_IN_BACKUP_OR_RESTORE_PASS")
print("G2_LIMITS: test-only AEAD/container, no real Drive/upload, no power-cut, "
      "no production backup retention/independent key custody or full host restore")
'''

def main():
    if os.geteuid() != 0:
        raise RuntimeError("Run as root only to prepare disposable nobody-owned fixtures")
    with tempfile.TemporaryDirectory(prefix="keelaryn-g2-fixture-") as name:
        root = Path(name)
        root.chmod(0o755)
        for n in ("owner", "repository", "restore-parent", "other"):
            p = root / n
            p.mkdir(mode=0o700)
            os.chown(p, USER.pw_uid, USER.pw_gid)
            p.chmod(0o700)
        sentinel = root / "other/SENTINEL.md"
        sentinel.write_text("Other owner is never copied\n")
        sentinel.chmod(0o600)
        os.chown(sentinel, USER.pw_uid, USER.pw_gid)
        env = dict(os.environ,
                   KEELARYN_MCP_MODE="local",
                   KEELARYN_MCP_ACCESS_MODE="default",
                   KEELARYN_MCP_OWNER_FS_TEST="1",
                   PYTHONDONTWRITEBYTECODE="1",
                   G2_TEST_SRC=str(SRC),
                   G2_TEST_BACKUP_DIR=str(G2.parent),
                   G2_TEST_G2_SCRIPT=str(G2),
                   G2_TEST_ROOT=str(root),
                   G2_TEST_PASSPHRASE="synthetic-only-passphrase-" + os.urandom(24).hex())
        result = subprocess.run(
            ["runuser", "-u", "nobody", "--", sys.executable, "-B", "-c", CHILD],
            capture_output=True, text=True, env=env, timeout=110)
        assert result.returncode == 0, result.stderr[-2500:]
        print(result.stdout, end="")


if __name__ == "__main__":
    main()
