from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "core"))
sys.path.insert(0, str(TESTS))

import test_drive_factory as factory_fixture
from drive_http_model import ModelDriveHttp
from keelaryn_core.drive_backend import DriveUncertainMutation
from keelaryn_core.drive_bundle import DriveBundleStore
from keelaryn_core.drive_discovery import DriveRestartDiscovery, LOCATOR_NAME
from keelaryn_core.drive_factory import DriveTransactionFactory
from keelaryn_core.drive_rest import GoogleDriveBackend
from keelaryn_core.drive_runtime import DriveRuntime
from keelaryn_core.drive_service import DrivePollingService, DriveServiceBlocked
from keelaryn_core.protocol import canonical_json_bytes


class DriveServiceTests(unittest.TestCase):
    @staticmethod
    def build():
        return factory_fixture.DriveFactoryTests.build()

    @staticmethod
    def postcheck_parent(fixture):
        return factory_fixture.DriveFactoryTests.postcheck_parent(fixture)

    @staticmethod
    def postcheck_bytes(bundle, decision: str):
        return factory_fixture.DriveFactoryTests.postcheck_bytes(bundle, decision)

    def discovered_bundle(self, drive, hub_id):
        found = DriveRestartDiscovery.from_hub_root(drive, hub_id).discover()
        self.assertIsNotNone(found.bundle)
        return found.bundle

    def test_pass_polling_cycle_consumes_ready_and_returns_idle(self) -> None:
        fixture = self.build()
        service = DrivePollingService(fixture.drive, fixture.hub_id)
        first = service.run_once()
        self.assertEqual(first.phase, "WAIT_POSTCHECK")
        self.assertFalse(first.ready_clean)
        bundle = self.discovered_bundle(fixture.drive, fixture.hub_id)

        fixture.drive.create_blob(
            self.postcheck_parent(fixture).file_id,
            "change-1.json",
            self.postcheck_bytes(bundle, "PASS"),
            label="external.postcheck.pass",
        )
        final = DrivePollingService(fixture.drive, fixture.hub_id).run_once()
        self.assertEqual(final.phase, "COMMITTED")
        self.assertTrue(final.ready_clean)

        self.assertIsNone(fixture.drive.exact_name(fixture.change_folder_id, "READY.json"))
        archived_ready = fixture.drive.exact_name(
            bundle.bundle_parent_id,
            "change-1.READY.consumed.json",
        )
        self.assertIsNotNone(archived_ready)
        control = fixture.drive.exact_name(fixture.hub_id, "control")
        active = fixture.drive.exact_name(control.file_id, "active")
        self.assertEqual(fixture.drive.list_children(active.file_id, name=LOCATOR_NAME), [])
        self.assertEqual(DrivePollingService(fixture.drive, fixture.hub_id).run_once().phase, "IDLE")

    def test_fail_polling_cycle_rolls_back_consumes_ready_and_returns_idle(self) -> None:
        fixture = self.build()
        service = DrivePollingService(fixture.drive, fixture.hub_id)
        self.assertEqual(service.run_once().phase, "WAIT_POSTCHECK")
        bundle = self.discovered_bundle(fixture.drive, fixture.hub_id)
        fixture.drive.create_blob(
            self.postcheck_parent(fixture).file_id,
            "change-1.json",
            self.postcheck_bytes(bundle, "FAIL"),
            label="external.postcheck.fail",
        )
        final = DrivePollingService(fixture.drive, fixture.hub_id).run_once()
        self.assertEqual(final.phase, "ROLLED_BACK")
        self.assertTrue(final.ready_clean)
        factory_fixture.DriveFactoryTests().assert_old(fixture)
        self.assertEqual(DrivePollingService(fixture.drive, fixture.hub_id).run_once().phase, "IDLE")

    def test_orphan_bundle_before_locator_is_resumed_by_service(self) -> None:
        fixture = self.build()
        bundle = DriveTransactionFactory(fixture.drive, fixture.hub_id).build_or_resume()
        self.assertIsNotNone(bundle)
        DriveBundleStore(fixture.drive, bundle).ensure()
        self.assertEqual(DrivePollingService(fixture.drive, fixture.hub_id).run_once().phase, "WAIT_POSTCHECK")
        restored = self.discovered_bundle(fixture.drive, fixture.hub_id)
        self.assertEqual(restored.to_bytes(), bundle.to_bytes())

    def test_lost_response_consuming_ready_recovers_before_locator_cleanup(self) -> None:
        fixture = self.build()
        self.assertEqual(DrivePollingService(fixture.drive, fixture.hub_id).run_once().phase, "WAIT_POSTCHECK")
        bundle = self.discovered_bundle(fixture.drive, fixture.hub_id)
        fixture.drive.create_blob(
            self.postcheck_parent(fixture).file_id,
            "change-1.json",
            self.postcheck_bytes(bundle, "PASS"),
            label="external.postcheck.pass",
        )
        self.assertEqual(DriveRuntime(fixture.drive, fixture.hub_id).restart().phase, "COMMITTED")

        failing = GoogleDriveBackend("token", http=ModelDriveHttp(fixture.drive, fail_after_mutation=1))
        with self.assertRaises(DriveUncertainMutation):
            DrivePollingService(failing, fixture.hub_id).run_once()

        # Server-side READY move happened despite the lost response; locator stayed
        # active because cleanup is ordered after Ready consumption.
        self.assertIsNone(fixture.drive.exact_name(fixture.change_folder_id, "READY.json"))
        control = fixture.drive.exact_name(fixture.hub_id, "control")
        active = fixture.drive.exact_name(control.file_id, "active")
        self.assertEqual(len(fixture.drive.list_children(active.file_id, name=LOCATOR_NAME)), 1)

        restarted = GoogleDriveBackend("token", http=ModelDriveHttp(fixture.drive))
        final = DrivePollingService(restarted, fixture.hub_id).run_once()
        self.assertEqual(final.phase, "COMMITTED")
        self.assertTrue(final.ready_clean)

    def test_changed_external_ready_after_commit_is_not_mutated_or_hidden(self) -> None:
        fixture = self.build()
        self.assertEqual(DrivePollingService(fixture.drive, fixture.hub_id).run_once().phase, "WAIT_POSTCHECK")
        bundle = self.discovered_bundle(fixture.drive, fixture.hub_id)
        fixture.drive.create_blob(
            self.postcheck_parent(fixture).file_id,
            "change-1.json",
            self.postcheck_bytes(bundle, "PASS"),
            label="external.postcheck.pass",
        )
        self.assertEqual(DriveRuntime(fixture.drive, fixture.hub_id).restart().phase, "COMMITTED")

        ready_item = fixture.drive.exact_name(fixture.change_folder_id, "READY.json")
        fixture.drive.update_content(
            ready_item.file_id,
            canonical_json_bytes(
                {
                    "schema": "keelaryn.ready.v1",
                    "state": "READY_FOR_COMMIT",
                    "change_id": "change-1",
                    "change_sha256": "0" * 64,
                }
            ),
            label="external.mutate-ready-after-commit",
        )
        with self.assertRaises(DriveServiceBlocked):
            DrivePollingService(fixture.drive, fixture.hub_id).run_once()
        self.assertEqual(fixture.drive.exact_name(fixture.change_folder_id, "READY.json").file_id, ready_item.file_id)
        self.assertIsNone(
            fixture.drive.exact_name(bundle.bundle_parent_id, "change-1.READY.consumed.json")
        )
        found = DriveRestartDiscovery.from_hub_root(fixture.drive, fixture.hub_id).discover()
        self.assertEqual(found.state, "READY_WITH_LOCATOR")
        self.assertEqual(found.runner_phase, "COMMITTED")

    def test_recovery_blocked_poll_keeps_locator_and_ready_marker(self) -> None:
        fixture = self.build()
        self.assertEqual(DrivePollingService(fixture.drive, fixture.hub_id).run_once().phase, "WAIT_POSTCHECK")
        bundle = self.discovered_bundle(fixture.drive, fixture.hub_id)
        snapshot_id = bundle.snapshot_plan.entries[0].snapshot_id
        fixture.drive.update_content(snapshot_id, b"damaged", label="external.damage-snapshot")

        blocked = DrivePollingService(fixture.drive, fixture.hub_id).run_once()
        self.assertEqual(blocked.phase, "RECOVERY_BLOCKED")
        self.assertFalse(blocked.ready_clean)
        self.assertIsNotNone(fixture.drive.exact_name(fixture.change_folder_id, "READY.json"))
        found = DriveRestartDiscovery.from_hub_root(fixture.drive, fixture.hub_id).discover()
        self.assertEqual(found.state, "RECOVERY_BLOCKED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
