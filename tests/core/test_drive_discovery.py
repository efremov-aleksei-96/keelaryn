from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "core"))
sys.path.insert(0, str(TESTS))

import test_drive_core as core_fixture
from drive_http_model import ModelDriveHttp
from keelaryn_core.drive_backend import DriveUncertainMutation
from keelaryn_core.drive_bundle import DriveBundleStore, DriveTransactionBundle
from keelaryn_core.drive_core import DriveCoreRunner
from keelaryn_core.drive_discovery import (
    DriveActiveLocatorBinding,
    DriveActiveLocatorStore,
    DriveDiscoveryBlocked,
    DriveRestartDiscovery,
    LOCATOR_NAME,
)
from keelaryn_core.drive_master import DriveMasterTransition
from keelaryn_core.drive_rest import GoogleDriveBackend
from keelaryn_core.protocol import FaultInjector, InjectedCrash


class DriveDiscoveryTests(unittest.TestCase):
    @staticmethod
    def build():
        return core_fixture.DriveCoreTests().build()

    @staticmethod
    def add_control_active(fixture):
        control = fixture.drive.create_folder(fixture.bundle.hub_root_id, "control", label="setup.control")
        active = fixture.drive.create_folder(control.file_id, "active", label="setup.active")
        return control, active

    def prepare_locator(self, fixture):
        _, active = self.add_control_active(fixture)
        DriveBundleStore(fixture.drive, fixture.bundle).ensure()
        binding = DriveActiveLocatorBinding.plan(fixture.drive, fixture.bundle, active.file_id)
        DriveActiveLocatorStore(fixture.drive, binding).ensure()
        return active, binding

    def test_ready_without_locator_is_clean(self) -> None:
        fixture = self.build()
        self.add_control_active(fixture)
        result = DriveRestartDiscovery.from_hub_root(
            fixture.drive,
            fixture.bundle.hub_root_id,
        ).discover()
        self.assertEqual(result.state, "READY_CLEAN")
        self.assertIsNone(result.bundle)
        self.assertIsNone(result.locator)

    def test_locator_roundtrip_loads_exact_preactivation_bundle(self) -> None:
        fixture = self.build()
        _, binding = self.prepare_locator(fixture)
        raw_bundle = fixture.bundle.to_bytes()

        discovery = DriveRestartDiscovery.from_hub_root(
            fixture.drive,
            fixture.bundle.hub_root_id,
        )
        result = discovery.discover()
        self.assertEqual(result.state, "READY_WITH_LOCATOR")
        self.assertEqual(result.runner_phase, "BASE_READY")
        self.assertEqual(result.locator, binding)
        self.assertEqual(result.bundle.to_bytes(), raw_bundle)

    def test_active_restart_recovers_bundle_without_process_transaction_object(self) -> None:
        fixture = self.build()
        self.prepare_locator(fixture)
        self.assertEqual(
            DriveCoreRunner(fixture.drive, fixture.bundle).run_until_quiescent().phase,
            "WAIT_POSTCHECK",
        )

        result = DriveRestartDiscovery.from_hub_root(
            fixture.drive,
            fixture.bundle.hub_root_id,
        ).discover()
        self.assertEqual(result.state, "ACTIVE")
        self.assertEqual(result.runner_phase, "ACTIVE_UNSAFE")
        self.assertEqual(result.bundle.to_bytes(), fixture.bundle.to_bytes())

    def test_recovery_blocked_restart_recovers_exact_bundle(self) -> None:
        fixture = self.build()
        self.prepare_locator(fixture)
        runner = DriveCoreRunner(fixture.drive, fixture.bundle)
        self.assertEqual(runner.run_until_quiescent().phase, "WAIT_POSTCHECK")
        snapshot_id = fixture.bundle.snapshot_plan.entries[0].snapshot_id
        fixture.drive.update_content(snapshot_id, b"damaged snapshot", label="external.damage-snapshot")
        self.assertEqual(runner.run_until_quiescent().phase, "RECOVERY_BLOCKED")

        result = DriveRestartDiscovery.from_hub_root(
            fixture.drive,
            fixture.bundle.hub_root_id,
        ).discover()
        self.assertEqual(result.state, "RECOVERY_BLOCKED")
        self.assertEqual(result.runner_phase, "RECOVERY_BLOCKED")
        self.assertEqual(result.bundle.to_bytes(), fixture.bundle.to_bytes())

    def test_zero_master_commit_gap_is_attributed_from_locator_and_bundle_only(self) -> None:
        fixture = self.build()
        self.prepare_locator(fixture)
        runner = DriveCoreRunner(fixture.drive, fixture.bundle)
        self.assertEqual(runner.run_until_quiescent().phase, "WAIT_POSTCHECK")
        fixture.drive.create_blob(
            fixture.postcheck_parent_id,
            fixture.postcheck_name,
            core_fixture.postcheck_bytes("PASS"),
            label="external.postcheck.pass",
        )
        fixture.drive.fault = FaultInjector("drive.master.change-1.commit.displace_old.after")
        with self.assertRaises(InjectedCrash):
            runner.run_until_quiescent()

        result = DriveRestartDiscovery.from_hub_root(
            fixture.drive,
            fixture.bundle.hub_root_id,
        ).discover()
        self.assertEqual(result.state, "RECOVERABLE_GAP")
        self.assertEqual(result.master_state, "MISSING")
        self.assertTrue(result.runner_phase.startswith("GAP_COMMIT_"))
        fixture.drive.fault = FaultInjector()
        status = DriveCoreRunner(fixture.drive, result.bundle).run_until_quiescent()
        self.assertEqual(status.phase, "COMMITTED")

    def test_duplicate_locator_is_fail_closed(self) -> None:
        fixture = self.build()
        active, binding = self.prepare_locator(fixture)
        fixture.drive.create_blob(
            active.file_id,
            LOCATOR_NAME,
            binding.to_bytes(),
            label="external.duplicate-locator",
        )
        with self.assertRaises(DriveDiscoveryBlocked):
            DriveRestartDiscovery.from_hub_root(
                fixture.drive,
                fixture.bundle.hub_root_id,
            ).discover()

    def test_malformed_locator_is_fail_closed(self) -> None:
        fixture = self.build()
        _, binding = self.prepare_locator(fixture)
        fixture.drive.update_content(binding.locator_id, b"{}", label="external.corrupt-locator")
        with self.assertRaises(DriveDiscoveryBlocked):
            DriveRestartDiscovery.from_hub_root(
                fixture.drive,
                fixture.bundle.hub_root_id,
            ).discover()

    def test_active_master_without_locator_is_fail_closed(self) -> None:
        fixture = self.build()
        self.add_control_active(fixture)
        self.assertEqual(
            DriveCoreRunner(fixture.drive, fixture.bundle).run_until_quiescent().phase,
            "WAIT_POSTCHECK",
        )
        with self.assertRaises(DriveDiscoveryBlocked):
            DriveRestartDiscovery.from_hub_root(
                fixture.drive,
                fixture.bundle.hub_root_id,
            ).discover()

    def test_unknown_master_is_not_repaired_by_valid_locator(self) -> None:
        fixture = self.build()
        self.prepare_locator(fixture)
        self.assertEqual(
            DriveCoreRunner(fixture.drive, fixture.bundle).run_until_quiescent().phase,
            "WAIT_POSTCHECK",
        )
        root, _ = DriveMasterTransition.read_unique_master(
            fixture.drive,
            fixture.bundle.hub_root_id,
        )
        fixture.drive.update_content(root.file_id, b"{}", label="external.corrupt-master")
        with self.assertRaises(DriveDiscoveryBlocked):
            DriveRestartDiscovery.from_hub_root(
                fixture.drive,
                fixture.bundle.hub_root_id,
            ).discover()

    def test_lost_locator_create_response_recovers_exact_locator_and_bundle_over_rest(self) -> None:
        fixture = self.build()
        _, active = self.add_control_active(fixture)
        DriveBundleStore(fixture.drive, fixture.bundle).ensure()

        failing_http = ModelDriveHttp(fixture.drive, fail_after_mutation=1)
        failing = GoogleDriveBackend("token", http=failing_http)
        binding = DriveActiveLocatorBinding.plan(failing, fixture.bundle, active.file_id)
        with self.assertRaises(DriveUncertainMutation):
            DriveActiveLocatorStore(failing, binding).ensure()

        restarted = GoogleDriveBackend("token", http=ModelDriveHttp(fixture.drive))
        DriveActiveLocatorStore(restarted, binding).verify()
        result = DriveRestartDiscovery.from_hub_root(
            restarted,
            fixture.bundle.hub_root_id,
        ).discover()
        self.assertEqual(result.state, "READY_WITH_LOCATOR")
        self.assertEqual(result.locator, binding)
        self.assertEqual(result.bundle.to_bytes(), fixture.bundle.to_bytes())


if __name__ == "__main__":
    unittest.main(verbosity=2)
