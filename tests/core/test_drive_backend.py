from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from keelaryn_core.drive_backend import (
    DriveAlreadyExists,
    DriveBackend,
    DriveTransportError,
)
from keelaryn_core.drive_model import DriveModel
from keelaryn_core.drive_transaction import BlobState, DriveOperation, DrivePublicationTransaction


class _ReadFailureProxy:
    def __init__(self, delegate: DriveModel):
        self.delegate = delegate

    def __getattr__(self, name: str):
        return getattr(self.delegate, name)

    def get(self, file_id: str, *, include_trashed: bool = True):
        raise DriveTransportError(f"simulated read failure for {file_id}")


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

    def test_reserved_file_id_is_exact_and_cannot_create_duplicate(self) -> None:
        drive = DriveModel()
        hub = drive.create_folder("root", "Hub")
        reserved = drive.generate_ids(2)

        blob = drive.create_blob(hub.file_id, "a.bin", b"a", file_id=reserved[0])
        folder = drive.create_folder(hub.file_id, "folder", file_id=reserved[1])
        self.assertEqual(blob.file_id, reserved[0])
        self.assertEqual(folder.file_id, reserved[1])

        with self.assertRaises(DriveAlreadyExists):
            drive.create_blob(hub.file_id, "duplicate.bin", b"b", file_id=reserved[0])

    def test_transport_failure_is_not_reclassified_as_missing_object(self) -> None:
        drive = DriveModel()
        hub = drive.create_folder("root", "Hub")
        staging = drive.create_folder(hub.file_id, "staging")
        history = drive.create_folder(hub.file_id, "history")
        rejected = drive.create_folder(hub.file_id, "rejected")
        payload = b"new"
        staged = drive.create_blob(staging.file_id, "new.bin", payload)
        op = DriveOperation(
            operation_id="add",
            kind="ADD",
            canonical_parent_id=hub.file_id,
            target_name="target.bin",
            old=None,
            new=BlobState.from_bytes(payload),
            staged_new_id=staged.file_id,
            staged_parent_id=staging.file_id,
        )
        tx = DrivePublicationTransaction(_ReadFailureProxy(drive), history.file_id, rejected.file_id)

        with self.assertRaises(DriveTransportError):
            tx.classify(op)


if __name__ == "__main__":
    unittest.main(verbosity=2)
