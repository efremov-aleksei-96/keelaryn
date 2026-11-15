"""Bounded large owner documents: UTF-8 chunk reads and small CAS deltas.

Separate opt-in from the legacy 64-KiB G1 API. Existing production owners are
unaffected until a specifically allowlisted scope and feature flag are enabled.
No external service, subprocess, Google Drive, or AI is used for operations.
"""
import hashlib
import json
import os
import re
import stat
import secrets
import fcntl
from local_ro import open_root, _parts
import owner_fs as g1

MAX_DOCUMENT = 2 * 1024 * 1024
MAX_CHUNK = 12 * 1024
MAX_DELTA = 12 * 1024
MAX_MATCH = 12 * 1024
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
WRITE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC


def _allow_owner(scope, *, writing):
    if scope.get("backend") != "owner-fs":
        raise ValueError("Large document operations require owner-fs")
    owner = scope.get("owner")
    if not isinstance(owner, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", owner):
        raise ValueError("Invalid owner")
    mode = os.environ.get("KEELARYN_MCP_MODE", "system")
    state = os.path.realpath(os.environ.get(
        "KEELARYN_MCP_STATE_DIR", "/var/lib/keelarynos-mcp-benchmark"))
    flag = os.environ.get("KEELARYN_MCP_LARGE_OWNER_PILOT") == "1"
    if not flag:
        raise ValueError("Large owner feature not enabled")
    if mode == "local":
        authorized = (
            os.geteuid() != 0
            and os.environ.get("KEELARYN_MCP_OWNER_FS_TEST") == "1"
            and os.environ.get("KEELARYN_MCP_ACCESS_MODE", "default") == "default")
    else:
        generic = (
            os.environ.get("KEELARYN_MCP_ACCESS_MODE") == "read-only"
            and os.environ.get("KEELARYN_MCP_MULTI_CANONICAL") == "1"
            and owner not in (
                "MusicLibrary", "KeelarynEnginePilot", "KeelarynFullPilot", "synthetic")
            and scope.get("canonical") is True
            and scope.get("snapshot_only") is False
            and scope.get("root") == state + "/" + owner.lower())
        fullpilot = (
            os.environ.get("KEELARYN_MCP_ACCESS_MODE") == "read-only"
            and os.environ.get("KEELARYN_MCP_FULL_PILOT") == "1"
            and owner == "KeelarynFullPilot"
            and scope.get("root") == state + "/full-pilot"
            and scope.get("allow") == [
                "PROJECT.md", "STATE.md", "MASTERY.csv", "JOURNAL.md"]
            and scope.get("canonical") is False
            and scope.get("snapshot_only") is False)
        authorized = generic or fullpilot
    if not authorized or scope.get("access") != "read-write":
        raise ValueError("Large owner scope not authorized")
    return owner


def _allowed_path(path, scope):
    parts = _parts(path)
    if len(parts) != 1 or path not in scope.get("allow", ()):
        raise ValueError("Large document is not exactly allowlisted")
    return path


def _read_all(dirfd, path):
    fd = os.open(path, READ_FLAGS, dir_fd=dirfd)
    try:
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid()
                or st.st_nlink != 1 or st.st_mode & 0o077
                or not 0 <= st.st_size <= MAX_DOCUMENT):
            raise ValueError("Unsafe, nonprivate or oversized owner document")
        chunks, total = [], 0
        while True:
            part = os.read(fd, 65536)
            if not part:
                break
            total += len(part)
            if total > MAX_DOCUMENT:
                raise ValueError("Owner document exceeds 2 MiB")
            chunks.append(part)
        after = os.fstat(fd)
        stable = (
            st.st_size == total
            and (st.st_dev, st.st_ino, st.st_mtime_ns, st.st_ctime_ns,
                 st.st_mode, st.st_uid, st.st_nlink) ==
            (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_ctime_ns,
             after.st_mode, after.st_uid, after.st_nlink))
        if not stable:
            raise ValueError("Owner document changed during read")
        blob = b"".join(chunks)
        try:
            blob.decode("utf-8")
        except UnicodeError:
            raise ValueError("Owner document is not valid UTF-8") from None
        return blob
    finally:
        os.close(fd)


def _read_info(dirfd, path):
    data = _read_all(dirfd, path)
    return data, hashlib.sha256(data).hexdigest()


def read_chunk(scope, args):
    _allow_owner(scope, writing=False)
    if not isinstance(args, dict) or set(args) - {"project", "path", "offset_bytes", "max_bytes", "expected_sha256"}:
        raise ValueError("Unsupported chunk read arguments")
    if args.get("project") != scope["owner"]:
        raise ValueError("Owner mismatch")
    path = _allowed_path(args.get("path"), scope)
    offset = args.get("offset_bytes", 0)
    limit = args.get("max_bytes", MAX_CHUNK)
    expected = args.get("expected_sha256")
    if type(offset) is not int or offset < 0 or offset > MAX_DOCUMENT:
        raise ValueError("Invalid byte offset")
    if type(limit) is not int or not (1 <= limit <= MAX_CHUNK):
        raise ValueError("Invalid chunk budget")
    if expected is not None and (type(expected) is not str or not g1.HASH.fullmatch(expected)):
        raise ValueError("Invalid SHA-256")
    fd = open_root(scope)
    try:
        raw, sha = _read_info(fd, path)
        if expected is not None and sha != expected:
            raise ValueError("Document version changed; resume from current SHA")
        if offset > len(raw):
            raise ValueError("Offset beyond EOF")
        block = raw[offset:offset+limit]
        try:
            # The caller controls a byte offset, but the budget may cut an
            # Armenian (or any other) multibyte UTF-8 character. Move the
            # trailing boundary backward, never skipping bytes or splitting
            # a character across responses.
            try:
                content = block.decode("utf-8")
            except UnicodeDecodeError as e:
                if e.reason != "unexpected end of data" or e.start == 0:
                    raise
                block = block[:e.start]
                content = block.decode("utf-8")
            if not block and offset < len(raw):
                raise ValueError("Chunk budget too small for next UTF-8 codepoint")
        except UnicodeDecodeError:
            raise ValueError("Offset is not a UTF-8 boundary") from None
        return {"path": path, "sha256": sha, "total_bytes": len(raw),
                "offset_bytes": offset, "returned_bytes": len(block),
                "next_offset_bytes": offset + len(block),
                "eof": offset + len(block) == len(raw),
                "content": content, "canonical": scope["canonical"],
                "source": "owner-fs"}
    finally:
        os.close(fd)


def _prepare(args, scope):
    if not isinstance(args, dict):
        raise ValueError("Delta request must be an object")
    act = args.get("action")
    required = {"project", "request_id", "action", "path", "expected_sha256"}
    if act == "append":
        required.add("content")
    elif act == "replace_once":
        required |= {"old_text", "new_text"}
    else:
        raise ValueError("Unsupported bounded delta")
    if set(args) != required or args["project"] != scope["owner"]:
        raise ValueError("Delta request fields do not match owner")
    request_id = args["request_id"]
    old_hash = args["expected_sha256"]
    if (type(request_id) is not str or not g1.REQUEST_ID.fullmatch(request_id)
            or type(old_hash) is not str or not g1.HASH.fullmatch(old_hash)):
        raise ValueError("Immutable ID and exact SHA-256 are required")
    path = _allowed_path(args["path"], scope)
    if act == "append":
        content = args["content"]
        if type(content) is not str or "\x00" in content:
            raise ValueError("Invalid append content")
        delta = content.encode("utf-8")
        if not 1 <= len(delta) <= MAX_DELTA:
            raise ValueError("Append content outside bounded budget")
        if path.endswith(".json"):
            raise ValueError("JSON cannot be blindly appended")
    else:
        old = args["old_text"]
        new = args["new_text"]
        if (type(old) is not str or type(new) is not str
                or "\x00" in old or "\x00" in new):
            raise ValueError("Invalid replacement text")
        if not (1 <= len(old.encode("utf-8")) <= MAX_MATCH
                and len(new.encode("utf-8")) <= MAX_DELTA):
            raise ValueError("Replacement outside bounded budget")
    fingerprint = hashlib.sha256(json.dumps(
        args, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    return act, path, old_hash, fingerprint


def _transform(old, args, action, path):
    if action == "append":
        new = old + args["content"].encode("utf-8")
    else:
        needle = args["old_text"].encode("utf-8")
        if old.count(needle) != 1:
            raise ValueError("Exact replacement text must occur once")
        new = old.replace(needle, args["new_text"].encode("utf-8"), 1)
    if len(new) > MAX_DOCUMENT:
        raise ValueError("New owner document exceeds 2 MiB")
    new.decode("utf-8")
    if path.endswith(".json"):
        json.loads(new)
    if path.endswith(".csv") and b"\r" in new and b"\r\n" not in new:
        raise ValueError("Unrecognized CSV line endings")
    return new


def _atomic_replace(dirfd, path, old_sha, new):
    name = ".g1-" + secrets.token_hex(16)
    fd = os.open(name, WRITE_FLAGS, 0o600, dir_fd=dirfd)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(new)
            stream.flush()
            os.fsync(stream.fileno())
        _, current = _read_info(dirfd, path)
        if current != old_sha:
            raise ValueError("Owner SHA precondition changed")
        os.replace(name, path, src_dir_fd=dirfd, dst_dir_fd=dirfd)
        os.fsync(dirfd)
    finally:
        try:
            os.unlink(name, dir_fd=dirfd)
        except FileNotFoundError:
            pass


def edit_delta(scope, args):
    _allow_owner(scope, writing=True)
    action, path, old_sha, fingerprint = _prepare(args, scope)
    rootfd = open_root(scope)
    try:
        journal = g1._ensure_journal(rootfd)
        try:
            lockfd = g1._lock(journal)
            try:
                use_history = g1._history_enabled(scope)
                g1._scan_journal(journal, args["request_id"], use_history)
                prior = g1._read_record(journal, args["request_id"], use_history)
                current_data, current_sha = _read_info(rootfd, path)
                if prior is not None:
                    if prior.get("fingerprint") != fingerprint or prior.get("action") != action:
                        raise ValueError("Idempotency ID reused with different payload")
                    if prior["status"] == "committed":
                        return {"status": "already_committed",
                                "path": path, "sha256": prior["new_sha256"],
                                "current_matches": current_sha == prior["new_sha256"]}
                    new_sha = prior["new_sha256"]
                    if current_sha not in (old_sha, new_sha):
                        raise ValueError("Pending write requires manual reconciliation")
                else:
                    if current_sha != old_sha:
                        raise ValueError("Initial large owner SHA precondition mismatch")
                    new_data = _transform(current_data, args, action, path)
                    new_sha = hashlib.sha256(new_data).hexdigest()
                    prior = {"request_id": args["request_id"],
                             "status": "intent", "fingerprint": fingerprint,
                             "action": action, "path": path,
                             "new_path": None, "expected_sha256": old_sha,
                             "new_sha256": new_sha}
                    g1._persist_record(journal, prior)
                    if os.environ.get("KEELARYN_LARGE_TEST_CRASH_AFTER") == "intent":
                        os._exit(81)
                if current_sha == old_sha and current_sha != new_sha:
                    new_data = _transform(current_data, args, action, path)
                    if hashlib.sha256(new_data).hexdigest() != new_sha:
                        raise ValueError("Retry contents do not match intent")
                    _atomic_replace(rootfd, path, old_sha, new_data)
                if _read_info(rootfd, path)[1] != new_sha:
                    raise ValueError("Large owner write did not persist")
                if os.environ.get("KEELARYN_LARGE_TEST_CRASH_AFTER") == "data":
                    os._exit(82)
                prior["status"] = "committed"
                g1._persist_record(journal, prior)
                if os.environ.get("KEELARYN_LARGE_TEST_CRASH_AFTER") == "receipt":
                    os._exit(83)
                return {"status": "committed", "path": path, "sha256": new_sha,
                        "atomic_scope": "one-file", "verified_readback": True}
            finally:
                fcntl.flock(lockfd, fcntl.LOCK_UN)
                os.close(lockfd)
        finally:
            os.close(journal)
    finally:
        os.close(rootfd)
