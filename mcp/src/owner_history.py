"""Bounded crash-safe history of completed MCP owner request receipts.

Receipt rotation is intentionally fail-closed, not unbounded. Never erase
historical request IDs: compact complete immutable receipt *values* into an
atomically updated segment, then delete only its identical active duplicates.
Each segment is bounded and itself included in the offsite tree backup.
"""
import hashlib
import json
import os
import re
import secrets
import stat

ARCHIVE = re.compile(r"history-([0-9]{6})\.json\Z")
ID = re.compile(r"[0-9a-f]{32}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
SCHEMA = "keelaryn-g1-history-v1"
MAX_SEGMENTS = 24
MAX_SEG_BYTES = 1024 * 1024
BATCH = 64
MAX_ACTIVE = 128
O_RDONLY = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC


def _files(jfd):
    names = sorted(x.name for x in os.scandir(jfd) if ARCHIVE.fullmatch(x.name))
    if len(names) > MAX_SEGMENTS:
        raise ValueError("Owner history segment limit reached")
    if names != [f"history-{i:06d}.json" for i in range(1, len(names) + 1)]:
        raise ValueError("Missing or nonsequential owner history segment")
    return names


def _valid_record(req, record):
    if (not ID.fullmatch(req) or not isinstance(record, dict)
            or record.get("request_id") != req
            or record.get("status") != "committed"
            or record.get("action") not in ("create", "replace", "rename", "delete",
                                             "append", "replace_once")
            or not isinstance(record.get("fingerprint"), str)
            or not SHA.fullmatch(record["fingerprint"])
            or not isinstance(record.get("new_sha256"), str)
            or not SHA.fullmatch(record["new_sha256"])
            or (record.get("expected_sha256") is not None
                and (not isinstance(record["expected_sha256"], str)
                     or not SHA.fullmatch(record["expected_sha256"])))):
        raise ValueError("Invalid committed owner-history receipt")


def _load_one(jfd, name):
    fd = os.open(name, O_RDONLY, dir_fd=jfd)
    try:
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid()
                or st.st_nlink != 1 or st.st_mode & 0o077
                or not 1 <= st.st_size <= MAX_SEG_BYTES):
            raise ValueError("Unsafe or oversized history segment")
        data = bytearray()
        while len(data) <= MAX_SEG_BYTES:
            b = os.read(fd, min(65536, MAX_SEG_BYTES + 1 - len(data)))
            if not b:
                break
            data.extend(b)
        if len(data) != st.st_size or len(data) > MAX_SEG_BYTES:
            raise ValueError("Invalid history segment size")
    finally:
        os.close(fd)
    try:
        obj = json.loads(data)
    except (ValueError, UnicodeError):
        raise ValueError("Corrupt owner-history segment") from None
    if (not isinstance(obj, dict) or set(obj) != {"schema", "receipts"}
            or obj["schema"] != SCHEMA or not isinstance(obj["receipts"], dict)
            or not obj["receipts"]):
        raise ValueError("Invalid owner-history schema")
    for req, item in obj["receipts"].items():
        _valid_record(req, item)
    return obj["receipts"]


def load(jfd):
    """Full verified request-id index; invalid/missing history blocks writes."""
    names = _files(jfd)
    index = {}
    for name in names:
        items = _load_one(jfd, name)
        if not index.keys().isdisjoint(items):
            raise ValueError("Duplicate historical request ID between segments")
        index.update(items)
    return index, names


def _write(jfd, name, records):
    raw = json.dumps({"schema": SCHEMA, "receipts": records},
                     sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if not 0 < len(raw) <= MAX_SEG_BYTES:
        raise ValueError("Owner history segment capacity exceeded")
    tmp = ".tmp-history-" + secrets.token_hex(16)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=jfd)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, name, src_dir_fd=jfd, dst_dir_fd=jfd)
        os.fsync(jfd)
    finally:
        try:
            os.unlink(tmp, dir_fd=jfd)
        except FileNotFoundError:
            pass


def reconcile_and_rotate(jfd, active, request_id):
    """Call only with the existing exclusive G1 .lock held.

    First repairs any interrupted cleanup after a fully persisted archive.
    A published history always wins over *identical* unlinked active receipts.
    In a crash before archive publication active receipts remain the source.
    """
    history, names = load(jfd)
    for req in sorted(set(active) & set(history)):
        if active[req] != history[req]:
            raise ValueError("Active receipt contradicts archived history")
        if active[req]["status"] != "committed":
            raise ValueError("Archived request is not committed in active journal")
    for req in sorted(set(active) & set(history)):
        os.unlink(req + ".json", dir_fd=jfd)
        del active[req]
    if set(active) & set(history):
        raise ValueError("Failed to reconcile active historical receipt")
    os.fsync(jfd)
    if len(active) < MAX_ACTIVE:
        return
    if len(active) > MAX_ACTIVE:
        raise ValueError("Owner active receipt limit exceeded")
    completed = [req for req in sorted(active)
                 if active[req]["status"] == "committed"]
    if len(completed) < BATCH:
        raise ValueError("Cannot compact unresolved owner request")
    selected = {req: active[req] for req in completed[:BATCH]}
    for req, item in selected.items():
        _valid_record(req, item)
    if names:
        last = names[-1]
        current = _load_one(jfd, last)
        candidate = dict(current)
        candidate.update(selected)
        size = len(json.dumps({"schema": SCHEMA, "receipts": candidate},
                              sort_keys=True, separators=(",", ":"),
                              ensure_ascii=False).encode("utf-8"))
        if size <= MAX_SEG_BYTES:
            target = last
            merged = candidate
        else:
            if len(names) >= MAX_SEGMENTS:
                raise ValueError("Owner historical capacity reached; fail closed")
            target = f"history-{len(names)+1:06d}.json"
            merged = selected
    else:
        target, merged = "history-000001.json", selected
    _write(jfd, target, merged)
    if os.environ.get("KEELARYN_HISTORY_TEST_CRASH_AFTER") == "publish":
        os._exit(91)
    for i, req in enumerate(selected):
        os.unlink(req + ".json", dir_fd=jfd)
        if i == 0 and os.environ.get("KEELARYN_HISTORY_TEST_CRASH_AFTER") == "first_unlink":
            os.fsync(jfd)
            os._exit(92)
    os.fsync(jfd)
