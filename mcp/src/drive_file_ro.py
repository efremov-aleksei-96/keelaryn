"""Default-off, exact-one-file Google Drive read-only backend.

The registry pins one Drive file ID, name and owner. No files.list, folder
traversal, cache, Google Drive writes or implicit access to neighboring files.
A separately approved Viewer-only service account must be granted the file;
OAuth drive.readonly scope is broad *within that principal's actual ACL*.

No credentials or private source documents belong in GitHub. The service
account JSON is read only from systemd CREDENTIALS_DIRECTORY. This backend
requires cryptography for RS256; it is imported only when the scope is used.
"""
import base64
import hashlib
import json
import os
import re
import stat
import time
import urllib.parse

from drive_live import _http as _google_http

TOKEN_URI = "https://oauth2.googleapis.com/token"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
ID_RE = re.compile(r"[A-Za-z0-9_-]{10,160}\Z")
ALIAS_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,99}\Z")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\Z")
MIMES = {".md": {"text/markdown", "text/plain", "application/octet-stream"},
         ".csv": {"text/csv", "text/plain", "application/octet-stream"},
         ".json": {"application/json", "text/plain", "application/octet-stream"}}
MAX_FILE_BYTES = 65536
MAX_CREDENTIAL_BYTES = 16384
METADATA_FIELDS = ("id,name,mimeType,size,version,trashed,shared,ownedByMe,"
                   "owners(emailAddress),capabilities(canEdit)")


def _base64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _credentials(alias):
    if not isinstance(alias, str) or not ALIAS_RE.fullmatch(alias):
        raise ValueError("Invalid service credential alias")
    directory = os.environ.get(
        "CREDENTIALS_DIRECTORY", "/run/credentials/keelarynos-mcp-benchmark.service")
    d = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        f = os.open(alias, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=d)
        try:
            st = os.fstat(f)
            if (not stat.S_ISREG(st.st_mode) or st.st_size < 1
                    or st.st_size > MAX_CREDENTIAL_BYTES or st.st_mode & 0o077):
                raise ValueError("Unsafe service account credential file")
            raw = os.read(f, MAX_CREDENTIAL_BYTES + 1)
        finally:
            os.close(f)
    finally:
        os.close(d)
    if len(raw) > MAX_CREDENTIAL_BYTES:
        raise ValueError("Oversized service account credential")
    try:
        data = json.loads(raw)
    except (UnicodeError, ValueError):
        raise ValueError("Invalid service account credential JSON") from None
    required = {"type", "client_email", "private_key", "private_key_id", "token_uri"}
    if not isinstance(data, dict) or not required <= set(data):
        raise ValueError("Missing service account credential fields")
    if (data["type"] != "service_account" or data["token_uri"] != TOKEN_URI
            or not isinstance(data["client_email"], str)
            or not EMAIL_RE.fullmatch(data["client_email"])
            or not data["client_email"].endswith(".gserviceaccount.com")
            or not isinstance(data["private_key_id"], str)
            or not re.fullmatch("[A-Za-z0-9]{10,100}", data["private_key_id"])
            or not isinstance(data["private_key"], str)
            or not data["private_key"].startswith("-----BEGIN PRIVATE KEY-----")):
        raise ValueError("Invalid service account credential type")
    # Explicit impersonation is not supported; this must be a standalone SA.
    if any(x in data for x in ("subject", "sub", "delegated_user", "impersonated_user")):
        raise ValueError("Impersonation is not permitted")
    return data


def _access_token(scope):
    credential = _credentials(scope["credential"])
    # Use maintained crypto primitives. No custom RSA implementation.
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
        key = serialization.load_pem_private_key(
            credential["private_key"].encode("ascii"), password=None)
        if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
            raise ValueError("Invalid service account RSA key")
    except (ImportError, TypeError, ValueError):
        raise ValueError("Service account signing unavailable") from None
    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT", "kid": credential["private_key_id"]}
    payload = {"iss": credential["client_email"], "scope": DRIVE_SCOPE,
               "aud": TOKEN_URI, "iat": now, "exp": now + 1800}
    base = ".".join(_base64url(json.dumps(item, separators=(",", ":")).encode())
                    for item in (header, payload))
    signature = key.sign(base.encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    assertion = base + "." + _base64url(signature)
    form = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": assertion,
    }).encode("ascii")
    response = json.loads(_google_http(
        TOKEN_URI, data=form, content_type="application/x-www-form-urlencoded",
        limit=4096))
    token = response.get("access_token")
    if (not isinstance(token, str) or not 15 <= len(token) <= 4096
            or response.get("token_type", "").lower() != "bearer"
            or type(response.get("expires_in")) is not int
            or not 1 <= response["expires_in"] <= 3600):
        raise ValueError("Service account access token unavailable")
    return token


def _metadata(scope, token):
    file_id = scope["file_id"]
    if not ID_RE.fullmatch(file_id):
        raise ValueError("Invalid pinned Drive file ID")
    query = urllib.parse.urlencode(
        {"fields": METADATA_FIELDS, "supportsAllDrives": "true"})
    raw = _google_http(
        "https://www.googleapis.com/drive/v3/files/" + file_id + "?" + query,
        token=token, limit=8192)
    try:
        item = json.loads(raw)
    except ValueError:
        raise ValueError("Invalid Drive metadata response") from None
    if not isinstance(item, dict) or item.get("id") != file_id:
        raise ValueError("Drive object ID mismatch")
    if (item.get("name") != scope["filename"] or item.get("trashed") is not False
            or item.get("shared") is not True
            or item.get("ownedByMe") is not False
            or not isinstance(item.get("capabilities"), dict)
            or item["capabilities"].get("canEdit") is not False):
        raise ValueError("Pinned Drive file ownership or access changed")
    owners = item.get("owners")
    if (not isinstance(owners, list) or len(owners) != 1
            or not isinstance(owners[0], dict)
            or owners[0].get("emailAddress") != scope["owner_email"]):
        raise ValueError("Pinned Drive owner changed")
    ext = next((x for x in MIMES if scope["filename"].endswith(x)), None)
    if ext is None or item.get("mimeType") not in MIMES[ext]:
        raise ValueError("Unsupported pinned Drive MIME type")
    size = item.get("size")
    if not isinstance(size, str) or not size.isdecimal():
        raise ValueError("Drive size unavailable")
    size = int(size)
    if not 0 <= size <= MAX_FILE_BYTES:
        raise ValueError("Pinned Drive file exceeds size bound")
    version = item.get("version")
    if not isinstance(version, str) or not version.isdecimal() or int(version) < 1:
        raise ValueError("Drive file version unavailable")
    return size, version


def _read(scope, token):
    size, version = _metadata(scope, token)
    data = _google_http(
        "https://www.googleapis.com/drive/v3/files/" + scope["file_id"] +
        "?alt=media", token=token, limit=MAX_FILE_BYTES)
    if len(data) != size:
        raise ValueError("Pinned Drive file content changed")
    new_size, new_version = _metadata(scope, token)
    if (size, version) != (new_size, new_version):
        raise ValueError("Pinned Drive file changed during read")
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("Pinned Drive file is not UTF-8") from None
    return {"path": scope["filename"], "content": content,
            "sha256": hashlib.sha256(data).hexdigest(), "version": version,
            "size_bytes": size, "source": "drive-file-ro",
            "canonical": True, "snapshot_only": False}


def operate(name, args, scope):
    # Enforce independently even if called directly with old cached names.
    if name not in ("list_files", "read_files", "search_files"):
        raise ValueError("Drive file scope forbids write operations")
    filename = scope["filename"]
    if name == "list_files":
        if args.get("path", "") != "":
            raise ValueError("Pinned Drive file is not a directory")
        limit = args.get("limit", 100)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Invalid listing limit")
        token = _access_token(scope)
        size, _ = _metadata(scope, token)
        return {"project": args.get("project"),
                "entries": [{"path": filename, "type": "file", "bytes": size}],
                "returned": 1, "truncated": False, "root": "single-drive-file",
                "source": "drive-file-ro", "access": "read-only",
                "canonical": True, "snapshot_only": False}
    if name == "read_files":
        if args.get("paths") != [filename]:
            raise ValueError("Only the one pinned Drive file can be read")
        off = args.get("offset_chars", 0)
        cap = args.get("max_chars", 16000)
        if (type(off) is not int or not 0 <= off <= MAX_FILE_BYTES
                or type(cap) is not int or not 1 <= cap <= 16384):
            raise ValueError("Invalid Drive read paging")
        doc = _read(scope, _access_token(scope))
        content = doc["content"]
        doc.update(content=content[off:off + cap], offset_chars=off,
                   next_offset_chars=min(len(content), off + cap),
                   total_chars=len(content), end_of_file=off + cap >= len(content))
        return {"project": args.get("project"), "files": [doc], "count": 1,
                "source": "drive-file-ro", "canonical": True,
                "snapshot_only": False}
    query = args.get("query")
    limit = args.get("limit", 20)
    if (not isinstance(query, str) or not 1 <= len(query) <= 80
            or "\x00" in query or type(limit) is not int or not 1 <= limit <= 20):
        raise ValueError("Invalid Drive search request")
    doc = _read(scope, _access_token(scope))
    hits = []
    for line_no, line in enumerate(doc["content"].splitlines(), 1):
        if query.casefold() in line.casefold():
            hits.append({"path": filename, "line": line_no,
                         "snippet": line[:256], "version": doc["version"]})
            if len(hits) >= limit:
                break
    return {"matches": hits, "scanned": 1, "truncated": len(hits) >= limit,
            "source": "drive-file-ro", "canonical": True}
