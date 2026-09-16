from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from keelaryn_core.drive_bootstrap import DriveHubBootstrap
from keelaryn_core.drive_model import DriveModel
from keelaryn_core.drive_workflow import DriveWorkflowBlocked
from keelaryn_core.protocol import FaultInjector, InjectedCrash
from keelaryn_core.reconciliation_state import DriveReconciliationStateService


class ReconciliationStateTests(unittest.TestCase):
    INITIAL = b"# Reconciliation State\n\nidle\n"
    NEW1 = b"# Reconciliation State\n\nclaiming project-a/result-1\n"
    NEW2 = b"# Reconciliation State\n\npreparing change-1\n"

    @staticmethod
    def build():
        drive = DriveModel()
        hub = drive.create_folder("root", "Hub", label="setup.hub")
        DriveHubBootstrap(drive, hub.file_id).run()
        return drive, hub.file_id

    def test_initialize_is_exact_and_idempotent(self) -> None:
        drive, hub_id = self.build()
        service = DriveReconciliationStateService(drive, hub_id)
        with self.assertRaises(DriveWorkflowBlocked):
            service.read()
        first = service.initialize(self.INITIAL)
        second = DriveReconciliationStateService(drive, hub_id).initialize(self.INITIAL)
        self.assertEqual(first, second)
        self.assertEqual(first.raw, self.INITIAL)
        with self.assertRaises(DriveWorkflowBlocked):
            service.initialize(b"different initial bytes")
        self.assertEqual(service.read(), first)

    def test_update_uses_reconciliation_bound_generic_authority(self) -> None:
        drive, hub_id = self.build()
        service = DriveReconciliationStateService(drive, hub_id)
        initial = service.initialize(self.INITIAL)
        update = service.update("r1", self.NEW1)
        current = service.read()
        self.assertNotEqual(initial.state_file_id, current.state_file_id)
        self.assertEqual(current.raw, self.NEW1)
        self.assertEqual(update.plan["owner_kind"], "RECONCILIATION")
        self.assertEqual(update.plan["owner_id"], "reconciliation")
        self.assertEqual(update.plan["owner_folder_id"], current.reconciliation_folder_id)
        self.assertEqual(update.plan["new"]["file_id"], current.state_file_id)
        self.assertEqual(service.update("r1", self.NEW1).done_file_id, update.done_file_id)

    def test_crash_matrix_recovers_without_reconciliation_specific_state_machine(self) -> None:
        points = (
            "drive.reconciliation-state.history.create.after",
            "drive.reconciliation-state.r1.folder.create.after",
            "drive.reconciliation-state.r1.plan.create.after",
            "drive.reconciliation-state.r1.new.create.after",
            "drive.reconciliation-state.r1.archive-old.after",
            "drive.reconciliation-state.r1.publish-new.after",
            "drive.reconciliation-state.r1.done.create.after",
        )
        for point in points:
            with self.subTest(point=point):
                drive, hub_id = self.build()
                DriveReconciliationStateService(drive, hub_id).initialize(self.INITIAL)
                drive.fault = FaultInjector(point)
                with self.assertRaises(InjectedCrash):
                    DriveReconciliationStateService(drive, hub_id).update("r1", self.NEW1)
                drive.fault = FaultInjector()
                recovered = DriveReconciliationStateService(drive, hub_id).update("r1", self.NEW1)
                state = DriveReconciliationStateService(drive, hub_id).read()
                self.assertEqual(state.raw, self.NEW1)
                self.assertEqual(state.state_file_id, recovered.plan["new"]["file_id"])

    def test_two_updates_form_same_retained_chain_contract_as_project_state(self) -> None:
        drive, hub_id = self.build()
        service = DriveReconciliationStateService(drive, hub_id)
        service.initialize(self.INITIAL)
        first = service.update("r1", self.NEW1)
        second = service.update("r2", self.NEW2)
        self.assertEqual(second.plan["old"]["file_id"], first.plan["new"]["file_id"])
        self.assertEqual(service.read().raw, self.NEW2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
