"""Read-only, pinned-ID Google Drive source ingress for ArmenianLearning.

Separate service-account reader: it must be shared each canonical raw file
individually. This module NEVER alters source Drive files, source permissions,
the live MCP service, or the existing backup destination. No scheduling.
Credential file is root-only and never logged.
"""
import base64
import csv
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

import drive_device_auth as oauth
from drive_plain_sender import BackupError, Drive
import drive_real_backup as backup

SA_FILE = Path("/etc/keelaryn-drive-backup/canvas-reader-sa.json")
SA_EMAIL = "keelaryn-source-reader@canvas-replica-509112-e4.iam.gserviceaccount.com"
SA_PROJECT = "canvas-replica-509112-e4"
SNAPSHOTS = Path("/var/lib/keelaryn-drive-backup/staging/ArmenianLearning")
PARENT_ID = "1y64LSe3-N3bGi4xghqZmoT0T5FBzNflH"
BASE_VERSION = "v20261113-01"
TOKEN_URL = "https://oauth2.googleapis.com/token"
READ_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
META_FIELDS = "id,name,mimeType,parents,trashed,size,modifiedTime,version,md5Checksum"
MAX_FILE = 1_000_000


def require(ok, msg):
    if not ok:
        raise BackupError(msg)


def _encode(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise BackupError("Unexpected Google OAuth redirect")


def _bearer():
    st = SA_FILE.lstat()
    require(stat.S_ISREG(st.st_mode) and st.st_uid == 0 and st.st_gid == 0
            and stat.S_IMODE(st.st_mode) == 0o600 and st.st_nlink == 1,
            "Unsafe service account credential permissions")
    cfg = json.loads(SA_FILE.read_bytes())
    require(cfg.get("type") == "service_account"
            and cfg.get("project_id") == SA_PROJECT
            and cfg.get("client_email") == SA_EMAIL
            and cfg.get("token_uri") == TOKEN_URL
            and isinstance(cfg.get("private_key"), str)
            and cfg["private_key"].startswith("-----BEGIN PRIVATE KEY-----")
            and isinstance(cfg.get("private_key_id"), str),
            "Unexpected service account identity")
    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT", "kid": cfg["private_key_id"]}
    claims = {"iss": SA_EMAIL, "aud": TOKEN_URL, "scope": READ_SCOPE,
              "iat": now, "exp": now + 600}
    unsigned = ".".join(_encode(json.dumps(x, separators=(",", ":")).encode())
                        for x in (header, claims))
    with tempfile.NamedTemporaryFile(prefix="keelaryn-sa-", mode="w", dir="/run") as key:
        os.fchmod(key.fileno(), 0o600)
        key.write(cfg["private_key"])
        key.flush()
        sig = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", key.name],
            input=unsigned.encode(), stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=20, check=True).stdout
    assertion = unsigned + "." + _encode(sig)
    post = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": assertion}).encode()
    req = urllib.request.Request(TOKEN_URL, data=post, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(req, timeout=30) as reply:
        obj = json.load(reply)
    require(obj.get("token_type", "").lower() == "bearer"
            and isinstance(obj.get("access_token"), str), "Google OAuth token unavailable")
    return obj["access_token"]


def _latest_local():
    oauth._private_dir(SNAPSHOTS)
    versions = sorted(p for p in SNAPSHOTS.iterdir()
                      if backup.VERS_RE.fullmatch(p.name) and p.is_dir()
                      and not p.is_symlink())
    require(versions and (SNAPSHOTS / BASE_VERSION) in versions, "Baseline missing")
    name, data, refs = backup._source(versions[-1])
    require(set(refs["files"]) == set(backup.EXPECTED), "Unpinned source set")
    require(refs.get("source") == "canonical Google Drive raw active core",
            "Unexpected source identity")
    require(len(set(r["source_drive_id"] for r in refs["files"].values())) == 7,
            "Duplicate canonical source ID")
    return name, data, refs


def _meta(api, fid):
    query = urllib.parse.urlencode({"fields": META_FIELDS})
    return api.json("GET", "/files/" + Drive._id(fid) + "?" + query)


def _read_all(api, refs):
    content, attributes = {}, {}
    for name, mime in backup.EXPECTED.items():
        fid = refs["files"][name]["source_drive_id"]
        before = _meta(api, fid)
        require(before.get("id") == fid and before.get("name") == name
                and before.get("mimeType") == mime
                and before.get("parents") == [PARENT_ID]
                and before.get("trashed") is False, "Canonical source identity changed")
        raw = api.media(fid)
        require(len(raw) <= MAX_FILE and int(before.get("size", -1)) == len(raw),
                "Canonical size changed during read")
        require(hashlib.md5(raw).hexdigest() == before["md5Checksum"]
                if before.get("md5Checksum") else True, "Source MD5 does not match Drive")
        raw.decode("utf-8")
        content[name] = raw
        attributes[name] = before
    # A bounded second metadata pass detects ordinary multi-file edit races.
    for name, first in attributes.items():
        second = _meta(api, refs["files"][name]["source_drive_id"])
        require(first == second, "Canonical source changed during capture")
    require(sum(map(len, content.values())) <= backup.MAX_ALL, "Snapshot exceeds cap")
    rows = list(csv.reader(io.StringIO(content["MASTERY.csv"].decode("utf8"))))
    require(len(rows) > 1 and len(rows[0]) == 16 and all(len(r) == 16 for r in rows),
            "Invalid MASTERY.csv")
    require(b"NEXT" in content["STATE.md"], "STATE.md missing NEXT")
    return content, attributes


def run(capture=False):
    require(os.geteuid() == 0, "Root-only source ingress")
    old_version, old_data, previous = _latest_local()
    api = Drive(_bearer())
    files, attrs = _read_all(api, previous)
    changed = [name for name in backup.EXPECTED if files[name] != old_data[name]]
    if not changed or not capture:
        return {"status": "unchanged" if not changed else "changed_not_captured",
                "files_read": len(files), "bytes_read": sum(map(len, files.values())),
                "compared_to": old_version, "changed_names": changed,
                "source": "Google Drive service-account read-only"}
    day = datetime.now(ZoneInfo("Asia/Yerevan")).strftime("%Y%m%d")
    existing = {p.name for p in SNAPSHOTS.iterdir()}
    index = next((n for n in range(1, 100) if f"v{day}-{n:02d}" not in existing), None)
    require(index is not None, "No available snapshot version slot")
    version = f"v{day}-{index:02d}"
    refs = {"schema": backup.SOURCE_SCHEMA, "owner": backup.OWNER,
            "source": previous["source"], "version": version,
            "files": {name: {
                "source_drive_id": previous["files"][name]["source_drive_id"],
                "size": len(files[name]),
                "sha256": hashlib.sha256(files[name]).hexdigest(),
                "source_modified_at": attrs[name].get("modifiedTime")}
                for name in backup.EXPECTED}}
    with tempfile.TemporaryDirectory(prefix=".keelaryn-source-stage-", dir=SNAPSHOTS) as tmp:
        part = Path(tmp)
        for name, raw in files.items():
            path = part / name
            with path.open("xb") as fd:
                fd.write(raw)
                fd.flush()
                os.fsync(fd.fileno())
            path.chmod(0o600)
        p = part / "source-refs.json"
        p.write_text(json.dumps(refs, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
        p.chmod(0o600)
        require(not (SNAPSHOTS / version).exists(), "Target snapshot appeared")
        os.rename(part, SNAPSHOTS / version)
    checked_version, checked, _ = backup._source(SNAPSHOTS / version)
    require(checked_version == version and checked == files,
            "Local staged source validation failed")
    return {"status": "captured_locally_not_backed_up", "version": version,
            "files_read": len(files), "bytes_read": sum(map(len, files.values())),
            "changed_names": changed, "source": "Google Drive service-account read-only"}


if __name__ == "__main__":
    try:
        require(len(sys.argv) == 2 and sys.argv[1] in ("check", "capture"),
                "Use check or capture")
        result = run(sys.argv[1] == "capture")
        print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    except Exception:
        # OAuth errors and file contents must not enter job logs.
        print('{"status":"failed","message":"Source verification failed; secrets not disclosed"}')
        raise SystemExit(1)
