"""One owner-scoped, append-only plain Drive backup of 7 current ArmenianLearning files.

Independent root-only CLI. Never imports or alters live MCP, Drive canonical
sources, old backup automations, or the connector-created pilot. Owner remains
Google Drive canonical until separate migration authorization. No scheduler.
"""
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

import drive_device_auth as oauth
from drive_plain_sender import Drive, BackupError, _read, FOLDER

OWNER = "ArmenianLearning"
ROOT_NAME = "KeelarynOS - real raw backups (drive.file)"
SOURCE_SCHEMA = "keelaryn-real-source-references-v1"
SCHEMA = "keelaryn-real-active-core-v1"
MARKER = ".keelaryn-backup-complete.json"
DEST_CONFIG = oauth.CONFIG / "destination.json"
EXPECTED = {
    "PROJECT_RULES.md": "text/markdown",
    "00__START_HERE.md": "text/markdown",
    "STATE.md": "text/markdown",
    "MASTERY.csv": "text/csv",
    "CURRICULUM.md": "text/markdown",
    "ERRORS.md": "text/markdown",
    "ArmenianLearning — Курс с абсолютного нуля - текущая методика и старт (2026-10-25).md": "text/markdown",
}
VERS_RE = re.compile(r"v[0-9]{8}-[0-9]{2}\Z")
MAX_ALL = 1_500_000


def deny(condition, message):
    if not condition:
        raise BackupError(message)


def new_api():
    return Drive(oauth.fresh_access_token())


def _json_file(path):
    try:
        v = json.loads(_read(path))
    except (UnicodeError, ValueError):
        raise BackupError("Invalid private local backup metadata") from None
    deny(isinstance(v, dict), "Invalid private metadata structure")
    return v


def _pin_destination(folder_id):
    if DEST_CONFIG.exists():
        item = _json_file(DEST_CONFIG)
        deny(item == {"schema": SCHEMA, "folder_id": folder_id},
             "Pinned backup folder ID mismatch")
        return
    oauth._atomic_write(DEST_CONFIG,
                        json.dumps({"schema": SCHEMA, "folder_id": folder_id}).encode())


def dest_id():
    d = _json_file(DEST_CONFIG)
    deny(d.get("schema") == SCHEMA, "Destination config schema mismatch")
    return Drive._id(d.get("folder_id"))


def _verified_folder(api, folder_id, expected_name):
    item = api.get(folder_id)
    deny(item.get("id") == folder_id and item.get("name") == expected_name
         and item.get("mimeType") == FOLDER and item.get("trashed") is False
         and item.get("shared") is False,
         "Backup folder name, type or privacy changed")
    return item


def bootstrap():
    api = new_api()
    folder = api.folder("root", ROOT_NAME)
    _verified_folder(api, folder, ROOT_NAME)
    _pin_destination(folder)
    return {"status": "private_destination_ready", "folder_id": folder}


def _source(dirpath):
    root = Path(dirpath).absolute()
    deny(VERS_RE.fullmatch(root.name) is not None, "Unexpected source version")
    for path in (root, *root.parents):
        deny(not path.is_symlink(), "Local source symlink path")
    oauth._private_dir(root)
    names = {p.name for p in root.iterdir()}
    deny(names == set(EXPECTED) | {"source-refs.json"}, "Incomplete active source tree")
    refs = _json_file(root / "source-refs.json")
    deny(refs.get("schema") == SOURCE_SCHEMA and refs.get("owner") == OWNER
         and refs.get("version") == root.name and isinstance(refs.get("files"), dict)
         and set(refs["files"]) == set(EXPECTED),
         "Source provenance or exact owner scope invalid")
    files = {}
    total = 0
    for name in EXPECTED:
        record = refs["files"][name]
        deny(isinstance(record, dict), "Invalid provenance entry")
        Drive._id(record.get("source_drive_id"))
        content = _read(root / name)
        deny(record.get("sha256") == hashlib.sha256(content).hexdigest()
             and record.get("size") == len(content) and len(content) <= 1_000_000,
             "Staged file differs from captured source")
        total += len(content)
        files[name] = content
        if name.endswith((".md", ".csv")):
            try:
                content.decode("utf-8")
            except UnicodeError:
                raise BackupError("Non-UTF-8 canonical source") from None
    deny(total <= MAX_ALL, "Excessive backup corpus")
    try:
        rows = list(csv.reader(io.StringIO(files["MASTERY.csv"].decode("utf8"))))
        deny(len(rows) > 1 and len(rows[0]) == 16 and all(len(r) == 16 for r in rows),
             "Active MASTERY.csv structure invalid")
        deny(b"NEXT" in files["STATE.md"], "No resumable state")
    except (ValueError, csv.Error):
        raise BackupError("Invalid active CSV snapshot") from None
    return root.name, files, refs


def _manifest(version, files, refs):
    return {"schema": SCHEMA, "owner": OWNER, "version": version,
            "canonical_owner_remains": "Google Drive original sources",
            "source_snapshot_type": "seven active Markdown/CSV files, not full historical project",
            "files": {name: {"size": len(files[name]),
                              "sha256": hashlib.sha256(files[name]).hexdigest(),
                              "source_drive_id": refs["files"][name]["source_drive_id"]}
                      for name in sorted(files)}}


def _bytes(m):
    return (json.dumps(m,ensure_ascii=False,sort_keys=True,separators=(",", ":")) + "\n").encode("utf-8")


def _check_full(api, version_id, files, marker=None):
    children = api.list(version_id)
    expected = set(EXPECTED) | ({MARKER} if marker is not None else set())
    deny(set(children) == expected, "Partial backup or extra remote object")
    for name, raw in files.items():
        obj = children[name]
        deny(obj.get("mimeType") == EXPECTED[name] and api.media(obj["id"]) == raw,
             "Remote byte-level readback mismatch")
    if marker is not None:
        deny(children[MARKER].get("mimeType") == "application/json"
             and api.media(children[MARKER]["id"]) == marker, "Completion marker mismatch")


def backup(local_version_dir):
    api = new_api()
    root_folder = dest_id()
    _verified_folder(api,root_folder,ROOT_NAME)
    version, files, refs = _source(local_version_dir)
    owner_id = api.folder(root_folder, OWNER)
    _verified_folder(api,owner_id,OWNER)
    version_id = api.folder(owner_id, version)
    _verified_folder(api,version_id,version)
    marker = _bytes(_manifest(version,files,refs))
    existing = api.list(version_id)
    deny(set(existing) <= set(EXPECTED) | {MARKER}, "Unknown remote version file")
    if MARKER in existing:
        _check_full(api, version_id, files, marker)
        return {"status":"already_complete","version":version,"file_count":len(files)}
    # Fail BEFORE uploading anything if a prior partial version was tampered.
    for name, obj in existing.items():
        deny(obj.get("mimeType") == EXPECTED[name]
             and api.media(obj["id"]) == files[name], "Corrupted partial backup")
    for name, content in files.items():
        api.ensure_file(version_id, name, EXPECTED[name], content)
    _check_full(api,version_id,files)
    api.ensure_file(version_id,MARKER,"application/json",marker)
    _check_full(api,version_id,files,marker)
    _, latest, _ = _source(local_version_dir)
    deny(latest == files, "Local source changed during backup")
    return {"status":"published","version":version,"file_count":len(files),
            "bytes":sum(len(x) for x in files.values()),"folder_id":version_id}


def _version_folder(api, version):
    deny(isinstance(version,str) and VERS_RE.fullmatch(version),
         "Invalid requested backup version")
    parent = dest_id()
    _verified_folder(api,parent,ROOT_NAME)
    owner = api.list(parent)
    deny(OWNER in owner and owner[OWNER].get("mimeType") == FOLDER,
         "Backup owner folder missing")
    owner_id = owner[OWNER]["id"]
    _verified_folder(api,owner_id,OWNER)
    items = api.list(owner_id)
    deny(version in items and items[version].get("mimeType") == FOLDER,
         "Requested version not found")
    vid = items[version]["id"]
    _verified_folder(api,vid,version)
    return vid


def restore(version, target):
    api = new_api()
    vid = _version_folder(api,version)
    children = api.list(vid)
    deny(set(children) == set(EXPECTED) | {MARKER}, "Backup folder is incomplete")
    deny(children[MARKER]["mimeType"] == "application/json", "Bad marker MIME type")
    marker = api.media(children[MARKER]["id"])
    try:
        manifest = json.loads(marker)
    except (ValueError,UnicodeError):
        raise BackupError("Invalid remote backup marker") from None
    deny(manifest.get("schema") == SCHEMA and manifest.get("version") == version
         and manifest.get("owner") == OWNER and isinstance(manifest.get("files"),dict)
         and set(manifest["files"]) == set(EXPECTED),
         "Backup manifest ownership or file inventory mismatch")
    files = {}
    for name in EXPECTED:
        obj = children[name]
        deny(obj["mimeType"] == EXPECTED[name], "Unexpected backed-up MIME")
        raw = api.media(obj["id"])
        expected = manifest["files"][name]
        deny(expected.get("size") == len(raw)
             and expected.get("sha256") == hashlib.sha256(raw).hexdigest(),
             "Backed-up file checksum mismatch")
        files[name] = raw
    folder = Path(target).absolute()
    deny(not folder.exists() and not folder.is_symlink(), "Restore path already exists")
    oauth._private_dir(folder.parent)
    partial = Path(tempfile.mkdtemp(prefix=".keelaryn-real-restore-",dir=folder.parent))
    try:
        for name,content in files.items():
            path = partial / name
            with path.open("xb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            path.chmod(0o600)
        # Ensure consumer can recover current learning position without Drive.
        deny("NEXT" in (partial/"STATE.md").read_text("utf8"),
             "Restored NEXT not usable")
        deny(not folder.exists(), "Restore destination appeared")
        os.rename(partial,folder)
    finally:
        if partial.exists():
            shutil.rmtree(partial)
    return {"status":"restored","version":version,"file_count":len(files),
            "bytes":sum(map(len,files.values()))}


def main():
    deny(os.geteuid() == 0, "Private root-only operation required")
    if len(sys.argv)==2 and sys.argv[1]=="bootstrap":
        result=bootstrap()
    elif len(sys.argv)==3 and sys.argv[1]=="backup":
        result=backup(sys.argv[2])
    elif len(sys.argv)==4 and sys.argv[1]=="restore":
        result=restore(sys.argv[2],sys.argv[3])
    else:
        raise BackupError("Use bootstrap, backup <staged-directory>, or restore <version> <new-directory>")
    print(json.dumps(result,sort_keys=True,ensure_ascii=False))


if __name__=="__main__":
    try:
        main()
    except Exception:
        # An HTTP client may throw with provider contents. Never echo it:
        # this job holds credentials and sensitive canonical data in memory.
        print('{"status":"failed","message":"Private backup operation blocked; no credentials disclosed"}')
        sys.exit(1)
