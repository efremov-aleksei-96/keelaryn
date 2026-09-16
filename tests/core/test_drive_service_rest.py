from __future__ import annotations

import sys
import unittest
from hashlib import sha256
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "core"))
sys.path.insert(0, str(TESTS))

import test_drive_factory as factory_fixture
from drive_http_model import ModelDriveHttp
from keelaryn_core.drive_backend import DriveUncertainMutation
from keelaryn_core.drive_discovery import LOCATOR_NAME
from keelaryn_core.drive_master import DriveMasterTransition
from keelaryn_core.drive_rest import GoogleDriveBackend
from keelaryn_core.drive_service import DrivePollingService
from keelaryn_core.protocol import canonical_json_bytes, strict_json_bytes, validate_master


class DriveServiceRestTests(unittest.TestCase):
    @staticmethod
    def build(decision: str):
        fixture = factory_fixture.DriveFactoryTests.build()
        change = strict_json_bytes(fixture.change_raw, label="CHANGE.rest-service")
        raw = canonical_json_bytes(
            {
                "schema": "keelaryn.postcheck.v1",
                "change_id": change["change_id"],
                "change_sha256": sha256(fixture.change_raw).hexdigest(),
                "base_canonical_epoch": change["base_canonical_epoch"],
                "decision": decision,
                "reason": f"full service REST {decision}",
            }
        )
        factory_fixture.DriveFactoryTests.postcheck_parent(fixture).drive if False else None
        fixture.drive.create_blob(
            factory_fixture.DriveFactoryTests.postcheck_parent(fixture).file_id,
            "change-1.json",
            raw,
            label=f"setup.postcheck.{decision}",
        )
        return fixture

    @staticmethod
    def assert_final(fixture, outcome: str) -> None:
        _, raw = DriveMasterTransition.read_unique_master(fixture.drive, fixture.hub_id)
        master = validate_master(strict_json_bytes(raw, label="MASTER.service-rest-final"))
        self_change = master["last_completed_change"]
        if self_change is None or self_change["outcome"] != outcome:
            raise AssertionError(f"unexpected final MASTER: {master}")
        if master["canonical_read_status"] != "SAFE" or master["state"] != "READY":
            raise AssertionError(f"final MASTER not READY/SAFE: {master}")
        if fixture.drive.exact_name(fixture.change_folder_id, "READY.json") is not None:
            raise AssertionError("consumed READY marker remained in Reconciliation work")
        control = fixture.drive.exact_name(fixture.hub_id, "control")
        active = fixture.drive.exact_name(control.file_id, "active")
        if fixture.drive.list_children(active.file_id, name=LOCATOR_NAME):
            raise AssertionError("active locator remained after terminal cleanup")

    def mutation_count_for(self, decision: str) -> int:
        fixture = self.build(decision)
        http = ModelDriveHttp(fixture.drive)
        backend = GoogleDriveBackend("token", http=http)
        status = DrivePollingService(backend, fixture.hub_id).run_once()
        expected = "COMMITTED" if decision == "PASS" else "ROLLED_BACK"
        self.assertEqual(status.phase, expected)
        self.assertTrue(status.ready_clean)
        self.assert_final(fixture, expected)
        return http.mutation_count

    def recover_after_uncertain(self, fixture, expected: str) -> str:
        restarted = GoogleDriveBackend("token", http=ModelDriveHttp(fixture.drive))
        last = None
        for _ in range(4):
            last = DrivePollingService(restarted, fixture.hub_id).run_once()
            if last.phase in {expected, "IDLE"} and last.ready_clean:
                break
        if last is None:
            raise AssertionError("service restart produced no status")
        self.assertIn(last.phase, {expected, "IDLE"})
        self.assertTrue(last.ready_clean)
        self.assert_final(fixture, expected)
        return last.phase

    def _matrix(self, decision: str) -> None:
        mutation_count = self.mutation_count_for(decision)
        self.assertGreater(mutation_count, 20)
        expected = "COMMITTED" if decision == "PASS" else "ROLLED_BACK"
        for mutation_number in range(1, mutation_count + 1):
            with self.subTest(decision=decision, mutation_number=mutation_number, total=mutation_count):
                fixture = self.build(decision)
                failing = GoogleDriveBackend(
                    "token",
                    http=ModelDriveHttp(fixture.drive, fail_after_mutation=mutation_number),
                )
                with self.assertRaises(DriveUncertainMutation):
                    DrivePollingService(failing, fixture.hub_id).run_once()
                self.recover_after_uncertain(fixture, expected)

    def test_pass_full_service_uncertain_response_after_every_mutation(self) -> None:
        self._matrix("PASS")

    def test_fail_full_service_uncertain_response_after_every_mutation(self) -> None:
        self._matrix("FAIL")


if __name__ == "__main__":
    unittest.main(verbosity=2)
