#!/usr/bin/env python3
"""No OAuth credentials, no Google network, no real owners, no service changes.

Runs as an unprivileged user against a disposable synthetic G1 snapshot and a
strict in-memory imitation of the minimal Drive v3 REST routes.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import urllib.parse

os.environ["KEELARYN_MCP_MODE"] = "local"
os.environ["KEELARYN_MCP_OWNER_FS_TEST"] = "1"
os.environ.pop("KEELARYN_DRIVE_PLAIN_LIVE", None)

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import drive_plain_sender as sender
import owner_fs
import test_g3_plain_copy as g3


class FakeDrive:
    def __init__(self):
        self.objects = {}
        self.index = 0
        self.lost_response = False
        self.uploads = 0
        self.requests = []
        self.parent = "BACKUPROOT_000001"
        self.objects[self.parent] = dict(id=self.parent, name="Synthetic Pilot",
                                         mimeType=sender.FOLDER, parents=["root"],
                                         trashed=False, shared=False, content=b"")

    def add(self, name, mime, parent, content=b""):
        self.index += 1
        file_id = "FAKE_DRIVE_ID_" + str(self.index).zfill(6)
        obj = dict(id=file_id, name=name, mimeType=mime,
                   parents=[parent], trashed=False, shared=False, content=content)
        self.objects[file_id] = obj
        return obj

    @staticmethod
    def metadata(obj):
        return {k: v for k, v in obj.items() if k != "content"}

    def handle(self, method, url, headers, body):
        assert headers["Authorization"] == "Bearer SYNTHETIC_FAKE_TOKEN"
        assert not ("PRIVATE KEY" in str(body) or "refresh_token" in str(body))
        assert method in ("GET", "POST"), "No destructive/overwrite Drive verbs"
        parsed = urllib.parse.urlsplit(url)
        self.requests.append((method, parsed.path))
        if parsed.hostname != "www.googleapis.com":
            raise AssertionError("Unexpected host")
        params = urllib.parse.parse_qs(parsed.query)
        if method == "GET" and parsed.path == "/drive/v3/files":
            q = params["q"][0]
            parent = q.split("'")[1]
            assert parent in self.objects
            children = [self.metadata(obj) for obj in self.objects.values()
                        if obj["parents"] == [parent] and obj["trashed"] is False]
            return 200, json.dumps({"files": children}).encode()
        if method == "GET" and parsed.path.startswith("/drive/v3/files/"):
            file_id = parsed.path.rsplit("/", 1)[1]
            if file_id not in self.objects:
                return 404, b"not found"
            obj = self.objects[file_id]
            if params.get("alt") == ["media"]:
                return 200, obj["content"]
            return 200, json.dumps(self.metadata(obj)).encode()
        if method == "POST" and parsed.path == "/drive/v3/files":
            assert body is not None
            item = json.loads(body)
            assert item["mimeType"] == sender.FOLDER
            assert len(item["parents"]) == 1
            return 200, json.dumps(self.metadata(
                self.add(item["name"], item["mimeType"], item["parents"][0])
            )).encode()
        if method == "POST" and parsed.path == "/upload/drive/v3/files":
            assert params == {"uploadType": ["multipart"],
                              "fields": ["id,name,mimeType,parents"]}
            content_type = headers["Content-Type"]
            assert content_type.startswith("multipart/related; boundary=")
            boundary = content_type.split("boundary=", 1)[1].encode()
            sections = body.split(b"--" + boundary)
            assert len(sections) == 4, "Multipart parser invariant"
            metadata_raw = sections[1].split(b"\r\n\r\n", 1)[1].rstrip(b"\r\n")
            media_raw = sections[2].split(b"\r\n\r\n", 1)[1]
            assert media_raw.endswith(b"\r\n")
            media_raw = media_raw[:-2]
            item = json.loads(metadata_raw)
            assert item["parents"] and item["mimeType"] != sender.FOLDER
            obj = self.add(item["name"], item["mimeType"],
                           item["parents"][0], media_raw)
            self.uploads += 1
            if self.lost_response:
                self.lost_response = False
                raise ConnectionError("Synthetic response lost AFTER provider created file")
            return 200, json.dumps(self.metadata(obj)).encode()
        raise AssertionError("Unexpected REST operation: " + method + " " + url)

    def child(self, parent, name):
        matches = [obj for obj in self.objects.values()
                   if obj["parents"] == [parent] and obj["name"] == name]
        assert len(matches) == 1, (parent, name, len(matches))
        return matches[0]


def make_versions(base):
    owner = base / "owner"
    owner.mkdir(mode=0o700)
    versions = base / "plain-versions"
    versions.mkdir(mode=0o700)
    scope = {"backend": "owner-fs", "owner": "PlainSynthetic",
             "root": str(owner), "allow": g3.ALLOW, "access": "read-write",
             "canonical": False, "snapshot_only": False}
    def mutate(action, i, path, **kwargs):
        return owner_fs.mutate(dict(project="PlainSynthetic", request_id=f"{i:032x}",
                                    action=action, path=path, **kwargs), scope)
    a = "# Synthetic course\nNEXT: LESSON-01\n"
    b = "# Synthetic course\nNEXT: LESSON-02\n"
    assert mutate("create", 1, "PROJECT.md", content=a,
                  expected_sha256=None)["verified_readback"]
    assert mutate("create", 2, "CURSOR.json", content='{"lesson":1}\n',
                  expected_sha256=None)["verified_readback"]
    assert mutate("create", 3, "MASTERY.csv", content="item,score\nA,2\n",
                  expected_sha256=None)["verified_readback"]
    g3.owner_fs = owner_fs
    v1 = g3.snapshot(owner, "v0001", scope)
    assert mutate("replace", 4, "PROJECT.md", content=b,
                  expected_sha256=hashlib.sha256(a.encode()).hexdigest())["verified_readback"]
    assert mutate("replace", 5, "CURSOR.json", content='{"lesson":2}\n',
                  expected_sha256=hashlib.sha256('{"lesson":1}\n'.encode()).hexdigest()
                  )["verified_readback"]
    v2 = g3.snapshot(owner, "v0002", scope)
    return v1, v2


def fail(call, expected, description):
    try:
        call()
    except expected:
        return
    raise AssertionError("Expected refusal: " + description)


def main():
    if os.geteuid() == 0:
        raise RuntimeError("Run unprivileged, never root")
    with tempfile.TemporaryDirectory(prefix="keelaryn-drive-sender-") as temp:
        base = Path(temp)
        v1, v2 = make_versions(base)
        remote = FakeDrive()
        fail(lambda: sender.Drive("", remote.handle), sender.BackupError,
             "missing token")
        fail(lambda: sender.Drive("SYNTHETIC_FAKE_TOKEN"), sender.BackupError,
             "default-off real HTTPS")

        api = sender.Drive("SYNTHETIC_FAKE_TOKEN", remote.handle)
        remote.lost_response = True
        fail(lambda: sender.publish_synthetic(api, v1, remote.parent),
             sender.BackupError, "provider committed but client lost response")
        version1 = remote.child(remote.parent, "v0001")
        assert sender.MARKER not in [o["name"] for o in remote.objects.values()
                                     if o["parents"] == [version1["id"]]]
        out = sender.publish_synthetic(api, v1, remote.parent)
        assert out["status"] == "published" and out["count"] == 7
        assert sender.publish_synthetic(api, v1, remote.parent)["status"] == "already_complete"
        assert sender.publish_synthetic(api, v2, remote.parent)["status"] == "published"
        version2 = remote.child(remote.parent, "v0002")
        assert remote.child(version1["id"], "PROJECT.md")["content"] != remote.child(
            version2["id"], "PROJECT.md")["content"]
        for v, folder in ((v1, version1), (v2, version2)):
            all_source = sender.source_files(v)
            j = remote.child(folder["id"], ".keelaryn-g1")
            for path, data in all_source.items():
                parent = folder["id"] if "/" not in path else j["id"]
                assert remote.child(parent, path.split("/")[-1])["content"] == data
        dest = base / "restored-v0002"
        restored = sender.restore_synthetic(api, version2["id"], dest)
        assert restored["status"] == "restored" and restored["count"] == 9
        assert sender.source_files(v2) == {p: (dest / p).read_bytes()
                                          for p in sender.source_files(v2)}
        fail(lambda: sender.restore_synthetic(api, version2["id"], dest),
             sender.BackupError, "existing restore directory")
        replay = owner_fs.mutate(
            dict(project="PlainSynthetic", request_id=f"{5:032x}",
                 action="replace", path="CURSOR.json",
                 content='{"lesson":2}\n',
                 expected_sha256=hashlib.sha256('{"lesson":1}\n'.encode()).hexdigest()),
            {**{"backend":"owner-fs","owner":"PlainSynthetic","allow":g3.ALLOW,
               "access":"read-write","canonical":False,"snapshot_only":False},
             "root":str(dest)})
        assert replay["status"] == "already_committed" and replay["current_matches"]

        # The published source is read-only at the protocol level.
        obj = remote.child(version2["id"], "PROJECT.md")
        saved = obj["content"]
        obj["content"] = b"damaged post-publication"
        fail(lambda: sender.publish_synthetic(api, v2, remote.parent),
             sender.BackupError, "tampered published version")
        fail(lambda: sender.restore_synthetic(api, version2["id"], base/"corrupt-restore"),
             sender.BackupError, "restore of tampered version")
        assert not (base/"corrupt-restore").exists()
        obj["content"] = saved

        # Duplicate name must fail closed; no overwrites.
        remote.add("MASTERY.csv", "text/csv", version2["id"], b"malicious duplicate")
        fail(lambda: sender.publish_synthetic(api, v2, remote.parent),
             sender.BackupError, "duplicate remote filename")
        assert not any(method in ("PATCH", "DELETE", "PUT") for method, _ in remote.requests)

        # Local symlink / unresolved G1 journal / unknown extra file refused.
        badroot = base / "bad"
        badroot.mkdir(mode=0o700)
        link = badroot / "v0003"
        link.symlink_to(v1, target_is_directory=True)
        fail(lambda: sender.source_files(link), sender.BackupError, "symlink root")
        (v1 / "EXTRA.md").write_text("Unexpected\n")
        fail(lambda: sender.source_files(v1), sender.BackupError, "unknown local file")
        (v1 / "EXTRA.md").unlink()
        receipt = v1 / ".keelaryn-g1" / f"{1:032x}.json"
        original = receipt.read_bytes()
        record = json.loads(original)
        record["status"] = "intent"
        receipt.write_text(json.dumps(record))
        fail(lambda: sender.source_files(v1), sender.BackupError,
             "unfinished G1 intent")
        receipt.write_bytes(original)

        remote.objects[remote.parent]["shared"] = True
        fail(lambda: sender.publish_synthetic(api, v1, remote.parent),
             sender.BackupError, "shared destination")
        print("DRIVE_PLAIN_SENDER_SYNTHETIC_G1_REPLAY_PASS")
        print("DRIVE_PLAIN_SENDER_INTERRUPTION_RESUME_DUPLICATE_TAMPER_DENIAL_PASS")
        print("DRIVE_PLAIN_SENDER_NO_NETWORK_NO_SECRET_NO_PROD_MUTATION_PASS")


if __name__ == "__main__":
    main()
