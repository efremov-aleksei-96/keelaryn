from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from keelaryn_core.drive_change import DriveChangeRunner
from keelaryn_core.drive_control import DriveControl
from keelaryn_core.drive_model import DriveModel
from keelaryn_core.drive_transaction import BlobState, DriveOperation
from keelaryn_core.protocol import FaultInjector, InjectedCrash


class DriveChangeTests(unittest.TestCase):
    def build(self, crash_point: str | None = None) -> tuple[DriveModel, DriveControl, bytes, str, str, str]:
        drive = DriveModel(fault=FaultInjector(crash_point))
        hub = drive.create_folder("root", "Hub", label="setup.hub")
        canonical = drive.create_folder(hub.file_id, "canonical", label="setup.canonical")
        control_parent = drive.create_folder(hub.file_id, "control", label="setup.control")
        stage = drive.create_folder(control_parent.file_id, "stage", label="setup.stage")
        history = drive.create_folder(hub.file_id, "history", label="setup.history")
        original = drive.create_folder(history.file_id, "original", label="setup.original")
        rejected = drive.create_folder(history.file_id, "rejected", label="setup.rejected")

        replace_old = b"replace old"
        replace_new = b"replace new"
        delete_old = b"delete old"
        add_new = b"add new"
        replace_old_item = drive.create_blob(canonical.file_id, "replace.txt", replace_old, label="setup.replace-old")
        delete_old_item = drive.create_blob(canonical.file_id, "delete.txt", delete_old, label="setup.delete-old")
        replace_new_item = drive.create_blob(stage.file_id, "replace.new", replace_new, label="setup.replace-new")
        add_new_item = drive.create_blob(stage.file_id, "add.new", add_new, label="setup.add-new")

        control = DriveControl(
            change_id="multi",
            hub_root_id=hub.file_id,
            canonical_root_id=canonical.file_id,
            history_original_parent_id=original.file_id,
            rejected_parent_id=rejected.file_id,
            operations=(
                DriveOperation(
                    "add",
                    "ADD",
                    canonical.file_id,
                    "added.txt",
                    None,
                    BlobState.from_bytes(add_new),
                    add_new_item.file_id,
                    stage.file_id,
                    None,
                ),
                DriveOperation(
                    "replace",
                    "REPLACE",
                    canonical.file_id,
                    "replace.txt",
                    BlobState.from_bytes(replace_old),
                    BlobState.from_bytes(replace_new),
                    replace_new_item.file_id,
                    stage.file_id,
                    replace_old_item.file_id,
                ),
                DriveOperation(
                    "delete",
                    "DELETE",
                    canonical.file_id,
                    "delete.txt",
                    BlobState.from_bytes(delete_old),
                    None,
                    None,
                    None,
                    delete_old_item.file_id,
                ),
            ),
        )
        return drive, control, control.to_bytes(), canonical.file_id, replace_old_item.file_id, delete_old_item.file_id

    def test_apply_then_semantic_fail_rollback(self) -> None:
        drive, control, _, canonical, replace_old_id, delete_old_id = self.build()
        runner = DriveChangeRunner(drive, control)
        self.assertTrue(runner.apply_all().all_new)
        self.assertEqual(drive.exact_name(canonical, "replace.txt").file_id, control.operations[1].staged_new_id)
        self.assertIsNone(drive.exact_name(canonical, "delete.txt"))
        self.assertTrue(runner.rollback_all().all_old)
        self.assertIsNone(drive.exact_name(canonical, "added.txt"))
        self.assertEqual(drive.exact_name(canonical, "replace.txt").file_id, replace_old_id)
        self.assertEqual(drive.exact_name(canonical, "delete.txt").file_id, delete_old_id)

    def test_apply_crash_matrix_recovers_from_control_only(self) -> None:
        points = [
            "drive.tx.add.add.publish.after",
            "drive.tx.replace.replace.displace_old.after",
            "drive.tx.replace.replace.publish_new.after",
            "drive.tx.delete.delete.displace_old.after",
        ]
        for point in points:
            with self.subTest(point=point):
                drive, control, raw, _, _, _ = self.build(point)
                runner = DriveChangeRunner(drive, control)
                with self.assertRaises(InjectedCrash):
                    runner.apply_all()
                restored = DriveControl.from_bytes(raw)
                restarted = DriveChangeRunner(drive, restored)
                self.assertTrue(restarted.apply_all().all_new)

    def test_rollback_crash_matrix_recovers_from_control_only(self) -> None:
        points = [
            "drive.tx.delete.delete.rollback.after",
            "drive.tx.replace.replace.reject_new.after",
            "drive.tx.replace.replace.restore_old.after",
            "drive.tx.add.add.rollback.after",
        ]
        for point in points:
            with self.subTest(point=point):
                drive, control, raw, _, _, _ = self.build()
                runner = DriveChangeRunner(drive, control)
                self.assertTrue(runner.apply_all().all_new)
                drive.fault.point = point
                drive.fault.fired = False
                with self.assertRaises(InjectedCrash):
                    runner.rollback_all()
                restored = DriveControl.from_bytes(raw)
                restarted = DriveChangeRunner(drive, restored)
                self.assertTrue(restarted.rollback_all().all_old)


if __name__ == "__main__":
    unittest.main(verbosity=2)
