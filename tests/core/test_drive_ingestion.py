from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "core"))
sys.path.insert(0, str(TESTS))

import test_drive_core as core_fixture
from drive_http_model import ModelDriveHttp
from keelaryn_core.drive_backend import DriveUncertainMutation
from keelaryn_core.drive_change import DriveChangeRunner
from keelaryn_core.drive_ingestion import (
    DriveChangePlanner,
    DriveReadyChangeBlocked,
    DriveReadyChangeLoader,
)
from keelaryn_core.drive_model import DriveModel
from keelaryn_core.drive_rest import GoogleDriveBackend
from keelaryn_core.protocol import FaultInjector, InjectedCrash, canonical_json_bytes


def present(content: bytes) -> dict[str, object]:
    return {"state": "PRESENT", "sha256": sha256(content).hexdigest(), "size": len(content)}


ABSENT = {"state": "ABSENT"}


@dataclass
class Fixture:
    drive: DriveModel
    hub_id: str
    canonical_id: str
    changes_id: str
    change_folder_id: str
    stage_id: str
    originals_id: str
    rejected_id: str
    replace_old_id: str
    delete_old_id: str
    add_prepared_id: str
    replace_prepared_id: str
    change_raw: bytes


class DriveIngestionTests(unittest.TestCase):
    def build(self, *, create_ready: bool = True, base_epoch: int = core_fixture.EPOCH) -> Fixture:
        drive = DriveModel()
        hub = drive.create_folder("root", "Hub")
        canonical = drive.create_folder(hub.file_id, "canonical")
        work = drive.create_folder(hub.file_id, "work")
        reconciliation = drive.create_folder(work.file_id, "reconciliation")
        changes = drive.create_folder(reconciliation.file_id, "changes")
        history = drive.create_folder(hub.file_id, "history")
        history_change = drive.create_folder(history.file_id, "change-1")
        stage = drive.create_folder(history_change.file_id, "stage")
        originals = drive.create_folder(history_change.file_id, "originals")
        rejected = drive.create_folder(history_change.file_id, "rejected")
        drive.create_blob(hub.file_id, "MASTER.json", core_fixture.ready_master())

        replace_old = b"replace-old"
        replace_new = b"replace-new"
        delete_old = b"delete-old"
        add_new = b"add-new"
        replace_old_item = drive.create_blob(canonical.file_id, "replace.txt", replace_old)
        delete_old_item = drive.create_blob(canonical.file_id, "delete.txt", delete_old)

        change_folder = drive.create_folder(changes.file_id, "change-1")
        prepared = drive.create_folder(change_folder.file_id, "prepared")
        add_prepared = drive.create_blob(prepared.file_id, "add.bin", add_new)
        replace_prepared = drive.create_blob(prepared.file_id, "replace.bin", replace_new)
        change = {
            "schema": "keelaryn.change.v1",
            "change_id": "change-1",
            "base_canonical_epoch": base_epoch,
            "operations": [
                {
                    "operation_id": "add",
                    "kind": "ADD",
                    "target": "added.txt",
                    "old": ABSENT,
                    "new": present(add_new),
                    "prepared_path": "prepared/add.bin",
                },
                {
                    "operation_id": "replace",
                    "kind": "REPLACE",
                    "target": "replace.txt",
                    "old": present(replace_old),
                    "new": present(replace_new),
                    "prepared_path": "prepared/replace.bin",
                },
                {
                    "operation_id": "delete",
                    "kind": "DELETE",
                    "target": "delete.txt",
                    "old": present(delete_old),
                    "new": ABSENT,
                },
            ],
        }
        change_raw = canonical_json_bytes(change)
        drive.create_blob(change_folder.file_id, "CHANGE.json", change_raw)
        if create_ready:
            ready = canonical_json_bytes(
                {
                    "schema": "keelaryn.ready.v1",
                    "state": "READY_FOR_COMMIT",
                    "change_id": "change-1",
                    "change_sha256": sha256(change_raw).hexdigest(),
                }
            )
            drive.create_blob(change_folder.file_id, "READY.json", ready)
        return Fixture(
            drive,
            hub.file_id,
            canonical.file_id,
            changes.file_id,
            change_folder.file_id,
            stage.file_id,
            originals.file_id,
            rejected.file_id,
            replace_old_item.file_id,
            delete_old_item.file_id,
            add_prepared.file_id,
            replace_prepared.file_id,
            change_raw,
        )

    @staticmethod
    def planner(drive, fixture: Fixture) -> DriveChangePlanner:
        return DriveChangePlanner(
            drive,
            hub_root_id=fixture.hub_id,
            canonical_root_id=fixture.canonical_id,
            stage_parent_id=fixture.stage_id,
            history_original_parent_id=fixture.originals_id,
            rejected_parent_id=fixture.rejected_id,
        )

    def load_and_plan(self, fixture: Fixture, drive=None):
        backend = drive or fixture.drive
        loader = DriveReadyChangeLoader(backend, fixture.changes_id)
        ready = loader.find_one_ready()
        self.assertIsNotNone(ready)
        return ready, self.planner(backend, fixture).plan(ready, loader)

    def test_ready_change_builds_control_that_applies_and_rolls_back(self) -> None:
        fixture = self.build()
        ready, control = self.load_and_plan(fixture)
        self.assertEqual(ready.change_sha256, sha256(fixture.change_raw).hexdigest())
        self.assertEqual([op.kind for op in control.operations], ["ADD", "REPLACE", "DELETE"])
        self.assertNotEqual(control.operations[0].staged_new_id, fixture.add_prepared_id)
        self.assertNotEqual(control.operations[1].staged_new_id, fixture.replace_prepared_id)
        self.assertEqual(control.operations[1].old_original_id, fixture.replace_old_id)
        self.assertEqual(control.operations[2].old_original_id, fixture.delete_old_id)

        runner = DriveChangeRunner(fixture.drive, control)
        self.assertTrue(runner.apply_all().all_new)
        self.assertTrue(runner.rollback_all().all_old)

    def test_no_ready_marker_returns_none(self) -> None:
        fixture = self.build(create_ready=False)
        self.assertIsNone(DriveReadyChangeLoader(fixture.drive, fixture.changes_id).find_one_ready())

    def test_multiple_ready_changes_fail_closed(self) -> None:
        fixture = self.build()
        second = fixture.drive.create_folder(fixture.changes_id, "change-2")
        change_raw = canonical_json_bytes(
            {
                "schema": "keelaryn.change.v1",
                "change_id": "change-2",
                "base_canonical_epoch": core_fixture.EPOCH,
                "operations": [
                    {
                        "operation_id": "x",
                        "kind": "ADD",
                        "target": "x.txt",
                        "old": ABSENT,
                        "new": present(b"x"),
                        "prepared_path": "prepared/x.bin",
                    }
                ],
            }
        )
        fixture.drive.create_blob(second.file_id, "CHANGE.json", change_raw)
        fixture.drive.create_blob(
            second.file_id,
            "READY.json",
            canonical_json_bytes(
                {
                    "schema": "keelaryn.ready.v1",
                    "state": "READY_FOR_COMMIT",
                    "change_id": "change-2",
                    "change_sha256": sha256(change_raw).hexdigest(),
                }
            ),
        )
        with self.assertRaises(DriveReadyChangeBlocked):
            DriveReadyChangeLoader(fixture.drive, fixture.changes_id).find_one_ready()

    def test_ready_hash_mismatch_fails_closed(self) -> None:
        fixture = self.build()
        ready_item = fixture.drive.exact_name(fixture.change_folder_id, "READY.json")
        fixture.drive.update_content(
            ready_item.file_id,
            canonical_json_bytes(
                {
                    "schema": "keelaryn.ready.v1",
                    "state": "READY_FOR_COMMIT",
                    "change_id": "change-1",
                    "change_sha256": "0" * 64,
                }
            ),
            label="external.bad-ready-hash",
        )
        with self.assertRaises(DriveReadyChangeBlocked):
            DriveReadyChangeLoader(fixture.drive, fixture.changes_id).find_one_ready()

    def test_old_state_mismatch_fails_before_control(self) -> None:
        fixture = self.build()
        fixture.drive.update_content(fixture.replace_old_id, b"changed-old", label="external.change-old")
        with self.assertRaises(DriveReadyChangeBlocked):
            self.load_and_plan(fixture)

    def test_prepared_state_mismatch_fails_before_control(self) -> None:
        fixture = self.build()
        fixture.drive.update_content(fixture.add_prepared_id, b"bad-prepared", label="external.change-prepared")
        with self.assertRaises(DriveReadyChangeBlocked):
            self.load_and_plan(fixture)

    def test_base_epoch_mismatch_fails_before_staging(self) -> None:
        fixture = self.build(base_epoch=core_fixture.EPOCH - 1)
        with self.assertRaises(DriveReadyChangeBlocked):
            self.load_and_plan(fixture)
        self.assertEqual(fixture.drive.list_children(fixture.stage_id), [])

    def test_duplicate_canonical_target_fails_closed(self) -> None:
        fixture = self.build()
        fixture.drive.create_blob(fixture.canonical_id, "replace.txt", b"replace-old", label="external.duplicate-old")
        with self.assertRaises(DriveReadyChangeBlocked):
            self.load_and_plan(fixture)

    def test_process_crash_after_staged_copy_recovers_by_deterministic_stage_name(self) -> None:
        fixture = self.build()
        loader = DriveReadyChangeLoader(fixture.drive, fixture.changes_id)
        ready = loader.find_one_ready()
        fixture.drive.fault = FaultInjector("drive.ingest.change-1.add.copy.after")
        with self.assertRaises(InjectedCrash):
            self.planner(fixture.drive, fixture).plan(ready, loader)

        fixture.drive.fault = FaultInjector()
        restored_loader = DriveReadyChangeLoader(fixture.drive, fixture.changes_id)
        restored = restored_loader.find_one_ready()
        control = self.planner(fixture.drive, fixture).plan(restored, restored_loader)
        self.assertEqual(len(fixture.drive.list_children(fixture.stage_id, name="add.new.staged.bin")), 1)
        self.assertIsNotNone(control.operations[0].staged_new_id)

    def test_rest_lost_copy_response_recovers_staging_without_duplicate(self) -> None:
        fixture = self.build()
        failing = GoogleDriveBackend("token", http=ModelDriveHttp(fixture.drive, fail_after_mutation=1))
        loader = DriveReadyChangeLoader(failing, fixture.changes_id)
        ready = loader.find_one_ready()
        with self.assertRaises(DriveUncertainMutation):
            self.planner(failing, fixture).plan(ready, loader)

        restarted = GoogleDriveBackend("token", http=ModelDriveHttp(fixture.drive))
        loader2 = DriveReadyChangeLoader(restarted, fixture.changes_id)
        ready2 = loader2.find_one_ready()
        control = self.planner(restarted, fixture).plan(ready2, loader2)
        self.assertEqual(len(restarted.list_children(fixture.stage_id, name="add.new.staged.bin")), 1)
        self.assertEqual(len(restarted.list_children(fixture.stage_id, name="replace.new.staged.bin")), 1)
        self.assertEqual(len(control.operations), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
