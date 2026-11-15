"""MusicLibrary two-file VPS pilot: immutable, byte-verified Drive backups.

Explicit root-only CLI. No canonical Drive source, Registry, music, other owner,
service, token or existing backup is changed. Google Drive is an offsite backup,
not required for an MCP file edit. Completion marker is uploaded last.

  KEELARYN_DRIVE_PLAIN_LIVE=1 python3 -B musiclibrary_pilot_backup.py backup trial
  KEELARYN_DRIVE_PLAIN_LIVE=1 python3 -B musiclibrary_pilot_backup.py backup live
  KEELARYN_DRIVE_PLAIN_LIVE=1 python3 -B musiclibrary_pilot_backup.py verify VERSION
  KEELARYN_DRIVE_PLAIN_LIVE=1 python3 -B musiclibrary_pilot_backup.py restore VERSION
The last command creates a NEW root-only recovery directory, never overwriting canon.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

import drive_real_backup as owner_backup
from drive_plain_sender import BackupError, FOLDER

LIVE = Path("/var/lib/private/keelarynos-mcp-benchmark/musiclibrary")
TRIAL = Path("/var/lib/keelaryn-drive-backup/musiclibrary-trial")
STATE = Path("/var/lib/keelaryn-drive-backup")
FOLDER_NAME = "MusicLibrary-VPS-Pilot"
MARKER = ".keelaryn-backup-complete.json"
SCHEMA = "keelaryn-musiclibrary-twofile-backup-v1"
FILENAMES = ("PROJECT.md", "STATE.md")
VERSION = re.compile(r"(trial|live)-[0-9a-f]{20}\Z")
MAX_BYTES = 65536
MAX_ALL = 131072
O_FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
O_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def require(ok, reason):
    if not ok:
        raise BackupError(reason)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _directory(path):
    require(path in (LIVE, TRIAL, STATE), "Non-allowlisted directory")
    for ancestor in (path, *path.parents):
        require(not ancestor.is_symlink(), "Symlink in source path")
    fd = os.open(path, O_DIR)
    try:
        st = os.fstat(fd)
        require(stat.S_ISDIR(st.st_mode) and not st.st_mode & 0o077
                and (path == LIVE or st.st_uid == 0),
                "Unsafe backup source root")
        return st.st_uid
    finally:
        os.close(fd)


def read_pair(mode):
    require(mode in ("trial", "live"), "Unknown source mode")
    root = TRIAL if mode == "trial" else LIVE
    uid = _directory(root)
    files = {}
    for name in FILENAMES:
        fd = os.open(root / name, O_FILE)
        try:
            before = os.fstat(fd)
            require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                    and before.st_uid == uid and not before.st_mode & 0o077
                    and before.st_size <= MAX_BYTES, "Unsafe source document")
            data = os.read(fd, MAX_BYTES + 1)
            after = os.fstat(fd)
            require(len(data) == before.st_size and len(data) <= MAX_BYTES
                    and (before.st_dev, before.st_ino, before.st_size,
                         before.st_mtime_ns, before.st_ctime_ns) ==
                    (after.st_dev, after.st_ino, after.st_size,
                     after.st_mtime_ns, after.st_ctime_ns),
                    "Source changed during read")
            data.decode("utf-8")
            files[name] = data
        finally:
            os.close(fd)
    require(sum(map(len, files.values())) <= MAX_ALL, "Backup corpus too large")
    return files


def _version(mode, files):
    raw = b"".join(name.encode() + b"\\0" + digest(files[name]).encode() + b"\\0"
                   for name in FILENAMES)
    return mode + "-" + digest(raw)[:20]


def _manifest(mode, version, files):
    return {"schema": SCHEMA, "version": version, "source": mode,
            "files": {name: {"size": len(data), "sha256": digest(data)}
                      for name, data in sorted(files.items())}}


def _serialize(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _api():
    require(os.geteuid() == 0, "Root-only backup command")
    require(os.environ.get("KEELARYN_DRIVE_PLAIN_LIVE") == "1",
            "Live Google Drive not explicitly enabled")
    return owner_backup.new_api()


def _backup_root(api, *, create):
    root_id = owner_backup.dest_id()
    owner_backup._verified_folder(api, root_id, owner_backup.ROOT_NAME)
    found = api.list(root_id)
    if FOLDER_NAME not in found:
        require(create, "MusicLibrary backup folder does not exist")
        folder_id = api.folder(root_id, FOLDER_NAME)
    else:
        require(found[FOLDER_NAME]["mimeType"] == FOLDER,
                "Backup destination has unexpected type")
        folder_id = found[FOLDER_NAME]["id"]
    owner_backup._verified_folder(api, folder_id, FOLDER_NAME)
    return folder_id


def _remote_pair(api, folder_id, version):
    children = api.list(folder_id)
    require(set(children) == set(FILENAMES) | {MARKER},
            "Remote version is incomplete")
    for name in FILENAMES:
        require(children[name]["mimeType"] == "text/markdown",
                "Remote MIME mismatch")
    require(children[MARKER]["mimeType"] == "application/json",
            "Remote completion marker MIME mismatch")
    marker_bytes = api.media(children[MARKER]["id"])
    try:
        manifest = json.loads(marker_bytes)
    except (UnicodeError, ValueError):
        raise BackupError("Corrupt completion marker") from None
    require(isinstance(manifest, dict) and manifest.get("schema") == SCHEMA
            and manifest.get("version") == version
            and manifest.get("source") in ("trial", "live")
            and version.startswith(manifest["source"] + "-")
            and set(manifest.get("files", {})) == set(FILENAMES)
            and marker_bytes == _serialize(manifest),
            "Untrusted remote manifest")
    files = {name: api.media(children[name]["id"]) for name in FILENAMES}
    require(manifest["files"] == _manifest(manifest["source"], version, files)["files"],
            "Remote file hash/length mismatch")
    require(_version(manifest["source"], files) == version,
            "Version identity mismatch")
    return files, manifest


def publish(mode):
    files = read_pair(mode)
    version = _version(mode, files)
    marker = _serialize(_manifest(mode, version, files))
    api = _api()
    parent = _backup_root(api, create=True)
    old = api.list(parent)
    if version in old:
        require(old[version]["mimeType"] == FOLDER, "Conflicting remote version")
    folder = api.folder(parent, version)
    children = api.list(folder)
    require(set(children) <= set(FILENAMES) | {MARKER},
            "Unexpected remote version contents")
    if MARKER not in children:
        for name in FILENAMES:
            api.ensure_file(folder, name, "text/markdown", files[name])
        api.ensure_file(folder, MARKER, "application/json", marker)
    restored, observed = _remote_pair(api, folder, version)
    require(restored == files and _serialize(observed) == marker,
            "Drive readback does not match staged source")
    require(read_pair(mode) == files, "Source changed during Drive upload")
    return {"status": "complete_verified", "version": version,
            "folder_id": folder, "bytes": sum(map(len, files.values())),
            "sha256": {name: digest(data) for name, data in files.items()}}


def recover(version, *, keep):
    require(isinstance(version, str) and VERSION.fullmatch(version),
            "Invalid restore version")
    api = _api()
    parent = _backup_root(api, create=False)
    found = api.list(parent)
    require(version in found and found[version]["mimeType"] == FOLDER,
            "Requested version does not exist")
    files, _ = _remote_pair(api, found[version]["id"], version)
    _directory(STATE)
    if keep:
        target = STATE / ("recovery-musiclibrary-" + version)
        require(not target.exists() and not target.is_symlink(),
                "Restore destination already exists")
        os.mkdir(target, 0o700)
    else:
        target = Path(tempfile.mkdtemp(prefix="musiclibrary-restore-check-", dir=STATE))
    try:
        for name in FILENAMES:
            fd = os.open(target / name,
                         os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                with os.fdopen(fd, "wb") as out:
                    out.write(files[name])
                    out.flush()
                    os.fsync(out.fileno())
            except BaseException:
                raise
            assert (target / name).read_bytes() == files[name]
        fd = os.open(target, O_DIR)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        return {"status": "restored_exact", "version": version,
                "retained": keep,
                "target": str(target) if keep else "ephemeral_deleted_after_check",
                "sha256": {name: digest(data) for name, data in files.items()}}
    finally:
        if not keep:
            for name in FILENAMES:
                (target / name).unlink(missing_ok=True)
            target.rmdir()


def main(argv):
    require(os.geteuid() == 0, "Root-only CLI")
    if argv == ["backup", "trial"]:
        return publish("trial")
    if argv == ["backup", "live"]:
        return publish("live")
    if len(argv) == 2 and argv[0] in ("verify", "restore"):
        return recover(argv[1], keep=(argv[0] == "restore"))
    raise BackupError("Usage: backup trial|live, verify VERSION, restore VERSION")


if __name__ == "__main__":
    try:
        print(json.dumps(main(sys.argv[1:]), sort_keys=True))
    except (BackupError, OSError, UnicodeError, ValueError):
        print(json.dumps({"status": "failed", "reason": "Bounded backup or recovery check failed"}))
        sys.exit(1)
