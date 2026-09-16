from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from drive_http_model import ModelDriveHttp
from keelaryn_core.drive_backend import DriveUncertainMutation
from keelaryn_core.drive_master import DriveMasterBinding, DriveMasterTransition, DriveMasterUnavailable
from keelaryn_core.drive_model import DriveModel
from keelaryn_core.drive_rest import GoogleDriveBackend
from keelaryn_core.drive_transaction import BlobState


class DriveMasterRestTests(unittest.TestCase):
    OLD = b'{"state":"READY","canonical_read_status":"SAFE","canonical_epoch":11}\n'
    NEW = b'{"state":"ACTIVE","canonical_read_status":"UNSAFE","canonical_epoch":11}\n'

    def build(self):
        drive = DriveModel()
        hub = drive.create_folder("root", "Keelaryn Hub")
        transition = drive.create_folder(hub.file_id, "master-transition")
        old = drive.create_blob(hub.file_id, "MASTER.json", self.OLD)
        backend = self.backend(drive)
        binding = DriveMasterTransition.plan(
            backend,
            transition_id="rest-master",
            root_id=hub.file_id,
            transition_parent_id=transition.file_id,
            expected_old=BlobState.from_bytes(self.OLD),
            new_bytes=self.NEW,
        )
        return drive, binding.to_bytes(), hub.file_id, old.file_id

    @staticmethod
    def backend(drive: DriveModel, *, fail_after_mutation: int | None = None) -> GoogleDriveBackend:
        return GoogleDriveBackend("token", http=ModelDriveHttp(drive, fail_after_mutation=fail_after_mutation))

    def test_uncertain_candidate_create_recovers_by_reserved_id(self) -> None:
        drive, raw, _, _ = self.build()
        binding = DriveMasterBinding.from_bytes(raw)
        failing = DriveMasterTransition(self.backend(drive, fail_after_mutation=1), binding)
        with self.assertRaises(DriveUncertainMutation):
            failing.prepare_candidate(self.NEW)

        restarted = DriveMasterTransition(self.backend(drive), DriveMasterBinding.from_bytes(raw))
        self.assertEqual(restarted.classify(), "OLD_PREPARED")
        self.assertEqual(restarted.publish(), "NEW")

    def test_uncertain_publish_mutation_matrix_recovers(self) -> None:
        for mutation_number, intermediate in ((1, "OLD_DISPLACED"), (2, "NEW")):
            with self.subTest(mutation_number=mutation_number):
                drive, raw, _, _ = self.build()
                binding = DriveMasterBinding.from_bytes(raw)
                prep = DriveMasterTransition(self.backend(drive), binding)
                self.assertEqual(prep.prepare_candidate(self.NEW), "OLD_PREPARED")

                failing = DriveMasterTransition(
                    self.backend(drive, fail_after_mutation=mutation_number),
                    DriveMasterBinding.from_bytes(raw),
                )
                with self.assertRaises(DriveUncertainMutation):
                    failing.publish()

                restarted = DriveMasterTransition(self.backend(drive), DriveMasterBinding.from_bytes(raw))
                self.assertEqual(restarted.classify(), intermediate)
                self.assertEqual(restarted.publish(), "NEW")

    def test_reader_rejects_gap_through_rest_backend(self) -> None:
        drive, raw, hub, _ = self.build()
        binding = DriveMasterBinding.from_bytes(raw)
        tx = DriveMasterTransition(self.backend(drive), binding)
        tx.prepare_candidate(self.NEW)

        failing = DriveMasterTransition(
            self.backend(drive, fail_after_mutation=1),
            DriveMasterBinding.from_bytes(raw),
        )
        with self.assertRaises(DriveUncertainMutation):
            failing.publish()

        with self.assertRaises(DriveMasterUnavailable):
            DriveMasterTransition.read_unique_master(self.backend(drive), hub)

    def test_uncertain_rollback_mutation_matrix_recovers_old(self) -> None:
        for mutation_number, intermediate in ((1, "NEW_REJECTED"), (2, "OLD_ROLLED_BACK")):
            with self.subTest(mutation_number=mutation_number):
                drive, raw, hub, old_id = self.build()
                binding = DriveMasterBinding.from_bytes(raw)
                normal = DriveMasterTransition(self.backend(drive), binding)
                normal.prepare_candidate(self.NEW)
                self.assertEqual(normal.publish(), "NEW")

                failing = DriveMasterTransition(
                    self.backend(drive, fail_after_mutation=mutation_number),
                    DriveMasterBinding.from_bytes(raw),
                )
                with self.assertRaises(DriveUncertainMutation):
                    failing.rollback()

                restarted = DriveMasterTransition(self.backend(drive), DriveMasterBinding.from_bytes(raw))
                self.assertEqual(restarted.classify(), intermediate)
                self.assertIn(restarted.rollback(), {"OLD_PREPARED", "OLD_ROLLED_BACK"})
                item, master = DriveMasterTransition.read_unique_master(self.backend(drive), hub)
                self.assertEqual(item.file_id, old_id)
                self.assertEqual(master, self.OLD)


if __name__ == "__main__":
    unittest.main(verbosity=2)
