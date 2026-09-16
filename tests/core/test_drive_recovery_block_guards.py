from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "core"))
sys.path.insert(0, str(TESTS))

import test_drive_core as core_fixture
from keelaryn_core.drive_backend import DriveNotFound
from keelaryn_core.drive_bundle import DriveTransactionBundle
from keelaryn_core.drive_core import DriveCoreBlocked, DriveCoreRunner
from keelaryn_core.drive_master import DriveMasterTransition
from keelaryn_core.drive_recovery_block import DriveRecoveryBlockRecord


class DriveRecoveryBlockedGuardTests(unittest.TestCase):
    @staticmethod
    def build():
        # Import the fixture module, not its TestCase symbol, so unittest discovery
        # does not duplicate the entire DriveCoreTests class in this module.
        return core_fixture.DriveCoreTests().build()

    def assert_reserved_block_candidate_absent(self, fixture) -> None:
        with self.assertRaises(DriveNotFound):
            fixture.drive.get(
                fixture.bundle.blocked_binding.candidate_master_id,
                include_trashed=False,
            )

    def test_corrupt_reserved_block_record_does_not_manufacture_blocked_master(self) -> None:
        fixture = self.build()
        self.assertEqual(
            DriveCoreRunner(fixture.drive, fixture.bundle).run_until_quiescent().phase,
            "WAIT_POSTCHECK",
        )
        binding = fixture.bundle.recovery_block_binding
        fixture.drive.create_blob(
            binding.record_parent_id,
            binding.record_name,
            b"{}",
            file_id=binding.record_id,
            label="external.corrupt-reserved-block-record",
        )

        with self.assertRaises(DriveCoreBlocked):
            DriveCoreRunner(
                fixture.drive,
                DriveTransactionBundle.from_bytes(fixture.bundle.to_bytes()),
            ).run_until_quiescent()

        self.assertEqual(DriveCoreRunner(fixture.drive, fixture.bundle).phase(), "ACTIVE_UNSAFE")
        self.assert_reserved_block_candidate_absent(fixture)

    def test_corrupt_active_unsafe_master_does_not_create_block_authority(self) -> None:
        fixture = self.build()
        self.assertEqual(
            DriveCoreRunner(fixture.drive, fixture.bundle).run_until_quiescent().phase,
            "WAIT_POSTCHECK",
        )
        root, _ = DriveMasterTransition.read_unique_master(
            fixture.drive,
            fixture.bundle.hub_root_id,
        )
        fixture.drive.update_content(root.file_id, b"corrupt MASTER", label="external.corrupt-master")

        with self.assertRaises(DriveCoreBlocked):
            DriveCoreRunner(fixture.drive, fixture.bundle).run_once()

        self.assertIsNone(
            DriveRecoveryBlockRecord(
                fixture.drive,
                fixture.bundle.recovery_block_binding,
            ).read()
        )
        self.assert_reserved_block_candidate_absent(fixture)

    def test_unattributable_zero_master_gap_does_not_create_block_authority(self) -> None:
        fixture = self.build()
        self.assertEqual(
            DriveCoreRunner(fixture.drive, fixture.bundle).run_until_quiescent().phase,
            "WAIT_POSTCHECK",
        )
        root, _ = DriveMasterTransition.read_unique_master(
            fixture.drive,
            fixture.bundle.hub_root_id,
        )
        fixture.drive.move_rename(
            root.file_id,
            fixture.bundle.master_transition_parent_id,
            "external.unknown.MASTER.json",
            label="external.make-unattributable-master-gap",
        )

        with self.assertRaises(DriveCoreBlocked):
            DriveCoreRunner(fixture.drive, fixture.bundle).run_once()

        self.assertIsNone(
            DriveRecoveryBlockRecord(
                fixture.drive,
                fixture.bundle.recovery_block_binding,
            ).read()
        )
        self.assert_reserved_block_candidate_absent(fixture)

    def test_corrupt_block_record_after_durable_block_keeps_blocked_master_unchanged(self) -> None:
        fixture = self.build()
        runner = DriveCoreRunner(fixture.drive, fixture.bundle)
        self.assertEqual(runner.run_until_quiescent().phase, "WAIT_POSTCHECK")
        snapshot_id = fixture.bundle.snapshot_plan.entries[0].snapshot_id
        fixture.drive.update_content(snapshot_id, b"damaged snapshot", label="external.damage-snapshot")
        self.assertEqual(runner.run_until_quiescent().phase, "RECOVERY_BLOCKED")

        root_before, raw_before = DriveMasterTransition.read_unique_master(
            fixture.drive,
            fixture.bundle.hub_root_id,
        )
        binding = fixture.bundle.recovery_block_binding
        fixture.drive.update_content(
            binding.record_id,
            b"{}",
            label="external.corrupt-durable-block-record",
        )

        with self.assertRaises(DriveCoreBlocked):
            DriveCoreRunner(fixture.drive, fixture.bundle).run_once()

        root_after, raw_after = DriveMasterTransition.read_unique_master(
            fixture.drive,
            fixture.bundle.hub_root_id,
        )
        self.assertEqual(root_after.file_id, root_before.file_id)
        self.assertEqual(raw_after, raw_before)
        self.assertEqual(DriveCoreRunner(fixture.drive, fixture.bundle).phase(), "RECOVERY_BLOCKED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
