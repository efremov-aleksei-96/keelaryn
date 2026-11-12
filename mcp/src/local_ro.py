"""Allowlisted read-only local filesystem MCP backend (Linux).

Local mode reads user-owned roots; system mode supports root-owned roots only
when explicit read-only access is enabled. Every path remains allowlisted.
Directory FDs and O_NOFOLLOW prevent traversal and symlink resolution.
"""
import hashlib
import os
import re
import stat

SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
SENSITIVE = re.compile(r"secret|credential|token|password|passwd|private.?key|\.env|\.git", re.I)
EXTENSIONS = (".md", ".csv", ".json")
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | getattr(os, "O_NONBLOCK", 0)
MAX_FILE = 65536
# Never use the changing DynamicUser UID as the owner of system-mode sources.
# The system service may read only root-owned source trees, and only when the
# already-enforced server-wide read-only mode is explicitly enabled.
DATA_OWNER = (0 if os.environ.get("KEELARYN_MCP_MODE") == "system"
              and os.environ.get("KEELARYN_MCP_ACCESS_MODE") == "read-only"
              else os.geteuid())
MAX_TOTAL = 262144
MAX_ENTRIES = 1000
MAX_SEARCH_FILES = 100
MAX_SEARCH_DIRECTORIES = 100
MAX_SEARCH_ENTRIES = 1000


def _parts(value, directory=False):
    if not isinstance(value, str) or len(value) > 320:
        raise ValueError("Invalid relative path")
    if value == "" and directory:
        return []
    parts = value.split("/")
    if (not 1 <= len(parts) <= 4 or any(
        not SEGMENT.fullmatch(p) or p.startswith(".") or SENSITIVE.search(p) for p in parts
    )):
        raise ValueError("Unsafe relative path")
    if not directory and not parts[-1].endswith(EXTENSIONS):
        raise ValueError("Only Markdown, CSV and JSON documents are supported")
    return parts


def validate_allow(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 40 or len(value) != len(set(map(str, value))):
        raise ValueError("Invalid or duplicate local allowlist")
    for entry in value:
        if not isinstance(entry, str):
            raise ValueError("Invalid local allowlist entry")
        directory = entry.endswith("/")
        parts = _parts(entry[:-1] if directory else entry, directory=directory)
        if not parts:
            raise ValueError("Root-wide allowance is prohibited")


def _check_directory(fd, is_root=False):
    s = os.fstat(fd)
    if not stat.S_ISDIR(s.st_mode):
        raise ValueError("Not a directory")
    if is_root and (s.st_uid != DATA_OWNER or s.st_mode & 0o022):
        raise ValueError("Local root ownership or permissions are unsafe")
    if not is_root:
        safe_owner = s.st_uid in (0, os.geteuid())
        safe_perms = not (s.st_mode & 0o022)
        # /tmp-like root-owned sticky ancestors are permitted; not data roots.
        sticky = s.st_uid == 0 and bool(s.st_mode & stat.S_ISVTX)
        if not safe_owner or not (safe_perms or sticky):
            raise ValueError("Unsafe local root ancestor")


def open_root(scope):
    root = scope["root"]
    if (not isinstance(root, str) or not 1 < len(root) <= 1024
            or not root.startswith("/") or os.path.normpath(root) != root
            or "\x00" in root):
        raise ValueError("Local root must be an absolute canonical path")
    components = root[1:].split("/")
    if any(p in ("", ".", "..") for p in components):
        raise ValueError("Invalid root component")
    fd = os.open("/", DIR_FLAGS)
    try:
        for part in components:
            _check_directory(fd)
            nxt = os.open(part, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = nxt
        _check_directory(fd, is_root=True)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _open_child_directory(parent_fd, name):
    """Open a direct child by descriptor; never follow a replaced symlink."""
    fd = os.open(name, DIR_FLAGS, dir_fd=parent_fd)
    try:
        s = os.fstat(fd)
        if not stat.S_ISDIR(s.st_mode) or s.st_uid != DATA_OWNER or s.st_mode & 0o022:
            raise ValueError("Unsafe project subdirectory")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _open_dir(scope, parts, root_fd=None):
    """Keep a caller-pinned root when traversing multiple paths."""
    fd = open_root(scope) if root_fd is None else os.dup(root_fd)
    try:
        for part in parts:
            nxt = _open_child_directory(fd, part)
            os.close(fd)
            fd = nxt
        return fd
    except BaseException:
        os.close(fd)
        raise


def _is_allowed(scope, path, directory=False):
    for item in scope["allow"]:
        if item.endswith("/"):
            prefix = item[:-1]
            if path == prefix and directory:
                return True
            if path.startswith(item):
                return True
            if directory and prefix.startswith(path + "/"):
                return True
        elif path == item and not directory:
            return True
        elif directory and item.startswith(path + "/"):
            return True
    return directory and path == ""


def _read(fd, name):
    opened = os.open(name, FILE_FLAGS, dir_fd=fd)
    try:
        before = os.fstat(opened)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != DATA_OWNER or before.st_mode & 0o022
                or before.st_size > MAX_FILE):
            raise ValueError("Unsafe document ownership, type or size")
        data = b""
        while len(data) <= MAX_FILE:
            chunk = os.read(opened, min(MAX_FILE + 1 - len(data), 65536))
            if not chunk:
                break
            data += chunk
        after = os.fstat(opened)
        if (len(data) != before.st_size or len(data) > MAX_FILE
                or before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns
                or before.st_ctime_ns != after.st_ctime_ns or before.st_mode != after.st_mode
                or before.st_uid != after.st_uid or before.st_nlink != after.st_nlink):
            raise ValueError("Unstable or oversized document")
        return data
    finally:
        os.close(opened)


def _directory_entries(fd):
    entries = []
    with os.scandir(fd) as iterator:
        for entry in iterator:
            if len(entries) >= MAX_ENTRIES:
                raise ValueError("Directory exceeds safe listing bound")
            entries.append(entry.name)
    return sorted(entries)


def _list(scope, path, limit):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be 1..100")
    parts = _parts(path, directory=True)
    if not _is_allowed(scope, path, directory=True):
        raise ValueError("Directory is not allowlisted")
    fd = _open_dir(scope, parts)
    try:
        visible = []
        for name in _directory_entries(fd):
            try:
                full = "/".join(parts + [name])
                _parts(full, directory=True)
                s = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISDIR(s.st_mode) and _is_allowed(scope, full, directory=True):
                    if s.st_uid == DATA_OWNER and not s.st_mode & 0o022:
                        visible.append({"path": full, "type": "directory", "bytes": None})
                elif stat.S_ISREG(s.st_mode) and _is_allowed(scope, full):
                    _parts(full)
                    if s.st_uid == DATA_OWNER and s.st_nlink == 1 and not s.st_mode & 0o022 and s.st_size <= MAX_FILE:
                        visible.append({"path": full, "type": "file", "bytes": s.st_size})
            except (ValueError, OSError):
                continue
        return {"entries": visible[:limit], "returned": min(len(visible), limit),
                "truncated": len(visible) > limit, "root": "configured-local-readonly",
                "source": "local-ro", "canonical": scope["canonical"], "access": "read-only"}
    finally:
        os.close(fd)


def _read_files(scope, paths):
    if (not isinstance(paths, list) or not 1 <= len(paths) <= 20
            or len(paths) != len(set(map(str, paths)))):
        raise ValueError("Invalid read paths")
    result = []
    total = 0
    root_fd = open_root(scope)
    try:
        for path in paths:
            parts = _parts(path)
            if not _is_allowed(scope, path):
                raise ValueError("Document is not allowlisted")
            fd = _open_dir(scope, parts[:-1], root_fd=root_fd)
            try:
                raw = _read(fd, parts[-1])
            finally:
                os.close(fd)
            total += len(raw)
            if total > MAX_TOTAL:
                raise ValueError("Read batch exceeds 256 KiB")
            result.append({"path": path, "sha256": hashlib.sha256(raw).hexdigest(),
                           "content": raw.decode("utf-8"), "source": "local-ro",
                           "canonical": scope["canonical"]})
    finally:
        os.close(root_fd)
    return {"files": result, "count": len(result), "bytes": total,
            "source": "local-ro", "canonical": scope["canonical"]}


def _search(scope, query, limit):
    if not isinstance(query, str) or not 1 <= len(query) <= 80 or "\x00" in query:
        raise ValueError("Invalid query")
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("Invalid search limit")
    hits = []
    scanned = 0
    truncated = False
    visited_directories = 0
    visited_entries = 0
    needle = query.casefold()

    def walk(fd, parts):
        nonlocal scanned, truncated, visited_directories, visited_entries
        if visited_directories >= MAX_SEARCH_DIRECTORIES:
            truncated = True
            return
        visited_directories += 1
        for name in _directory_entries(fd):
            if truncated:
                return
            if visited_entries >= MAX_SEARCH_ENTRIES:
                truncated = True
                return
            visited_entries += 1
            full = "/".join(parts + [name])
            try:
                _parts(full, directory=True)
                s = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISDIR(s.st_mode) and len(parts) < 3 and _is_allowed(scope, full, directory=True):
                    if s.st_uid == DATA_OWNER and not s.st_mode & 0o022:
                        child = _open_child_directory(fd, name)
                        try:
                            walk(child, parts + [name])
                        finally:
                            os.close(child)
                elif stat.S_ISREG(s.st_mode) and _is_allowed(scope, full):
                    _parts(full)
                    if scanned >= MAX_SEARCH_FILES:
                        truncated = True
                        return
                    raw = _read(fd, name)
                    scanned += 1
                    for n, line in enumerate(raw.decode("utf-8").splitlines(), 1):
                        if needle in line.casefold():
                            hits.append({"path": full, "line": n, "snippet": line[:256]})
                            if len(hits) >= limit:
                                truncated = True
                                return
            except (ValueError, OSError, UnicodeError):
                continue

    root_fd = open_root(scope)
    try:
        walk(root_fd, [])
    finally:
        os.close(root_fd)
    return {"matches": hits, "scanned": scanned, "truncated": truncated,
            "visited_directories": visited_directories, "visited_entries": visited_entries,
            "source": "local-ro", "canonical": scope["canonical"]}


def operate(name, args, scope):
    if name in ("edit_files", "delete_files"):
        raise ValueError("Local project is read-only: edits and deletes are forbidden")
    if name == "list_files":
        return _list(scope, args.get("path", ""), args.get("limit", 100))
    if name == "read_files":
        return _read_files(scope, args.get("paths"))
    if name == "search_files":
        return _search(scope, args.get("query"), args.get("limit", 20))
    raise ValueError("Unsupported local file operation")
