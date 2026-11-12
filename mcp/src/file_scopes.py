"""Root-owned, bounded project allowlist for five generic file MCP operations.

Workspace is synthetic-only. Existing credentials scopes are pinned snapshots.
A drive-live read-only scope may be configured after OAuth credential provisioning;
it fetches the original authorized Drive files on each read, without mirroring.
No Drive live scopes are enabled by default; no Drive writes are permitted.
"""
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from local_ro import validate_allow as validate_local_allow, open_root as open_local_root

MODE = os.environ.get("KEELARYN_MCP_MODE", "system")
if MODE not in ("system", "local") or (MODE == "local" and os.geteuid() == 0):
    raise ValueError("Invalid MCP operating mode")
CONFIG = Path(os.environ.get("KEELARYN_MCP_CONFIG", "/etc/keelarynos-mcp-benchmark/file-scopes.json"))
MAX_CONFIG = 32768
MAX_DOC = 65536
O_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
O_FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
FILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}\.(md|csv|json)$")
CRED_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")
SHA = re.compile(r"^[0-9a-f]{64}$")


def _read_bytes(fd, limit):
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > limit:
        raise ValueError("Unsafe file type, links or size")
    data = b""
    while len(data) <= limit:
        block = os.read(fd, min(limit + 1 - len(data), 65536))
        if not block:
            break
        data += block
    if len(data) != st.st_size or len(data) > limit:
        raise ValueError("Short or oversized file")
    return data


def load_scopes():
    if MODE == "local":
        # Anchor the registry to a private, non-symlinked parent directory.
        # A leaf-only O_NOFOLLOW would still follow symlinked ancestors.
        parent_fd = open_local_root({"root": str(CONFIG.parent)})
        try:
            fd = os.open(CONFIG.name, O_FILE, dir_fd=parent_fd)
        finally:
            os.close(parent_fd)
    else:
        fd = os.open(CONFIG, O_FILE)
    try:
        st = os.fstat(fd)
        expected_owner = os.geteuid() if MODE == "local" else 0
        forbidden_permissions = 0o077 if MODE == "local" else 0o022
        if st.st_uid != expected_owner or (st.st_mode & forbidden_permissions):
            raise ValueError("Registry has unsafe ownership or permissions")
        raw = _read_bytes(fd, MAX_CONFIG)
    finally:
        os.close(fd)
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict) or set(data) != {"schema", "scopes"} or data["schema"] != "keelarynos_mcp_file_scopes_v1":
        raise ValueError("Unsupported or malformed scope registry")
    scopes = data["scopes"]
    if not isinstance(scopes, dict) or not ((1 if MODE == "local" else 2) <= len(scopes) <= 20):
        raise ValueError("Invalid scope count")
    if scopes.get("synthetic") != {
        "backend": "workspace",
        "access": "read-write",
        "description": "Ephemeral synthetic-only benchmark files",
    }:
        raise ValueError("Synthetic scope must remain fixed")
    for project, info in scopes.items():
        if not IDENTIFIER.fullmatch(project) or not isinstance(info, dict):
            raise ValueError("Invalid scope name or entry")
        if project == "synthetic":
            continue
        if info.get("backend") == "local-ro":
            if MODE != "local" or set(info) != {"backend", "access", "snapshot_only", "canonical", "root", "allow"}:
                raise ValueError("Local scope requires unprivileged local mode and exact fields")
            if (info["access"] != "read-only" or info["snapshot_only"] is not False
                    or type(info["canonical"]) is not bool):
                raise ValueError("Local scopes must be explicitly read-only")
            validate_local_allow(info["allow"])
            fd = open_local_root(info)
            os.close(fd)
            continue
        if info.get("backend") == "drive-live":
            required = {"backend", "access", "snapshot_only", "canonical", "root_id", "credential", "allow"}
            if set(info) != required:
                raise ValueError("Invalid live Drive scope fields")
            if (info["access"], info["snapshot_only"], info["canonical"]) != ("read-only", False, True):
                raise ValueError("Live Drive scopes are read-only only")
            if not re.fullmatch(r"[A-Za-z0-9_-]{10,160}", info["root_id"]):
                raise ValueError("Invalid live Drive root ID")
            if not CRED_NAME.fullmatch(info["credential"]):
                raise ValueError("Invalid live Drive credential alias")
            allows = info["allow"]
            if not isinstance(allows, list) or not (1 <= len(allows) <= 40):
                raise ValueError("Drive scope requires a bounded positive allowlist")
            for item in allows:
                if not isinstance(item, str) or not (1 <= len(item) <= 400):
                    raise ValueError("Invalid Drive allowlist entry")
                parts = item.rstrip("/").split("/")
                if not (1 <= len(parts) <= 5) or any(
                    part in ("", ".", "..") or part.startswith(".") or
                    not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", part)
                    for part in parts
                ):
                    raise ValueError("Unsafe Drive allowlist entry")
                if not item.endswith("/") and not item.endswith((".md", ".csv", ".json")):
                    raise ValueError("Drive allowlist file must be Markdown, CSV or JSON")
            continue
        if set(info) != {"backend", "access", "snapshot_only", "canonical", "documents"}:
            raise ValueError("Invalid read-only scope fields")
        if (info["backend"], info["access"], info["snapshot_only"], info["canonical"]) != ("credentials", "read-only", True, False):
            raise ValueError("Only noncanonical read-only credentials scopes are supported")
        docs = info["documents"]
        if not isinstance(docs, dict) or not (1 <= len(docs) <= 20):
            raise ValueError("Invalid document inventory")
        for name, details in docs.items():
            if not isinstance(name, str) or not FILE_NAME.fullmatch(name) or not isinstance(details, dict):
                raise ValueError("Unsafe document name")
            if set(details) != {"credential", "sha256", "source_modified_utc", "source_url"}:
                raise ValueError("Invalid document fields")
            if not all(isinstance(v, str) for v in details.values()):
                raise ValueError("Invalid document metadata")
            if not CRED_NAME.fullmatch(details["credential"]) or not SHA.fullmatch(details["sha256"]):
                raise ValueError("Invalid credential alias or SHA-256")
            if not details["source_url"].startswith("https://drive.google.com/file/d/"):
                raise ValueError("Source metadata must identify a Drive file")
            if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+Z", details["source_modified_utc"]):
                raise ValueError("Invalid source modified date")
    return scopes


SCOPES = load_scopes()


def get_scope(project):
    if not isinstance(project, str) or project not in SCOPES:
        raise ValueError("Project scope is not allowed")
    return SCOPES[project]


def _read_credential(info):
    credential_dir = os.environ.get(
        "CREDENTIALS_DIRECTORY",
        "/run/credentials/keelarynos-mcp-benchmark.service",
    )
    directory_fd = os.open(credential_dir, O_DIRECTORY)
    try:
        fd = os.open(info["credential"], O_FILE, dir_fd=directory_fd)
        try:
            contents = _read_bytes(fd, MAX_DOC)
        finally:
            os.close(fd)
    finally:
        os.close(directory_fd)
    if hashlib.sha256(contents).hexdigest() != info["sha256"]:
        raise ValueError("Read-only snapshot SHA-256 mismatch")
    return contents


def read_snapshot(project, name):
    info = get_scope(project)
    if info["backend"] != "credentials":
        raise ValueError("Scope is not a credentials snapshot")
    if not isinstance(name, str) or name not in info["documents"]:
        raise ValueError("File not in project's read-only allowlist")
    d = info["documents"][name]
    return _read_credential(d), d


def list_snapshot(project, limit):
    info = get_scope(project)
    if info["backend"] != "credentials":
        raise ValueError("Scope is not a credentials snapshot")
    names = sorted(info["documents"])
    entries = []
    for name in names[:limit]:
        raw, _ = read_snapshot(project, name)
        entries.append({"path": name, "type": "file", "bytes": len(raw)})
    return {"project": project, "entries": entries, "returned": len(entries),
            "truncated": len(names) > len(entries), "root": "pinned-credential-snapshots",
            "snapshot_only": True, "canonical": False, "access": "read-only"}


def preflight():
    checks = 0
    for project, scope in SCOPES.items():
        if scope["backend"] == "local-ro":
            fd = open_local_root(scope)
            os.close(fd)
        if scope["backend"] == "credentials":
            for name in sorted(scope["documents"]):
                raw, meta = read_snapshot(project, name)
                if not raw or hashlib.sha256(raw).hexdigest() != meta["sha256"]:
                    raise ValueError("Snapshot preflight failed")
                checks += 1
    print("FILE_SCOPES_RO_PREFLIGHT_PASS documents=" + str(checks), flush=True)


if __name__ == "__main__":
    if sys.argv[1:] != ["--preflight"]:
        raise SystemExit("Only --preflight is supported")
    preflight()
