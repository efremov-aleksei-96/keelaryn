from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from keelaryn_core.drive_model import BLOB_MIME, FOLDER_MIME, DriveModel
from keelaryn_core.protocol import FaultInjector, InjectedCrash, ProtocolError


class DriveModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.drive = DriveModel()
        self.hub = self.drive.create_folder("root", "Keelaryn Hub")

    def test_blob_identity_version_revision_and_checksum(self) -> None:
        item = self.drive.create_blob(self.hub.file_id, "a.txt", b"one")
        self.assertEqual(item.version, 1)
        self.assertIsNotNone(item.head_revision_id)
        first_revision = item.head_revision_id
        first_id = item.file_id
        updated = self.drive.update_content(item.file_id, b"two")
        self.assertEqual(updated.file_id, first_id)
        self.assertEqual(updated.version, 2)
        self.assertNotEqual(updated.head_revision_id, first_revision)
        self.assertEqual(self.drive.download(item.file_id), b"two")
        self.assertEqual(updated.sha256_checksum, "3fc4ccfe745870e2c0d99f71f30ff0656c8dedd41cc1d7d3d376b0dbe685e2f3")

    def test_duplicate_names_are_preserved_and_exact_name_fails_closed(self) -> None:
        self.drive.create_blob(self.hub.file_id, "same.txt", b"a")
        self.drive.create_blob(self.hub.file_id, "same.txt", b"b")
        self.assertEqual(len(self.drive.list_children(self.hub.file_id, name="same.txt")), 2)
        with self.assertRaises(ProtocolError):
            self.drive.exact_name(self.hub.file_id, "same.txt")

    def test_move_rename_preserves_file_id_and_bytes(self) -> None:
        other = self.drive.create_folder(self.hub.file_id, "other")
        item = self.drive.create_blob(self.hub.file_id, "a.txt", b"payload")
        moved = self.drive.move_rename(item.file_id, other.file_id, "b.txt")
        self.assertEqual(moved.file_id, item.file_id)
        self.assertEqual(moved.version, item.version + 1)
        self.assertEqual(self.drive.download(item.file_id), b"payload")
        self.assertIsNone(self.drive.exact_name(self.hub.file_id, "a.txt"))
        self.assertEqual(self.drive.exact_name(other.file_id, "b.txt").file_id, item.file_id)

    def test_copy_creates_distinct_verified_object(self) -> None:
        source = self.drive.create_blob(self.hub.file_id, "source.bin", b"payload")
        copy = self.drive.copy_blob(source.file_id, self.hub.file_id, "copy.bin")
        self.assertNotEqual(copy.file_id, source.file_id)
        self.assertEqual(copy.sha256_checksum, source.sha256_checksum)
        self.assertEqual(copy.size, source.size)
        self.assertEqual(self.drive.download(copy.file_id), b"payload")

    def test_stale_get_is_one_shot(self) -> None:
        item = self.drive.create_blob(self.hub.file_id, "a", b"old")
        stale = self.drive.get(item.file_id)
        live = self.drive.update_content(item.file_id, b"new")
        self.drive.inject_stale_get(item.file_id, stale)
        self.assertEqual(self.drive.get(item.file_id).version, stale.version)
        self.assertEqual(self.drive.get(item.file_id).version, live.version)

    def test_stale_list_is_one_shot(self) -> None:
        old = self.drive.create_blob(self.hub.file_id, "a", b"old")
        stale = self.drive.list_children(self.hub.file_id, name="a")
        self.drive.move_rename(old.file_id, self.hub.file_id, "b")
        self.drive.inject_stale_list(self.hub.file_id, "a", stale)
        self.assertEqual(len(self.drive.list_children(self.hub.file_id, name="a")), 1)
        self.assertEqual(self.drive.list_children(self.hub.file_id, name="a"), [])

    def test_external_edit_is_observable_as_same_id_new_version(self) -> None:
        item = self.drive.create_blob(self.hub.file_id, "a", b"old")
        before = self.drive.get(item.file_id)
        self.drive.update_content(item.file_id, b"external", label="external.edit")
        after = self.drive.get(item.file_id)
        self.assertEqual(after.file_id, before.file_id)
        self.assertGreater(after.version, before.version)
        self.assertNotEqual(after.sha256_checksum, before.sha256_checksum)

    def test_fault_after_remote_mutation_leaves_durable_object_for_recovery(self) -> None:
        drive = DriveModel(fault=FaultInjector("drive.create_blob.after"))
        hub = drive.create_folder("root", "Hub", label="setup.folder")
        with self.assertRaises(InjectedCrash):
            drive.create_blob(hub.file_id, "a", b"payload")
        matches = drive.list_children(hub.file_id, name="a")
        self.assertEqual(len(matches), 1)
        self.assertEqual(drive.download(matches[0].file_id), b"payload")

    def test_folder_has_no_blob_checksum_or_revision(self) -> None:
        folder = self.drive.create_folder(self.hub.file_id, "folder")
        self.assertEqual(folder.mime_type, FOLDER_MIME)
        self.assertIsNone(folder.sha256_checksum)
        self.assertIsNone(folder.head_revision_id)
        blob = self.drive.create_blob(folder.file_id, "blob", b"x", mime_type=BLOB_MIME)
        self.assertIsNotNone(blob.sha256_checksum)
        self.assertIsNotNone(blob.head_revision_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
