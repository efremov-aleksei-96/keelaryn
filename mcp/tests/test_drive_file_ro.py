#!/usr/bin/env python3
"""Offline, root-owned registry + synthetic service-account tests (no network).

Run as root; the MCP child and fake LoadCredential are owned by nobody.
All Google API calls are monkeypatched and cannot access Google or user data.
"""
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import tempfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

SRC = Path(__file__).resolve().parents[1] / "src"
OWNER = "synthetic-owner@example.test"
ACCOUNT = "synthetic-test@fake-project.iam.gserviceaccount.com"
FILE_ID = "syntheticPinnedID12345"
FILENAME = "synthetic_rules.md"
PAYLOAD = "# Synthetic rules\nexact-file-needle\n"
SCOPE = {
    "backend": "drive-file-ro", "access": "read-only",
    "snapshot_only": False, "canonical": True,
    "file_id": FILE_ID, "filename": FILENAME,
    "owner_email": OWNER, "credential": "synthetic-sa.json",
}

CHILD = r'''
import base64
import hashlib
import json
import os
import sys
import urllib.parse

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

sys.path.insert(0, os.environ["TEST_SRC"])
import drive_file_ro as backend
from fs_tools import file_tool

FILE_ID = "syntheticPinnedID12345"
FILENAME = "synthetic_rules.md"
OWNER = "synthetic-owner@example.test"
PAYLOAD = b"# Synthetic rules\nexact-file-needle\n"
token_str = "synthetic-opaque-access-token-only"
state = {"mode": "", "metadata_calls": 0, "all_urls": [], "token_requests": 0}

def metadata():
    value = {
        "id": FILE_ID, "name": FILENAME, "mimeType": "text/markdown",
        "size": str(len(PAYLOAD)), "version": "11", "trashed": False,
        "shared": True, "ownedByMe": False,
        "owners": [{"emailAddress": OWNER}],
        "capabilities": {"canEdit": False},
    }
    mode = state["mode"]
    if mode == "wrong_id": value["id"] = "OTHERFILE99999999999"
    if mode == "wrong_owner": value["owners"][0]["emailAddress"] = "unknown@example.test"
    if mode == "shared_false": value["shared"] = False
    if mode == "editable": value["capabilities"]["canEdit"] = True
    if mode == "owned": value["ownedByMe"] = True
    if mode == "trashed": value["trashed"] = True
    if mode == "mime": value["mimeType"] = "application/vnd.google-apps.document"
    if mode == "oversize": value["size"] = "65537"
    if mode == "stale" and state["metadata_calls"] >= 2: value["version"] = "12"
    if mode == "renamed" and state["metadata_calls"] >= 2: value["name"] = "different.md"
    if mode == "missing_version": value.pop("version")
    return value

def fake_http(url, token=None, data=None, content_type=None, limit=None):
    state["all_urls"].append(url)
    if url == backend.TOKEN_URI:
        state["token_requests"] += 1
        assert token is None and content_type == "application/x-www-form-urlencoded"
        values = urllib.parse.parse_qs(data.decode("ascii"))
        assert values["grant_type"] == ["urn:ietf:params:oauth:grant-type:jwt-bearer"]
        head, claims, signature = values["assertion"][0].split(".")
        decode = lambda v: base64.urlsafe_b64decode(v + "=" * (-len(v) % 4))
        header, body = json.loads(decode(head)), json.loads(decode(claims))
        assert header["alg"] == "RS256" and header["typ"] == "JWT"
        assert body["iss"].endswith(".gserviceaccount.com")
        assert body["aud"] == backend.TOKEN_URI
        assert body["scope"] == backend.DRIVE_SCOPE
        assert "sub" not in body
        assert body["exp"] - body["iat"] == 1800
        private = backend._credentials("synthetic-sa.json")["private_key"].encode()
        public = serialization.load_pem_private_key(private, password=None).public_key()
        public.verify(decode(signature), (head + "." + claims).encode(),
                      padding.PKCS1v15(), hashes.SHA256())
        if state["mode"] == "bad_token":
            return b'{"access_token":"short","token_type":"Bearer","expires_in":3600}'
        return json.dumps({"access_token": token_str,
                           "token_type": "Bearer", "expires_in": 1800}).encode()
    assert token == token_str, "no unauthenticated Drive API call"
    prefix = "https://www.googleapis.com/drive/v3/files/" + FILE_ID
    assert url.startswith(prefix + "?"), "unexpected file ID or files.list"
    query = urllib.parse.parse_qs(url.partition("?")[2])
    if query == {"alt": ["media"]}:
        if state["mode"] == "bad_body":
            return b"wrong body of same size"[:len(PAYLOAD)]
        if state["mode"] == "invalid_utf8":
            return b"\xff" * len(PAYLOAD)
        if state["mode"] == "denied":
            raise ValueError("Synthetic provider permission denied")
        return PAYLOAD
    assert query.get("supportsAllDrives") == ["true"]
    assert query.get("fields") == [backend.METADATA_FIELDS]
    state["metadata_calls"] += 1
    if state["mode"] == "denied":
        raise ValueError("Synthetic provider permission denied")
    return json.dumps(metadata()).encode()

backend._google_http = fake_http

def call(name, args):
    return file_tool(name, dict(args, project="OneFile"))

def decoded(response):
    assert not response.get("isError"), response
    return json.loads(response["content"][0]["text"])

listed = decoded(call("list_files", {"path": "", "limit": 1}))
assert listed["returned"] == 1 and len(listed["entries"]) == 1
assert listed["entries"][0]["path"] == FILENAME
assert listed["root"] == "single-drive-file"
assert listed["canonical"] is True

read = decoded(call("read_files", {"paths": [FILENAME], "offset_chars": 2, "max_chars": 9}))
doc = read["files"][0]
assert doc["content"] == PAYLOAD.decode()[2:11]
assert doc["sha256"] == hashlib.sha256(PAYLOAD).hexdigest()
assert doc["version"] == "11" and doc["canonical"] is True
assert doc["next_offset_chars"] == 11 and doc["end_of_file"] is False

hits = decoded(call("search_files", {"query": "exact-file", "limit": 2}))
assert hits["scanned"] == 1 and hits["matches"][0]["path"] == FILENAME
assert any("files/" + FILE_ID in x for x in state["all_urls"])
assert not any("files?" in x or "/files" == x.split("?")[0][-6:] for x in state["all_urls"])
assert state["token_requests"] == 3
print("OFFLINE_SINGLE_FILE_LIST_READ_SEARCH_JWT_SIGNATURE_PASS")

for name, args in [
    ("list_files", {"path": "/"}),
    ("read_files", {"paths": ["../synthetic_rules.md"]}),
    ("read_files", {"paths": ["something_else.md"]}),
    ("read_files", {"paths": [FILENAME, FILENAME]}),
    ("read_files", {"paths": [FILENAME], "max_chars": 32768}),
    ("read_files", {"paths": [FILENAME], "offset_chars": -1}),
    ("search_files", {"query": ""}),
    ("search_files", {"query": "x", "limit": 21}),
    ("edit_files", {"edits": [{"path": FILENAME, "content": "WRONG"}]}),
    ("delete_files", {"files": [{"path": FILENAME, "expected_sha256": "0"*64}]}),
]:
    assert call(name, args).get("isError"), (name, args)
print("OFFLINE_PATH_PAGING_WRITE_AND_UNKNOWN_FILE_DENIAL_PASS")

for mode in ["wrong_id", "wrong_owner", "shared_false", "editable", "owned",
             "trashed", "mime", "oversize", "stale", "renamed",
             "missing_version", "bad_body", "invalid_utf8", "denied", "bad_token"]:
    state["mode"] = mode
    state["metadata_calls"] = 0
    response = call("read_files", {"paths": [FILENAME]})
    assert response.get("isError"), (mode, response)
state["mode"] = ""
print("OFFLINE_PROVIDER_PERMISSION_OWNER_VERSION_MIME_SIZE_FAIL_CLOSED_PASS")

assert backend._credentials("synthetic-sa.json")["type"] == "service_account"
for invalid_alias in ("../synthetic-sa.json", "other/account", "Invalid Name", ""):
    try: backend._credentials(invalid_alias)
    except ValueError: pass
    else: raise AssertionError("unsafe alias accepted")
print("OFFLINE_SERVICE_CREDENTIAL_ALIAS_BOUNDARY_PASS")
assert not any("drive/v3/files?" in x for x in state["all_urls"])
print("OFFLINE_NO_DRIVE_FOLDER_TRAVERSAL_OR_OTHER_ID_PASS")
'''

def main():
    if os.geteuid() != 0:
        raise RuntimeError("Run synthetic owner-permission test as root")
    nobody = pwd.getpwnam("nobody")
    with tempfile.TemporaryDirectory(prefix="keelaryn-drive-file-ro-") as dirname:
        root = Path(dirname)
        root.chmod(0o755)
        creds = root / "credentials"
        creds.mkdir(mode=0o700)
        os.chown(creds, nobody.pw_uid, nobody.pw_gid)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private = key.private_bytes(serialization.Encoding.PEM,
                                    serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()).decode()
        credential = {
            "type": "service_account",
            "client_email": ACCOUNT, "private_key": private,
            "private_key_id": "a" * 40,
            "token_uri": "https://oauth2.googleapis.com/token",
        }
        cred = creds / "synthetic-sa.json"
        cred.write_text(json.dumps(credential))
        cred.chmod(0o600)
        os.chown(cred, nobody.pw_uid, nobody.pw_gid)
        registry = root / "scope.json"
        registry.write_text(json.dumps({
            "schema": "keelarynos_mcp_file_scopes_v1",
            "scopes": {
                "synthetic": {
                    "backend": "workspace", "access": "read-write",
                    "description": "Ephemeral synthetic-only benchmark files",
                },
                "OneFile": SCOPE,
            },
        }))
        registry.chmod(0o644)
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
                   KEELARYN_MCP_ACCESS_MODE="read-only",
                   KEELARYN_MCP_CONFIG=str(registry),
                   CREDENTIALS_DIRECTORY=str(creds),
                   TEST_SRC=str(SRC))
        # Deliberately omit KEELARYN_MCP_MODE, exactly like the running unit.
        env.pop("KEELARYN_MCP_MODE", None)
        result = subprocess.run(
            ["runuser", "-u", "nobody", "--", sys.executable, "-B", "-c", CHILD],
            capture_output=True, text=True, env=env, timeout=35)
        assert result.returncode == 0, result.stderr[-1000:]
        print(result.stdout, end="")
        legacy = dict(env, KEELARYN_MCP_ACCESS_MODE="default")
        test = subprocess.run(
            ["runuser", "-u", "nobody", "--", sys.executable, "-B", "-c",
             "import sys;sys.path.insert(0,sys.argv[1]);import file_scopes",
             str(SRC)],
            capture_output=True, text=True, env=legacy, timeout=15)
        assert test.returncode != 0
        assert "Single-file Drive requires system read-only mode" in test.stderr
        print("OFFLINE_SINGLE_FILE_SCOPE_DEFAULT_OFF_PASS")
        # Invalid access policy fails at registry load; no network/token needed.
        for key, value in [
            ("file_id", "../other"),
            ("filename", "../private.md"),
            ("owner_email", "missing-domain"),
            ("credential", "../secret.json"),
            ("canonical", False),
        ]:
            original = SCOPE[key]
            SCOPE[key] = value
            data = json.loads(registry.read_text())
            data["scopes"]["OneFile"] = SCOPE
            registry.write_text(json.dumps(data))
            test = subprocess.run(
                ["runuser", "-u", "nobody", "--", sys.executable, "-B", "-c",
                 "import sys;sys.path.insert(0,sys.argv[1]);import file_scopes",
                 str(SRC)],
                capture_output=True, text=True, env=env, timeout=15)
            assert test.returncode != 0, (key, test.stdout)
            SCOPE[key] = original
        print("OFFLINE_SCOPE_INVALID_ID_OWNER_FILENAME_ALIAS_FAIL_CLOSED_PASS")

if __name__ == "__main__":
    main()
