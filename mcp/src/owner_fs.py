"""G1 ONLY: opt-in, unprivileged, single-owner persistent filesystem mutations.

No service-account, real project, systemd or shared-root deployment is enabled.
Each request is one atomic file operation with a durable non-content intent and
receipt. After a crash, the same request ID and payload can reconcile; a
different request must not bypass an unresolved intent. Does not provide a
multi-file transaction or protection against another writer using the same UID.
"""
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat

from local_ro import open_root, _parts as local_parts, _read as local_read

MAX_BYTES = 65536
MAX_RECEIPTS = 128
HASH = re.compile(r"[0-9a-f]{64}\Z")
REQUEST_ID = re.compile(r"[0-9a-f]{32}\Z")
JOURNAL = ".keelaryn-g1"
LOCK = ".lock"
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _validate_path(path, scope):
    parts = local_parts(path)
    if len(parts) != 1 or path not in scope["allow"]:
        raise ValueError("Owner path must be an exact allowlisted filename")
    return path


def _validate(args, scope):
    if not isinstance(args, dict):
        raise ValueError("Mutation arguments must be an object")
    action = args.get("action")
    required = {"project", "request_id", "action", "path"}
    if action in ("create", "replace"):
        required |= {"content", "expected_sha256"}
    elif action == "rename":
        required |= {"new_path", "expected_sha256"}
    elif action == "delete":
        required |= {"expected_sha256"}
    else:
        raise ValueError("Unsupported owner mutation action")
    if set(args) != required or args["project"] != scope["owner"]:
        raise ValueError("Mutation fields or owner do not match")
    if type(args["request_id"]) is not str or not REQUEST_ID.fullmatch(args["request_id"]):
        raise ValueError("Invalid immutable request ID")
    path = _validate_path(args["path"], scope)
    if action == "rename" and _validate_path(args["new_path"], scope) == path:
        raise ValueError("Rename needs a different exact destination")
    expected = args.get("expected_sha256")
    if action == "create":
        if expected is not None:
            raise ValueError("Create must assert absent source")
    elif not isinstance(expected, str) or not HASH.fullmatch(expected):
        raise ValueError("SHA-256 compare-and-swap required")
    if action in ("create", "replace"):
        content = args["content"]
        if not isinstance(content, str) or "\x00" in content:
            raise ValueError("Content must be UTF-8 without NUL")
        raw = content.encode("utf-8")
        if len(raw) > MAX_BYTES:
            raise ValueError("Owner file exceeds 64 KiB")
        if path.endswith(".json"):
            json.loads(content)
        if path.endswith(".csv"):
            # CSV parsing is a domain-specific contract; here enforce UTF-8
            # and sane newlines, never silently rewrite columns.
            if "\r" in content and "\r\n" not in content:
                raise ValueError("Unsupported CSV line ending")
    else:
        raw = None
    fingerprint = digest(json.dumps(args, sort_keys=True,
                                   separators=(",", ":"), ensure_ascii=False)
                         .encode("utf-8"))
    return action, path, expected, raw, fingerprint


def _checked_file(root_fd, name):
    try:
        fd = os.open(name, FILE_FLAGS, dir_fd=root_fd)
    except FileNotFoundError:
        return None
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
                or before.st_nlink != 1 or before.st_mode & 0o077
                or before.st_size > MAX_BYTES):
            raise ValueError("Unsafe owner file type, links, owner, mode or size")
        data = b""
        while len(data) <= MAX_BYTES:
            piece = os.read(fd, MAX_BYTES + 1 - len(data))
            if not piece:
                break
            data += piece
        after = os.fstat(fd)
        if (len(data) != before.st_size or before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns
                or before.st_ino != after.st_ino or len(data) > MAX_BYTES):
            raise ValueError("Concurrent or oversized owner file")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("Owner file not UTF-8") from None
        return digest(data)
    finally:
        os.close(fd)


def _ensure_journal(root_fd):
    root = os.fstat(root_fd)
    if (root.st_uid != os.geteuid() or root.st_mode & 0o077
            or not stat.S_ISDIR(root.st_mode)):
        raise ValueError("Owner root must be private to effective UID")
    try:
        os.mkdir(JOURNAL, 0o700, dir_fd=root_fd)
        os.fsync(root_fd)
    except FileExistsError:
        pass
    fd = os.open(JOURNAL, DIR_FLAGS, dir_fd=root_fd)
    st = os.fstat(fd)
    if st.st_uid != os.geteuid() or st.st_mode & 0o077:
        os.close(fd)
        raise ValueError("Unsafe owner journal permissions")
    return fd


def _lock(jfd):
    fd = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o600, dir_fd=jfd)
    st = os.fstat(fd)
    if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid()
            or st.st_nlink != 1 or st.st_mode & 0o077):
        os.close(fd)
        raise ValueError("Unsafe owner lock")
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def _read_record(jfd, request_id):
    try:
        fd = os.open(request_id + ".json", FILE_FLAGS, dir_fd=jfd)
    except FileNotFoundError:
        return None
    try:
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1
                or st.st_uid != os.geteuid() or st.st_mode & 0o077
                or st.st_size > 4096):
            raise ValueError("Unsafe owner journal record")
        value = json.loads(os.read(fd, 4097))
        if (not isinstance(value, dict) or value.get("request_id") != request_id
                or value.get("status") not in ("intent", "committed")):
            raise ValueError("Invalid owner journal entry")
        return value
    finally:
        os.close(fd)


def _persist_record(jfd, record):
    data = json.dumps(record, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")
    if len(data) > 4096:
        raise ValueError("Owner journal record oversized")
    name = ".tmp-" + secrets.token_hex(16)
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=jfd)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(name, record["request_id"] + ".json",
                   src_dir_fd=jfd, dst_dir_fd=jfd)
        os.fsync(jfd)
    finally:
        try:
            os.unlink(name, dir_fd=jfd)
        except FileNotFoundError:
            pass


def _scan_journal(jfd, request_id):
    receipts = []
    with os.scandir(jfd) as entries:
        for entry in entries:
            name = entry.name
            if name == LOCK:
                continue
            if (not name.endswith(".json") or
                    not REQUEST_ID.fullmatch(name[:-5])):
                raise ValueError("Unresolved temporary or unknown owner journal entry")
            receipts.append(name[:-5])
            if len(receipts) > MAX_RECEIPTS:
                raise ValueError("Owner receipt bound exceeded; maintenance required")
    for other in receipts:
        if other != request_id and _read_record(jfd, other)["status"] == "intent":
            raise ValueError("Another owner request has unresolved intent")
    return receipts


def _state(root_fd, action, path, expected, new_sha, destination):
    current = _checked_file(root_fd, path)
    other = _checked_file(root_fd, destination) if destination else None
    if action in ("create", "replace"):
        if current == new_sha:
            return "after"
        if current == expected and (action == "replace" or expected is None):
            return "before"
    elif action == "delete":
        if current is None:
            return "after"
        if current == expected:
            return "before"
    elif action == "rename":
        if current is None and other == expected:
            return "after"
        if current == expected and other is None:
            return "before"
    raise ValueError("Owner state does not match intent; manual reconciliation required")


def _apply(root_fd, action, path, expected, raw, destination):
    if action in ("create", "replace"):
        name = ".g1-" + secrets.token_hex(16)
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=root_fd)
        try:
            with os.fdopen(fd, "wb") as out:
                out.write(raw)
                out.flush()
                os.fsync(out.fileno())
            if _checked_file(root_fd, path) != expected:
                raise ValueError("Owner SHA precondition changed")
            if action == "create":
                # Atomic create without replacing a different concurrent file.
                os.link(name, path, src_dir_fd=root_fd, dst_dir_fd=root_fd,
                        follow_symlinks=False)
            else:
                os.replace(name, path, src_dir_fd=root_fd, dst_dir_fd=root_fd)
            os.fsync(root_fd)
        finally:
            try:
                os.unlink(name, dir_fd=root_fd)
                os.fsync(root_fd)
            except FileNotFoundError:
                pass
    elif action == "rename":
        if (_checked_file(root_fd, path) != expected
                or _checked_file(root_fd, destination) is not None):
            raise ValueError("Rename precondition changed")
        os.rename(path, destination, src_dir_fd=root_fd, dst_dir_fd=root_fd)
        os.fsync(root_fd)
    elif action == "delete":
        if _checked_file(root_fd, path) != expected:
            raise ValueError("Delete precondition changed")
        os.unlink(path, dir_fd=root_fd)
        os.fsync(root_fd)


def mutate(args, scope):
    if (os.environ.get("KEELARYN_MCP_MODE") != "local"
            or os.environ.get("KEELARYN_MCP_ACCESS_MODE", "default") != "default"
            or os.environ.get("KEELARYN_MCP_OWNER_FS_TEST") != "1"
            or scope.get("backend") != "owner-fs"):
        raise ValueError("Owner mutation backend is development-only and disabled")
    action, path, expected, raw, fingerprint = _validate(args, scope)
    destination = args.get("new_path")
    new_sha = digest(raw) if raw is not None else (
        expected if action == "rename" else None)
    root_fd = open_root(scope)
    try:
        jfd = _ensure_journal(root_fd)
        try:
            lfd = _lock(jfd)
            try:
                _scan_journal(jfd, args["request_id"])
                record = _read_record(jfd, args["request_id"])
                if record is not None:
                    if record["fingerprint"] != fingerprint:
                        raise ValueError("Idempotency ID reused with different payload")
                    if record["status"] == "committed":
                        return {"status": "already_committed",
                                "request_id": args["request_id"],
                                "action": action, "path": path,
                                "new_path": destination, "sha256": record["new_sha256"],
                                "current_matches": _state_for_receipt(
                                    root_fd, action, path, record["new_sha256"], destination)}
                else:
                    record = {"request_id": args["request_id"], "status": "intent",
                              "fingerprint": fingerprint, "action": action,
                              "path": path, "new_path": destination,
                              "expected_sha256": expected, "new_sha256": new_sha}
                    # Before intent, validate source and destination.
                    if _state(root_fd, action, path, expected, new_sha, destination) != "before":
                        raise ValueError("Initial owner SHA precondition mismatch")
                    _persist_record(jfd, record)
                    if os.environ.get("KEELARYN_G1_TEST_CRASH_AFTER") == "intent":
                        os._exit(73)
                state = _state(root_fd, action, path, expected, new_sha, destination)
                if state == "before":
                    if raw is None and action in ("create", "replace"):
                        raise ValueError("Content required to retry pending write")
                    _apply(root_fd, action, path, expected, raw, destination)
                if _state(root_fd, action, path, expected, new_sha, destination) != "after":
                    raise ValueError("Owner write readback did not match")
                if os.environ.get("KEELARYN_G1_TEST_CRASH_AFTER") == "data":
                    os._exit(74)
                record["status"] = "committed"
                _persist_record(jfd, record)
                if os.environ.get("KEELARYN_G1_TEST_CRASH_AFTER") == "receipt":
                    os._exit(75)
                return {"status": "committed", "request_id": args["request_id"],
                        "action": action, "path": path, "new_path": destination,
                        "sha256": new_sha, "atomic_scope": "one-file",
                        "verified_readback": True}
            finally:
                fcntl.flock(lfd, fcntl.LOCK_UN)
                os.close(lfd)
        finally:
            os.close(jfd)
    finally:
        os.close(root_fd)


def _state_for_receipt(root_fd, action, path, new_sha, destination):
    # A committed receipt remains authoritative for request completion, even
    # when a *later* request legitimately modified the same path.
    try:
        if action == "delete":
            return _checked_file(root_fd, path) is None
        if action == "rename":
            return (_checked_file(root_fd, path) is None and
                    _checked_file(root_fd, destination) == new_sha)
        return _checked_file(root_fd, path) == new_sha
    except (ValueError, OSError):
        return False
