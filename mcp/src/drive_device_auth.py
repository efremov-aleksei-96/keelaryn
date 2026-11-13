"""Private, one-time device OAuth bootstrap for an independently approved Drive sender.

No Google credentials in this repository. Separate root-only directories outside
the running MCP are used; the script does not start a service or copy files.
Google TV/limited-input device grant: only drive.file, no broader scope.
"""
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

CONFIG = Path("/etc/keelaryn-drive-backup")
STATE = Path("/var/lib/keelaryn-drive-backup")
SCOPE = "https://www.googleapis.com/auth/drive.file"
DEVICE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ID = re.compile(r"[0-9]+-[a-z0-9]+\.apps\.googleusercontent\.com\Z")
SCHEMA = "keelaryn-drive-oauth-device-v1"


class AuthError(ValueError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AuthError("Google OAuth redirect forbidden")


def _private_dir(path):
    st = path.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid() or st.st_mode & 0o077:
        raise AuthError("Unsafe credential directory")


def _read(path, limit=4096):
    _private_dir(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid()
                or st.st_mode & 0o077 or st.st_nlink != 1 or st.st_size > limit):
            raise AuthError("Unsafe credential file")
        body = os.read(fd, limit + 1)
        if len(body) != st.st_size:
            raise AuthError("Changed credential file")
        return body
    finally:
        os.close(fd)


def _read_json(path):
    try:
        value = json.loads(_read(path))
    except (UnicodeError, ValueError):
        raise AuthError("Invalid local authorization state") from None
    if not isinstance(value, dict):
        raise AuthError("Invalid authorization state type")
    return value


def _atomic_write(path, raw, *, replace=False):
    _private_dir(path.parent)
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= 4096:
        raise AuthError("Invalid local secret payload")
    if path.is_symlink() or (path.exists() and not replace):
        raise AuthError("Existing local authorization state must not be replaced")
    fd, name = tempfile.mkstemp(prefix=".oauth-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            os.fchmod(f.fileno(), 0o600)
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        if not replace and path.exists():
            raise AuthError("Authorization target appeared concurrently")
        os.replace(name, path)
        d = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(d)
        finally:
            os.close(d)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _client_id():
    value = _read(CONFIG / "client-id", limit=256).decode("ascii").strip()
    if not ID.fullmatch(value):
        raise AuthError("Invalid OAuth client ID")
    return value


def _client_secret():
    value = _read(CONFIG / "client-secret", limit=2048).decode("ascii").strip()
    if not 5 <= len(value) <= 1024 or any(c.isspace() for c in value):
        raise AuthError("Client secret not present or invalid")
    return value


def post_google(url, data):
    if url not in (DEVICE_URL, TOKEN_URL):
        raise AuthError("Non-Google OAuth endpoint forbidden")
    raw = urllib.parse.urlencode(data).encode("ascii")
    req = urllib.request.Request(url, data=raw, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=20) as r:
            status = r.status
            body = r.read(4097)
    except urllib.error.HTTPError as e:
        status = e.code
        body = e.read(4097)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise AuthError("Google OAuth network error") from None
    if len(body) > 4096:
        raise AuthError("Google OAuth response exceeded limit")
    try:
        value = json.loads(body)
    except (ValueError, UnicodeError):
        raise AuthError("Google OAuth returned invalid JSON") from None
    if not isinstance(value, dict):
        raise AuthError("Google OAuth returned invalid object")
    return status, value


def start(*, post=post_google, now=time.time):
    """Return public URL/user_code only; persist nonpublic device_code locally."""
    _private_dir(CONFIG)
    _private_dir(STATE)
    _client_secret()  # Must be safely installed before requesting authorization.
    if (STATE / "refresh-token.json").exists():
        raise AuthError("Already authorized: do not issue another refresh token")
    path = STATE / "pending-device.json"
    if path.exists():
        old = _read_json(path)
        if old.get("expires_at", 0) > now() + 30 and old.get("client_id") == _client_id():
            return {"status": "existing", "verification_url": old["verification_url"],
                    "user_code": old["user_code"], "expires_in": int(old["expires_at"] - now())}
    status, reply = post(DEVICE_URL, {"client_id": _client_id(), "scope": SCOPE})
    if status != 200:
        # Never return full error body from Google.
        return {"status": "rejected", "error": str(reply.get("error", reply.get("error_code", "unknown")))[:80]}
    try:
        code = reply["device_code"]
        user = reply["user_code"]
        url = reply["verification_url"]
        interval = reply["interval"]
        expiry = reply["expires_in"]
    except KeyError:
        raise AuthError("Incomplete Google device challenge") from None
    if (not isinstance(code, str) or not 8 <= len(code) <= 1024
            or not isinstance(user, str) or not 4 <= len(user) <= 40
            or any(not (32 <= ord(c) <= 126) for c in user)
            or not isinstance(url, str) or url not in ("https://www.google.com/device",
                                                      "https://www.google.com/device/")
            or type(interval) is not int or not 1 <= interval <= 60
            or type(expiry) is not int or not 30 <= expiry <= 3600):
        raise AuthError("Unexpected device challenge parameters")
    value = {"schema": SCHEMA, "client_id": _client_id(), "device_code": code,
             "user_code": user, "verification_url": url, "expires_at": int(now()) + expiry,
             "interval": interval, "last_poll": 0}
    _atomic_write(path, json.dumps(value, separators=(",", ":")).encode(), replace=path.exists())
    return {"status": "ready", "verification_url": url,
            "user_code": user, "expires_in": expiry}


def poll(*, post=post_google, now=time.time):
    """One bounded token request, never polling unattended or printing tokens."""
    _private_dir(CONFIG)
    _private_dir(STATE)
    saved = STATE / "refresh-token.json"
    if saved.exists():
        return {"status": "already_authorized"}
    pending = STATE / "pending-device.json"
    value = _read_json(pending)
    if value.get("schema") != SCHEMA or value.get("client_id") != _client_id():
        raise AuthError("Invalid cached OAuth device flow")
    if value.get("expires_at", 0) <= now():
        return {"status": "expired"}
    interval = value["interval"]
    if now() - value["last_poll"] < interval:
        return {"status": "wait", "seconds": int(interval - (now() - value["last_poll"]) + 1)}
    value["last_poll"] = int(now())
    _atomic_write(pending, json.dumps(value, separators=(",", ":")).encode(), replace=True)
    status, reply = post(TOKEN_URL, {"client_id": _client_id(),
                                    "client_secret": _client_secret(),
                                    "device_code": value["device_code"],
                                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
    if status != 200:
        error = reply.get("error", "unknown")
        if error == "authorization_pending":
            return {"status": "pending"}
        if error == "slow_down":
            value["interval"] = min(120, interval + 5)
            _atomic_write(pending, json.dumps(value, separators=(",", ":")).encode(), replace=True)
            return {"status": "slow_down"}
        return {"status": "denied", "error": str(error)[:60]}
    if (reply.get("scope") != SCOPE or reply.get("token_type", "").lower() != "bearer"
            or not isinstance(reply.get("access_token"), str)
            or not 10 <= len(reply["access_token"]) <= 4096
            or not isinstance(reply.get("refresh_token"), str)
            or not 10 <= len(reply["refresh_token"]) <= 4096):
        raise AuthError("Unexpected OAuth scope or token response: not stored")
    refresh = {"schema": SCHEMA, "client_id": _client_id(),
               "scope": SCOPE, "refresh_token": reply["refresh_token"],
               "acquired_at": int(now())}
    _atomic_write(saved, json.dumps(refresh, separators=(",", ":")).encode())
    return {"status": "authorized", "scope": SCOPE, "refresh_stored": True}


def fresh_access_token(*, post=post_google):
    """Call only inside an independently approved backup operation."""
    saved = _read_json(STATE / "refresh-token.json")
    if saved.get("schema") != SCHEMA or saved.get("client_id") != _client_id() or saved.get("scope") != SCOPE:
        raise AuthError("Refresh token identity or scope mismatch")
    token = saved.get("refresh_token")
    if not isinstance(token, str) or not 10 <= len(token) <= 4096:
        raise AuthError("Missing OAuth refresh token")
    status, reply = post(TOKEN_URL, {"client_id": _client_id(),
                                    "client_secret": _client_secret(),
                                    "refresh_token": token, "grant_type": "refresh_token"})
    if status != 200 or (reply.get("scope") not in (None, SCOPE)
                         or reply.get("token_type", "").lower() != "bearer"
                         or not isinstance(reply.get("access_token"), str)
                         or not 10 <= len(reply["access_token"]) <= 4096):
        raise AuthError("Google did not provide a valid drive.file access token")
    return reply["access_token"]


def main():
    if os.geteuid() != 0:
        raise AuthError("Expected isolated root-only credential bootstrap")
    if len(sys.argv) != 2 or sys.argv[1] not in ("start", "poll", "refresh-check"):
        raise AuthError("Use start, poll or refresh-check")
    if sys.argv[1] == "start":
        out = start()
    elif sys.argv[1] == "poll":
        out = poll()
    else:
        token = fresh_access_token()
        out = {"status": "refresh_valid", "scope": SCOPE} if token else {"status": "refresh_failed"}
    print(json.dumps(out, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (AuthError, OSError, ValueError, KeyError, TypeError):
        # Do not leak credential data, local JSON or provider response.
        print('{"status":"error","message":"OAuth setup blocked; inspect state without secrets"}')
        sys.exit(1)
