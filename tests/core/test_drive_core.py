from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from keelaryn_core.drive_bundle import DriveTransactionBundle
from keelaryn_core.drive_control import DriveControl
from keelaryn_core.drive_core import DriveCoreBlocked, DriveCoreRunner
from keelaryn_core.drive_execution_rollback import (
    DriveExecutionRollbackBinding,
    DriveExecutionRollbackMarker,
)
from keelaryn_core.drive_master import DriveMasterTransition
from keelaryn_core.drive_model import DriveModel
from keelaryn_core.drive_postcheck import DrivePostcheckBinding
from keelaryn_core.drive_snapshot import DriveSnapshotPlan
from keelaryn_core.drive_transaction import BlobState, DriveOperation
from keelaryn_core.protocol import (
    FaultInjector,
    InjectedCrash,
    ProtocolError,
    canonical_json_bytes,
    strict_json_bytes,
    validate_master,
)


CHANGE_SHA = "f" * 64
EPOCH = 3


def ready_master() -> bytes:
    return canonical_json_bytes(
        {
            "schema": "keelaryn.master.v1",
            "state": "READY",
            "canonical_read_status": "SAFE",
            "canonical_epoch": EPOCH,
            "active_change": None,
            "current_stage": None,
            "last_completed_change": None,
        }
    )


def active_master(*, unsafe: bool) -> bytes:
    return canonical_json_bytes(
        {
            "schema": "keelaryn.master.v1",
            "state": "ACTIVE",
            "canonical_read_status": "UNSAFE" if unsafe else "SAFE",
            "canonical_epoch": EPOCH,
            "active_change": {
                "change_id": "change-1",
                "change_sha256": CHANGE_SHA,
                "base_canonical_epoch": EPOCH,
            },
            "current_stage": "APPLY" if unsafe else "SNAPSHOT",
            "last_completed_change": None,
        }
    )


def final_master(outcome: str) -> bytes:
    return canonical_json_bytes(
        {
            "schema": "keelaryn.master.v1",
            "state": "READY",
            "canonical_read_status": "SAFE",
            "canonical_epoch": EPOCH + 1,
            "active_change": None,
            "current_stage": None,
            "last_completed_change": {
                "change_id": "change-1",
                "change_sha256": CHANGE_SHA,
                "outcome": outcome,
                "completed_epoch": EPOCH + 1,
            },
        }
    )


def postcheck_bytes(decision: str) -> bytes:
    return canonical_json_bytes(
        {
            "schema": "keelaryn.postcheck.v1",
            "change_id": "change-1",
            "change_sha256": CHANGE_SHA,
            "base_canonical_epoch": EPOCH,
            "decision": decision,
            "reason": f"semantic {decision}",
        }
    )


@dataclass
class Fixture:
    drive: DriveModel
    bundle: DriveTransactionBundle
    canonical_id: str
    postcheck_parent_id: str
    postcheck_name: str
    add_new_id: str
    replace_old_id: str
    replace_new_id: str
    delete_old_id: str


class FailOnceApplyBackend:
    def __init__(self, inner: DriveModel) -> None:
        self.inner = inner
        self.fired = False

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def move_rename(self, file_id, parent_id, name, *, label="drive.move_rename"):
        if not self.fired and label == "drive.tx.add.add.publish":
            self.fired = True
            raise ProtocolError("deterministic apply failure before ADD mutation")
        return self.inner.move_rename(file_id, parent_id, name, label=label)


class DriveCoreTests(unittest.TestCase):
    def build(self, *, decision: str | None = None, crash_point: str | None = None) -> Fixture:
        drive = DriveModel(fault=FaultInjector(crash_point))
        hub = drive.create_folder("root", "Hub", label="setup.hub")
        canonical = drive.create_folder(hub.file_id, "canonical", label="setup.canonical")
        stage = drive.create_folder(hub.file_id, "stage", label="setup.stage")
        history = drive.create_folder(hub.file_id, "history", label="setup.history")
        bundle_parent = drive.create_folder(history.file_id, "change-1", label="setup.bundle-parent")
        snapshots_parent = drive.create_folder(bundle_parent.file_id, "snapshots", label="setup.snapshots")
        originals = drive.create_folder(bundle_parent.file_id, "originals", label="setup.originals")
        rejected = drive.create_folder(bundle_parent.file_id, "rejected", label="setup.rejected")
        transitions = drive.create_folder(hub.file_id, "master-transitions", label="setup.transitions")
        postcheck_parent = drive.create_folder(hub.file_id, "postcheck", label="setup.postcheck")
        receipts = drive.create_folder(bundle_parent.file_id, "receipts", label="setup.receipts")
        markers = drive.create_folder(bundle_parent.file_id, "markers", label="setup.markers")

        drive.create_blob(hub.file_id, "MASTER.json", ready_master(), label="setup.master")

        replace_old = b"replace-old"
        replace_new = b"replace-new"
        delete_old = b"delete-old"
        add_new = b"add-new"
        replace_old_item = drive.create_blob(canonical.file_id, "replace.txt", replace_old, label="setup.replace-old")
        delete_old_item = drive.create_blob(canonical.file_id, "delete.txt", delete_old, label="setup.delete-old")
        replace_new_item = drive.create_blob(stage.file_id, "replace.new", replace_new, label="setup.replace-new")
        add_new_item = drive.create_blob(stage.file_id, "add.new", add_new, label="setup.add-new")

        control = DriveControl(
            change_id="change-1",
            hub_root_id=hub.file_id,
            canonical_root_id=canonical.file_id,
            history_original_parent_id=originals.file_id,
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
        snapshots = DriveSnapshotPlan.plan(drive, control, snapshots_parent.file_id)
        postcheck = DrivePostcheckBinding.plan(
            drive,
            change_id="change-1",
            change_sha256=CHANGE_SHA,
            base_canonical_epoch=EPOCH,
            source_parent_id=postcheck_parent.file_id,
            source_name="change-1.json",
            receipt_parent_id=receipts.file_id,
        )
        execution = DriveExecutionRollbackBinding.plan(
            drive,
            change_id="change-1",
            change_sha256=CHANGE_SHA,
            base_canonical_epoch=EPOCH,
            marker_parent_id=markers.file_id,
        )
        bundle = DriveTransactionBundle.plan(
            drive,
            change_sha256=CHANGE_SHA,
            base_canonical_epoch=EPOCH,
            bundle_parent_id=bundle_parent.file_id,
            master_transition_parent_id=transitions.file_id,
            control=control,
            snapshot_plan=snapshots,
            postcheck_binding=postcheck,
            execution_rollback_binding=execution,
            active_safe_master_bytes=active_master(unsafe=False),
            active_unsafe_master_bytes=active_master(unsafe=True),
            committed_master_bytes=final_master("COMMITTED"),
            rolled_back_master_bytes=final_master("ROLLED_BACK"),
        )
        if decision is not None:
            drive.create_blob(
                postcheck_parent.file_id,
                "change-1.json",
                postcheck_bytes(decision),
                label="setup.postcheck-decision",
            )
        return Fixture(
            drive=drive,
            bundle=bundle,
            canonical_id=canonical.file_id,
            postcheck_parent_id=postcheck_parent.file_id,
            postcheck_name="change-1.json",
            add_new_id=add_new_item.file_id,
            replace_old_id=replace_old_item.file_id,
            replace_new_id=replace_new_item.file_id,
            delete_old_id=delete_old_item.file_id,
        )

    def assert_new(self, fixture: Fixture) -> None:
        drive = fixture.drive
        self.assertEqual(drive.exact_name(fixture.canonical_id, "added.txt").file_id, fixture.add_new_id)
        self.assertEqual(drive.exact_name(fixture.canonical_id, "replace.txt").file_id, fixture.replace_new_id)
        self.assertIsNone(drive.exact_name(fixture.canonical_id, "delete.txt"))

    def assert_old(self, fixture: Fixture) -> None:
        drive = fixture.drive
        self.assertIsNone(drive.exact_name(fixture.canonical_id, "added.txt"))
        self.assertEqual(drive.exact_name(fixture.canonical_id, "replace.txt").file_id, fixture.replace_old_id)
        self.assertEqual(drive.exact_name(fixture.canonical_id, "delete.txt").file_id, fixture.delete_old_id)

    def final_master_value(self, fixture: Fixture):
        _, raw = DriveMasterTransition.read_unique_master(fixture.drive, fixture.bundle.hub_root_id)
        return validate_master(strict_json_bytes(raw, label="MASTER.final"))

    def test_wait_then_pass_commits_from_bundle_only_restart(self) -> None:
        fixture = self.build()
        raw_bundle = fixture.bundle.to_bytes()
        status = DriveCoreRunner(fixture.drive, fixture.bundle).run_until_quiescent()
        self.assertEqual(status.phase, "WAIT_POSTCHECK")
        self.assertEqual(DriveCoreRunner(fixture.drive, fixture.bundle).phase(), "ACTIVE_UNSAFE")
        self.assert_new(fixture)

        fixture.drive.create_blob(
            fixture.postcheck_parent_id,
            fixture.postcheck_name,
            postcheck_bytes("PASS"),
            label="external.postcheck.pass",
        )
        restored = DriveTransactionBundle.from_bytes(raw_bundle)
        status = DriveCoreRunner(fixture.drive, restored).run_until_quiescent()
        self.assertEqual(status.phase, "COMMITTED")
        self.assert_new(fixture)
        master = self.final_master_value(fixture)
        self.assertEqual(master["canonical_epoch"], EPOCH + 1)
        self.assertEqual(master["last_completed_change"]["outcome"], "COMMITTED")

    def test_fail_decision_rolls_back_and_increments_epoch(self) -> None:
        fixture = self.build(decision="FAIL")
        raw_bundle = fixture.bundle.to_bytes()
        status = DriveCoreRunner(fixture.drive, fixture.bundle).run_until_quiescent()
        self.assertEqual(status.phase, "ROLLED_BACK")
        self.assert_old(fixture)
        self.assertEqual(DriveCoreRunner(fixture.drive, DriveTransactionBundle.from_bytes(raw_bundle)).phase(), "ROLLED_BACK")
        master = self.final_master_value(fixture)
        self.assertEqual(master["canonical_epoch"], EPOCH + 1)
        self.assertEqual(master["last_completed_change"]["outcome"], "ROLLED_BACK")

    def test_staged_corruption_in_active_safe_aborts_without_epoch_change(self) -> None:
        fixture = self.build()
        runner = DriveCoreRunner(fixture.drive, fixture.bundle)
        self.assertEqual(runner.run_once().phase, "PROGRESSED")
        self.assertEqual(runner.phase(), "ACTIVE_SAFE")
        fixture.drive.update_content(fixture.add_new_id, b"corrupted", label="external.corrupt-staged")

        status = runner.run_until_quiescent()
        self.assertEqual(status.phase, "ABORTED_SAFE")
        self.assert_old(fixture)
        master = self.final_master_value(fixture)
        self.assertEqual(master["state"], "READY")
        self.assertEqual(master["canonical_epoch"], EPOCH)
        self.assertIsNone(master["last_completed_change"])

    def test_deterministic_apply_failure_records_marker_then_rolls_back(self) -> None:
        fixture = self.build()
        backend = FailOnceApplyBackend(fixture.drive)
        status = DriveCoreRunner(backend, fixture.bundle).run_until_quiescent()
        self.assertEqual(status.phase, "ROLLED_BACK")
        self.assertTrue(backend.fired)
        self.assertTrue(DriveExecutionRollbackMarker(fixture.drive, fixture.bundle.execution_rollback_binding).active())
        self.assert_old(fixture)
        self.assertEqual(self.final_master_value(fixture)["last_completed_change"]["outcome"], "ROLLED_BACK")

    def test_snapshot_corruption_after_unsafe_blocks_commit(self) -> None:
        fixture = self.build()
        runner = DriveCoreRunner(fixture.drive, fixture.bundle)
        self.assertEqual(runner.run_until_quiescent().phase, "WAIT_POSTCHECK")
        snapshot_id = fixture.bundle.snapshot_plan.entries[0].snapshot_id
        fixture.drive.update_content(snapshot_id, b"damaged snapshot", label="external.damage-snapshot")
        fixture.drive.create_blob(
            fixture.postcheck_parent_id,
            fixture.postcheck_name,
            postcheck_bytes("PASS"),
            label="external.postcheck.pass",
        )
        with self.assertRaises(DriveCoreBlocked):
            DriveCoreRunner(fixture.drive, DriveTransactionBundle.from_bytes(fixture.bundle.to_bytes())).run_until_quiescent()
        self.assertEqual(DriveCoreRunner(fixture.drive, fixture.bundle).phase(), "ACTIVE_UNSAFE")

    def test_commit_crash_matrix_recovers_from_bundle_bytes_only(self) -> None:
        points = [
            "drive.bundle.change-1.create.after",
            "drive.master.change-1.activate.candidate.create.after",
            "drive.master.change-1.activate.displace_old.after",
            "drive.master.change-1.activate.publish_candidate.after",
            "drive.snapshot.change-1.replace.copy.after",
            "drive.snapshot.change-1.delete.copy.after",
            "drive.master.change-1.unsafe.candidate.create.after",
            "drive.master.change-1.unsafe.displace_old.after",
            "drive.master.change-1.unsafe.publish_candidate.after",
            "drive.tx.add.add.publish.after",
            "drive.tx.replace.replace.displace_old.after",
            "drive.tx.replace.replace.publish_new.after",
            "drive.tx.delete.delete.displace_old.after",
            "drive.postcheck.change-1.PASS.receipt.create.after",
            "drive.master.change-1.commit.candidate.create.after",
            "drive.master.change-1.commit.displace_old.after",
            "drive.master.change-1.commit.publish_candidate.after",
        ]
        for point in points:
            with self.subTest(point=point):
                fixture = self.build(decision="PASS", crash_point=point)
                raw_bundle = fixture.bundle.to_bytes()
                with self.assertRaises(InjectedCrash):
                    DriveCoreRunner(fixture.drive, fixture.bundle).run_until_quiescent()
                restored = DriveTransactionBundle.from_bytes(raw_bundle)
                status = DriveCoreRunner(fixture.drive, restored).run_until_quiescent()
                self.assertEqual(status.phase, "COMMITTED")
                self.assert_new(fixture)

    def test_rollback_crash_matrix_recovers_from_bundle_bytes_only(self) -> None:
        points = [
            "drive.postcheck.change-1.FAIL.receipt.create.after",
            "drive.tx.delete.delete.rollback.after",
            "drive.tx.replace.replace.reject_new.after",
            "drive.tx.replace.replace.restore_old.after",
            "drive.tx.add.add.rollback.after",
            "drive.master.change-1.rollback.candidate.create.after",
            "drive.master.change-1.rollback.displace_old.after",
            "drive.master.change-1.rollback.publish_candidate.after",
        ]
        for point in points:
            with self.subTest(point=point):
                fixture = self.build(decision="FAIL", crash_point=point)
                raw_bundle = fixture.bundle.to_bytes()
                with self.assertRaises(InjectedCrash):
                    DriveCoreRunner(fixture.drive, fixture.bundle).run_until_quiescent()
                restored = DriveTransactionBundle.from_bytes(raw_bundle)
                status = DriveCoreRunner(fixture.drive, restored).run_until_quiescent()
                self.assertEqual(status.phase, "ROLLED_BACK")
                self.assert_old(fixture)


if __name__ == "__main__":
    unittest.main(verbosity=2)
