"""Single safe iteration for ArmenianLearning's seven-file Google Drive backup.

NO timer or service is installed by this file. No deletion, canonical Drive edit,
credential disclosure or retention policy. Run as root only from isolated VPS.

Usage:
  python3 -B drive_backup_iteration.py selftest  # offline mocks, no credentials
  KEELARYN_DRIVE_PLAIN_LIVE=1 python3 -B drive_backup_iteration.py check
  KEELARYN_DRIVE_PLAIN_LIVE=1 python3 -B drive_backup_iteration.py run

Journal-safe structured one-line summary. 0=success/no changes,
1=failed (retry after inspecting cause), 75=another iteration holds the lock.
"""
import contextlib
import fcntl
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

import drive_real_backup as backup
import drive_source_ingest as source
from drive_plain_sender import BackupError, Drive

LOCK_PATH = Path("/var/lib/keelaryn-drive-backup/armenianlearning-iteration.lock")
VALID_REMOTE = {"already_complete", "published"}


class Busy(Exception):
    """Another iteration currently holds the filesystem lock."""


def require(condition, message):
    if not condition:
        raise BackupError(message)


@contextlib.contextmanager
def locked(path=LOCK_PATH):
    """Nonblocking POSIX lock on one pinned root-only regular file."""
    parent = path.parent
    pst = parent.lstat()
    require(stat.S_ISDIR(pst.st_mode) and pst.st_uid == 0
            and stat.S_IMODE(pst.st_mode) == 0o700,
            "Unsafe lock directory")
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        st = os.fstat(fd)
        require(stat.S_ISREG(st.st_mode) and st.st_uid == 0
                and st.st_gid == 0 and st.st_nlink == 1
                and stat.S_IMODE(st.st_mode) == 0o600,
                "Unsafe lock file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Busy() from None
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _latest():
    name, _data, _refs = source._latest_local()
    require(backup.VERS_RE.fullmatch(name), "Invalid local version")
    return name


def _publish(version):
    """Writer already verifies marker-last complete versions and resumes partials."""
    require(backup.VERS_RE.fullmatch(version), "Invalid publish version")
    stage = source.SNAPSHOTS / version
    result = backup.backup(stage)
    require(result.get("status") in VALID_REMOTE
            and result.get("version") == version
            and result.get("file_count") == 7, "Unexpected backup result")
    return result["status"]


def _do_cycle(latest, capture, publish):
    """Pure orchestration: first recover any unpublished latest stage."""
    prev = publish(latest)
    require(prev in VALID_REMOTE, "Previous snapshot not committed")
    outcome = capture()
    if outcome.get("status") == "unchanged":
        require(outcome.get("files_read") == 7 and not outcome.get("changed_names"),
                "Unexpected unchanged reader result")
        return {"status": "unchanged", "latest_version": latest,
                "prior_reconciliation": prev, "files_read": 7}
    require(outcome.get("status") == "captured_locally_not_backed_up"
            and outcome.get("files_read") == 7,
            "Unexpected capture result")
    version = outcome.get("version")
    require(isinstance(version, str) and backup.VERS_RE.fullmatch(version)
            and version > latest
            and bool(outcome.get("changed_names")), "Unexpected new snapshot version")
    remote = publish(version)
    return {"status": "new_version_published", "latest_version": version,
            "previous_version": latest, "prior_reconciliation": prev,
            "publish_status": remote, "files_read": 7,
            "changed_names": outcome["changed_names"],
            "bytes_read": outcome.get("bytes_read")}


def _remote_check(version):
    """Read-only, bounded manifest check for latest local source snapshot.

    A marker/manifest validates the completed publication claim, not a fresh
    byte-exact restore. Full byte readback happens inside backup.backup().
    """
    stage = source.SNAPSHOTS / version
    v, files, refs = backup._source(stage)
    require(v == version, "Wrong snapshot version")
    api = backup.new_api()
    root = backup.dest_id()
    backup._verified_folder(api, root, backup.ROOT_NAME)
    owners = api.list(root)
    if backup.OWNER not in owners:
        return "pending_remote_owner"
    owner = owners[backup.OWNER]
    backup._verified_folder(api, owner["id"], backup.OWNER)
    versions = api.list(owner["id"])
    if version not in versions:
        return "pending_remote_version"
    version_id = versions[version]["id"]
    backup._verified_folder(api, version_id, version)
    objects = api.list(version_id)
    if backup.MARKER not in objects:
        require(set(objects) <= set(backup.EXPECTED),
                "Unexpected incomplete backup objects")
        return "pending_remote_marker"
    require(set(objects) == set(backup.EXPECTED) | {backup.MARKER},
            "Completed backup has wrong file inventory")
    marker = objects[backup.MARKER]
    require(marker.get("mimeType") == "application/json",
            "Invalid complete marker mime")
    expected = backup._bytes(backup._manifest(v, files, refs))
    require(api.media(marker["id"]) == expected,
            "Completed manifest mismatches source snapshot")
    return "complete_manifest_verified"


def _check():
    latest = _latest()
    remote = _remote_check(latest)
    result = source.run(False)
    require(result.get("status") in ("unchanged", "changed_not_captured")
            and result.get("files_read") == 7, "Unexpected source probe")
    return {"status": "checked_no_changes_written", "latest_local_version": latest,
            "latest_remote": remote, "source_status": result["status"],
            "changed_names": result.get("changed_names", []),
            "bytes_read": result.get("bytes_read")}


def _selftest():
    # Entirely offline: no Google, no production snapshot or credential reads.
    name = "v20261114-01"
    later = "v20261115-01"
    calls = []
    def pub(path):
        calls.append(path)
        return "already_complete"
    noop = lambda: {"status": "unchanged", "files_read": 7, "changed_names": []}
    result = _do_cycle(name, noop, pub)
    assert result["status"] == "unchanged" and calls == [name]
    calls.clear()
    def new():
        return {"status": "captured_locally_not_backed_up", "files_read": 7,
                "version": later, "changed_names": ["STATE.md"],
                "bytes_read": 123}
    result = _do_cycle(name, new, pub)
    assert result["status"] == "new_version_published"
    assert calls == [name, later]
    calls.clear()
    def resumed(version):
        calls.append(version)
        return "published" if version == name else "already_complete"
    result = _do_cycle(name, noop, resumed)
    assert result["prior_reconciliation"] == "published" and calls == [name]
    calls.clear()
    def fail_on_new(version):
        calls.append(version)
        if version == later:
            raise BackupError("simulated remote outage")
        return "already_complete"
    try:
        _do_cycle(name, new, fail_on_new)
        raise AssertionError("Unreported upload failure")
    except BackupError as ex:
        assert "simulated remote outage" in str(ex) and calls == [name, later]
    calls.clear()
    def deny_stale(_version):
        raise BackupError("simulated failed previous-version reconciliation")
    try:
        _do_cycle(name, new, deny_stale)
        raise AssertionError("Source capture incorrectly proceeded")
    except BackupError:
        assert not calls
    with tempfile.TemporaryDirectory(prefix="keelaryn-flock-test-") as tmp:
        lock_root = Path(tmp)
        os.chmod(lock_root, 0o700)
        with locked(lock_root / "mutex"):
            try:
                with locked(lock_root / "mutex"):
                    raise AssertionError("Two concurrent locks allowed")
            except Busy:
                pass
        with locked(lock_root / "mutex"):
            pass
    return {"status": "selftest_passed",
            "cases": ["unchanged", "changed", "pending_resume",
                      "upload_failure", "prior_reconcile_failure",
                      "lock_collision", "lock_release"]}


def main(argv):
    phase = "init"
    if argv == ["selftest"]:
        try:
            print(json.dumps(_selftest(), sort_keys=True))
            return 0
        except Exception:
            print('{"status":"failed","phase":"selftest"}')
            return 1
    if argv not in (["check"], ["run"]):
        print('{"status":"invalid_usage","valid":["selftest","check","run"]}')
        return 2
    if os.geteuid() != 0:
        print('{"status":"failed","phase":"requires_root"}')
        return 1
    if os.environ.get("KEELARYN_DRIVE_PLAIN_LIVE") != "1":
        print('{"status":"failed","phase":"explicit_live_gate"}')
        return 1
    try:
        with locked():
            if argv == ["check"]:
                phase = "read_only_check"
                result = _check()
            else:
                phase = "resume_and_publish"
                latest = _latest()
                result = _do_cycle(latest, source_capture, _publish)
            print(json.dumps(result, sort_keys=True, ensure_ascii=False))
            return 0
    except Busy:
        print('{"status":"busy","reason":"another_iteration_running"}')
        return 75
    except Exception:
        # Do not output traceback, OAuth tokens, canonical file content,
        # provider response bodies, local path credentials, or private keys.
        print(json.dumps({"status": "failed", "phase": phase,
                          "recovery": "inspect private status; retry same iteration; pending stage kept"}))
        return 1


def source_capture():
    return source.run(True)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
