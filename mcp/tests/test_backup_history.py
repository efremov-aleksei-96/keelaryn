#!/usr/bin/env python3
"""Offline backup+restore roundtrip of a synthetic owner G1 archive.

Fake Drive API, no cloud credentials or real project reads. Demonstrates that
archive segments remain in the same verified owner tree as the canonical file.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import types

BASE = Path(__file__).resolve().parents[1] / "src"
class BackupError(ValueError):
    pass
sender = types.ModuleType("drive_plain_sender")
sender.BackupError = BackupError
sender.FOLDER = "application/vnd.google-apps.folder"
sys.modules["drive_plain_sender"] = sender
sys.modules["drive_real_backup"] = types.ModuleType("drive_real_backup")
spec = importlib.util.spec_from_file_location("offline_tree", BASE / "drive_tree_backup.py")
tree = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tree)


class FakeRemote:
    def __init__(self, files, version):
        self.objects = {}
        self.blobs = {}
        self.objects["version"] = {}
        self.objects["project"] = {}
        self.objects["journal"] = {}
        def item(folder, name, mime, blob=None):
            key = f"{folder}-{name}"
            self.objects[folder][name] = {"id": key, "mimeType": mime}
            if blob is not None:
                self.blobs[key] = blob
        item("version", "historysynthetic", sender.FOLDER)
        item("version", tree.MARKER, "application/json",
             tree._json(dict(tree._manifest(files), version=version)))
        for path, content in files.items():
            parts = path.split("/")
            if len(parts) == 2:
                name = parts[1]
                item("project", name,
                     "text/markdown" if name.endswith(".md") else
                     "text/csv" if name.endswith(".csv") else "application/json",
                     content)
            else:
                assert parts[1] == ".keelaryn-g1"
                item("journal", parts[2],
                     "application/json" if parts[2].endswith(".json")
                     else "application/octet-stream", content)
        item("project", ".keelaryn-g1", sender.FOLDER)
        self.objects["version-historysynthetic"] = self.objects["project"]
        self.objects["project-.keelaryn-g1"] = self.objects["journal"]
    def list(self, node):
        return self.objects[node]
    def media(self, node):
        return self.blobs[node]


def main():
    with tempfile.TemporaryDirectory(prefix="keelaryn-history-backup-fixture-") as dirname:
        top = Path(dirname)
        top.chmod(0o700)
        root = top / "data"
        root.mkdir(mode=0o700)
        owner = root / "historysynthetic"
        owner.mkdir(mode=0o700)
        state = owner / "STATE.md"
        state.write_text("# synthetic owner\n")
        state.chmod(0o600)
        journal = owner / ".keelaryn-g1"
        journal.mkdir(mode=0o700)
        lock = journal / ".lock"
        lock.write_bytes(b"")
        lock.chmod(0o600)
        committed = {
            "request_id": "0" * 32,
            "status": "committed",
            "fingerprint": "b" * 64,
            "action": "replace",
            "path": "STATE.md",
            "new_path": None,
            "expected_sha256": "a" * 64,
            "new_sha256": hashlib.sha256(state.read_bytes()).hexdigest(),
        }
        archive = {
            "schema": "keelaryn-g1-history-v1",
            "receipts": {"0" * 32: committed},
        }
        archive_path = journal / "history-000001.json"
        archive_path.write_text(json.dumps(archive))
        archive_path.chmod(0o600)
        next_entry = dict(committed, request_id="1" * 32)
        next_path = journal / ("1" * 32 + ".json")
        next_path.write_text(json.dumps(next_entry))
        next_path.chmod(0o600)
        config = top / "registry.json"
        config.write_text(json.dumps({
            "schema": "keelarynos_mcp_file_scopes_v1",
            "scopes": {
                "synthetic": {"backend": "workspace", "access": "read-write",
                              "description": "Ephemeral synthetic-only benchmark files"},
                "HistorySynthetic": {
                    "backend": "owner-fs", "owner": "HistorySynthetic",
                    "root": str(owner), "access": "read-write",
                    "allow": ["STATE.md"], "canonical": True,
                    "snapshot_only": False,
                }
            },
        }))
        config.chmod(0o600)
        tree.ROOT, tree.REGISTRY = root, config
        files = tree._snapshot()
        assert set(files) == {
            "historysynthetic/STATE.md",
            "historysynthetic/.keelaryn-g1/.lock",
            "historysynthetic/.keelaryn-g1/history-000001.json",
            "historysynthetic/.keelaryn-g1/" + "1" * 32 + ".json",
        }
        version = tree._identity(files)
        restored = tree._remote(FakeRemote(files, version), "version", version)
        assert restored == files
        for name, data in restored.items():
            target = top / "restore" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            assert target.read_bytes() == data
        assert json.loads((top / "restore" / "historysynthetic" /
                           ".keelaryn-g1" / "history-000001.json").read_bytes()) == archive
        print("HISTORY_ARCHIVE_OFFLINE_REMOTE_ROUNDTRIP_PASS", version)

        # If an archive's content changes after publishing the completion
        # marker, the marker hashes must reject it on restore.
        fake = FakeRemote(files, version)
        fake.blobs["journal-history-000001.json"] = b"tampered"
        try:
            tree._remote(fake, "version", version)
        except BackupError:
            print("HISTORY_ARCHIVE_TAMPER_RESTORE_DENIED_PASS")
        else:
            raise AssertionError("Tampered archive passed remote verification")
        archive_path.write_bytes(b"{invalid")
        try:
            tree._snapshot()
        except BackupError:
            print("HISTORY_ARCHIVE_CORRUPTION_BACKUP_DENIED_PASS")
        else:
            raise AssertionError("Corrupted archive passed source snapshot")
        print("ALL_HISTORY_BACKUP_OFFLINE_TESTS_PASS")


if __name__ == "__main__":
    main()
