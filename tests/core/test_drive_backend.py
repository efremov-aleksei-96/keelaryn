from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from keelaryn_core.drive_backend import DriveBackend
from keelaryn_core.drive_model import DriveModel


class DriveBackendContractTests(unittest.TestCase):
    def test_model_structurally_implements_backend_contract(self) -> None:
        self.assertIsInstance(DriveModel(), DriveBackend)

    def test_metadata_does_not_embed_blob_content(self) -> None:
        drive = DriveModel()
        hub = drive.create_folder("root", "Hub")
        payload = b"backend-neutral payload"
        item = drive.create_blob(hub.file_id, "payload.bin", payload)

        self.assertFalse(hasattr(item, "content"))
        self.assertEqual(item.size, len(payload))
        self.assertEqual(item.sha256_checksum, hashlib.sha256(payload).hexdigest())
        self.assertEqual(drive.download(item.file_id), payload)

    def test_list_and_get_return_metadata_only_but_exact_identity_survives_move(self) -> None:
        drive = DriveModel()
        hub = drive.create_folder("root", "Hub")
        other = drive.create_folder(hub.file_id, "other")
        item = drive.create_blob(hub.file_id, "a.bin", b"abc")

        listed = drive.list_children(hub.file_id, name="a.bin")[0]
        self.assertEqual(listed.file_id, item.file_id)
        self.assertFalse(hasattr(listed, "content"))

        moved = drive.move_rename(item.file_id, other.file_id, "b.bin")
        fetched = drive.get(item.file_id)
        self.assertEqual(fetched.file_id, item.file_id)
        self.assertEqual(fetched.parent_id, other.file_id)
        self.assertEqual(fetched.name, "b.bin")
        self.assertEqual(fetched.version, moved.version)
        self.assertEqual(drive.download(item.file_id), b"abc")


if __name__ == "__main__":
    unittest.main(verbosity=2)
