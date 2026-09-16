from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from drive_http_model import ModelDriveHttp
from keelaryn_core.drive_backend import DriveUncertainMutation
from keelaryn_core.drive_execution_rollback import (
    DriveExecutionRollbackBinding,
    DriveExecutionRollbackBlocked,
    DriveExecutionRollbackMarker,
)
from keelaryn_core.drive_model import DriveModel
from keelaryn_core.drive_rest import GoogleDriveBackend
from keelaryn_core.protocol import canonical_json_bytes


CHANGE_SHA = "e" * 64


class DriveExecutionRollbackTests(unittest.TestCase):
    def build(self) -> tuple[DriveModel, DriveExecutionRollbackBinding, str]:
        drive = DriveModel()
        hub = drive.create_folder("root", "Hub")
        control = drive.create_folder(hub.file_id, "control")
        binding = DriveExecutionRollbackBinding.plan(
            drive,
            change_id="change-1",
            change_sha256=CHANGE_SHA,
            base_canonical_epoch=4,
            marker_parent_id=control.file_id,
        )
        return drive, binding, control.file_id

    def test_binding_roundtrip(self) -> None:
        _, binding, _ = self.build()
        self.assertEqual(DriveExecutionRollbackBinding.from_bytes(binding.to_bytes()), binding)

    def test_record_is_idempotent_and_direction_is_id_bound(self) -> None:
        drive, binding, _ = self.build()
        marker = DriveExecutionRollbackMarker(drive, binding)
        self.assertFalse(marker.active())
        self.assertTrue(marker.record("deterministic apply failure"))
        self.assertTrue(marker.active())
        self.assertTrue(marker.record("different later diagnostic text"))
        self.assertTrue(marker.active())

    def test_marker_identity_or_location_mutation_fails_closed(self) -> None:
        drive, binding, control = self.build()
        marker = DriveExecutionRollbackMarker(drive, binding)
        marker.record("failure")

        drive.update_content(
            binding.marker_id,
            canonical_json_bytes(
                {
                    "schema": "keelaryn.drive-execution-rollback.v1",
                    "change_id": "other",
                    "change_sha256": CHANGE_SHA,
                    "base_canonical_epoch": 4,
                    "reason": "tampered",
                }
            ),
        )
        with self.assertRaises(DriveExecutionRollbackBlocked):
            marker.active()

        # Restore a valid object at the same ID then move it to an unexpected parent.
        drive.update_content(
            binding.marker_id,
            canonical_json_bytes(
                {
                    "schema": "keelaryn.drive-execution-rollback.v1",
                    "change_id": "change-1",
                    "change_sha256": CHANGE_SHA,
                    "base_canonical_epoch": 4,
                    "reason": "failure",
                }
            ),
        )
        other = drive.create_folder("root", "other")
        drive.move_rename(binding.marker_id, other.file_id, binding.marker_name)
        with self.assertRaises(DriveExecutionRollbackBlocked):
            marker.active()
        self.assertNotEqual(other.file_id, control)

    def test_rest_lost_marker_create_response_recovers_by_reserved_id(self) -> None:
        drive = DriveModel()
        hub = drive.create_folder("root", "Hub")
        control = drive.create_folder(hub.file_id, "control")
        backend = GoogleDriveBackend("token", http=ModelDriveHttp(drive, fail_after_mutation=1))
        binding = DriveExecutionRollbackBinding.plan(
            backend,
            change_id="change-1",
            change_sha256=CHANGE_SHA,
            base_canonical_epoch=4,
            marker_parent_id=control.file_id,
        )
        raw = binding.to_bytes()

        with self.assertRaises(DriveUncertainMutation):
            DriveExecutionRollbackMarker(backend, binding).record("deterministic failure")

        restarted = GoogleDriveBackend("token", http=ModelDriveHttp(drive))
        restored = DriveExecutionRollbackBinding.from_bytes(raw)
        marker = DriveExecutionRollbackMarker(restarted, restored)
        self.assertTrue(marker.active())
        self.assertTrue(marker.record("not used because marker already exists"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
