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
from keelaryn_core.drive_bootstrap import DriveHubBootstrap
from keelaryn_core.drive_model import DriveModel
from keelaryn_core.drive_rest import GoogleDriveBackend
from keelaryn_core.drive_workflow import DriveWorkflowBlocked
from keelaryn_core.reconciliation_state import DriveReconciliationStateService


class ReconciliationStateRestTests(unittest.TestCase):
    INITIAL = DriveHubBootstrap.initial_reconciliation_state_bytes()
    NEW = b"# Reconciliation State\n\nworking\n"

    @staticmethod
    def build():
        drive = DriveModel()
        hub = drive.create_folder("root", "Hub", label="setup.hub")
        DriveHubBootstrap(drive, hub.file_id).run()
        return drive, hub.file_id

    def test_initialize_is_read_only_over_rest(self) -> None:
        drive, hub_id = self.build()
        http = ModelDriveHttp(drive)
        backend = GoogleDriveBackend("token", http=http)
        state = DriveReconciliationStateService(backend, hub_id).initialize(self.INITIAL)
        self.assertEqual(state.raw, self.INITIAL)
        self.assertEqual(http.mutation_count, 0)
        with self.assertRaises(DriveWorkflowBlocked):
            DriveReconciliationStateService(backend, hub_id).initialize(b"different")
        self.assertEqual(http.mutation_count, 0)

    def mutation_count(self) -> int:
        drive, hub_id = self.build()
        DriveReconciliationStateService(drive, hub_id).initialize(self.INITIAL)
        http = ModelDriveHttp(drive)
        backend = GoogleDriveBackend("token", http=http)
        DriveReconciliationStateService(backend, hub_id).update("r1", self.NEW)
        self.assertGreater(http.mutation_count, 0)
        return http.mutation_count

    def test_update_recovers_after_every_uncertain_rest_mutation(self) -> None:
        count = self.mutation_count()
        for mutation_number in range(1, count + 1):
            with self.subTest(mutation_number=mutation_number, total=count):
                drive, hub_id = self.build()
                DriveReconciliationStateService(drive, hub_id).initialize(self.INITIAL)
                failing = GoogleDriveBackend(
                    "token",
                    http=ModelDriveHttp(drive, fail_after_mutation=mutation_number),
                )
                with self.assertRaises(DriveUncertainMutation):
                    DriveReconciliationStateService(failing, hub_id).update("r1", self.NEW)

                restarted = GoogleDriveBackend("token", http=ModelDriveHttp(drive))
                service = DriveReconciliationStateService(restarted, hub_id)
                completed = service.update("r1", self.NEW)
                current = service.read()
                self.assertEqual(current.raw, self.NEW)
                self.assertEqual(current.state_file_id, completed.plan["new"]["file_id"])
                self.assertEqual(completed.plan["owner_kind"], "RECONCILIATION")
                self.assertEqual(completed.plan["owner_id"], "reconciliation")


if __name__ == "__main__":
    unittest.main(verbosity=2)
