#!/usr/bin/env python3
"""Offline verification of a restored Keelaryn owner tree.

No Google, credentials, MCP server, network or write access is required.
A manifest is evidence of byte equality, NOT a backup, authenticity signature
or a writer-fence. Use with a quiescent copy, never as a live migration switch.

  python3 -B portable_verify.py manifest /absolute/staged-tree > marker.json
  python3 -B portable_verify.py verify /absolute/restored-tree marker.json
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

from owner_history import _valid_record as validate_committed_receipt

SCHEMA = "keelaryn-vps-project-tree-v1"  # Compatible with drive_tree_backup.py
VERSION = re.compile(r"tree-[0-9a-f]{24}\Z")
PROJECT = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
DOC = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}\.(md|csv|json)\Z")
RECEIPT = re.compile(r"[0-9a-f]{32}\.json\Z")
ARCHIVE = re.compile(r"history-[0-9]{6}\.json\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
MAX_FILES = 400
MAX_SINGLE = 2 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024
MAX_MARKER = 256 * 1024  # 400 long filename entries exceed 64 KiB
O_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
O_FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC


class InvalidTree(ValueError):
    pass


def require(value, message):
    if not value:
        raise InvalidTree(message)


def canonical_root(arg):
    root = Path(arg)
    require(root.is_absolute() and str(root) == os.path.normpath(str(root)),
            "Tree path must be absolute and normalized")
    # Prevent unexpected ancestor symlink traversal, including a symlink root.
    fd = os.open("/", O_DIR)
    try:
        for segment in root.parts[1:]:
            nxt = os.open(segment, O_DIR, dir_fd=fd)
            os.close(fd)
            fd = nxt
        require(stat.S_ISDIR(os.fstat(fd).st_mode) and
                not os.fstat(fd).st_mode & 0o077,
                "Tree root must be private")
        return fd
    except BaseException:
        os.close(fd)
        raise


def names(fd):
    return sorted(os.listdir(fd))


def read_file(dir_fd, name, owner_uid):
    fd = os.open(name, O_FILE, dir_fd=dir_fd)
    try:
        first = os.fstat(fd)
        require(stat.S_ISREG(first.st_mode) and first.st_nlink == 1
                and first.st_uid == owner_uid and not first.st_mode & 0o077
                and first.st_size <= MAX_SINGLE, "Unsafe file or oversized object")
        data = bytearray()
        while len(data) <= MAX_SINGLE:
            part = os.read(fd, min(65536, MAX_SINGLE + 1 - len(data)))
            if not part:
                break
            data.extend(part)
        last = os.fstat(fd)
        def stamp(st):
            return (st.st_dev, st.st_ino, st.st_size,
                    st.st_mtime_ns, st.st_ctime_ns)
        require(len(data) == first.st_size and stamp(first) == stamp(last),
                "File changed while verifying")
        return bytes(data)
    finally:
        os.close(fd)


def snapshot(root):
    root_fd = canonical_root(root)
    locks = []
    try:
        projects = names(root_fd)
        require(1 <= len(projects) <= 20
                and all(PROJECT.fullmatch(p) for p in projects),
                "Invalid owner directory inventory")
        owner_fds = []
        try:
            # Open all owner directories and take all available journal locks
            # before reading project bytes. A noncooperating writer is NOT fenced.
            for project in projects:
                pfd = os.open(project, O_DIR, dir_fd=root_fd)
                require(not os.fstat(pfd).st_mode & 0o077,
                        "Owner directory is not private")
                owner_fds.append((project, pfd))
                if ".keelaryn-g1" in names(pfd):
                    jfd = os.open(".keelaryn-g1", O_DIR, dir_fd=pfd)
                    try:
                        require(not os.fstat(jfd).st_mode & 0o077
                                and os.fstat(jfd).st_uid == os.fstat(pfd).st_uid,
                                "Journal directory has unsafe ownership or access")
                        require(".lock" in names(jfd), "Owner journal has no lock")
                        lock_fd = os.open(".lock", O_FILE, dir_fd=jfd)
                        try:
                            lock_info = os.fstat(lock_fd)
                            require(stat.S_ISREG(lock_info.st_mode)
                                    and lock_info.st_nlink == 1
                                    and lock_info.st_uid == os.fstat(pfd).st_uid
                                    and not lock_info.st_mode & 0o077
                                    and lock_info.st_size == 0,
                                    "Invalid owner journal lock")
                            try:
                                fcntl.flock(lock_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                            except BlockingIOError:
                                raise InvalidTree("Owner mutation is active") from None
                            locks.append(lock_fd)
                        except BaseException:
                            os.close(lock_fd)
                            raise
                    finally:
                        os.close(jfd)
            files = {}
            total = 0
            def add(key, data):
                nonlocal total
                require(len(files) < MAX_FILES and len(data) <= MAX_SINGLE,
                        "Tree exceeds file count/size limit")
                total += len(data)
                require(total <= MAX_TOTAL, "Tree exceeds total size limit")
                files[key] = {"bytes": len(data),
                              "sha256": hashlib.sha256(data).hexdigest()}
            for project, pfd in owner_fds:
                entries = names(pfd)
                documents = [x for x in entries if x != ".keelaryn-g1"]
                require(documents and all(DOC.fullmatch(x) for x in documents),
                        "Unexpected owner filename")
                for filename in documents:
                    add(project + "/" + filename,
                        read_file(pfd, filename, os.fstat(pfd).st_uid))
                if ".keelaryn-g1" in entries:
                    jfd = os.open(".keelaryn-g1", O_DIR, dir_fd=pfd)
                    try:
                        jnames = names(jfd)
                        require(".lock" in jnames and all(
                            x == ".lock" or RECEIPT.fullmatch(x)
                            or ARCHIVE.fullmatch(x) for x in jnames),
                            "Unexpected journal filename")
                        archives = [x for x in jnames if ARCHIVE.fullmatch(x)]
                        require(archives == [f"history-{i:06d}.json"
                                             for i in range(1, len(archives) + 1)],
                                "Journal history segments are not consecutive")
                        seen = {}
                        for name in jnames:
                            data = read_file(jfd, name, os.fstat(pfd).st_uid)
                            if name == ".lock":
                                require(data == b"", "Invalid journal lock contents")
                            else:
                                try:
                                    obj = json.loads(data)
                                except (ValueError, UnicodeError):
                                    raise InvalidTree("Unparseable G1 journal entry") from None
                                if ARCHIVE.fullmatch(name):
                                    require(isinstance(obj, dict)
                                            and set(obj) == {"schema", "receipts"}
                                            and obj["schema"] == "keelaryn-g1-history-v1"
                                            and isinstance(obj["receipts"], dict)
                                            and obj["receipts"],
                                            "Invalid archived receipt collection")
                                    require(len(data) <= 1024 * 1024,
                                            "Oversized G1 archive segment")
                                    records = obj["receipts"]
                                else:
                                    records = {name[:-5]: obj}
                                for req, value in records.items():
                                    try:
                                        validate_committed_receipt(req, value)
                                    except ValueError:
                                        raise InvalidTree(
                                            "Unresolved or invalid committed G1 receipt") from None
                                    require(req not in seen or seen[req] == value,
                                            "Conflicting active/archived G1 receipt")
                                    seen[req] = value
                            add(project + "/.keelaryn-g1/" + name, data)
                    finally:
                        os.close(jfd)
            return {"schema": SCHEMA, "files": dict(sorted(files.items()))}
        finally:
            for _, pfd in owner_fds:
                os.close(pfd)
    finally:
        for fd in locks:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        os.close(root_fd)


def identity(manifest):
    raw = (json.dumps(manifest, sort_keys=True,
                      separators=(",", ":")) + "\n").encode()
    return "tree-" + hashlib.sha256(raw).hexdigest()[:24]


def parse_marker(path):
    fd = os.open(path, O_FILE)
    try:
        require(os.fstat(fd).st_size <= MAX_MARKER, "Oversized marker")
        raw = os.read(fd, MAX_MARKER + 1)
        require(len(raw) <= MAX_MARKER, "Oversized marker")
    finally:
        os.close(fd)
    marker = json.loads(raw)
    require(isinstance(marker, dict)
            and set(marker) == {"schema", "files", "version"}
            and marker.get("schema") == SCHEMA
            and isinstance(marker.get("files"), dict)
            and VERSION.fullmatch(str(marker.get("version"))),
            "Invalid tree completion marker")
    files = marker["files"]
    require(1 <= len(files) <= MAX_FILES, "Invalid marker file count")
    for path, entry in files.items():
        parts = path.split("/")
        require(len(parts) in (2, 3) and PROJECT.fullmatch(parts[0])
                and ((len(parts) == 2 and DOC.fullmatch(parts[1]))
                     or (len(parts) == 3 and parts[1] == ".keelaryn-g1"
                         and (parts[2] == ".lock" or RECEIPT.fullmatch(parts[2])
                              or ARCHIVE.fullmatch(parts[2]))))
                and isinstance(entry, dict)
                and set(entry) == {"bytes", "sha256"}
                and type(entry["bytes"]) is int
                and 0 <= entry["bytes"] <= MAX_SINGLE
                and isinstance(entry["sha256"], str)
                and HASH.fullmatch(entry["sha256"]),
                "Invalid marker file path or digest")
    require(marker["version"] == identity({"schema": SCHEMA, "files": files}),
            "Completion marker identity mismatch")
    return marker


def main(argv):
    if len(argv) == 2 and argv[0] == "manifest":
        manifest = snapshot(argv[1])
        print(json.dumps(dict(manifest, version=identity(manifest)),
                         sort_keys=True, ensure_ascii=False))
        return
    if len(argv) == 3 and argv[0] == "verify":
        marker = parse_marker(argv[2])
        current = snapshot(argv[1])
        require(current == {k: marker[k] for k in ("schema", "files")},
                "Restored tree differs from completion marker")
        print(json.dumps({"status": "verified_bytes",
                          "version": marker["version"],
                          "files": len(current["files"]),
                          "bytes": sum(x["bytes"] for x in current["files"].values())},
                         sort_keys=True))
        return
    raise InvalidTree("Usage: portable_verify.py manifest ABS_TREE | verify ABS_TREE MARKER")


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except (InvalidTree, OSError, ValueError, TypeError, UnicodeError) as exc:
        print("PORTABLE_VERIFY_FAILED: " + str(exc)[:150], file=sys.stderr)
        raise SystemExit(1)
