from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from drive_http_model import ModelDriveHttp
from keelaryn_core.drive_backend import DriveUncertainMutation
from keelaryn_core.drive_model import DriveModel
from keelaryn_core.drive_recovery_block import (
    DriveRecoveryBlockBinding,
    DriveRecoveryBlockCorrupt,
    DriveRecoveryBlockRecord,
)
from keelaryn_core.drive_rest import GoogleDriveBackend
from keelaryn_core.protocol import canonical_json_bytes


CHANGE_SHA = "7" * 64


class DriveRecoveryBlockTests(unittest.TestCase):
    def build(self):
        drive = DriveModel()
        hub = drive.create_folder("root", "Hub")
        records = drive.create_folder(hub.file_id, "recovery")
        binding = DriveRecoveryBlockBinding.plan(
            drive,
            change_id="change-1",
            change_sha256=CHANGE_SHA,
            base_canonical_epoch=9,
            record_parent_id=records.file_id,
        )
        return drive, binding, records.file_id

    def test_binding_roundtrip_and_record_idempotence(self) -> None:
        drive, binding, _ = self.build()
        restored = DriveRecoveryBlockBinding.from_bytes(binding.to_bytes())
        self.assertEqual(restored, binding)
        record = DriveRecoveryBlockRecord(drive, restored)
        self.assertIsNone(record.read())
        first = record.record("unknown canonical bytes")
        second = record.record("later diagnostic must not rewrite first record")
        self.assertEqual(first, second)
        self.assertEqual(first["reason"], "unknown canonical bytes")
        self.assertEqual(first["observed_phase"], "ACTIVE_UNSAFE")

    def test_record_identity_content_and_location_tamper_fail_closed(self) -> None:
        drive, binding, _ = self.build()
        record = DriveRecoveryBlockRecord(drive, binding)
        record.record("reason")
        drive.update_content(
            binding.record_id,
            canonical_json_bytes(
                {
                    "schema": "keelaryn.drive-recovery-block.v1",
                    "change_id": "other",
                    "change_sha256": CHANGE_SHA,
                    "base_canonical_epoch": 9,
                    "observed_phase": "ACTIVE_UNSAFE",
                    "reason": "tampered",
                }
            ),
        )
        with self.assertRaises(DriveRecoveryBlockCorrupt):
            record.read()

        drive.update_content(
            binding.record_id,
            canonical_json_bytes(
                {
                    "schema": "keelaryn.drive-recovery-block.v1",
                    "change_id": "change-1",
                    "change_sha256": CHANGE_SHA,
                    "base_canonical_epoch": 9,
                    "observed_phase": "ACTIVE_UNSAFE",
                    "reason": "reason",
                }
            ),
        )
        other = drive.create_folder("root", "other")
        drive.move_rename(binding.record_id, other.file_id, binding.record_name)
        with self.assertRaises(DriveRecoveryBlockCorrupt):
            record.read()

    def test_rest_lost_record_create_response_recovers_by_reserved_id(self) -> None:
        drive = DriveModel()
        hub = drive.create_folder("root", "Hub")
        records = drive.create_folder(hub.file_id, "recovery")
        backend = GoogleDriveBackend("token", http=ModelDriveHttp(drive, fail_after_mutation=1))
        binding = DriveRecoveryBlockBinding.plan(
            backend,
            change_id="change-1",
            change_sha256=CHANGE_SHA,
            base_canonical_epoch=9,
            record_parent_id=records.file_id,
        )
        raw = binding.to_bytes()
        with self.assertRaises(DriveUncertainMutation):
            DriveRecoveryBlockRecord(backend, binding).record("unknown canonical bytes")

        restarted = GoogleDriveBackend("token", http=ModelDriveHttp(drive))
        restored = DriveRecoveryBlockBinding.from_bytes(raw)
        value = DriveRecoveryBlockRecord(restarted, restored).read()
        self.assertIsNotNone(value)
        self.assertEqual(value["reason"], "unknown canonical bytes")


if __name__ == "__main__":
    unittest.main(verbosity=2)
