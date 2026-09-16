from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from drive_http_model import ModelDriveHttp
from keelaryn_core.drive_backend import DriveUncertainMutation
from keelaryn_core.drive_control import DriveControl
from keelaryn_core.drive_model import DriveModel
from keelaryn_core.drive_rest import GoogleDriveBackend
from keelaryn_core.drive_snapshot import DriveSnapshotBlocked, DriveSnapshotPlan, DriveSnapshotter
from keelaryn_core.drive_transaction import BlobState, DriveOperation
from keelaryn_core.protocol import FaultInjector, InjectedCrash


class DriveSnapshotTests(unittest.TestCase):
    def build(self, *, fault_point: str | None = None):
        drive = DriveModel(fault=FaultInjector(fault_point))
        hub = drive.create_folder("root", "Hub", label="setup.hub")
        canonical = drive.create_folder(hub.file_id, "canonical", label="setup.canonical")
        stage = drive.create_folder(hub.file_id, "stage", label="setup.stage")
        snapshot_parent = drive.create_folder(hub.file_id, "snapshot", label="setup.snapshot")
        rejected = drive.create_folder(hub.file_id, "rejected", label="setup.rejected")

        replace_old = b"replace old"
        replace_new = b"replace new"
        delete_old = b"delete old"
        add_new = b"add new"
        replace_old_item = drive.create_blob(canonical.file_id, "replace.txt", replace_old, label="setup.replace-old")
        delete_old_item = drive.create_blob(canonical.file_id, "delete.txt", delete_old, label="setup.delete-old")
        replace_new_item = drive.create_blob(stage.file_id, "replace.new", replace_new, label="setup.replace-new")
        add_new_item = drive.create_blob(stage.file_id, "add.new", add_new, label="setup.add-new")

        control = DriveControl(
            change_id="snap",
            hub_root_id=hub.file_id,
            canonical_root_id=canonical.file_id,
            history_original_parent_id=snapshot_parent.file_id,
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
        return drive, control, snapshot_parent.file_id

    @staticmethod
    def rest(drive: DriveModel, *, fail_after_mutation: int | None = None) -> GoogleDriveBackend:
        return GoogleDriveBackend("token", http=ModelDriveHttp(drive, fail_after_mutation=fail_after_mutation))

    def test_plan_roundtrip_and_verified_independent_snapshots(self) -> None:
        drive, control, snapshot_parent = self.build()
        plan = DriveSnapshotPlan.plan(drive, control, snapshot_parent)
        raw = plan.to_bytes()
        restored = DriveSnapshotPlan.from_bytes(raw)
        self.assertEqual(restored, plan)
        self.assertEqual([entry.operation_id for entry in plan.entries], ["replace", "delete"])

        snapshots = DriveSnapshotter(drive, restored).ensure_all()
        self.assertEqual(len(snapshots), 2)
        for entry, snapshot in zip(restored.entries, snapshots, strict=True):
            self.assertEqual(snapshot.file_id, entry.snapshot_id)
            self.assertNotEqual(snapshot.file_id, entry.source_id)
            self.assertEqual(snapshot.parent_id, snapshot_parent)
            self.assertEqual(drive.download(snapshot.file_id), drive.download(entry.source_id))
        self.assertEqual(len(DriveSnapshotter(drive, restored).verify_all()), 2)

    def test_direct_copy_crash_recovers_from_plan_only(self) -> None:
        drive, control, snapshot_parent = self.build()
        plan = DriveSnapshotPlan.plan(drive, control, snapshot_parent)
        raw = plan.to_bytes()
        drive.fault.point = "drive.snapshot.snap.replace.copy.after"
        drive.fault.fired = False
        with self.assertRaises(InjectedCrash):
            DriveSnapshotter(drive, plan).ensure_all()

        drive.fault.point = None
        drive.fault.fired = False
        restarted = DriveSnapshotter(drive, DriveSnapshotPlan.from_bytes(raw))
        self.assertEqual(len(restarted.ensure_all()), 2)
        self.assertEqual(len(restarted.verify_all()), 2)

    def test_source_edit_before_snapshot_blocks(self) -> None:
        drive, control, snapshot_parent = self.build()
        plan = DriveSnapshotPlan.plan(drive, control, snapshot_parent)
        replace = plan.entries[0]
        drive.update_content(replace.source_id, b"external mutation")
        with self.assertRaises(DriveSnapshotBlocked):
            DriveSnapshotter(drive, plan).ensure_all()

    def test_snapshot_edit_after_copy_blocks_verification(self) -> None:
        drive, control, snapshot_parent = self.build()
        plan = DriveSnapshotPlan.plan(drive, control, snapshot_parent)
        snapshotter = DriveSnapshotter(drive, plan)
        snapshotter.ensure_all()
        drive.update_content(plan.entries[0].snapshot_id, b"corrupt snapshot")
        with self.assertRaises(DriveSnapshotBlocked):
            snapshotter.verify_all()

    def test_snapshot_move_after_copy_blocks_verification(self) -> None:
        drive, control, snapshot_parent = self.build()
        other = drive.create_folder(control.hub_root_id, "other")
        plan = DriveSnapshotPlan.plan(drive, control, snapshot_parent)
        snapshotter = DriveSnapshotter(drive, plan)
        snapshotter.ensure_all()
        entry = plan.entries[0]
        drive.move_rename(entry.snapshot_id, other.file_id, entry.snapshot_name)
        with self.assertRaises(DriveSnapshotBlocked):
            snapshotter.verify_all()

    def test_rest_lost_copy_response_recovers_by_reserved_snapshot_id(self) -> None:
        drive, control, snapshot_parent = self.build()
        plan = DriveSnapshotPlan.plan(self.rest(drive), control, snapshot_parent)
        raw = plan.to_bytes()
        failing = DriveSnapshotter(self.rest(drive, fail_after_mutation=1), plan)
        with self.assertRaises(DriveUncertainMutation):
            failing.ensure_all()

        restarted = DriveSnapshotter(self.rest(drive), DriveSnapshotPlan.from_bytes(raw))
        self.assertEqual(len(restarted.ensure_all()), 2)
        self.assertEqual(len(restarted.verify_all()), 2)

    def test_add_only_change_has_no_snapshot_entries(self) -> None:
        drive, control, snapshot_parent = self.build()
        add_only = DriveControl(
            change_id="add-only",
            hub_root_id=control.hub_root_id,
            canonical_root_id=control.canonical_root_id,
            history_original_parent_id=control.history_original_parent_id,
            rejected_parent_id=control.rejected_parent_id,
            operations=(control.operations[0],),
        )
        plan = DriveSnapshotPlan.plan(drive, add_only, snapshot_parent)
        self.assertEqual(plan.entries, ())
        self.assertEqual(DriveSnapshotter(drive, plan).ensure_all(), ())


if __name__ == "__main__":
    unittest.main(verbosity=2)
