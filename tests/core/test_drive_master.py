from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from keelaryn_core.drive_master import (
    DriveMasterBinding,
    DriveMasterRecoveryBlocked,
    DriveMasterTransition,
    DriveMasterUnavailable,
)
from keelaryn_core.drive_model import DriveModel
from keelaryn_core.drive_transaction import BlobState
from keelaryn_core.protocol import FaultInjector, InjectedCrash


class DriveMasterTests(unittest.TestCase):
    OLD = b'{"state":"READY","canonical_read_status":"SAFE","canonical_epoch":7}\n'
    NEW = b'{"state":"ACTIVE","canonical_read_status":"UNSAFE","canonical_epoch":7}\n'

    def build(self, crash_point: str | None = None):
        drive = DriveModel(fault=FaultInjector(crash_point))
        hub = drive.create_folder("root", "Keelaryn Hub", label="setup.hub")
        transition = drive.create_folder(hub.file_id, "master-transition", label="setup.transition")
        old = drive.create_blob(hub.file_id, "MASTER.json", self.OLD, label="setup.master")
        binding = DriveMasterTransition.plan(
            drive,
            transition_id="tx-master",
            root_id=hub.file_id,
            transition_parent_id=transition.file_id,
            expected_old=BlobState.from_bytes(self.OLD),
            new_bytes=self.NEW,
        )
        raw = binding.to_bytes()
        return drive, DriveMasterBinding.from_bytes(raw), raw, hub.file_id, transition.file_id, old.file_id

    def test_plan_roundtrip_binds_old_and_reserved_candidate(self) -> None:
        drive, binding, raw, hub, transition, old_id = self.build()
        restored = DriveMasterBinding.from_bytes(raw)
        self.assertEqual(restored, binding)
        self.assertEqual(binding.root_id, hub)
        self.assertEqual(binding.transition_parent_id, transition)
        self.assertEqual(binding.old_master_id, old_id)
        self.assertNotEqual(binding.candidate_master_id, old_id)
        self.assertEqual(binding.old_state, BlobState.from_bytes(self.OLD))
        self.assertEqual(binding.new_state, BlobState.from_bytes(self.NEW))
        self.assertEqual(DriveMasterTransition(drive, binding).classify(), "OLD_UNPREPARED")

    def test_prepare_publish_and_read_new_master(self) -> None:
        drive, binding, _, hub, _, _ = self.build()
        tx = DriveMasterTransition(drive, binding)
        self.assertEqual(tx.prepare_candidate(self.NEW), "OLD_PREPARED")
        self.assertEqual(tx.publish(), "NEW")
        item, raw = DriveMasterTransition.read_unique_master(drive, hub)
        self.assertEqual(item.file_id, binding.candidate_master_id)
        self.assertEqual(raw, self.NEW)
        self.assertEqual(tx.publish(), "NEW")

    def test_candidate_create_crash_recovers_from_binding_only(self) -> None:
        drive, binding, raw, _, _, _ = self.build()
        drive.fault.point = "drive.master.tx-master.candidate.create.after"
        drive.fault.fired = False
        with self.assertRaises(InjectedCrash):
            DriveMasterTransition(drive, binding).prepare_candidate(self.NEW)

        restarted = DriveMasterTransition(drive, DriveMasterBinding.from_bytes(raw))
        self.assertEqual(restarted.classify(), "OLD_PREPARED")
        self.assertEqual(restarted.publish(), "NEW")

    def test_publish_crash_matrix_recovers_from_binding_only(self) -> None:
        for point, intermediate in (
            ("drive.master.tx-master.displace_old.after", "OLD_DISPLACED"),
            ("drive.master.tx-master.publish_candidate.after", "NEW"),
        ):
            with self.subTest(point=point):
                drive, binding, raw, _, _, _ = self.build()
                tx = DriveMasterTransition(drive, binding)
                self.assertEqual(tx.prepare_candidate(self.NEW), "OLD_PREPARED")
                drive.fault.point = point
                drive.fault.fired = False
                with self.assertRaises(InjectedCrash):
                    tx.publish()

                restarted = DriveMasterTransition(drive, DriveMasterBinding.from_bytes(raw))
                self.assertEqual(restarted.classify(), intermediate)
                self.assertEqual(restarted.publish(), "NEW")

    def test_normal_reader_rejects_zero_master_during_swap_gap(self) -> None:
        drive, binding, raw, hub, _, _ = self.build()
        tx = DriveMasterTransition(drive, binding)
        tx.prepare_candidate(self.NEW)
        drive.fault.point = "drive.master.tx-master.displace_old.after"
        drive.fault.fired = False
        with self.assertRaises(InjectedCrash):
            tx.publish()

        with self.assertRaises(DriveMasterUnavailable):
            DriveMasterTransition.read_unique_master(drive, hub)
        restarted = DriveMasterTransition(drive, DriveMasterBinding.from_bytes(raw))
        self.assertEqual(restarted.classify(), "OLD_DISPLACED")

    def test_rollback_from_gap_restores_old_without_publishing_new(self) -> None:
        drive, binding, _, hub, _, old_id = self.build()
        tx = DriveMasterTransition(drive, binding)
        tx.prepare_candidate(self.NEW)
        drive.fault.point = "drive.master.tx-master.displace_old.after"
        drive.fault.fired = False
        with self.assertRaises(InjectedCrash):
            tx.publish()
        drive.fault.point = None
        drive.fault.fired = False

        self.assertEqual(tx.rollback(), "OLD_PREPARED")
        item, raw = DriveMasterTransition.read_unique_master(drive, hub)
        self.assertEqual(item.file_id, old_id)
        self.assertEqual(raw, self.OLD)

    def test_rollback_crash_matrix_recovers_from_binding_only(self) -> None:
        for point, intermediate in (
            ("drive.master.tx-master.reject_candidate.after", "NEW_REJECTED"),
            ("drive.master.tx-master.restore_old.after", "OLD_ROLLED_BACK"),
        ):
            with self.subTest(point=point):
                drive, binding, raw, hub, _, old_id = self.build()
                tx = DriveMasterTransition(drive, binding)
                tx.prepare_candidate(self.NEW)
                self.assertEqual(tx.publish(), "NEW")
                drive.fault.point = point
                drive.fault.fired = False
                with self.assertRaises(InjectedCrash):
                    tx.rollback()

                restarted = DriveMasterTransition(drive, DriveMasterBinding.from_bytes(raw))
                self.assertEqual(restarted.classify(), intermediate)
                final = restarted.rollback()
                self.assertIn(final, {"OLD_PREPARED", "OLD_ROLLED_BACK"})
                item, master = DriveMasterTransition.read_unique_master(drive, hub)
                self.assertEqual(item.file_id, old_id)
                self.assertEqual(master, self.OLD)

    def test_duplicate_master_blocks_reader_and_recovery(self) -> None:
        drive, binding, _, hub, _, _ = self.build()
        tx = DriveMasterTransition(drive, binding)
        tx.prepare_candidate(self.NEW)
        drive.create_blob(hub, "MASTER.json", b"foreign")
        with self.assertRaises(DriveMasterUnavailable):
            DriveMasterTransition.read_unique_master(drive, hub)
        with self.assertRaises(DriveMasterRecoveryBlocked):
            tx.classify()

    def test_external_old_master_edit_blocks_transition(self) -> None:
        drive, binding, _, _, _, _ = self.build()
        tx = DriveMasterTransition(drive, binding)
        tx.prepare_candidate(self.NEW)
        drive.update_content(binding.old_master_id, b"external edit")
        with self.assertRaises(DriveMasterRecoveryBlocked):
            tx.classify()

    def test_external_candidate_edit_blocks_transition(self) -> None:
        drive, binding, _, _, _, _ = self.build()
        tx = DriveMasterTransition(drive, binding)
        tx.prepare_candidate(self.NEW)
        drive.update_content(binding.candidate_master_id, b"external edit")
        with self.assertRaises(DriveMasterRecoveryBlocked):
            tx.classify()


if __name__ == "__main__":
    unittest.main(verbosity=2)
