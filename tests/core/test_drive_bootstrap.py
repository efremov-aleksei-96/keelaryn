from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "core"))
sys.path.insert(0, str(TESTS))

from drive_http_model import ModelDriveHttp
from keelaryn_core.drive_backend import DriveUncertainMutation
from keelaryn_core.drive_bootstrap import DriveBootstrapBlocked, DriveHubBootstrap
from keelaryn_core.drive_master import MASTER_NAME
from keelaryn_core.drive_model import DriveModel
from keelaryn_core.drive_rest import GoogleDriveBackend


class DriveBootstrapTests(unittest.TestCase):
    @staticmethod
    def fresh():
        drive = DriveModel()
        hub = drive.create_folder("root", "Hub", label="setup.hub")
        return drive, hub.file_id

    def assert_layout(self, drive, hub_id) -> None:
        canonical = drive.exact_name(hub_id, "canonical")
        work = drive.exact_name(hub_id, "work")
        reconciliation = drive.exact_name(work.file_id, "reconciliation")
        changes = drive.exact_name(reconciliation.file_id, "changes")
        postcheck = drive.exact_name(reconciliation.file_id, "postcheck")
        control = drive.exact_name(hub_id, "control")
        active = drive.exact_name(control.file_id, "active")
        history = drive.exact_name(hub_id, "history")
        for item in (canonical, work, reconciliation, changes, postcheck, control, active, history):
            self.assertIsNotNone(item)
            self.assertTrue(item.is_folder)
        masters = drive.list_children(hub_id, name=MASTER_NAME)
        self.assertEqual(len(masters), 1)

    def test_fresh_bootstrap_is_idempotent(self) -> None:
        drive, hub_id = self.fresh()
        first = DriveHubBootstrap(drive, hub_id).run()
        self.assertEqual(first.state, "INITIALIZED")
        self.assertEqual(first.master["state"], "READY")
        self.assertEqual(first.master["canonical_read_status"], "SAFE")
        self.assertEqual(first.master["canonical_epoch"], 0)
        self.assert_layout(drive, hub_id)

        second = DriveHubBootstrap(drive, hub_id).run()
        self.assertEqual(second.state, "EXISTING")
        self.assertEqual(second.layout, first.layout)
        self.assertEqual(second.master_file_id, first.master_file_id)

    def test_nonempty_canonical_without_master_never_gets_blessed(self) -> None:
        drive, hub_id = self.fresh()
        canonical = drive.create_folder(hub_id, "canonical", label="setup.canonical")
        drive.create_blob(canonical.file_id, "unknown.txt", b"unknown", label="setup.unknown")
        with self.assertRaises(DriveBootstrapBlocked):
            DriveHubBootstrap(drive, hub_id).run()
        self.assertEqual(drive.list_children(hub_id, name=MASTER_NAME), [])

    def test_unknown_root_material_blocks_initialization(self) -> None:
        drive, hub_id = self.fresh()
        drive.create_blob(hub_id, "mystery.bin", b"unknown", label="setup.mystery")
        with self.assertRaises(DriveBootstrapBlocked):
            DriveHubBootstrap(drive, hub_id).run()
        self.assertEqual(drive.list_children(hub_id, name=MASTER_NAME), [])

    def test_existing_master_with_missing_structure_is_read_only_failure(self) -> None:
        drive, hub_id = self.fresh()
        drive.create_folder(hub_id, "canonical", label="setup.canonical")
        drive.create_blob(hub_id, MASTER_NAME, DriveHubBootstrap.initial_master_bytes(), label="setup.master")
        with self.assertRaises(DriveBootstrapBlocked):
            DriveHubBootstrap(drive, hub_id).run()
        self.assertIsNone(drive.exact_name(hub_id, "history"))
        self.assertEqual(len(drive.list_children(hub_id, name=MASTER_NAME)), 1)

    def test_duplicate_structural_folder_blocks_without_master(self) -> None:
        drive, hub_id = self.fresh()
        drive.create_folder(hub_id, "canonical", label="setup.canonical-1")
        drive.create_folder(hub_id, "canonical", label="setup.canonical-2")
        with self.assertRaises(DriveBootstrapBlocked):
            DriveHubBootstrap(drive, hub_id).run()
        self.assertEqual(drive.list_children(hub_id, name=MASTER_NAME), [])

    def mutation_count(self) -> int:
        drive, hub_id = self.fresh()
        http = ModelDriveHttp(drive)
        result = DriveHubBootstrap(GoogleDriveBackend("token", http=http), hub_id).run()
        self.assertEqual(result.state, "INITIALIZED")
        self.assert_layout(drive, hub_id)
        return http.mutation_count

    def test_rest_lost_response_after_every_bootstrap_mutation_recovers(self) -> None:
        count = self.mutation_count()
        self.assertGreaterEqual(count, 9)
        for mutation_number in range(1, count + 1):
            with self.subTest(mutation_number=mutation_number, total=count):
                drive, hub_id = self.fresh()
                failing = GoogleDriveBackend(
                    "token",
                    http=ModelDriveHttp(drive, fail_after_mutation=mutation_number),
                )
                with self.assertRaises(DriveUncertainMutation):
                    DriveHubBootstrap(failing, hub_id).run()

                restarted = GoogleDriveBackend("token", http=ModelDriveHttp(drive))
                result = DriveHubBootstrap(restarted, hub_id).run()
                self.assertIn(result.state, {"INITIALIZED", "EXISTING"})
                self.assert_layout(drive, hub_id)
                self.assertEqual(result.master["canonical_epoch"], 0)
                self.assertEqual(result.master["canonical_read_status"], "SAFE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
