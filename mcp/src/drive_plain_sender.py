"""Development-only plain Drive backup sender for a *fictional* owner.

No credentials, scheduling, local live-owner lookup or automatic activation.
The API client takes a short-lived bearer token in memory from an OUTSIDE,
separately approved OAuth provider. Normal use is mock-only until an explicit
live-enable gate; no secrets are stored or acquired here.

Raw Drive files are created only (never PATCH/DELETE). A final COMPLETE marker
separates resumable partial uploads from verified versions. No claim of
transactional remote publication against concurrent malicious writers.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import urllib.error
import urllib.parse
import urllib.request

API = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3"
FOLDER = "application/vnd.google-apps.folder"
ID = re.compile(r"[A-Za-z0-9_-]{10,160}\Z")
VERSION = re.compile(r"v[0-9]{4}\Z")
RECEIPT = re.compile(r"[0-9a-f]{32}\.json\Z")
TOP = {"PROJECT.md": "text/markdown", "CURSOR.json": "application/json",
       "MASTERY.csv": "text/csv"}
MARKER = ".keelaryn-export-complete.json"
SCHEMA = "keelaryn-synthetic-plain-drive-v1"
MAX_FILE = 65536
MAX_TOTAL = 600000
MAX_ITEMS = 135
MAX_REPLY = 750000


class BackupError(ValueError):
    """Safe failure. Never contains a bearer token or response body."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise BackupError("Drive API redirects are not permitted")


def https_exchange(method, url, headers, body):
    """Production transport: fixed official HTTPS endpoints, no redirects."""
    if not (url.startswith(API + "/") or url.startswith(UPLOAD + "/")):
        raise BackupError("Disallowed HTTP endpoint")
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=20) as response:
            data = response.read(MAX_REPLY + 1)
            if len(data) > MAX_REPLY:
                raise BackupError("Oversized Drive response")
            return response.status, data
    except urllib.error.HTTPError as e:
        raise BackupError("Drive request returned HTTP " + str(e.code)) from None
    except (urllib.error.URLError, TimeoutError):
        raise BackupError("Drive network request failed") from None


def _safe_object(path, *, directory=False):
    try:
        st = path.lstat()
    except FileNotFoundError:
        raise BackupError("Missing local snapshot object") from None
    if (st.st_uid != os.geteuid() or st.st_mode & 0o077
            or (not stat.S_ISDIR(st.st_mode) if directory
                else not stat.S_ISREG(st.st_mode) or st.st_nlink != 1)):
        raise BackupError("Unsafe local snapshot owner, type or permissions")
    return st


def _read(path):
    _safe_object(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1
                or st.st_uid != os.geteuid() or st.st_mode & 0o077
                or st.st_size > MAX_FILE):
            raise BackupError("Unsafe or oversized local file")
        data = os.read(fd, MAX_FILE + 1)
        after = os.fstat(fd)
        if (len(data) != st.st_size or len(data) > MAX_FILE or
                (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_size,
                    after.st_mtime_ns, after.st_ctime_ns)):
            raise BackupError("Local snapshot changed during read")
        return data
    finally:
        os.close(fd)


def source_files(version_dir):
    """Allow only the known fictional owner and its fully committed G1 receipts."""
    root = Path(version_dir).absolute()
    if not VERSION.fullmatch(root.name):
        raise BackupError("Expected versioned synthetic snapshot directory")
    for ancestor in (root, *root.parents):
        if ancestor.is_symlink():
            raise BackupError("Symlink in snapshot ancestor path")
    _safe_object(root, directory=True)
    journal = root / ".keelaryn-g1"
    _safe_object(journal, directory=True)
    if {p.name for p in root.iterdir()} != set(TOP) | {".keelaryn-g1"}:
        raise BackupError("Unexpected or missing synthetic owner file")
    journal_names = {p.name for p in journal.iterdir()}
    if ".lock" not in journal_names:
        raise BackupError("Missing G1 lock")
    receipts = sorted(journal_names - {".lock"})
    if not 1 <= len(receipts) <= 128 or not all(
            RECEIPT.fullmatch(x) for x in receipts):
        raise BackupError("Unexpected G1 receipt")
    names = [*TOP, ".keelaryn-g1/.lock"]
    names += [".keelaryn-g1/" + x for x in receipts]
    files = {name: _read(root / name) for name in names}
    if files[".keelaryn-g1/.lock"]:
        raise BackupError("Unexpected nonempty lock file")
    for name in receipts:
        try:
            entry = json.loads(files[".keelaryn-g1/" + name])
        except (ValueError, UnicodeError):
            raise BackupError("Invalid G1 receipt") from None
        if (not isinstance(entry, dict) or entry.get("status") != "committed"
                or entry.get("request_id") != name[:-5]):
            raise BackupError("Uncommitted or mismatched G1 receipt")
    try:
        if "NEXT: " not in files["PROJECT.md"].decode("utf-8"):
            raise BackupError("Missing human-readable NEXT")
        cursor = json.loads(files["CURSOR.json"])
        if not isinstance(cursor, dict):
            raise BackupError("Invalid synthetic cursor")
        files["MASTERY.csv"].decode("utf-8")
    except (UnicodeError, ValueError):
        raise BackupError("Nonportable synthetic source") from None
    if sum(len(data) for data in files.values()) > MAX_TOTAL:
        raise BackupError("Snapshot exceeds overall byte cap")
    return files


def manifest(version, files):
    return {"schema": SCHEMA, "version": version,
            "files": {name: {"size": len(data),
                             "sha256": hashlib.sha256(data).hexdigest()}
                      for name, data in sorted(files.items())}}


def _marker_bytes(man):
    return (json.dumps(man, sort_keys=True, separators=(",", ":")) + "\n").encode()


class Drive:
    """Tiny REST client with injectable transport. No token acquisition."""
    def __init__(self, bearer, exchange=None):
        if not isinstance(bearer, str) or not 8 <= len(bearer) <= 4096 or any(
                x.isspace() for x in bearer):
            raise BackupError("Missing or invalid short-lived bearer")
        if exchange is None and os.environ.get("KEELARYN_DRIVE_PLAIN_LIVE") != "1":
            raise BackupError("Direct network disabled pending separate consent")
        self.__bearer = bearer
        self.exchange = exchange or https_exchange

    def request(self, method, path, *, upload=False, body=None, mime=None,
                response_limit=MAX_REPLY):
        if method not in ("GET", "POST"):
            raise BackupError("Read or create only")
        base = UPLOAD if upload else API
        if not path.startswith("/files"):
            raise BackupError("Unsupported Drive route")
        url = base + path
        if not (url.startswith(API + "/files") or
                url.startswith(UPLOAD + "/files")):
            raise BackupError("Unsafe Drive URL")
        headers = {"Authorization": "Bearer " + self.__bearer}
        if mime:
            headers["Content-Type"] = mime
        try:
            status, raw = self.exchange(method, url, headers, body)
        except BackupError:
            raise
        except Exception:
            raise BackupError("Drive request failed or outcome unknown") from None
        if status not in (200, 201) or not isinstance(raw, bytes) or len(raw) > response_limit:
            raise BackupError("Drive request status or response bounds invalid")
        return raw

    def json(self, method, path, data=None):
        body = json.dumps(data, separators=(",", ":")).encode() if data is not None else None
        raw = self.request(method, path, body=body,
                           mime="application/json" if body is not None else None)
        try:
            reply = json.loads(raw)
        except (UnicodeError, ValueError):
            raise BackupError("Invalid Drive JSON") from None
        if not isinstance(reply, dict):
            raise BackupError("Invalid Drive object")
        return reply

    def get(self, file_id):
        self._id(file_id)
        return self.json("GET", "/files/" + file_id + "?fields=id,name,mimeType,parents,trashed,shared")

    @staticmethod
    def _id(value):
        if not isinstance(value, str) or not ID.fullmatch(value):
            raise BackupError("Invalid Drive ID")
        return value

    def list(self, parent):
        self._id(parent)
        query = urllib.parse.urlencode({
            "q": "'" + parent + "' in parents and trashed = false",
            "fields": "nextPageToken,files(id,name,mimeType,parents,trashed,size)",
            "pageSize": "1000"})
        item = self.json("GET", "/files?" + query)
        files = item.get("files")
        if (not isinstance(files, list) or len(files) > 1000
                or item.get("nextPageToken")):
            raise BackupError("Incomplete Drive listing")
        out = {}
        for obj in files:
            if (not isinstance(obj, dict) or not isinstance(obj.get("name"), str)
                    or obj.get("name") in out or not isinstance(obj.get("parents"), list)
                    or obj.get("parents") != [parent] or obj.get("trashed") is not False):
                raise BackupError("Unexpected or duplicate remote child")
            self._id(obj.get("id"))
            out[obj["name"]] = obj
        return out

    def folder(self, parent, name):
        children = self.list(parent)
        if name in children:
            item = children[name]
            if item.get("mimeType") != FOLDER:
                raise BackupError("Existing Drive path is not a folder")
            return item["id"]
        data = self.json("POST", "/files?fields=id,name,mimeType,parents",
                         {"name": name, "mimeType": FOLDER, "parents": [parent]})
        self._created(data, parent, name, FOLDER)
        return data["id"]

    def _created(self, obj, parent, name, mime):
        self._id(obj.get("id"))
        if (obj.get("name") != name or obj.get("mimeType") != mime
                or obj.get("parents") != [parent]):
            raise BackupError("Created Drive metadata mismatch")

    def media(self, file_id):
        self._id(file_id)
        return self.request("GET", "/files/" + file_id + "?alt=media",
                            response_limit=MAX_FILE)

    def upload(self, parent, name, mime, data):
        if len(data) > MAX_FILE:
            raise BackupError("Oversized upload")
        metadata = json.dumps({"name": name, "mimeType": mime,
                               "parents": [parent]}, separators=(",", ":")).encode()
        boundary = "keelaryn_plain_" + hashlib.sha256(metadata + data).hexdigest()[:24]
        delim = boundary.encode()
        if delim in metadata or delim in data:
            raise BackupError("Multipart boundary collision")
        body = (b"--" + delim + b"\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
                + metadata + b"\r\n--" + delim + b"\r\nContent-Type: "
                + mime.encode("ascii") + b"\r\n\r\n" + data
                + b"\r\n--" + delim + b"--\r\n")
        path = "/files?uploadType=multipart&fields=id,name,mimeType,parents"
        raw = self.request("POST", path, upload=True, body=body,
                           mime="multipart/related; boundary=" + boundary)
        try:
            obj = json.loads(raw)
        except (UnicodeError, ValueError):
            raise BackupError("Invalid upload response") from None
        if not isinstance(obj, dict):
            raise BackupError("Invalid upload metadata")
        self._created(obj, parent, name, mime)
        return obj["id"]

    def ensure_file(self, parent, name, mime, data):
        children = self.list(parent)
        if name in children:
            obj = children[name]
            if obj.get("mimeType") != mime:
                raise BackupError("Conflicting file MIME")
            file_id = obj["id"]
        else:
            file_id = self.upload(parent, name, mime, data)
        if self.media(file_id) != data:
            raise BackupError("Remote file bytes differ; refusing overwrite")
        return file_id


def _check_remote(api, folder_id, expected_files, marker=None):
    children = api.list(folder_id)
    allowed = set(TOP) | {".keelaryn-g1"}
    if marker is not None:
        allowed.add(MARKER)
    if set(children) != allowed:
        raise BackupError("Remote version incomplete or contains extra entries")
    if children[".keelaryn-g1"]["mimeType"] != FOLDER:
        raise BackupError("Missing remote G1 directory")
    journal_id = children[".keelaryn-g1"]["id"]
    journal = api.list(journal_id)
    expected_j = {name.split("/", 1)[1] for name in expected_files if name.startswith(".keelaryn-g1/")}
    if set(journal) != expected_j:
        raise BackupError("Remote G1 receipts missing or extra")
    for name, data in expected_files.items():
        if "/" in name:
            obj = journal[name.split("/", 1)[1]]
        else:
            obj = children[name]
        mime = (TOP.get(name) if "/" not in name else
                "application/json" if name.endswith(".json") else "application/octet-stream")
        if obj["mimeType"] != mime or api.media(obj["id"]) != data:
            raise BackupError("Remote SHA/readback mismatch")
    if marker is not None:
        obj = children[MARKER]
        if obj["mimeType"] != "application/json" or api.media(obj["id"]) != marker:
            raise BackupError("Completion marker changed")


def publish_synthetic(api, source, parent_id):
    """Create/resume exactly one synthetic version; completed versions immutable."""
    Drive._id(parent_id)
    files = source_files(source)
    version = Path(source).name
    man = manifest(version, files)
    marker = _marker_bytes(man)
    p = api.get(parent_id)
    if (p.get("id") != parent_id or p.get("mimeType") != FOLDER or
            p.get("trashed") is not False or p.get("shared") is not False):
        raise BackupError("Destination folder is not verified private")
    version_id = api.folder(parent_id, version)
    previous = api.list(version_id)
    if MARKER in previous:
        _check_remote(api, version_id, files, marker)
        return {"status": "already_complete", "version": version, "count": len(files)}
    if not set(previous) <= set(TOP) | {".keelaryn-g1"}:
        raise BackupError("Unknown remote partial content")
    # Validate *all* pre-existing objects before any new upload. A failed or
    # corrupted prior attempt must not be silently repaired or added to.
    for name, obj in previous.items():
        if name == ".keelaryn-g1":
            if obj.get("mimeType") != FOLDER:
                raise BackupError("Conflicting journal directory")
            nested = api.list(obj["id"])
            expected_names = {p.split("/", 1)[1] for p in files
                              if p.startswith(".keelaryn-g1/")}
            if not set(nested) <= expected_names:
                raise BackupError("Unexpected partial journal entry")
            for rec, item in nested.items():
                path = ".keelaryn-g1/" + rec
                mime = "application/json" if rec.endswith(".json") else "application/octet-stream"
                if item.get("mimeType") != mime or api.media(item["id"]) != files[path]:
                    raise BackupError("Previously uploaded G1 receipt changed")
        elif obj.get("mimeType") != TOP[name] or api.media(obj["id"]) != files[name]:
            raise BackupError("Previously uploaded owner file changed")
    for name in TOP:
        api.ensure_file(version_id, name, TOP[name], files[name])
    journal_id = api.folder(version_id, ".keelaryn-g1")
    for path in sorted(name for name in files if name.startswith(".keelaryn-g1/")):
        name = path.split("/", 1)[1]
        mime = "application/json" if name.endswith(".json") else "application/octet-stream"
        api.ensure_file(journal_id, name, mime, files[path])
    _check_remote(api, version_id, files)
    api.ensure_file(version_id, MARKER, "application/json", marker)
    _check_remote(api, version_id, files, marker)
    if source_files(source) != files:
        raise BackupError("Source changed while publishing")
    return {"status": "published", "version": version, "count": len(files)}


def restore_synthetic(api, version_folder_id, target_dir):
    """Independent provider readback into a new empty local directory."""
    import tempfile
    Drive._id(version_folder_id)
    target = Path(target_dir).absolute()
    if target.exists() or target.is_symlink():
        raise BackupError("Restore target already exists")
    parent = target.parent
    _safe_object(parent, directory=True)
    children = api.list(version_folder_id)
    if MARKER not in children or ".keelaryn-g1" not in children:
        raise BackupError("Unpublished/incomplete Drive version")
    raw = api.media(children[MARKER]["id"])
    try:
        man = json.loads(raw)
    except (UnicodeError, ValueError):
        raise BackupError("Invalid completion marker") from None
    if (not isinstance(man, dict) or man.get("schema") != SCHEMA
            or not isinstance(man.get("version"), str)
            or not VERSION.fullmatch(man["version"])):
        raise BackupError("Unrecognized completion marker")
    version_info = api.get(version_folder_id)
    if (version_info.get("name") != man["version"]
            or version_info.get("mimeType") != FOLDER
            or version_info.get("trashed") is not False
            or version_info.get("shared") is not False):
        raise BackupError("Restored version folder identity or privacy mismatch")
    mfiles = man.get("files")
    if not isinstance(mfiles, dict) or not 4 <= len(mfiles) <= MAX_ITEMS:
        raise BackupError("Invalid marker file listing")
    restored = {}
    nested = api.list(children[".keelaryn-g1"]["id"])
    if set(children) != set(TOP) | {".keelaryn-g1", MARKER}:
        raise BackupError("Unexpected restore items")
    if set(nested) != {p.split("/", 1)[1] for p in mfiles if p.startswith(".keelaryn-g1/")}:
        raise BackupError("Unexpected nested restore items")
    for name, recorded in mfiles.items():
        if name in TOP:
            entry = children[name]
        elif name.startswith(".keelaryn-g1/"):
            entry = nested[name.split("/", 1)[1]]
        else:
            raise BackupError("Unexpected restored path")
        mime = (TOP[name] if name in TOP else
                "application/json" if name.endswith(".json") else "application/octet-stream")
        if entry.get("mimeType") != mime:
            raise BackupError("Unexpected restored file type")
        data = api.media(entry["id"])
        if (not isinstance(recorded, dict) or recorded.get("size") != len(data)
                or recorded.get("sha256") != hashlib.sha256(data).hexdigest()):
            raise BackupError("Restore SHA mismatch")
        restored[name] = data
    # Validate format and G1 semantics before publication; use a private,
    # standalone temporary snapshot as validation input.
    tmp = Path(tempfile.mkdtemp(prefix=".keelaryn-restore-", dir=parent))
    try:
        (tmp / ".keelaryn-g1").mkdir(mode=0o700)
        for name, data in restored.items():
            file = tmp / name
            with file.open("xb") as fp:
                fp.write(data)
                fp.flush()
                os.fsync(fp.fileno())
            file.chmod(0o600)
        (tmp / ".keelaryn-g1").chmod(0o700)
        # source_files requires version-shaped name; format check is independent.
        if set(restored) != set(TOP) | {".keelaryn-g1/.lock"} | {
                ".keelaryn-g1/" + n for n in nested if n != ".lock"}:
            raise BackupError("Incomplete reconstructed tree")
        if b"NEXT: " not in restored["PROJECT.md"]:
            raise BackupError("No human-readable NEXT")
        for name, data in restored.items():
            if name.startswith(".keelaryn-g1/") and name.endswith(".json"):
                if json.loads(data).get("status") != "committed":
                    raise BackupError("Bad restored G1 receipt")
        if target.exists():
            raise BackupError("Restore destination appeared unexpectedly")
        os.rename(tmp, target)
        return {"status": "restored", "version": man["version"], "count": len(restored)}
    finally:
        if tmp.exists():
            import shutil
            shutil.rmtree(tmp)
