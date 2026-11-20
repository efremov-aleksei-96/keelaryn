#!/usr/bin/env python3
"""Deterministic Google Drive -> private VPS staging. No canonical cutover.

Read-only OAuth credential is isolated from the existing drive.file backup.
Each owner folder is explicitly pinned in a root-only config. No AI, no deletes,
no API writes, no recursive child access, no Google-native lossy conversions.
"""
import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from drive_plain_sender import Drive, REAL_FILE_LIMIT
from drive_bulk_oauth import fresh_reader

CONFIG = Path("/etc/keelaryn-drive-bulk/owners.json")
STAGE = Path("/var/lib/keelaryn-migration-staging/bulk-automatic")
SCHEMA = "keelaryn-drive-bulk-stage-v1"
META = "id,name,mimeType,parents,trashed,size,md5Checksum,modifiedTime"
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}\Z")
ID = re.compile(r"[A-Za-z0-9_-]{15,128}\Z")
DENIED = {"bankruptcy", "secrets", "vault", ".git"}
TEXT_MIME = {".md": {"text/markdown", "text/plain"},
             ".csv": {"text/csv", "text/plain", "application/vnd.ms-excel"},
             ".json": {"application/json", "text/plain"},
             ".txt": {"text/plain"}}
BINARY_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".png": "image/png", ".pdf": "application/pdf",
               ".webp": "image/webp",
               ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
               ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
LIMIT_FILES = 400
LIMIT_TOTAL = 64 * 1024 * 1024


def require(ok, message):
    if not ok:
        raise ValueError(message)


def private_dir(path, create=False):
    if create:
        path.mkdir(mode=0o700, exist_ok=True)
    st = path.lstat()
    require(stat.S_ISDIR(st.st_mode) and not path.is_symlink()
            and st.st_uid == 0 and st.st_gid == 0
            and stat.S_IMODE(st.st_mode) == 0o700,
            "Invalid private staging/config directory")


def private_file(path):
    st = path.lstat()
    require(stat.S_ISREG(st.st_mode) and not path.is_symlink()
            and st.st_uid == 0 and st.st_gid == 0
            and st.st_nlink == 1 and stat.S_IMODE(st.st_mode) == 0o600,
            "Invalid root-only source configuration/manifest")
    require(st.st_size <= 250_000, "Metadata file oversized")
    return json.loads(path.read_text(encoding="utf-8"))


def source_config():
    private_dir(CONFIG.parent)
    data = private_file(CONFIG)
    require(data.get("schema") == SCHEMA and
            isinstance(data.get("owners"), list) and
            1 <= len(data["owners"]) <= 64, "Invalid source list")
    owners = {}
    used_ids = set()
    for x in data["owners"]:
        require(isinstance(x, dict) and set(x) == {"owner", "folder_id"}
                and isinstance(x["owner"], str)
                and NAME.fullmatch(x["owner"]) and x["owner"].lower() not in DENIED
                and isinstance(x["folder_id"], str) and ID.fullmatch(x["folder_id"])
                and x["owner"] not in owners and x["folder_id"] not in used_ids,
                "Unsafe or duplicate source owner")
        owners[x["owner"]] = x["folder_id"]
        used_ids.add(x["folder_id"])
    return owners


def metadata(api, file_id):
    Drive._id(file_id)
    q = urllib.parse.urlencode({"fields": META})
    obj = api.json("GET", "/files/" + file_id + "?" + q)
    require(isinstance(obj, dict) and obj.get("id") == file_id
            and obj.get("trashed") is False, "Source identity invalid")
    return obj


def source_tree(api, owner, folder_id):
    root = metadata(api, folder_id)
    require(root.get("name") == owner
            and root.get("mimeType") == "application/vnd.google-apps.folder",
            "Owner folder mismatch")
    children = api.list(folder_id)
    require(len(children) <= LIMIT_FILES, "Owner file count over bound")
    out = []
    for name, item in sorted(children.items()):
        require(isinstance(name, str) and item["parents"] == [folder_id]
                and item.get("trashed") is False, "Unsafe owner child")
        if not NAME.fullmatch(name) or name.lower() in DENIED:
            raise ValueError("Unsupported or forbidden filename in selected owner")
        is_dir = item["mimeType"] == "application/vnd.google-apps.folder"
        suffix = Path(name).suffix.lower()
        supported = ((suffix in TEXT_MIME and item["mimeType"] in TEXT_MIME[suffix])
                     or (suffix in BINARY_MIME
                         and item["mimeType"] == BINARY_MIME[suffix]))
        size = item.get("size")
        raw_size = int(size) if isinstance(size, str) and size.isdecimal() else None
        eligibility = ("CHILD_OWNER_NOT_ENTERED" if is_dir else
                       "SUPPORTED_DIRECT_SOURCE" if supported and raw_size is not None
                       and raw_size <= REAL_FILE_LIMIT else
                       "TOO_LARGE" if supported and raw_size is not None
                       else "NATIVE_OR_OTHER_REQUIRES_ADAPTATION")
        out.append({"name": name, "id": item["id"], "mime": item["mimeType"],
                    "size": raw_size, "classification": eligibility})
    return out


def checked_read(api, parent, item):
    original = metadata(api, item["id"])
    require(original.get("parents") == [parent]
            and original.get("name") == item["name"]
            and original.get("mimeType") == item["mime"]
            and original.get("size") == str(item["size"]),
            "Source changed before download")
    raw = api.media(item["id"])
    require(len(raw) == item["size"], "Media byte count mismatch")
    md5 = original.get("md5Checksum")
    if md5 is not None:
        require(hashlib.md5(raw).hexdigest() == md5, "Drive MD5 mismatch")
    suffix = Path(item["name"]).suffix.lower()
    if suffix in TEXT_MIME:
        decoded = raw.decode("utf-8-sig")
        require("\x00" not in decoded, "Binary data disguised as UTF-8")
    elif suffix in (".jpg", ".jpeg"):
        require(raw.startswith(bytes.fromhex("ffd8ff")) and
                raw.endswith(bytes.fromhex("ffd9")), "Invalid JPEG bytes")
    elif suffix == ".png":
        require(raw.startswith(bytes.fromhex("89504e470d0a1a0a")), "Invalid PNG")
    elif suffix == ".pdf":
        require(raw.startswith(b"%PDF-"), "Invalid PDF")
    elif suffix == ".webp":
        require(raw[:4] == b"RIFF" and raw[8:12] == b"WEBP",
                "Invalid WebP evidence")
    elif suffix in (".docx", ".xlsx"):
        require(raw.startswith(bytes.fromhex("504b0304")),
                "Invalid Office OpenXML original")
    second = metadata(api, item["id"])
    require(original == second, "Source modified during download")
    return raw, original


def write_exact(path, data):
    if path.exists():
        require(path.is_file() and not path.is_symlink()
                and stat.S_IMODE(path.stat().st_mode) == 0o600
                and path.stat().st_uid == 0
                and path.read_bytes() == data,
                "Previous staging conflict; refusing overwrite")
        return "already_verified"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as output:
        os.fchmod(output.fileno(), 0o600)
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    require(path.read_bytes() == data, "Local stage readback mismatch")
    return "written_and_verified"


def manifest_atomic(root, value):
    data = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    with tempfile.NamedTemporaryFile(dir=root, prefix=".manifest-", delete=False) as tmp:
        temp = Path(tmp.name)
        os.fchmod(tmp.fileno(), 0o600)
        tmp.write(data)
        tmp.flush()
        os.fsync(tmp.fileno())
    try:
        target = root / "source-manifest.json"
        if target.exists():
            previous = private_file(target)
            require(previous.get("schema") == SCHEMA, "Existing manifest invalid")
        os.replace(temp, target)
        fd = os.open(root, os.O_DIRECTORY | os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if temp.exists():
            temp.unlink()


def offline_validate():
    private_dir(STAGE)
    m = private_file(STAGE / "source-manifest.json")
    require(m.get("schema") == SCHEMA and isinstance(m.get("files"), list),
            "Stage manifest invalid")
    count = 0
    for item in m["files"]:
        require(set(item) >= {"owner", "name", "size", "sha256"}, "Manifest fields absent")
        owner, name = item["owner"], item["name"]
        require(NAME.fullmatch(owner) and owner.lower() not in DENIED
                and NAME.fullmatch(name), "Manifest unsafe path")
        p = STAGE / owner / name
        private_dir(p.parent)
        st = p.lstat()
        require(stat.S_ISREG(st.st_mode) and not p.is_symlink()
                and st.st_uid == 0 and stat.S_IMODE(st.st_mode) == 0o600,
                "Stage file attributes changed")
        raw = p.read_bytes()
        require(len(raw) == item["size"]
                and hashlib.sha256(raw).hexdigest() == item["sha256"],
                "Stage checksum mismatch")
        count += 1
    require(count == m.get("total_files"), "Manifest file count mismatch")
    return {"status": "offline_stage_verified", "files": count,
            "bytes": sum(x["size"] for x in m["files"]),
            "active_canonical_changed": False}


def capture(mode, selected, source_auth="device"):
    owners = source_config()
    require(selected and all(x in owners for x in selected)
            and len(selected) == len(set(selected)), "Select exact allowed owners")
    if source_auth == "service-account":
        from drive_source_ingest import _bearer
        api = Drive(_bearer(), max_file=REAL_FILE_LIMIT)
    else:
        api = Drive(fresh_reader(), max_file=REAL_FILE_LIMIT)
    is_stage = mode in ("stage", "stage-folder-sa")
    all_rows, total, report = [], 0, {}
    for owner in selected:
        fid = owners[owner]
        before = source_tree(api, owner, fid)
        eligible = [x for x in before if x["classification"] == "SUPPORTED_DIRECT_SOURCE"]
        blockers = [x for x in before if x["classification"] != "SUPPORTED_DIRECT_SOURCE"]
        report[owner] = {"supported_direct": len(eligible),
                         "unsupported_or_children": len(blockers),
                         "requires_review": len(blockers) > 0}
        if not is_stage:
            continue
        private_dir(STAGE, create=True)
        dest = STAGE / owner
        private_dir(dest, create=True)
        for item in eligible:
            require(len(all_rows) < LIMIT_FILES, "Batch file count exceeds cap")
            raw, attributes = checked_read(api, fid, item)
            total += len(raw)
            require(total <= LIMIT_TOTAL, "Batch too large; no live changes made")
            write_exact(dest / item["name"], raw)
            all_rows.append({"owner": owner, "name": item["name"],
                             "source_id": item["id"], "source_parent": fid,
                             "mime": item["mime"], "size": len(raw),
                             "sha256": hashlib.sha256(raw).hexdigest(),
                             "source_modified": attributes.get("modifiedTime")})
        after = source_tree(api, owner, fid)
        require(before == after, "Owner listing changed during capture")
    if is_stage:
        manifest_atomic(STAGE, {"schema": SCHEMA,
                        "status": "staged_not_active",
                        "created_utc": datetime.now(timezone.utc).isoformat(),
                        "total_files": len(all_rows), "files": all_rows,
                        "owners": report})
    return {"status": "staged_not_active" if is_stage else "read_only_inventory",
            "selected_owners": len(selected), "owners": report,
            "staged_files": len(all_rows), "staged_bytes": total,
            "active_canonical_changed": False, "backup_proven": False,
            "source_auth": source_auth}



def shared_file_pins(selected):
    """Exact authorized files, not Drive folder traversal or all-Drive OAuth."""
    owners = source_config()
    raw = private_file(CONFIG)
    pins = raw.get("pinned_files")
    require(isinstance(pins, list) and 1 <= len(pins) <= 80,
            "No controlled service-account file pins")
    seen = set()
    chosen = []
    for item in pins:
        require(isinstance(item, dict) and set(item) ==
                {"owner", "id", "name", "mime", "size", "sha256"},
                "Unexpected pin schema")
        owner = item["owner"]
        name = item["name"]
        fid = item["id"]
        sha = item["sha256"]
        size = item["size"]
        mime = item["mime"]
        suffix = Path(name).suffix.lower() if isinstance(name, str) else ""
        valid_mime = (mime in TEXT_MIME[suffix] if suffix in TEXT_MIME else
                      mime == BINARY_MIME[suffix] if suffix in BINARY_MIME else False)
        require(owner in owners and
                isinstance(name, str) and NAME.fullmatch(name) and
                name.lower() not in DENIED and
                isinstance(fid, str) and ID.fullmatch(fid) and
                isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha) and
                type(size) is int and 0 <= size <= REAL_FILE_LIMIT and
                valid_mime and
                (owner, name) not in seen and fid not in seen,
                "Unapproved, duplicate, or invalid real file pin")
        seen.add((owner, name))
        seen.add(fid)
        if owner in selected:
            chosen.append(item)
    require(chosen and all(any(x["owner"] == o for x in chosen) for o in selected),
            "Selected owner lacks individually authorized source pins")
    return chosen


def pinned_source_read(api, pin):
    """Read one file directly shared with the existing read-only service account."""
    import drive_source_ingest as sa
    fid = pin["id"]
    before = sa._meta(api, fid)
    # Google may omit parents when only a single file, not its folder,
    # is shared to the service account. Explicit pinned ID + SHA is authority.
    require(before.get("id") == fid and before.get("name") == pin["name"]
            and before.get("mimeType") == pin["mime"]
            and before.get("trashed") is False
            and before.get("size") == str(pin["size"]),
            "Shared source has different identity or metadata")
    raw = api.media(fid)
    require(len(raw) == pin["size"] and
            hashlib.sha256(raw).hexdigest() == pin["sha256"],
            "Shared source SHA256 mismatch")
    md5 = before.get("md5Checksum")
    if md5:
        require(hashlib.md5(raw).hexdigest() == md5, "Provider MD5 mismatch")
    suffix = Path(pin["name"]).suffix.lower()
    if suffix in TEXT_MIME:
        require("\x00" not in raw.decode("utf-8-sig"), "Non-text UTF-8 source")
    if suffix in (".jpg", ".jpeg"):
        require(raw.startswith(bytes.fromhex("ffd8ff")) and
                raw.endswith(bytes.fromhex("ffd9")), "Invalid JPEG source")
    if suffix == ".png":
        require(raw.startswith(bytes.fromhex("89504e470d0a1a0a")), "Invalid PNG")
    if suffix == ".pdf":
        require(raw.startswith(b"%PDF-"), "Invalid PDF")
    require(sa._meta(api, fid) == before, "Source modified during pinned read")
    return raw, before


def shared_capture(mode, selected):
    """No AI or Drive write; only an explicit, already-shared source allowlist."""
    from drive_source_ingest import _bearer
    owners = source_config()
    require(1 <= len(selected) <= len(owners) and
            len(selected) == len(set(selected)) and
            all(o in owners for o in selected), "Invalid selected owners")
    pins = shared_file_pins(selected)
    api = Drive(_bearer(), max_file=REAL_FILE_LIMIT)
    rows = []
    total = 0
    if mode == "stage-shared":
        private_dir(STAGE, create=True)
    for pin in pins:
        raw, attrs = pinned_source_read(api, pin)
        total += len(raw)
        require(total <= LIMIT_TOTAL and len(rows) < LIMIT_FILES,
                "Source batch exceeds bounds")
        if mode == "stage-shared":
            folder = STAGE / pin["owner"]
            private_dir(folder, create=True)
            write_exact(folder / pin["name"], raw)
        rows.append({"owner": pin["owner"], "name": pin["name"],
                     "source_id": pin["id"], "source_parent": owners[pin["owner"]],
                     "mime": pin["mime"], "size": len(raw),
                     "sha256": pin["sha256"],
                     "source_modified": attrs.get("modifiedTime")})
    if mode == "stage-shared":
        manifest_atomic(STAGE, {"schema": SCHEMA,
                        "status": "staged_not_active",
                        "created_utc": datetime.now(timezone.utc).isoformat(),
                        "total_files": len(rows), "files": rows,
                        "owners": {name: {"pinned_file_count": sum(
                            p["owner"] == name for p in rows)} for name in selected}})
    return {"status": ("staged_not_active" if mode == "stage-shared"
                       else "read_only_pinned_inventory"),
            "selected_owners": len(selected), "files": len(rows),
            "bytes": total, "source_auth": "individual_service_account_reader",
            "active_canonical_changed": False, "backup_proven": False}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("inventory", "stage", "inventory-shared", "stage-shared", "inventory-folder-sa", "stage-folder-sa", "verify-stage"))
    parser.add_argument("--owners", nargs="*", default=[])
    args = parser.parse_args()
    require(os.geteuid() == 0, "Root-only migrate")
    if args.mode == "verify-stage":
        result = offline_validate()
    elif args.mode in ("inventory-shared", "stage-shared"):
        result = shared_capture(args.mode, args.owners)
    elif args.mode in ("inventory-folder-sa", "stage-folder-sa"):
        result = capture(args.mode, args.owners, source_auth="service-account")
    else:
        result = capture(args.mode, args.owners)
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Never disclose private metadata, tokens, source titles, or file text.
        print('{"status":"blocked","reason":"Source permission, format, bounds, or verification failed","active_canonical_changed":false}')
        sys.exit(1)
