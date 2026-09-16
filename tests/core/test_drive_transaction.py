from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from keelaryn_core.drive_model import DriveModel
from keelaryn_core.drive_transaction import BlobState, DriveOperation, DrivePublicationTransaction, DriveRecoveryBlocked
from keelaryn_core.protocol import FaultInjector, InjectedCrash


class DriveTransactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.drive = DriveModel()
        self.hub = self.drive.create_folder("root", "Hub")
        self.canonical = self.drive.create_folder(self.hub.file_id, "canonical")
        self.control = self.drive.create_folder(self.hub.file_id, "control")
        self.stage = self.drive.create_folder(self.control.file_id, "stage")
        self.history = self.drive.create_folder(self.hub.file_id, "history")
        self.original = self.drive.create_folder(self.history.file_id, "original")
        self.rejected = self.drive.create_folder(self.history.file_id, "rejected")
        self.tx = DrivePublicationTransaction(self.drive, self.original.file_id, self.rejected.file_id)

    def _add(self) -> DriveOperation:
        data = b"new add\n"
        staged = self.drive.create_blob(self.stage.file_id, "add.bin", data)
        return DriveOperation(
            "add",
            "ADD",
            self.canonical.file_id,
            "added.txt",
            None,
            BlobState.from_bytes(data),
            staged.file_id,
            self.stage.file_id,
        )

    def _replace(self) -> DriveOperation:
        old = b"old replace\n"
        new = b"new replace\n"
        current = self.drive.create_blob(self.canonical.file_id, "replace.txt", old)
        staged = self.drive.create_blob(self.stage.file_id, "replace.bin", new)
        op = DriveOperation(
            "replace",
            "REPLACE",
            self.canonical.file_id,
            "replace.txt",
            BlobState.from_bytes(old),
            BlobState.from_bytes(new),
            staged.file_id,
            self.stage.file_id,
        )
        self.tx.capture_old_identity(op)
        self.assertEqual(op.old_original_id, current.file_id)
        return op

    def _delete(self) -> DriveOperation:
        old = b"old delete\n"
        current = self.drive.create_blob(self.canonical.file_id, "delete.txt", old)
        op = DriveOperation(
            "delete",
            "DELETE",
            self.canonical.file_id,
            "delete.txt",
            BlobState.from_bytes(old),
            None,
        )
        self.tx.capture_old_identity(op)
        self.assertEqual(op.old_original_id, current.file_id)
        return op

    def test_add_apply_and_rollback(self) -> None:
        op = self._add()
        self.assertEqual(self.tx.classify(op), "OLD")
        self.tx.apply(op)
        self.assertEqual(self.tx.classify(op), "NEW")
        self.tx.rollback(op)
        self.assertEqual(self.tx.classify(op), "OLD")
        self.assertIsNone(self.drive.exact_name(self.canonical.file_id, "added.txt"))
        rejected = self.drive.get(op.staged_new_id)
        self.assertEqual(rejected.parent_id, self.rejected.file_id)

    def test_delete_apply_and_rollback_preserves_old_file_id(self) -> None:
        op = self._delete()
        old_id = op.old_original_id
        self.tx.apply(op)
        self.assertEqual(self.tx.classify(op), "NEW")
        self.assertIsNone(self.drive.exact_name(self.canonical.file_id, "delete.txt"))
        self.tx.rollback(op)
        self.assertEqual(self.tx.classify(op), "OLD")
        restored = self.drive.exact_name(self.canonical.file_id, "delete.txt")
        self.assertEqual(restored.file_id, old_id)

    def test_replace_apply_and_rollback_preserves_both_object_identities(self) -> None:
        op = self._replace()
        old_id = op.old_original_id
        new_id = op.staged_new_id
        self.tx.apply(op)
        self.assertEqual(self.tx.classify(op), "NEW")
        self.assertEqual(self.drive.exact_name(self.canonical.file_id, "replace.txt").file_id, new_id)
        self.assertEqual(self.drive.get(old_id).parent_id, self.original.file_id)
        self.tx.rollback(op)
        self.assertEqual(self.tx.classify(op), "OLD")
        self.assertEqual(self.drive.exact_name(self.canonical.file_id, "replace.txt").file_id, old_id)
        self.assertEqual(self.drive.get(new_id).parent_id, self.rejected.file_id)

    def test_replace_restart_after_old_displacement_completes_apply(self) -> None:
        drive = DriveModel(fault=FaultInjector("drive.tx.replace.replace.displace_old.after"))
        hub = drive.create_folder("root", "Hub", label="setup.hub")
        canonical = drive.create_folder(hub.file_id, "canonical", label="setup.canonical")
        stage = drive.create_folder(hub.file_id, "stage", label="setup.stage")
        history = drive.create_folder(hub.file_id, "history", label="setup.history")
        original = drive.create_folder(history.file_id, "original", label="setup.original")
        rejected = drive.create_folder(history.file_id, "rejected", label="setup.rejected")
        old = b"old"
        new = b"new"
        old_item = drive.create_blob(canonical.file_id, "x", old, label="setup.old")
        new_item = drive.create_blob(stage.file_id, "new", new, label="setup.new")
        op = DriveOperation(
            "replace",
            "REPLACE",
            canonical.file_id,
            "x",
            BlobState.from_bytes(old),
            BlobState.from_bytes(new),
            new_item.file_id,
            stage.file_id,
            old_item.file_id,
        )
        tx = DrivePublicationTransaction(drive, original.file_id, rejected.file_id)
        with self.assertRaises(InjectedCrash):
            tx.apply(op)
        self.assertEqual(tx.classify(op), "OLD_DISPLACED")
        tx.apply(op)
        self.assertEqual(tx.classify(op), "NEW")

    def test_replace_restart_mid_rollback_restores_old(self) -> None:
        op = self._replace()
        self.tx.apply(op)
        self.drive.fault.point = "drive.tx.replace.replace.reject_new.after"
        self.drive.fault.fired = False
        with self.assertRaises(InjectedCrash):
            self.tx.rollback(op)
        self.assertEqual(self.tx.classify(op), "NEW_REJECTED")
        self.tx.rollback(op)
        self.assertEqual(self.tx.classify(op), "OLD")

    def test_replace_can_rollback_directly_from_old_displaced(self) -> None:
        op = self._replace()
        self.drive.move_rename(
            op.old_original_id,
            self.original.file_id,
            "replace.old",
            label="manual.displace",
        )
        self.assertEqual(self.tx.classify(op), "OLD_DISPLACED")
        self.tx.rollback(op)
        self.assertEqual(self.tx.classify(op), "OLD")

    def test_external_edit_of_published_new_blocks_rollback(self) -> None:
        op = self._replace()
        self.tx.apply(op)
        self.drive.update_content(op.staged_new_id, b"external mutation", label="external.edit")
        self.assertEqual(self.tx.classify(op), "UNKNOWN")
        with self.assertRaises(DriveRecoveryBlocked):
            self.tx.rollback(op)
        self.assertEqual(self.drive.download(op.staged_new_id), b"external mutation")

    def test_duplicate_canonical_target_fails_closed(self) -> None:
        op = self._add()
        self.drive.create_blob(self.canonical.file_id, "added.txt", b"external one")
        self.drive.create_blob(self.canonical.file_id, "added.txt", b"external two")
        with self.assertRaises(DriveRecoveryBlocked):
            self.tx.classify(op)

    def test_old_identity_changed_after_capture_blocks_apply(self) -> None:
        op = self._replace()
        self.drive.update_content(op.old_original_id, b"external old mutation", label="external.old")
        self.assertEqual(self.tx.classify(op), "UNKNOWN")
        with self.assertRaises(DriveRecoveryBlocked):
            self.tx.apply(op)


if __name__ == "__main__":
    unittest.main(verbosity=2)
