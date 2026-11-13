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
# Load owner_fs only after dropping privileges in the disposable child.

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



def mock_drive_transfer(source, destination, version, *, stop_after=None, corrupt=False):
    """Test-only one-way, resumable plain-file transfer. No Google API.

    A partial copy stays under .incoming-<version>, never under a published
    version name. Bad/unknown staged files fail closed; the test operator must
    inspect and remove them rather than replacing them silently.
    """
    import json
    import re
    if version not in ("v0001", "v0002", "v0003"):
        raise ValueError("Invalid mock backup version")
    if source.is_symlink() or not source.is_dir():
        raise ValueError("Invalid source directory")
    if {p.name for p in source.iterdir()} != set(ALLOW) | {".keelaryn-g1"}:
        raise ValueError("Incomplete or unexpected source")
    journal = source / ".keelaryn-g1"
    if journal.is_symlink() or not journal.is_dir():
        raise ValueError("Missing or unsafe journal")
    receipts = sorted(x.name for x in journal.iterdir() if x.name != ".lock")
    if not (1 <= len(receipts) <= 128) or any(
        re.fullmatch(r"[0-9a-f]{32}\.json", x) is None for x in receipts
    ):
        raise ValueError("Unexpected G1 journal")
    if not (journal / ".lock").is_file():
        raise ValueError("Missing journal lock")
    relative = [Path(x) for x in ALLOW]
    relative += [Path(".keelaryn-g1") / x for x in [".lock", *receipts]]
    expected = {}
    for path in relative:
        item = source / path
        metadata = item.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ValueError("Unsafe source object")
        content = item.read_bytes()
        if path.suffix == ".json" and path.parts[0] == ".keelaryn-g1":
            receipt = json.loads(content)
            if receipt.get("status") != "committed":
                raise ValueError("Unresolved source journal")
        expected[path.as_posix()] = hashlib.sha256(content).hexdigest()
    if b"NEXT: " not in (source / "PROJECT.md").read_bytes():
        raise ValueError("Missing readable NEXT")

    destination.mkdir(mode=0o700, exist_ok=True)
    published = destination / version
    staged = destination / (".incoming-" + version)
    if published.exists() or published.is_symlink():
        raise ValueError("Published backup is immutable")
    if staged.is_symlink():
        raise ValueError("Unsafe incoming path")
    staged.mkdir(mode=0o700, exist_ok=True)
    # Existing partial files must match exactly; never repair changed bytes.
    actual = {}
    for path in staged.rglob("*"):
        if path.is_symlink():
            raise ValueError("Symlink in incoming copy")
        if path.is_file():
            relative_name = path.relative_to(staged).as_posix()
            if relative_name not in expected:
                raise ValueError("Unknown incoming file")
            actual[relative_name] = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual[relative_name] != expected[relative_name]:
                raise ValueError("Corrupt incoming file")
        elif not path.is_dir() or path.relative_to(staged).as_posix() != ".keelaryn-g1":
            raise ValueError("Unknown incoming directory")
    count = 0
    for relative_name, checksum in sorted(expected.items()):
        if relative_name in actual:
            continue
        target = staged / relative_name
        target.parent.mkdir(mode=0o700, exist_ok=True)
        with target.open("xb") as out:
            out.write((source / relative_name).read_bytes())
            out.flush()
            os.fsync(out.fileno())
        target.chmod(0o600)
        count += 1
        if corrupt and count == 1:
            with target.open("r+b") as out:
                out.write(b"X")
                out.flush()
                os.fsync(out.fileno())
        if stop_after is not None and count == stop_after:
            raise InterruptedError("Simulated upload interrupted before publication")
    for relative_name, checksum in expected.items():
        if hashlib.sha256((staged / relative_name).read_bytes()).hexdigest() != checksum:
            raise ValueError("Mock upload SHA-256 mismatch")
    for path in (staged / ".keelaryn-g1", staged):
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_DIRECTORY), "rb") as directory_fd:
            os.fsync(directory_fd.fileno())
    if published.exists():
        raise ValueError("Refusing to replace published backup")
    # Test fixture has a single writer. Atomic no-replace publication against
    # independent concurrent writers is NOT established by this mock.
    staged.rename(published)
    with os.fdopen(os.open(destination, os.O_RDONLY | os.O_DIRECTORY), "rb") as directory_fd:
        os.fsync(directory_fd.fileno())
    assert all(
        hashlib.sha256((published / path).read_bytes()).hexdigest() == sha
        for path, sha in expected.items()
    )
    return published


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
            try:
                os.setgid(GID)
                os.setuid(UID)
                os.environ.update(env)
                import importlib
                globals()["owner_fs"] = importlib.import_module("owner_fs")
                import local_ro
                st = owner.stat()
                assert (st.st_uid == os.geteuid() == local_ro.DATA_OWNER
                        and (st.st_mode & 0o777) == 0o700), (
                            "G3 fixture mismatch", st.st_uid, os.geteuid(),
                            local_ro.DATA_OWNER, oct(st.st_mode & 0o777))
                exec(compile(CHILD, "<synthetic-plain-copy-test>", "exec"),
                     globals(), globals())
            except BaseException:
                import traceback
                traceback.print_exc()
                os._exit(1)
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
restored = root.parent / "plain-versions" / "restored"
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
# Mock-drive transfer: a deliberately local destination, never a real Drive API.
mock = root.parent / "mock-drive"
remote_v1 = mock_drive_transfer(v1, mock, "v0001")
assert files(remote_v1) == old
try:
    mock_drive_transfer(v2, mock, "v0002", corrupt=True)
except ValueError:
    pass
else:
    raise AssertionError("Corrupted transfer was published")
assert not (mock / "v0002").exists()
try:
    mock_drive_transfer(v2, mock, "v0002")
except ValueError:
    pass
else:
    raise AssertionError("Corrupted partial upload was silently repaired")
# Explicit operator cleanup is safe only for this disposable synthetic target.
shutil.rmtree(mock / ".incoming-v0002")
try:
    mock_drive_transfer(v2, mock, "v0002", stop_after=2)
except InterruptedError:
    pass
else:
    raise AssertionError("Simulated interruption did not fire")
assert not (mock / "v0002").exists()
assert (mock / ".incoming-v0002").is_dir()
remote_v2 = mock_drive_transfer(v2, mock, "v0002")  # idempotent resume
assert files(remote_v2) == files(v2)
assert files(remote_v1) == old  # previous valid version is retained
assert "NEXT: LESSON-01" in (remote_v1 / "PROJECT.md").read_text()
assert "NEXT: LESSON-02" in (remote_v2 / "PROJECT.md").read_text()
try:
    mock_drive_transfer(v1, mock, "v0001")
except ValueError:
    pass
else:
    raise AssertionError("Published version was overwritten")
incomplete = root.parent / "incomplete-test-source"
shutil.copytree(v2, incomplete)
(incomplete / "CURSOR.json").unlink()
try:
    mock_drive_transfer(incomplete, mock, "v0003")
except ValueError:
    pass
else:
    raise AssertionError("Missing source file was accepted")
assert not (mock / "v0003").exists()
recovered_from_mock = root.parent / "restored-from-mock"
shutil.copytree(remote_v2, recovered_from_mock)
assert files(recovered_from_mock) == files(v2)
replay_mock = owner_fs.mutate(
    dict(project=OWNER, request_id=f"{5:032x}", action="replace",
         path="CURSOR.json", content='{"lesson":2}',
         expected_sha256=H('{"lesson":1}')),
    dict(scope, root=str(recovered_from_mock)))
assert replay_mock["status"] == "already_committed" and replay_mock["current_matches"]
print("G3_MOCK_DRIVE_INTEGRITY_INTERRUPTION_RESUME_RESTORE_PASS", flush=True)

print("SYNTHETIC_PLAIN_DIRECTORY_READABLE_AND_RESTORED", flush=True)
'''


if __name__ == "__main__":
    main()
