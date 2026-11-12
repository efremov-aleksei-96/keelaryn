"""File-only MCP operations confined to a dedicated synthetic workspace.

No caller-supplied absolute paths, command execution, symlink traversal,
directory creation, removal, or writes outside the fixed workspace.
"""
import hashlib
import os
import re
import secrets
import stat
from pathlib import Path
from file_scopes import SCOPES, get_scope, read_snapshot, list_snapshot
from drive_live import operate as live_drive_operation

FS_ROOT = Path(os.environ.get("KEELARYN_MCP_STATE_DIR", "/var/lib/keelarynos-mcp-benchmark")) / "workspace"
TYPES = (".md", ".csv", ".json")
VALID_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
VALID_SHA = re.compile(r"^[0-9a-f]{64}$")
MAX_FILE = 65536
MAX_BATCH = 10
MAX_TOTAL = 262144
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC


def _parts(raw, directory=False):
    if not isinstance(raw, str) or len(raw) > 320:
        raise ValueError("Invalid relative path")
    if raw == "" and directory:
        return []
    names = raw.split("/")
    if len(names) > 4 or not names or any(
        part in (".", "..") or not VALID_SEGMENT.fullmatch(part)
        for part in names
    ):
        raise ValueError("Invalid relative path (no absolute paths or traversal)")
    if not directory and not names[-1].endswith(TYPES):
        raise ValueError("Only .md, .csv, or .json files are permitted")
    return names


def _open_dir(parts):
    fd = os.open(FS_ROOT, DIR_FLAGS)
    try:
        for part in parts:
            nxt = os.open(part, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read_file(fd, name):
    f = os.open(name, FILE_FLAGS, dir_fd=fd)
    try:
        st = os.fstat(f)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            raise ValueError("Only ordinary single-link files are permitted")
        if st.st_size > MAX_FILE:
            raise ValueError("File exceeds 64 KiB")
        chunks = []
        remaining = MAX_FILE + 1
        while remaining:
            block = os.read(f, min(remaining, 65536))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        raw = b"".join(chunks)
        if len(raw) > MAX_FILE or len(raw) != st.st_size:
            raise ValueError("File was oversized or changed during read")
        return raw
    finally:
        os.close(f)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def list_files(args):
    path = args.get("path", "")
    parts = _parts(path, directory=True)
    limit = args.get("limit", 100)
    if not isinstance(limit, int) or isinstance(limit, bool) or not (1 <= limit <= 100):
        raise ValueError("limit must be 1 to 100")
    fd = _open_dir(parts)
    try:
        entries = []
        names = sorted(os.listdir(fd))
        for name in names:
            if not VALID_SEGMENT.fullmatch(name):
                continue
            st = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISDIR(st.st_mode) and len(parts) < 4:
                kind = "directory"
            elif stat.S_ISREG(st.st_mode) and name.endswith(TYPES) and st.st_nlink == 1:
                kind = "file"
            else:
                continue
            entries.append({"path": "/".join(parts + [name]), "type": kind,
                            "bytes": st.st_size if kind == "file" else None})
            if len(entries) >= limit:
                break
        return {"entries": entries, "returned": len(entries),
                "truncated": len(names) > len(entries), "root": "isolated-workspace"}
    finally:
        os.close(fd)


def read_files(args):
    paths = args.get("paths")
    if not isinstance(paths, list) or not (1 <= len(paths) <= 20):
        raise ValueError("paths must contain 1 to 20 paths")
    if len(set(map(str, paths))) != len(paths):
        raise ValueError("Duplicate paths are not allowed")
    output, total = [], 0
    for path in paths:
        parts = _parts(path)
        fd = _open_dir(parts[:-1])
        try:
            raw = _read_file(fd, parts[-1])
        finally:
            os.close(fd)
        total += len(raw)
        if total > 262144:
            raise ValueError("Read batch exceeds 256 KiB")
        output.append({"path": path, "sha256": _sha(raw), "content": raw.decode("utf-8")})
    return {"files": output, "count": len(output), "bytes": total}


def search_files(args):
    query = args.get("query")
    limit = args.get("limit", 20)
    if not isinstance(query, str) or not 1 <= len(query) <= 80 or "\x00" in query:
        raise ValueError("query must be 1 to 80 characters")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
        raise ValueError("limit must be 1 to 20")
    matches, scanned, truncated = [], 0, False
    needle = query.casefold()

    def walk(parts):
        nonlocal scanned, truncated
        fd = _open_dir(parts)
        try:
            for name in sorted(os.listdir(fd)):
                if scanned >= 200 or len(matches) >= limit:
                    truncated = True
                    return
                if not VALID_SEGMENT.fullmatch(name):
                    continue
                st = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISDIR(st.st_mode) and len(parts) < 3:
                    walk(parts + [name])
                elif stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and name.endswith(TYPES):
                    scanned += 1
                    if st.st_size > MAX_FILE:
                        continue
                    try:
                        text = _read_file(fd, name).decode("utf-8")
                    except (UnicodeError, ValueError, OSError):
                        continue
                    for line_number, line in enumerate(text.splitlines(), 1):
                        if needle in line.casefold():
                            matches.append({"path": "/".join(parts + [name]),
                                            "line": line_number, "snippet": line[:256]})
                            if len(matches) >= limit:
                                truncated = True
                                return
        finally:
            os.close(fd)

    walk([])
    return {"matches": matches, "scanned": scanned, "truncated": truncated}


def edit_files(args):
    edits = args.get("edits")
    if not isinstance(edits, list) or not (1 <= len(edits) <= MAX_BATCH):
        raise ValueError("edits must contain 1 to 10 entries")
    checked, total, paths = [], 0, set()
    try:
        for edit in edits:
            if not isinstance(edit, dict) or set(edit) != {"path", "content", "expected_sha256"}:
                raise ValueError("Each edit needs path, content and expected_sha256")
            path = edit["path"]
            parts = _parts(path)
            if path in paths:
                raise ValueError("Duplicate edit path")
            paths.add(path)
            content = edit["content"]
            expected = edit["expected_sha256"]
            if not isinstance(content, str):
                raise ValueError("content must be UTF-8 text")
            raw = content.encode("utf-8")
            total += len(raw)
            if len(raw) > MAX_FILE or total > MAX_TOTAL:
                raise ValueError("Edit payload exceeds size limit")
            if expected is not None and (not isinstance(expected, str) or not VALID_SHA.fullmatch(expected)):
                raise ValueError("expected_sha256 must be lowercase SHA-256 or null")
            fd = _open_dir(parts[:-1])
            try:
                try:
                    before = _read_file(fd, parts[-1])
                except FileNotFoundError:
                    if expected is not None:
                        raise ValueError("Target absent; refusing replacement")
                    before = None
                if before is None and expected is not None:
                    raise ValueError("Creation requires expected_sha256=null")
                if before is not None and expected is None:
                    raise ValueError("Existing file; refusing create without SHA-256")
                if before is not None and _sha(before) != expected:
                    raise ValueError("SHA-256 precondition mismatch")
                checked.append((fd, path, parts[-1], raw, expected))
            except BaseException:
                os.close(fd)
                raise
        results = []
        for fd, path, name, raw, expected in checked:
            # A second precondition check catches changes during preflight.
            try:
                current = _read_file(fd, name)
            except FileNotFoundError:
                current = None
            if (current is None) != (expected is None):
                raise ValueError("File changed while preparing edit")
            if current is not None and _sha(current) != expected:
                raise ValueError("SHA-256 precondition changed")
            # Publish fully-written content atomically. Never overwrite on create.
            temp = "." + name + "." + secrets.token_hex(12) + ".tmp"
            newfd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                            0o600, dir_fd=fd)
            try:
                with os.fdopen(newfd, "wb") as out:
                    out.write(raw)
                    out.flush()
                    os.fsync(out.fileno())
                if current is None:
                    os.link(temp, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
                else:
                    os.replace(temp, name, src_dir_fd=fd, dst_dir_fd=fd)
            finally:
                try:
                    os.unlink(temp, dir_fd=fd)
                except FileNotFoundError:
                    pass
            os.fsync(fd)
            confirmed = _read_file(fd, name)
            if confirmed != raw:
                raise ValueError("Readback mismatch after edit")
            results.append({"path": path,
                            "sha256": _sha(confirmed), "bytes": len(confirmed),
                            "action": "created" if expected is None else "replaced"})
        return {"files": results, "count": len(results), "bytes": total,
                "atomic_scope": "per-file; not a multi-file transaction"}
    finally:
        for fd, _, _, _, _ in checked:
            os.close(fd)


def delete_files(args):
    """Delete only explicit workspace files matching the caller's SHA-256."""
    entries = args.get("files")
    if not isinstance(entries, list) or not (1 <= len(entries) <= MAX_BATCH):
        raise ValueError("files must contain 1 to 10 entries")
    checked, names = [], set()
    try:
        for item in entries:
            if not isinstance(item, dict) or set(item) != {"path", "expected_sha256"}:
                raise ValueError("Each file needs path and expected_sha256")
            path = item["path"]
            parts = _parts(path)
            expected = item["expected_sha256"]
            if path in names:
                raise ValueError("Duplicate deletion path")
            names.add(path)
            if not isinstance(expected, str) or not VALID_SHA.fullmatch(expected):
                raise ValueError("Deletion requires lowercase SHA-256")
            fd = _open_dir(parts[:-1])
            try:
                content = _read_file(fd, parts[-1])
                if _sha(content) != expected:
                    raise ValueError("SHA-256 precondition mismatch")
                checked.append((fd, path, parts[-1], expected))
            except BaseException:
                os.close(fd)
                raise
        removed = []
        for fd, path, name, expected in checked:
            content = _read_file(fd, name)
            if _sha(content) != expected:
                raise ValueError("SHA-256 precondition changed")
            os.unlink(name, dir_fd=fd)
            os.fsync(fd)
            try:
                os.stat(name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise ValueError("Deletion verification failed")
            removed.append({"path": path, "sha256": expected})
        return {"removed": removed, "count": len(removed),
                "atomic_scope": "per-file; no multi-file transaction"}
    finally:
        for fd, _, _, _ in checked:
            os.close(fd)


FILE_TOOLS = [
    {"name": "list_files", "description": "List files in a permitted project scope. Project-scoped synthetic files, historical snapshots or configured live Drive read-only files.",
     "inputSchema": {"type": "object", "properties": {"project": {"type": "string", "minLength": 1, "maxLength": 64, "default": "synthetic", "description": "Project name from server-side allowlist; omitted selects synthetic workspace"}, 
         "path": {"type": "string", "description": "Relative directory path; blank for root", "default": ""},
         "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 100}},
         "additionalProperties": False}},
    {"name": "read_files", "description": "Read UTF-8 documents in a permitted project scope, with SHA-256. Existing snapshots are noncanonical; configured live Drive scopes read the source directly.",
     "inputSchema": {"type": "object", "properties": {"project": {"type": "string", "minLength": 1, "maxLength": 64, "default": "synthetic", "description": "Project name from server-side allowlist; omitted selects synthetic workspace"}, "paths": {
         "type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 20},
         "offset_chars": {"type": "integer", "minimum": 0, "default": 0,
                          "description": "Character offset for paged UTF-8 text reads"},
         "max_chars": {"type": "integer", "minimum": 1, "maximum": 16384,
                       "default": 16000, "description": "Maximum characters returned per file"}},
         "required": ["paths"], "additionalProperties": False}},
    {"name": "search_files", "description": "Search text in a permitted project scope; Search within an authorized project scope only.",
     "inputSchema": {"type": "object", "properties": {"project": {"type": "string", "minLength": 1, "maxLength": 64, "default": "synthetic", "description": "Project name from server-side allowlist; omitted selects synthetic workspace"}, 
         "query": {"type": "string", "minLength": 1, "maxLength": 80},
         "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 20}},
         "required": ["query"], "additionalProperties": False}},
    {"name": "delete_files", "description": "Delete synthetic workspace files only, requiring exact current SHA-256. Always denied for snapshot and live Drive scopes.",
     "inputSchema": {"type": "object", "properties": {"project": {"type": "string", "minLength": 1, "maxLength": 64, "default": "synthetic", "description": "Project name from server-side allowlist; omitted selects synthetic workspace"}, 
         "files": {"type": "array", "minItems": 1, "maxItems": 10,
           "items": {"type": "object", "properties": {
             "path": {"type": "string"},
             "expected_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}},
             "required": ["path", "expected_sha256"], "additionalProperties": False}}},
         "required": ["files"], "additionalProperties": False}},
    {"name": "edit_files", "description": "Create or atomically replace synthetic workspace files only, with SHA-256 preconditions. Always denied for snapshot and live Drive scopes.",
     "inputSchema": {"type": "object", "properties": {"project": {"type": "string", "minLength": 1, "maxLength": 64, "default": "synthetic", "description": "Project name from server-side allowlist; omitted selects synthetic workspace"}, 
         "edits": {"type": "array", "minItems": 1, "maxItems": 10,
          "items": {"type": "object", "properties": {
            "path": {"type": "string"},
            "content": {"type": "string", "maxLength": 65536},
            "expected_sha256": {"type": ["string", "null"]}},
            "required": ["path", "content", "expected_sha256"],
            "additionalProperties": False}}},
         "required": ["edits"], "additionalProperties": False}}
]
FILE_HANDLERS = {
    "list_files": list_files,
    "read_files": read_files,
    "search_files": search_files,
    "edit_files": edit_files,
    "delete_files": delete_files,
}

def _snapshot_operation(name, args, project):
    """Read-only credential backend; never resolves a caller path on the VPS."""
    if name in ("edit_files", "delete_files"):
        raise ValueError("Read-only project scope: writes and deletes are forbidden")
    if name == "list_files":
        path = args.get("path", "")
        limit = args.get("limit", 100)
        if path != "":
            raise ValueError("Snapshot project has no subdirectories")
        if not isinstance(limit, int) or isinstance(limit, bool) or not (1 <= limit <= 100):
            raise ValueError("limit must be 1 to 100")
        return list_snapshot(project, limit)
    if name == "read_files":
        paths = args.get("paths")
        if not isinstance(paths, list) or not 1 <= len(paths) <= 20:
            raise ValueError("paths must contain 1 to 20 paths")
        if len(set(map(str, paths))) != len(paths):
            raise ValueError("Duplicate paths are not allowed")
        result, total = [], 0
        for path in paths:
            if not isinstance(path, str):
                raise ValueError("Invalid filename")
            # No absolute paths, subdirectories, traversal or arbitrary assets.
            parts = _parts(path)
            if len(parts) != 1:
                raise ValueError("Snapshot file must be a single allowed filename")
            raw, meta = read_snapshot(project, path)
            total += len(raw)
            if total > MAX_TOTAL:
                raise ValueError("Read batch exceeds 256 KiB")
            result.append({"path": path, "sha256": _sha(raw),
                           "content": raw.decode("utf-8"),
                           "source_url": meta["source_url"],
                           "source_modified_utc": meta["source_modified_utc"],
                           "snapshot_only": True, "canonical": False})
        return {"project": project, "files": result, "count": len(result),
                "bytes": total, "snapshot_only": True, "canonical": False}
    if name == "search_files":
        query = args.get("query")
        limit = args.get("limit", 20)
        if not isinstance(query, str) or not 1 <= len(query) <= 80 or "\x00" in query:
            raise ValueError("query must be 1 to 80 characters")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
            raise ValueError("limit must be 1 to 20")
        needle = query.casefold()
        hits, scanned, truncated = [], 0, False
        for path in sorted(SCOPES[project]["documents"]):
            raw, _ = read_snapshot(project, path)
            scanned += 1
            for line_no, line in enumerate(raw.decode("utf-8").splitlines(), 1):
                if needle in line.casefold():
                    hits.append({"path": path, "line": line_no, "snippet": line[:256]})
                    if len(hits) >= limit:
                        truncated = True
                        break
            if truncated:
                break
        return {"project": project, "matches": hits, "scanned": scanned,
                "truncated": truncated, "snapshot_only": True, "canonical": False}
    raise ValueError("Unsupported operation")


def _route_file_tool(name, args):
    if not isinstance(args, dict):
        raise ValueError("Tool arguments must be an object")
    allowed = {
        "list_files": {"path", "limit"},
        "read_files": {"paths", "offset_chars", "max_chars"},
        "search_files": {"query", "limit"},
        "edit_files": {"edits"},
        "delete_files": {"files"},
    }[name] | {"project"}
    if not set(args) <= allowed:
        raise ValueError("Unsupported arguments")
    project = args.get("project", "synthetic")
    scope = get_scope(project)
    if scope["backend"] == "drive-live":
        return live_drive_operation(name, args, scope)
    if scope["backend"] == "workspace":
        result = FILE_HANDLERS[name]({k: v for k, v in args.items() if k != "project"})
    elif scope["backend"] == "credentials":
        result = _snapshot_operation(name, args, project)
    else:
        raise ValueError("Unknown project backend")
    if name == "read_files" and ("offset_chars" in args or "max_chars" in args):
        off, cap = args.get("offset_chars", 0), args.get("max_chars", 16000)
        if type(off) is not int or not 0 <= off <= 4 * 1024 * 1024 or type(cap) is not int or not 1 <= cap <= 16384:
            raise ValueError("Invalid read offset or length")
        for item in result["files"]:
            full = item["content"]
            item["content"] = full[off:off + cap]
            item["offset_chars"] = off
            item["next_offset_chars"] = min(len(full), off + cap)
            item["total_chars"] = len(full)
            item["end_of_file"] = off + cap >= len(full)
    return result



def file_tool(name, args):
    try:
        value = _route_file_tool(name, args)
        import json
        return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}]}
    except (ValueError, OSError, UnicodeError) as e:
        return {"isError": True, "content": [
            {"type": "text", "text": type(e).__name__ + ": " + str(e)[:180]}]}
