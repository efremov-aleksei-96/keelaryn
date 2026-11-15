"""VPS canonical project-tree backup, using the existing private Drive sender.

One shared physical service-state root, but only all explicitly canonical owner-fs
project directories in the root-owned MCP registry are included. Noncanonical
synthetic and engine-pilot areas, service health, tokens and other state are NOT
part of the project data tree. Include each project's committed MCP CAS journal.

No service or scheduler is created. Invoke this CLI through the existing timer
only after a separate successful live snapshot/remote byte-exact restore.

  KEELARYN_DRIVE_PLAIN_LIVE=1 python3 -B drive_tree_backup.py backup
  KEELARYN_DRIVE_PLAIN_LIVE=1 python3 -B drive_tree_backup.py verify tree-<hash>
  KEELARYN_DRIVE_PLAIN_LIVE=1 python3 -B drive_tree_backup.py restore tree-<hash>

"restore" creates a new root-only directory; NEVER overwrites a canonical file.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

import drive_real_backup as existing
from drive_plain_sender import BackupError, FOLDER

ROOT = Path("/var/lib/private/keelarynos-mcp-benchmark")
REGISTRY = Path("/etc/keelarynos-mcp-benchmark/file-scopes.json")
RECOVERY = Path("/var/lib/keelaryn-drive-backup")
FOLDER_NAME = "VPS-canonical-project-tree"
SCHEMA = "keelaryn-vps-project-tree-v1"
MARKER = ".keelaryn-tree-complete.json"
VERSION = re.compile(r"tree-[0-9a-f]{24}\Z")
PROJECT = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
DOC = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}\.(md|csv|json)\Z")
RECEIPT = re.compile(r"[0-9a-f]{32}\.json\Z")
MAX_FILES = 400
MAX_BYTES = 64 * 1024 * 1024
MAX_SINGLE = 2 * 1024 * 1024
O_FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
O_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def need(condition, message):
    if not condition:
        raise BackupError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def _stat_dir(path, *, uid=None):
    fd = os.open(path, O_DIR)
    try:
        st = os.fstat(fd)
        need(stat.S_ISDIR(st.st_mode) and not st.st_mode & 0o077
             and (uid is None or st.st_uid == uid), "Unsafe project directory")
        return st.st_uid
    finally:
        os.close(fd)


def _file(path, uid):
    fd = os.open(path, O_FILE)
    try:
        before = os.fstat(fd)
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
             and before.st_uid == uid and not before.st_mode & 0o077
             and before.st_size <= MAX_SINGLE, "Unsafe project file")
        data = os.read(fd, MAX_SINGLE + 1)
        after = os.fstat(fd)
        need(len(data) == before.st_size and len(data) <= MAX_SINGLE
             and (before.st_dev, before.st_ino, before.st_size,
                  before.st_mtime_ns, before.st_ctime_ns) ==
             (after.st_dev, after.st_ino, after.st_size,
              after.st_mtime_ns, after.st_ctime_ns),
             "Project file changed during backup")
        return data
    finally:
        os.close(fd)


def _scopes():
    need(os.geteuid() == 0 and not ROOT.is_symlink()
         and not REGISTRY.is_symlink(), "Root-only canonical tree operation")
    _stat_dir(ROOT)
    raw = REGISTRY.read_bytes()
    need(len(raw) < 32768 and REGISTRY.stat().st_uid == 0
         and not REGISTRY.stat().st_mode & 0o022, "Unsafe scope registry")
    try:
        config = json.loads(raw)
    except (UnicodeError, ValueError):
        raise BackupError("Invalid scope registry") from None
    need(isinstance(config, dict)
         and config.get("schema") == "keelarynos_mcp_file_scopes_v1"
         and isinstance(config.get("scopes"), dict), "Unexpected scope schema")
    selected = {}
    for name, v in config["scopes"].items():
        need(isinstance(v, dict), "Invalid scope")
        if v.get("canonical") is not True:
            continue
        # Canonical Drive/cloud scope is not locally stored and must not
        # silently be claimed as protected by a VPS directory backup.
        need(v.get("backend") == "owner-fs"
             and v.get("access") == "read-write"
             and v.get("snapshot_only") is False
             and v.get("owner") == name and PROJECT.fullmatch(name),
             "Canonical scope not covered by VPS owner-fs tree")
        sub = name.lower()
        path = ROOT / sub
        need(v.get("root") == str(path) and not path.is_symlink()
             and isinstance(v.get("allow"), list)
             and 1 <= len(v["allow"]) <= 40
             and len(v["allow"]) == len(set(v["allow"]))
             and all(isinstance(f, str) and DOC.fullmatch(f)
                     for f in v["allow"]),
             "Nonportable canonical project scope")
        need(sub not in selected, "Duplicate project root")
        selected[sub] = (path, set(v["allow"]))
    need(1 <= len(selected) <= 20, "No canonical VPS projects")
    return selected


def _snapshot():
    selected = _scopes()
    files = {}
    for sub, (root, allowed) in sorted(selected.items()):
        uid = _stat_dir(root, uid=ROOT.stat().st_uid)
        children = set(os.listdir(root))
        need(children <= allowed | {".keelaryn-g1"} and allowed <= children,
             "Unexpected/missing file in canonical project root")
        journal = root / ".keelaryn-g1"
        lock_fd = None
        try:
            if journal.exists() or journal.is_symlink():
                need(not journal.is_symlink(), "Symlinked MCP journal")
                _stat_dir(journal, uid=uid)
                entries = set(os.listdir(journal))
                need(".lock" in entries
                     and all(x == ".lock" or RECEIPT.fullmatch(x)
                             for x in entries), "Unsafe MCP receipt names")
                lock_fd = os.open(journal / ".lock", O_FILE)
                s = os.fstat(lock_fd)
                need(stat.S_ISREG(s.st_mode) and s.st_uid == uid
                     and s.st_nlink == 1 and not s.st_mode & 0o077
                     and s.st_size == 0, "Unsafe G1 lock")
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise BackupError("Owner mutation active: retry backup") from None
                files[sub + "/.keelaryn-g1/.lock"] = b""
                for name in sorted(entries - {".lock"}):
                    data = _file(journal / name, uid)
                    try:
                        receipt = json.loads(data)
                    except (UnicodeError, ValueError):
                        raise BackupError("Invalid MCP receipt") from None
                    need(isinstance(receipt, dict)
                         and receipt.get("status") == "committed"
                         and receipt.get("request_id") == name[:-5],
                         "Incomplete MCP intent: reconcile before backup")
                    files[sub + "/.keelaryn-g1/" + name] = data
            for name in sorted(allowed):
                data = _file(root / name, uid)
                data.decode("utf-8")
                files[sub + "/" + name] = data
        finally:
            if lock_fd is not None:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)
    need(1 <= len(files) <= MAX_FILES
         and sum(len(x) for x in files.values()) <= MAX_BYTES,
         "Project tree exceeds safe snapshot bounds")
    return files


def _manifest(files):
    return {"schema": SCHEMA, "files": {
        name: {"bytes": len(data), "sha256": sha(data)}
        for name, data in sorted(files.items())
    }}


def _json(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _identity(files):
    return "tree-" + sha(_json(_manifest(files)))[:24]


def _api():
    need(os.geteuid() == 0 and os.environ.get("KEELARYN_DRIVE_PLAIN_LIVE") == "1",
         "Explicit root-only Drive access required")
    return existing.new_api()


def _drive_root(api, create=False):
    root_id = existing.dest_id()
    existing._verified_folder(api, root_id, existing.ROOT_NAME)
    children = api.list(root_id)
    if FOLDER_NAME not in children:
        need(create, "Backup root does not exist")
        backup_id = api.folder(root_id, FOLDER_NAME)
    else:
        need(children[FOLDER_NAME]["mimeType"] == FOLDER,
             "Unexpected backup folder type")
        backup_id = children[FOLDER_NAME]["id"]
    existing._verified_folder(api, backup_id, FOLDER_NAME)
    return backup_id


def _remote(api, version_id, version):
    top = api.list(version_id)
    need(MARKER in top and top[MARKER]["mimeType"] == "application/json",
         "Remote version incomplete")
    marker_data = api.media(top[MARKER]["id"])
    try:
        man = json.loads(marker_data)
    except (UnicodeError, ValueError):
        raise BackupError("Unparseable completion marker") from None
    need(isinstance(man, dict) and man.get("schema") == SCHEMA
         and man.get("version") == version
         and isinstance(man.get("files"), dict)
         and 1 <= len(man["files"]) <= MAX_FILES
         and marker_data == _json(man),
         "Invalid remote manifest")
    # Validate the complete marker inventory before any project media reads.
    # Total and per-file bounds apply to offsite restores as well as upload.
    need(all(isinstance(n, str) and isinstance(v, dict)
             and set(v) == {"bytes", "sha256"}
             and type(v["bytes"]) is int and 0 <= v["bytes"] <= MAX_SINGLE
             and isinstance(v["sha256"], str)
             and re.fullmatch(r"[0-9a-f]{64}", v["sha256"])
             for n, v in man["files"].items())
         and sum(v["bytes"] for v in man["files"].values()) <= MAX_BYTES,
         "Unbounded or invalid remote file inventory")
    paths = set(man["files"])
    projects = {p.split("/")[0] for p in paths}
    need(all(PROJECT.fullmatch(p) for p in projects)
         and set(top) == projects | {MARKER},
         "Remote project-tree inventory mismatch")
    files = {}
    for project in sorted(projects):
        need(top[project]["mimeType"] == FOLDER, "Remote project is not a folder")
        child = api.list(top[project]["id"])
        wanted = {p.split("/")[1] for p in paths
                  if p.startswith(project + "/") and p.count("/") == 1}
        journals = {p for p in paths
                    if p.startswith(project + "/.keelaryn-g1/")}
        if journals:
            wanted.add(".keelaryn-g1")
        need(set(child) == wanted, "Remote project folder has unexpected contents")
        for name in sorted(wanted - {".keelaryn-g1"}):
            need(DOC.fullmatch(name) and child[name]["mimeType"] in (
                 "text/markdown", "text/csv", "application/json"),
                 "Remote file not a supported document")
            files[project + "/" + name] = api.media(child[name]["id"])
        if journals:
            need(child[".keelaryn-g1"]["mimeType"] == FOLDER,
                 "Remote journal directory missing")
            j = api.list(child[".keelaryn-g1"]["id"])
            names = {p.rsplit("/", 1)[1] for p in journals}
            need(set(j) == names and ".lock" in names,
                 "Remote journal inventory mismatch")
            for name in sorted(names):
                need(name == ".lock" or RECEIPT.fullmatch(name),
                     "Remote journal object invalid")
                files[project + "/.keelaryn-g1/" + name] = api.media(j[name]["id"])
    need(_manifest(files)["files"] == man["files"]
         and _identity(files) == version,
         "Remote version byte/hash mismatch")
    return files


def backup():
    snapshot = _snapshot()
    version = _identity(snapshot)
    api = _api()
    parent = _drive_root(api, create=True)
    version_id = api.folder(parent, version)
    children = api.list(version_id)
    projects = {p.split("/")[0] for p in snapshot}
    need(set(children) <= projects | {MARKER},
         "Unrecognized partial backup content")
    if MARKER not in children:
        for project in sorted(projects):
            dir_id = api.folder(version_id, project)
            for path, data in sorted(snapshot.items()):
                if not path.startswith(project + "/") or path.count("/") != 1:
                    continue
                name = path.split("/")[1]
                mime = ("text/markdown" if name.endswith(".md") else
                        "text/csv" if name.endswith(".csv") else "application/json")
                api.ensure_file(dir_id, name, mime, data)
            journal = {p: v for p, v in snapshot.items()
                       if p.startswith(project + "/.keelaryn-g1/")}
            if journal:
                j_id = api.folder(dir_id, ".keelaryn-g1")
                for path, data in sorted(journal.items()):
                    name = path.rsplit("/", 1)[1]
                    mime = "application/json" if name.endswith(".json") else "application/octet-stream"
                    api.ensure_file(j_id, name, mime, data)
        api.ensure_file(version_id, MARKER, "application/json",
                        _json(dict(_manifest(snapshot), version=version)))
    restored = _remote(api, version_id, version)
    need(restored == snapshot and _snapshot() == snapshot,
         "Remote backup or source readback mismatch")
    return {"status": "complete_verified", "version": version,
            "files": len(snapshot), "projects": sorted(projects),
            "bytes": sum(map(len, snapshot.values()))}


def restore(version, keep):
    need(isinstance(version, str) and VERSION.fullmatch(version),
         "Invalid version")
    api = _api()
    parent = _drive_root(api)
    versions = api.list(parent)
    need(version in versions and versions[version]["mimeType"] == FOLDER,
         "Unknown or invalid remote version")
    files = _remote(api, versions[version]["id"], version)
    _stat_dir(RECOVERY, uid=0)
    if keep:
        target = RECOVERY / ("restore-vps-tree-" + version)
        need(not target.exists() and not target.is_symlink(), "Recovery destination exists")
        os.mkdir(target, 0o700)
    else:
        target = Path(tempfile.mkdtemp(prefix="verify-vps-tree-", dir=RECOVERY))
    try:
        for name, data in sorted(files.items()):
            parts = name.split("/")
            need(len(parts) in (2, 3) and PROJECT.fullmatch(parts[0])
                 and (DOC.fullmatch(parts[-1]) or
                      parts[-2:] == [".keelaryn-g1", ".lock"]),
                 "Unsafe restore path")
            parentdir = target
            for part in parts[:-1]:
                parentdir = parentdir / part
                if not parentdir.exists():
                    os.mkdir(parentdir, 0o700)
            with open(parentdir / parts[-1], "xb") as f:
                os.fchmod(f.fileno(), 0o600)
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            need((parentdir / parts[-1]).read_bytes() == data,
                 "Restored file differs")
        return {"status": "restored_exact", "version": version,
                "files": len(files),
                "path": str(target) if keep else "temporary_verified_then_removed"}
    finally:
        if not keep:
            for name in sorted(files, key=lambda x: (-x.count("/"), x)):
                (target / name).unlink()
            for path in sorted((p for p in target.rglob("*") if p.is_dir()),
                               key=lambda x: -len(x.parts)):
                path.rmdir()
            target.rmdir()


def main(argv):
    if argv == ["backup"]:
        return backup()
    if len(argv) == 2 and argv[0] in ("verify", "restore"):
        return restore(argv[1], keep=(argv[0] == "restore"))
    raise BackupError("Usage: backup | verify VERSION | restore VERSION")


if __name__ == "__main__":
    try:
        print(json.dumps(main(sys.argv[1:]), sort_keys=True))
    except (BackupError, OSError, ValueError, UnicodeError):
        print('{"status":"failed","reason":"Root tree backup/restore blocked; see owner documentation"}')
        raise SystemExit(1)
