from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from drive_http_model import ModelDriveHttp
from keelaryn_core.drive_backend import DriveAlreadyExists, DriveUncertainMutation
from keelaryn_core.drive_change import DriveChangeRunner
from keelaryn_core.drive_control import DriveControl
from keelaryn_core.drive_model import DriveModel
from keelaryn_core.drive_rest import GoogleDriveBackend
from keelaryn_core.drive_transaction import BlobState, DriveOperation


class DriveRestRecoveryTests(unittest.TestCase):
    def build_change(self) -> tuple[DriveModel, bytes, str, str, str]:
        drive = DriveModel()
        hub = drive.create_folder("root", "Hub")
        canonical = drive.create_folder(hub.file_id, "canonical")
        control_parent = drive.create_folder(hub.file_id, "control")
        stage = drive.create_folder(control_parent.file_id, "stage")
        history = drive.create_folder(hub.file_id, "history")
        original = drive.create_folder(history.file_id, "original")
        rejected = drive.create_folder(history.file_id, "rejected")

        replace_old = b"replace old"
        replace_new = b"replace new"
        delete_old = b"delete old"
        add_new = b"add new"
        replace_old_item = drive.create_blob(canonical.file_id, "replace.txt", replace_old)
        delete_old_item = drive.create_blob(canonical.file_id, "delete.txt", delete_old)
        replace_new_item = drive.create_blob(stage.file_id, "replace.new", replace_new)
        add_new_item = drive.create_blob(stage.file_id, "add.new", add_new)

        control = DriveControl(
            change_id="rest-multi",
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
        return drive, control.to_bytes(), canonical.file_id, replace_old_item.file_id, delete_old_item.file_id

    @staticmethod
    def backend(drive: DriveModel, *, fail_after_mutation: int | None = None) -> GoogleDriveBackend:
        return GoogleDriveBackend("token", http=ModelDriveHttp(drive, fail_after_mutation=fail_after_mutation))

    def test_uncertain_reserved_id_create_recovers_by_exact_file_id(self) -> None:
        drive = DriveModel()
        hub = drive.create_folder("root", "Hub")
        stage = drive.create_folder(hub.file_id, "stage")
        backend = self.backend(drive, fail_after_mutation=1)
        reserved = backend.generate_ids(1)[0]
        payload = b"created despite lost response"

        with self.assertRaises(DriveUncertainMutation):
            backend.create_blob(stage.file_id, "payload.bin", payload, file_id=reserved)

        restarted = self.backend(drive)
        item = restarted.get(reserved, include_trashed=False)
        self.assertEqual(item.file_id, reserved)
        self.assertEqual(item.parent_id, stage.file_id)
        self.assertEqual(restarted.download(reserved), payload)
        with self.assertRaises(DriveAlreadyExists):
            restarted.create_blob(stage.file_id, "payload.bin", payload, file_id=reserved)
        self.assertEqual(restarted.get(reserved).file_id, reserved)

    def test_uncertain_reserved_id_copy_recovers_by_exact_file_id(self) -> None:
        drive = DriveModel()
        hub = drive.create_folder("root", "Hub")
        stage = drive.create_folder(hub.file_id, "stage")
        source = drive.create_blob(hub.file_id, "source.bin", b"source")
        backend = self.backend(drive, fail_after_mutation=1)
        reserved = backend.generate_ids(1)[0]

        with self.assertRaises(DriveUncertainMutation):
            backend.copy_blob(source.file_id, stage.file_id, "copy.bin", file_id=reserved)

        restarted = self.backend(drive)
        copied = restarted.get(reserved, include_trashed=False)
        self.assertEqual(copied.parent_id, stage.file_id)
        self.assertEqual(restarted.download(reserved), b"source")

    def test_rest_apply_uncertain_mutation_matrix_recovers_from_control_only(self) -> None:
        # ADD publish; REPLACE old displacement; REPLACE new publish; DELETE displacement.
        for mutation_number in range(1, 5):
            with self.subTest(mutation_number=mutation_number):
                drive, raw, _, _, _ = self.build_change()
                control = DriveControl.from_bytes(raw)
                failing = DriveChangeRunner(
                    self.backend(drive, fail_after_mutation=mutation_number),
                    control,
                )
                with self.assertRaises(DriveUncertainMutation):
                    failing.apply_all()

                # Process-local objects are discarded. Recovery starts only from
                # durable control bytes plus remote Drive state.
                restored = DriveControl.from_bytes(raw)
                restarted = DriveChangeRunner(self.backend(drive), restored)
                self.assertTrue(restarted.apply_all().all_new)

    def test_rest_rollback_uncertain_mutation_matrix_recovers_from_control_only(self) -> None:
        # Reverse order: DELETE restore; REPLACE reject NEW; REPLACE restore OLD;
        # ADD remove-from-canonical.
        for mutation_number in range(1, 5):
            with self.subTest(mutation_number=mutation_number):
                drive, raw, canonical, replace_old_id, delete_old_id = self.build_change()
                control = DriveControl.from_bytes(raw)
                self.assertTrue(DriveChangeRunner(self.backend(drive), control).apply_all().all_new)

                failing = DriveChangeRunner(
                    self.backend(drive, fail_after_mutation=mutation_number),
                    DriveControl.from_bytes(raw),
                )
                with self.assertRaises(DriveUncertainMutation):
                    failing.rollback_all()

                restarted = DriveChangeRunner(self.backend(drive), DriveControl.from_bytes(raw))
                self.assertTrue(restarted.rollback_all().all_old)
                check = self.backend(drive)
                self.assertIsNone(check.exact_name(canonical, "added.txt"))
                self.assertEqual(check.exact_name(canonical, "replace.txt").file_id, replace_old_id)
                self.assertEqual(check.exact_name(canonical, "delete.txt").file_id, delete_old_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
