from __future__ import annotations

import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from drive_http_model import ModelDriveHttp
from keelaryn_core.drive_backend import DriveUncertainMutation
from keelaryn_core.drive_bundle import (
    DriveBundleBlocked,
    DriveBundleStore,
    DriveTransactionBundle,
    ExactJsonComponent,
)
from keelaryn_core.drive_control import DriveControl
from keelaryn_core.drive_execution_rollback import DriveExecutionRollbackBinding
from keelaryn_core.drive_model import DriveModel
from keelaryn_core.drive_postcheck import DrivePostcheckBinding
from keelaryn_core.drive_rest import GoogleDriveBackend
from keelaryn_core.drive_snapshot import DriveSnapshotPlan
from keelaryn_core.drive_transaction import BlobState, DriveOperation
from keelaryn_core.protocol import canonical_json_bytes


CHANGE_SHA = "b" * 64
EPOCH = 11


def master_ready(*, epoch: int, completed=None) -> bytes:
    return canonical_json_bytes(
        {
            "schema": "keelaryn.master.v1",
            "state": "READY",
            "canonical_read_status": "SAFE",
            "canonical_epoch": epoch,
            "active_change": None,
            "current_stage": None,
            "last_completed_change": completed,
        }
    )


def master_active(*, unsafe: bool, completed=None) -> bytes:
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
            "last_completed_change": completed,
        }
    )


def master_completed(outcome: str) -> bytes:
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


class DriveBundleTests(unittest.TestCase):
    def build(self) -> tuple[DriveModel, DriveTransactionBundle]:
        drive = DriveModel()
        hub = drive.create_folder("root", "Hub")
        canonical = drive.create_folder(hub.file_id, "canonical")
        stage = drive.create_folder(hub.file_id, "stage")
        history = drive.create_folder(hub.file_id, "history")
        bundle_parent = drive.create_folder(history.file_id, "change-1")
        snapshots_parent = drive.create_folder(bundle_parent.file_id, "snapshots")
        originals = drive.create_folder(bundle_parent.file_id, "originals")
        rejected = drive.create_folder(bundle_parent.file_id, "rejected")
        transitions = drive.create_folder(hub.file_id, "master-transitions")
        source_postcheck = drive.create_folder(hub.file_id, "postcheck")
        receipt_parent = drive.create_folder(bundle_parent.file_id, "receipts")
        control_markers = drive.create_folder(bundle_parent.file_id, "control-markers")

        previous_completed = {
            "change_id": "previous",
            "change_sha256": "c" * 64,
            "outcome": "COMMITTED",
            "completed_epoch": EPOCH,
        }
        drive.create_blob(hub.file_id, "MASTER.json", master_ready(epoch=EPOCH, completed=previous_completed))

        old_bytes = b"old canonical bytes"
        new_bytes = b"new canonical bytes"
        old_item = drive.create_blob(canonical.file_id, "topic.md", old_bytes)
        staged = drive.create_blob(stage.file_id, "topic.new", new_bytes)
        control = DriveControl(
            change_id="change-1",
            hub_root_id=hub.file_id,
            canonical_root_id=canonical.file_id,
            history_original_parent_id=originals.file_id,
            rejected_parent_id=rejected.file_id,
            operations=(
                DriveOperation(
                    operation_id="replace-topic",
                    kind="REPLACE",
                    canonical_parent_id=canonical.file_id,
                    target_name="topic.md",
                    old=BlobState.from_bytes(old_bytes),
                    new=BlobState.from_bytes(new_bytes),
                    staged_new_id=staged.file_id,
                    staged_parent_id=stage.file_id,
                    old_original_id=old_item.file_id,
                ),
            ),
        )
        snapshot_plan = DriveSnapshotPlan.plan(drive, control, snapshots_parent.file_id)
        postcheck = DrivePostcheckBinding.plan(
            drive,
            change_id="change-1",
            change_sha256=CHANGE_SHA,
            base_canonical_epoch=EPOCH,
            source_parent_id=source_postcheck.file_id,
            source_name="change-1.json",
            receipt_parent_id=receipt_parent.file_id,
        )
        execution_rollback = DriveExecutionRollbackBinding.plan(
            drive,
            change_id="change-1",
            change_sha256=CHANGE_SHA,
            base_canonical_epoch=EPOCH,
            marker_parent_id=control_markers.file_id,
        )
        bundle = DriveTransactionBundle.plan(
            drive,
            change_sha256=CHANGE_SHA,
            base_canonical_epoch=EPOCH,
            bundle_parent_id=bundle_parent.file_id,
            master_transition_parent_id=transitions.file_id,
            control=control,
            snapshot_plan=snapshot_plan,
            postcheck_binding=postcheck,
            execution_rollback_binding=execution_rollback,
            active_safe_master_bytes=master_active(unsafe=False, completed=previous_completed),
            active_unsafe_master_bytes=master_active(unsafe=True, completed=previous_completed),
            committed_master_bytes=master_completed("COMMITTED"),
            rolled_back_master_bytes=master_completed("ROLLED_BACK"),
        )
        return drive, bundle

    def test_bundle_roundtrip_binds_exact_subcontracts_and_master_chain(self) -> None:
        _, bundle = self.build()
        raw = bundle.to_bytes()
        restored = DriveTransactionBundle.from_bytes(raw)
        self.assertEqual(restored, bundle)
        self.assertEqual(restored.control.change_id, "change-1")
        self.assertEqual(restored.snapshot_plan.entries[0].operation_id, "replace-topic")
        self.assertNotEqual(restored.postcheck_binding.pass_receipt_id, restored.postcheck_binding.fail_receipt_id)
        self.assertNotIn(
            restored.execution_rollback_binding.marker_id,
            {restored.postcheck_binding.pass_receipt_id, restored.postcheck_binding.fail_receipt_id},
        )
        self.assertEqual(restored.unsafe_binding.old_master_id, restored.activate_binding.candidate_master_id)
        self.assertEqual(restored.commit_binding.old_master_id, restored.unsafe_binding.candidate_master_id)
        self.assertEqual(restored.rollback_binding.old_master_id, restored.unsafe_binding.candidate_master_id)

    def test_starting_ready_master_is_exact_component_and_preserves_previous_completion(self) -> None:
        _, bundle = self.build()
        starting = json.loads(bundle.starting_ready_master_component.raw.decode())
        active = json.loads(bundle.active_safe_master_component.raw.decode())
        self.assertEqual(starting["last_completed_change"], active["last_completed_change"])
        self.assertEqual(bundle.activate_binding.old_state, BlobState.from_bytes(bundle.starting_ready_master_component.raw))

    def test_store_is_idempotent_and_detects_later_bundle_mutation(self) -> None:
        drive, bundle = self.build()
        store = DriveBundleStore(drive, bundle)
        first = store.ensure()
        second = store.ensure()
        self.assertEqual(first.file_id, bundle.bundle_file_id)
        self.assertEqual(second.file_id, bundle.bundle_file_id)
        self.assertEqual(drive.download(bundle.bundle_file_id), bundle.to_bytes())

        drive.update_content(bundle.bundle_file_id, b"{}")
        with self.assertRaises(DriveBundleBlocked):
            store.verify()

    def test_component_byte_tamper_is_rejected_before_cross_contract_parsing(self) -> None:
        _, bundle = self.build()
        value = json.loads(bundle.to_bytes().decode())
        value["components"]["control"]["text"] += " "
        tampered = canonical_json_bytes(value)
        with self.assertRaises(DriveBundleBlocked):
            DriveTransactionBundle.from_bytes(tampered)

    def test_cross_component_snapshot_change_identity_mismatch_is_rejected(self) -> None:
        _, bundle = self.build()
        snapshots = bundle.snapshot_plan
        bad_plan = replace(snapshots, change_id="other-change")
        bad = replace(bundle, snapshot_component=ExactJsonComponent(bad_plan.to_bytes()))
        with self.assertRaises(DriveBundleBlocked):
            bad.to_bytes()

    def test_reserved_identity_collision_is_rejected(self) -> None:
        _, bundle = self.build()
        bad = replace(bundle, bundle_file_id=bundle.postcheck_binding.pass_receipt_id)
        with self.assertRaises(DriveBundleBlocked):
            bad.to_bytes()

    def test_active_safe_master_cannot_change_previous_completion(self) -> None:
        _, bundle = self.build()
        changed_previous = {
            "change_id": "different",
            "change_sha256": "d" * 64,
            "outcome": "COMMITTED",
            "completed_epoch": EPOCH,
        }
        bad = replace(bundle, active_safe_master_component=ExactJsonComponent(master_active(unsafe=False, completed=changed_previous)))
        with self.assertRaises(DriveBundleBlocked):
            bad.to_bytes()

    def test_rest_lost_bundle_create_response_recovers_by_reserved_bundle_id(self) -> None:
        drive, bundle = self.build()
        failing = GoogleDriveBackend("token", http=ModelDriveHttp(drive, fail_after_mutation=1))
        with self.assertRaises(DriveUncertainMutation):
            DriveBundleStore(failing, bundle).ensure()

        restored = DriveTransactionBundle.from_bytes(bundle.to_bytes())
        restarted = GoogleDriveBackend("token", http=ModelDriveHttp(drive))
        item = DriveBundleStore(restarted, restored).ensure()
        self.assertEqual(item.file_id, restored.bundle_file_id)
        self.assertEqual(restarted.download(item.file_id), restored.to_bytes())


if __name__ == "__main__":
    unittest.main(verbosity=2)
