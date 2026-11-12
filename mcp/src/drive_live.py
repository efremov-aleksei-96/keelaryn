"""Live Google Drive read-only backend for scoped raw files.

Live authority remains the original Drive file. No mirror or cache.
Only Google HTTPS API, credentials supplied by systemd LoadCredential.
Real Drive writes deliberately disabled pending proven provider CAS.

Enablement contract (not activated as of 2026-11-12):
  1. Obtain a narrowly authorized, revocable Google OAuth refresh credential.
  2. Store JSON with client_id, client_secret, refresh_token in a root-only
     file outside the MCP sandbox. Pass it with systemd LoadCredential as
     drive-oauth.json; never store secrets in the scope registry.
  3. Add exactly one pilot to the existing root-owned file-scopes.json with:
     backend=drive-live, access=read-only, canonical=true,
     snapshot_only=false, root_id=<Drive folder ID>,
     credential=drive-oauth.json, allow=[exact relative file paths or dirs/].
     The same loaded credential can serve subsequent allowlisted projects.
  4. Preflight, restart this same service, test list/read chunks/search
     against one noncritical Drive folder; compare with source Drive metadata.
  5. Do NOT enable live writes: Drive v3 conditional media update / atomic
     compare-and-swap is not established. Test only on noncanonical objects
     after an authoritative conflict-prevention mechanism is confirmed.

Last verified: synthetic CAS from ChatGPT, mocked Drive read/search/security,
live backend schema/stdin paging, service healthy; no real Drive OAuth access.
NEXT: provision limited pilot-folder Drive API authorization, then live read-only
pilot. No data migration or canonical source switching.
"""
import hashlib
import json
import os
import re
import stat
import urllib.error
import urllib.parse
import urllib.request

MIME_DIR = "application/vnd.google-apps.folder"
MIMES = {".md": {"text/markdown", "text/plain", "application/octet-stream"},
         ".csv": {"text/csv", "text/plain", "application/octet-stream"},
         ".json": {"application/json", "text/plain", "application/octet-stream"}}
MAX_MEDIA = 4 * 1024 * 1024
MAX_BYTES = 32 * 1024
FILE_ID = re.compile(r"^[A-Za-z0-9_-]{10,160}$")
BAD_NAMES = re.compile(r"(secret|credential|token|password|passwd|private.?key|[.]env|[.]git)", re.I)
def _safe_segment(name):
    return 1 <= len(name) <= 100 and all(ord(c) >= 32 and ord(c) != 127 and c not in ("/", chr(92)) for c in name)

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Unexpected Google API redirect")

_OPENER = urllib.request.build_opener(_NoRedirect)

def _http(url, token=None, data=None, content_type=None, limit=MAX_MEDIA + 1):
    if not (url.startswith("https://www.googleapis.com/drive/v3/") or
            url == "https://oauth2.googleapis.com/token"):
        raise ValueError("Disallowed API endpoint")
    headers = {"Accept": "application/json"}
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    try:
        with _OPENER.open(req, timeout=15) as res:
            body = res.read(limit + 1)
            if len(body) > limit:
                raise ValueError("Google API response exceeds bound")
            return body
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        raise ValueError("Google API request failed") from None

def _credentials(alias):
    p = os.environ.get("CREDENTIALS_DIRECTORY", "/run/credentials/keelarynos-mcp-benchmark.service")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,99}", alias):
        raise ValueError("Invalid credential alias")
    d = os.open(p, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        f = os.open(alias, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=d)
        try:
            s = os.fstat(f)
            if not stat.S_ISREG(s.st_mode) or s.st_size > 4096:
                raise ValueError("Invalid credential file")
            raw = os.read(f, 4097)
        finally:
            os.close(f)
    finally:
        os.close(d)
    if len(raw) > 4096:
        raise ValueError("Invalid credential size")
    obj = json.loads(raw)
    if not isinstance(obj, dict) or set(obj) != {"client_id", "client_secret", "refresh_token"}:
        raise ValueError("Invalid OAuth credential format")
    if not all(isinstance(x, str) and 1 <= len(x) <= 2048 for x in obj.values()):
        raise ValueError("Invalid OAuth credential values")
    return obj

def _token(scope):
    c = _credentials(scope["credential"])
    data = urllib.parse.urlencode({"client_id": c["client_id"],
        "client_secret": c["client_secret"], "refresh_token": c["refresh_token"],
        "grant_type": "refresh_token"}).encode("ascii")
    response = json.loads(_http("https://oauth2.googleapis.com/token", data=data,
                      content_type="application/x-www-form-urlencoded", limit=4096))
    token = response.get("access_token")
    if not isinstance(token, str) or len(token) < 15:
        raise ValueError("Drive OAuth refresh unavailable")
    return token

def _json_get(path, token, params=None):
    query = "?" + urllib.parse.urlencode(params) if params else ""
    return json.loads(_http("https://www.googleapis.com/drive/v3/" + path + query,
                            token=token, limit=1024*1024))

def _parts(path, directory=False):
    if not isinstance(path, str) or len(path) > 400:
        raise ValueError("Invalid relative Drive path")
    if path == "" and directory:
        return []
    names = path.split("/")
    if not 1 <= len(names) <= 5:
        raise ValueError("Invalid Drive path depth")
    for name in names:
        if name in ("", ".", "..") or not _safe_segment(name) or name.startswith(".") or BAD_NAMES.search(name):
            raise ValueError("Unsafe relative Drive path")
    if not directory and not any(names[-1].lower().endswith(x) for x in MIMES):
        raise ValueError("Not a permitted text file")
    return names

def _allowed(scope, path):
    return any(path == item or (item.endswith("/") and path.startswith(item))
               for item in scope["allow"])

def _branch_allowed(scope, path):
    if _allowed(scope, path):
        return True
    return any(item.startswith(path + "/") for item in scope["allow"])

def _children(folder_id, token):
    if not FILE_ID.fullmatch(folder_id):
        raise ValueError("Invalid Drive folder ID")
    all_items = []
    page = None
    while True:
        params = {"q": "'" + folder_id + "' in parents and trashed = false",
                  "fields": "nextPageToken,files(id,name,mimeType,size,parents,trashed,version,headRevisionId)",
                  "pageSize": 100, "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"}
        if page:
            params["pageToken"] = page
        payload = _json_get("files", token, params)
        batch = payload.get("files")
        if not isinstance(batch, list):
            raise ValueError("Invalid Drive directory response")
        for e in batch:
            if not isinstance(e, dict) or folder_id not in e.get("parents", []) or e.get("trashed"):
                raise ValueError("Drive directory parent mismatch")
            if not FILE_ID.fullmatch(str(e.get("id", ""))):
                raise ValueError("Invalid Drive child ID")
        all_items.extend(batch)
        if len(all_items) > 1000:
            raise ValueError("Drive directory too large for safe traversal")
        page = payload.get("nextPageToken")
        if not page:
            break
    return all_items

def _child(folder_id, name, token):
    matches = [x for x in _children(folder_id, token) if x.get("name") == name]
    if len(matches) != 1:
        raise ValueError("Missing or ambiguous Drive path")
    return matches[0]

def _resolve(scope, path, token, directory=False):
    names = _parts(path, directory)
    folder_id = scope["root_id"]
    if not names:
        return {"id": folder_id, "mimeType": MIME_DIR, "name": ""}
    for i, name in enumerate(names):
        item = _child(folder_id, name, token)
        intermediate = i < len(names)-1
        if intermediate or directory:
            if item.get("mimeType") != MIME_DIR:
                raise ValueError("Drive parent is not a directory")
        folder_id = item["id"]
    return item

def _valid_file(item, path):
    extension = next((x for x in MIMES if path.lower().endswith(x)), None)
    if extension is None or item.get("mimeType") not in MIMES[extension]:
        raise ValueError("Unsupported Drive file MIME type")
    try:
        size = int(item["size"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("Drive file size missing") from None
    if size < 0 or size > MAX_MEDIA:
        raise ValueError("Drive raw file exceeds 4 MiB read bound")
    return size

def _read(scope, path, token):
    if not _allowed(scope, path):
        raise ValueError("Drive file not allowed by project policy")
    item = _resolve(scope, path, token)
    size = _valid_file(item, path)
    ident = item["id"]
    version = str(item.get("version", ""))
    if not version:
        raise ValueError("Drive version unavailable")
    data = _http("https://www.googleapis.com/drive/v3/files/" + ident + "?alt=media",
                 token=token, limit=MAX_MEDIA)
    if len(data) != size:
        raise ValueError("Drive content size changed")
    after = _json_get("files/" + ident, token,
               {"fields": "id,name,mimeType,size,parents,trashed,version", "supportsAllDrives":"true"})
    if (str(after.get("version", "")) != version or after.get("name") != item.get("name")
            or after.get("mimeType") != item.get("mimeType") or
            after.get("size") != item.get("size") or after.get("trashed")):
        raise ValueError("Drive file changed during read")
    content = data.decode("utf-8")
    return {"path": path, "sha256": hashlib.sha256(data).hexdigest(),
            "version": version, "content": content, "size_bytes": len(data),
            "source": "drive-live", "canonical": True, "snapshot_only": False}

def _walk(scope, token, path, max_items=60):
    queue = [path]
    results = []
    count = 0
    while queue:
        base = queue.pop(0)
        folder = _resolve(scope, base, token, directory=True)
        for item in _children(folder["id"], token):
            name = item.get("name")
            if not isinstance(name, str):
                continue
            full = base + "/" + name if base else name
            try:
                _parts(full, directory=True)
            except ValueError:
                continue
            if item["mimeType"] == MIME_DIR and _branch_allowed(scope, full):
                queue.append(full)
            elif item["mimeType"] != MIME_DIR and _allowed(scope, full) and any(full.lower().endswith(x) for x in MIMES):
                count += 1
                if count > max_items:
                    raise ValueError("Drive search exceeds bounded file count")
                results.append(full)
    return results

def operate(name, args, scope):
    if name in ("edit_files", "delete_files"):
        raise ValueError("Drive live scope is read-only; external write CAS not verified")
    token = _token(scope)
    if name == "list_files":
        path = args.get("path", "")
        limit = args.get("limit", 100)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Invalid listing limit")
        folder = _resolve(scope, path, token, directory=True)
        entries = []
        for child in _children(folder["id"], token):
            full = path + "/" + child["name"] if path else child["name"]
            try:
                _parts(full, directory=True)
            except ValueError:
                continue
            kind = "directory" if child["mimeType"] == MIME_DIR else "file"
            if kind == "directory" and not _branch_allowed(scope, full):
                continue
            if kind == "file" and (not _allowed(scope, full) or
                                  not any(full.lower().endswith(x) for x in MIMES)):
                continue
            if kind == "file":
                try:
                    _valid_file(child, full)
                except ValueError:
                    continue
            entries.append({"path": full, "type": kind,
                           "bytes": int(child["size"]) if kind == "file" else None})
        entries.sort(key=lambda x: x["path"])
        return {"project": args.get("project"), "entries": entries[:limit],
                "returned": min(limit, len(entries)), "truncated": len(entries) > limit,
                "source": "drive-live", "canonical": True, "snapshot_only": False}
    if name == "read_files":
        paths = args.get("paths")
        if not isinstance(paths, list) or not 1 <= len(paths) <= 20 or len(set(map(str,paths))) != len(paths):
            raise ValueError("Invalid Drive read paths")
        off = args.get("offset_chars", 0)
        cap = args.get("max_chars", 16000)
        if type(off) is not int or not 0 <= off <= MAX_MEDIA or type(cap) is not int or not 1 <= cap <= 16384:
            raise ValueError("Invalid Drive read offset/length")
        results = []
        for path in paths:
            _parts(path)
            doc = _read(scope, path, token)
            full = doc.pop("content")
            doc["content"] = full[off:off+cap]
            doc["offset_chars"] = off
            doc["next_offset_chars"] = min(len(full), off+cap)
            doc["total_chars"] = len(full)
            doc["end_of_file"] = off+cap >= len(full)
            results.append(doc)
        return {"project": args.get("project"), "files": results, "count": len(results),
                "source": "drive-live", "canonical": True, "snapshot_only": False}
    if name == "search_files":
        query = args.get("query")
        limit = args.get("limit", 20)
        if not isinstance(query, str) or not 1 <= len(query) <= 80 or type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("Invalid Drive search request")
        matches, scanned = [], 0
        for path in _walk(scope, token, ""):
            d = _read(scope, path, token)
            scanned += 1
            for lineno, line in enumerate(d["content"].splitlines(), 1):
                if query.casefold() in line.casefold():
                    matches.append({"path":path, "line":lineno, "snippet":line[:256],
                                    "version":d["version"]})
                    if len(matches) >= limit:
                        return {"matches":matches,"scanned":scanned,"truncated":True,
                                "source":"drive-live","canonical":True}
        return {"matches":matches,"scanned":scanned,"truncated":False,
                "source":"drive-live","canonical":True}
    raise ValueError("Unsupported live Drive operation")

