from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from drive_http_model import ModelDriveHttp
from keelaryn_core.drive_backend import DriveUncertainMutation
from keelaryn_core.drive_bundle import DriveTransactionBundle
from keelaryn_core.drive_control import DriveControl
from keelaryn_core.drive_core import DriveCoreRunner
from keelaryn_core.drive_execution_rollback import DriveExecutionRollbackBinding
from keelaryn_core.drive_model import DriveModel
from keelaryn_core.drive_postcheck import DrivePostcheckBinding
from keelaryn_core.drive_rest import GoogleDriveBackend
from keelaryn_core.drive_snapshot import DriveSnapshotPlan
from keelaryn_core.drive_transaction import BlobState, DriveOperation
from keelaryn_core.protocol import canonical_json_bytes


CHANGE_SHA = "9" * 64
EPOCH = 5


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
                "change_id": "rest-change",
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
                "change_id": "rest-change",
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
            "change_id": "rest-change",
            "change_sha256": CHANGE_SHA,
            "base_canonical_epoch": EPOCH,
            "decision": decision,
            "reason": f"semantic {decision}",
        }
    )


@dataclass
class RestFixture:
    drive: DriveModel
    backend: GoogleDriveBackend
    http: ModelDriveHttp
    bundle: DriveTransactionBundle
    canonical_id: str
    add_new_id: str
    replace_old_id: str
    replace_new_id: str
    delete_old_id: str


class DriveCoreRestTests(unittest.TestCase):
    def build(self, decision: str | None, *, fail_after_mutation: int | None = None) -> RestFixture:
        drive = DriveModel()
        hub = drive.create_folder("root", "Hub")
        canonical = drive.create_folder(hub.file_id, "canonical")
        stage = drive.create_folder(hub.file_id, "stage")
        history = drive.create_folder(hub.file_id, "history")
        bundle_parent = drive.create_folder(history.file_id, "rest-change")
        snapshots_parent = drive.create_folder(bundle_parent.file_id, "snapshots")
        originals = drive.create_folder(bundle_parent.file_id, "originals")
        rejected = drive.create_folder(bundle_parent.file_id, "rejected")
        transitions = drive.create_folder(hub.file_id, "master-transitions")
        postcheck_parent = drive.create_folder(hub.file_id, "postcheck")
        receipts = drive.create_folder(bundle_parent.file_id, "receipts")
        markers = drive.create_folder(bundle_parent.file_id, "markers")
        drive.create_blob(hub.file_id, "MASTER.json", ready_master())

        add_bytes = b"rest-add"
        replace_old = b"rest-replace-old"
        replace_new = b"rest-replace-new"
        delete_old = b"rest-delete-old"
        replace_old_item = drive.create_blob(canonical.file_id, "replace.txt", replace_old)
        delete_old_item = drive.create_blob(canonical.file_id, "delete.txt", delete_old)
        add_new_item = drive.create_blob(stage.file_id, "add.new", add_bytes)
        replace_new_item = drive.create_blob(stage.file_id, "replace.new", replace_new)

        http = ModelDriveHttp(drive, fail_after_mutation=fail_after_mutation)
        backend = GoogleDriveBackend("token", http=http)
        control = DriveControl(
            change_id="rest-change",
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
                    BlobState.from_bytes(add_bytes),
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
        snapshots = DriveSnapshotPlan.plan(backend, control, snapshots_parent.file_id)
        postcheck = DrivePostcheckBinding.plan(
            backend,
            change_id="rest-change",
            change_sha256=CHANGE_SHA,
            base_canonical_epoch=EPOCH,
            source_parent_id=postcheck_parent.file_id,
            source_name="rest-change.json",
            receipt_parent_id=receipts.file_id,
        )
        execution = DriveExecutionRollbackBinding.plan(
            backend,
            change_id="rest-change",
            change_sha256=CHANGE_SHA,
            base_canonical_epoch=EPOCH,
            marker_parent_id=markers.file_id,
        )
        bundle = DriveTransactionBundle.plan(
            backend,
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
            drive.create_blob(postcheck_parent.file_id, "rest-change.json", postcheck_bytes(decision))
        return RestFixture(
            drive=drive,
            backend=backend,
            http=http,
            bundle=bundle,
            canonical_id=canonical.file_id,
            add_new_id=add_new_item.file_id,
            replace_old_id=replace_old_item.file_id,
            replace_new_id=replace_new_item.file_id,
            delete_old_id=delete_old_item.file_id,
        )

    def assert_committed(self, fixture: RestFixture) -> None:
        self.assertEqual(fixture.drive.exact_name(fixture.canonical_id, "added.txt").file_id, fixture.add_new_id)
        self.assertEqual(fixture.drive.exact_name(fixture.canonical_id, "replace.txt").file_id, fixture.replace_new_id)
        self.assertIsNone(fixture.drive.exact_name(fixture.canonical_id, "delete.txt"))

    def assert_rolled_back(self, fixture: RestFixture) -> None:
        self.assertIsNone(fixture.drive.exact_name(fixture.canonical_id, "added.txt"))
        self.assertEqual(fixture.drive.exact_name(fixture.canonical_id, "replace.txt").file_id, fixture.replace_old_id)
        self.assertEqual(fixture.drive.exact_name(fixture.canonical_id, "delete.txt").file_id, fixture.delete_old_id)

    def mutation_count_for(self, decision: str) -> int:
        fixture = self.build(decision)
        status = DriveCoreRunner(fixture.backend, fixture.bundle).run_until_quiescent()
        self.assertEqual(status.phase, "COMMITTED" if decision == "PASS" else "ROLLED_BACK")
        return fixture.http.mutation_count

    def test_rest_pass_uncertain_response_matrix_recovers_every_mutation(self) -> None:
        mutation_count = self.mutation_count_for("PASS")
        self.assertGreater(mutation_count, 10)
        for mutation_number in range(1, mutation_count + 1):
            with self.subTest(mutation_number=mutation_number, total=mutation_count):
                fixture = self.build("PASS", fail_after_mutation=mutation_number)
                raw_bundle = fixture.bundle.to_bytes()
                with self.assertRaises(DriveUncertainMutation):
                    DriveCoreRunner(fixture.backend, fixture.bundle).run_until_quiescent()

                restarted = GoogleDriveBackend("token", http=ModelDriveHttp(fixture.drive))
                restored = DriveTransactionBundle.from_bytes(raw_bundle)
                status = DriveCoreRunner(restarted, restored).run_until_quiescent()
                self.assertEqual(status.phase, "COMMITTED")
                self.assert_committed(fixture)

    def test_rest_fail_uncertain_response_matrix_recovers_every_mutation(self) -> None:
        mutation_count = self.mutation_count_for("FAIL")
        self.assertGreater(mutation_count, 10)
        for mutation_number in range(1, mutation_count + 1):
            with self.subTest(mutation_number=mutation_number, total=mutation_count):
                fixture = self.build("FAIL", fail_after_mutation=mutation_number)
                raw_bundle = fixture.bundle.to_bytes()
                with self.assertRaises(DriveUncertainMutation):
                    DriveCoreRunner(fixture.backend, fixture.bundle).run_until_quiescent()

                restarted = GoogleDriveBackend("token", http=ModelDriveHttp(fixture.drive))
                restored = DriveTransactionBundle.from_bytes(raw_bundle)
                status = DriveCoreRunner(restarted, restored).run_until_quiescent()
                self.assertEqual(status.phase, "ROLLED_BACK")
                self.assert_rolled_back(fixture)

    def test_rest_recovery_block_uncertain_response_matrix_recovers_every_block_mutation(self) -> None:
        baseline = self.build(None)
        self.assertEqual(DriveCoreRunner(baseline.backend, baseline.bundle).run_until_quiescent().phase, "WAIT_POSTCHECK")
        before_block = baseline.http.mutation_count
        snapshot_id = baseline.bundle.snapshot_plan.entries[0].snapshot_id
        baseline.drive.update_content(snapshot_id, b"damaged snapshot")
        self.assertEqual(DriveCoreRunner(baseline.backend, baseline.bundle).run_until_quiescent().phase, "RECOVERY_BLOCKED")
        after_block = baseline.http.mutation_count
        self.assertEqual(after_block - before_block, 4)

        for mutation_number in range(before_block + 1, after_block + 1):
            with self.subTest(mutation_number=mutation_number, block_start=before_block + 1, block_end=after_block):
                fixture = self.build(None, fail_after_mutation=mutation_number)
                raw_bundle = fixture.bundle.to_bytes()
                self.assertEqual(
                    DriveCoreRunner(fixture.backend, fixture.bundle).run_until_quiescent().phase,
                    "WAIT_POSTCHECK",
                )
                snapshot_id = fixture.bundle.snapshot_plan.entries[0].snapshot_id
                fixture.drive.update_content(snapshot_id, b"damaged snapshot")

                with self.assertRaises(DriveUncertainMutation):
                    DriveCoreRunner(fixture.backend, fixture.bundle).run_until_quiescent()

                restarted = GoogleDriveBackend("token", http=ModelDriveHttp(fixture.drive))
                restored = DriveTransactionBundle.from_bytes(raw_bundle)
                status = DriveCoreRunner(restarted, restored).run_until_quiescent()
                self.assertEqual(status.phase, "RECOVERY_BLOCKED")
                self.assertEqual(DriveCoreRunner(restarted, restored).phase(), "RECOVERY_BLOCKED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
