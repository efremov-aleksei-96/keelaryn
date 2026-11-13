#!/usr/bin/env python3
"""G3 portable plain-directory export: synthetic owner and no cloud dependency.

No encryption, archive, database, credential, ChatGPT, Drive, systemd or real
project. Verifies 2 human-readable versions and G1 receipt replay. Tests are
disposable and do not claim the plain folders are production backups.
"""
import fcntl
import hashlib
import os
from pathlib import Path
import pwd
import shutil
import stat
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import owner_fs

UID = pwd.getpwnam("nobody").pw_uid
GID = pwd.getpwnam("nobody").pw_gid
OWNER = "PlainSynthetic"
ALLOW = ["PROJECT.md", "CURSOR.json", "MASTERY.csv"]
H = lambda text: hashlib.sha256(text.encode("utf-8")).hexdigest()


def snapshot(root, version, scope):
    if version not in ("v0001", "v0002", "v0003"):
        raise ValueError("Invalid synthetic version")
    backup_root = root.parent / "plain-versions"
    backup_root.mkdir(mode=0o700, exist_ok=True)
    target = backup_root / version
    if target.exists():
        raise ValueError("Backup version must not be overwritten")
    fd = owner_fs.open_root(scope)
    try:
        jfd = owner_fs._ensure_journal(fd)
        lock = owner_fs._lock(jfd)
        try:
            owner_fs._scan_journal(jfd, "0"*32)
            for name in os.listdir(jfd):
                if name == ".lock":
                    continue
                if owner_fs._read_record(jfd, name[:-5])["status"] != "committed":
                    raise ValueError("Unresolved G1 intent")
            if set(root.iterdir()) != {root / ".keelaryn-g1"} | {
                    root / name for name in ALLOW}:
                raise ValueError("Unexpected synthetic file")
            tmp = backup_root / (".pending-" + version)
            if tmp.exists():
                raise ValueError("Unknown pending snapshot")
            tmp.mkdir(mode=0o700)
            try:
                for name in ALLOW:
                    expected = owner_fs._checked_file(fd, name)
                    if expected is None:
                        raise ValueError("Missing owner file")
                    # One-level, no-symlink read. No archives or rewrites.
                    srcfd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
                    try:
                        data = os.read(srcfd, owner_fs.MAX_BYTES + 1)
                    finally:
                        os.close(srcfd)
                    if hashlib.sha256(data).hexdigest() != expected:
                        raise ValueError("Changed owner data")
                    dest = tmp / name
                    with dest.open("xb") as out:
                        out.write(data)
                        out.flush()
                        os.fsync(out.fileno())
                    dest.chmod(0o600)
                j = tmp / ".keelaryn-g1"
                j.mkdir(mode=0o700)
                for rec in sorted(os.listdir(jfd)):
                    if rec == ".lock":
                        continue
                    data = owner_fs._read_record(jfd, rec[:-5])
                    if data["status"] != "committed":
                        raise ValueError("Incomplete journal")
                    # Store the receipt bytes, not a reserialized variant.
                    srcfd = os.open(rec, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=jfd)
                    try:
                        raw = os.read(srcfd, 4097)
                    finally:
                        os.close(srcfd)
                    with (j / rec).open("xb") as out:
                        out.write(raw)
                        out.flush()
                        os.fsync(out.fileno())
                    (j / rec).chmod(0o600)
                (j / ".lock").touch(mode=0o600)
                (j / ".lock").chmod(0o600)
                os.rename(tmp, target)
            except BaseException:
                # This is a disposable test; an unpublished temp never counts
                # as a valid version and can be inspected/removed by test owner.
                raise
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
            os.close(lock)
            os.close(jfd)
    finally:
        os.close(fd)
    return target


def files(directory):
    result = {}
    for p in directory.rglob("*"):
        if p.is_file() and p.name != ".lock":
            assert not p.is_symlink()
            result[str(p.relative_to(directory))] = p.read_bytes()
    return result


def main():
    if os.geteuid() != 0:
        raise RuntimeError("Run as root solely to construct nobody-owned synthetic fixture")
    with tempfile.TemporaryDirectory(prefix="keelaryn-g3-plain-copy-") as tmp:
        base = Path(tmp)
        base.chmod(0o755)
        owner = base / "owner"
        owner.mkdir(mode=0o700)
        os.chown(owner, UID, GID)
        repo = base / "plain-versions"
        repo.mkdir(mode=0o700)
        os.chown(repo, UID, GID)
        args = [sys.executable, "-B", "-c", CHILD]
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
                   KEELARYN_MCP_MODE="local",
                   KEELARYN_MCP_ACCESS_MODE="default",
                   KEELARYN_MCP_OWNER_FS_TEST="1",
                   G3_PLAIN_OWNER_DIR=str(owner))
        p = os.fork()
        if p == 0:
            os.setgid(GID)
            os.setuid(UID)
            exec(compile(CHILD, "<synthetic-plain-copy-test>", "exec"))
            os._exit(0)
        _, status = os.waitpid(p, 0)
        assert os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0, status
        assert not any(x.name.startswith(".pending-") for x in repo.iterdir())
        print("G3_PLAIN_TEXT_EXPORT_VERSIONS_AND_REPLAY_PASS")


CHILD = r'''
from pathlib import Path
import os
import shutil
root = Path(os.environ["G3_PLAIN_OWNER_DIR"])
scope = {"backend": "owner-fs", "owner": OWNER, "root": str(root),
         "allow": ALLOW, "access": "read-write",
         "canonical": False, "snapshot_only": False}
def mutate(action, idx, path, **args):
    return owner_fs.mutate(dict(project=OWNER, request_id=f"{idx:032x}",
                                action=action, path=path, **args), scope)
a = "# Armenian-like synthetic course\nNEXT: LESSON-01\n"
b = "# Armenian-like synthetic course\nNEXT: LESSON-02\n"
assert mutate("create", 1, "PROJECT.md", content=a, expected_sha256=None)["verified_readback"]
assert mutate("create", 2, "CURSOR.json", content='{"lesson":1}', expected_sha256=None)["verified_readback"]
assert mutate("create", 3, "MASTERY.csv", content="id,score\nA,2\n", expected_sha256=None)["verified_readback"]
v1 = snapshot(root, "v0001", scope)
assert (v1 / "PROJECT.md").read_text() == a
assert (v1 / "CURSOR.json").read_text() == '{"lesson":1}'
assert (v1 / "MASTERY.csv").read_text() == "id,score\nA,2\n"
old = files(v1)
assert len(old) == 6  # 3 source files + 3 G1 receipts
assert mutate("replace", 4, "PROJECT.md", content=b, expected_sha256=H(a))["verified_readback"]
assert mutate("replace", 5, "CURSOR.json", content='{"lesson":2}',
              expected_sha256=H('{"lesson":1}'))["verified_readback"]
v2 = snapshot(root, "v0002", scope)
assert (v2 / "PROJECT.md").read_text() == b
assert files(v1) == old  # copy is versioned, not a two-way sync
assert files(v1) != files(v2)
assert len(files(v2)) == 8
assert "NEXT: LESSON-01" in (v1 / "PROJECT.md").read_text()
assert "NEXT: LESSON-02" in (v2 / "PROJECT.md").read_text()
# Plain files open directly with stdlib tools, not the MCP or a decryptor.
restored = root.parent / "restored"
shutil.copytree(v2, restored)
new_scope = dict(scope, root=str(restored))
replay = owner_fs.mutate(
    dict(project=OWNER, request_id=f"{5:032x}", action="replace",
         path="CURSOR.json", content='{"lesson":2}',
         expected_sha256=H('{"lesson":1}')), new_scope)
assert replay["status"] == "already_committed" and replay["current_matches"]
assert files(restored) == files(v2)
try:
    snapshot(root, "v0001", scope)
except ValueError:
    pass
else:
    raise AssertionError("Backup version overwritten")
# Stale unfinished intent means no new publishable copy.
intent_path = root / ".keelaryn-g1" / ("f"*32 + ".json")
intent_path.write_text('{"request_id":"' + "f"*32 + '","status":"intent"}')
try:
    snapshot(root, "v0003", scope)
except ValueError:
    pass
else:
    raise AssertionError("Inconsistent G1 intent exported")
intent_path.unlink()
assert not (root.parent / "plain-versions/v0003").exists()
print("SYNTHETIC_PLAIN_DIRECTORY_READABLE_AND_RESTORED", flush=True)
'''


if __name__ == "__main__":
    main()
