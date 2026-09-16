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
from keelaryn_core.drive_core import DriveCoreRunner
from keelaryn_core.drive_discovery import DriveRestartDiscovery, LOCATOR_NAME
from keelaryn_core.drive_rest import GoogleDriveBackend
from keelaryn_core.drive_runtime import DriveRuntime, DriveRuntimeBlocked
from keelaryn_core.protocol import FaultInjector, InjectedCrash


class DriveRuntimeTests(unittest.TestCase):
    @staticmethod
    def build(*, decision: str | None = None):
        return core_fixture.DriveCoreTests().build(decision=decision)

    @staticmethod
    def add_control_active(fixture):
        control = fixture.drive.create_folder(fixture.bundle.hub_root_id, "control", label="setup.control")
        active = fixture.drive.create_folder(control.file_id, "active", label="setup.active")
        return active

    def test_new_pass_transaction_keeps_locator_until_safe_cleanup(self) -> None:
        fixture = self.build(decision="PASS")
        active = self.add_control_active(fixture)
        runtime = DriveRuntime(fixture.drive, fixture.bundle.hub_root_id)

        result = runtime.run_new(fixture.bundle)
        self.assertEqual(result.phase, "COMMITTED")
        locators = fixture.drive.list_children(active.file_id, name=LOCATOR_NAME)
        self.assertEqual(len(locators), 1)

        cleaned = runtime.cleanup_ready_locator()
        self.assertEqual(cleaned.phase, "READY_CLEAN")
        self.assertEqual(fixture.drive.list_children(active.file_id, name=LOCATOR_NAME), [])
        discovery = DriveRestartDiscovery.from_hub_root(
            fixture.drive,
            fixture.bundle.hub_root_id,
        ).discover()
        self.assertEqual(discovery.state, "READY_CLEAN")

    def test_process_loss_after_locator_before_activation_resumes_from_hub_only(self) -> None:
        fixture = self.build()
        self.add_control_active(fixture)
        first = DriveRuntime(fixture.drive, fixture.bundle.hub_root_id)
        binding = first.prepare(fixture.bundle)

        # Drop process-local bundle/locator variables as authority. A fresh runtime
        # discovers the locator and exact bundle from Drive and continues activation.
        restarted = DriveRuntime(fixture.drive, fixture.bundle.hub_root_id)
        result = restarted.restart()
        self.assertEqual(result.phase, "WAIT_POSTCHECK")
        discovered = DriveRestartDiscovery.from_hub_root(
            fixture.drive,
            fixture.bundle.hub_root_id,
        ).discover()
        self.assertEqual(discovered.state, "ACTIVE")
        self.assertEqual(discovered.locator.locator_id, binding.locator_id)

    def test_active_restart_then_postcheck_commits_without_original_bundle_object(self) -> None:
        fixture = self.build()
        self.add_control_active(fixture)
        runtime = DriveRuntime(fixture.drive, fixture.bundle.hub_root_id)
        runtime.prepare(fixture.bundle)
        self.assertEqual(DriveRuntime(fixture.drive, fixture.bundle.hub_root_id).restart().phase, "WAIT_POSTCHECK")

        fixture.drive.create_blob(
            fixture.postcheck_parent_id,
            fixture.postcheck_name,
            core_fixture.postcheck_bytes("PASS"),
            label="external.postcheck.pass",
        )
        final = DriveRuntime(fixture.drive, fixture.bundle.hub_root_id).restart()
        self.assertEqual(final.phase, "COMMITTED")

    def test_zero_master_gap_restart_discovers_bundle_and_completes_commit(self) -> None:
        fixture = self.build()
        self.add_control_active(fixture)
        runtime = DriveRuntime(fixture.drive, fixture.bundle.hub_root_id)
        runtime.prepare(fixture.bundle)
        self.assertEqual(runtime.restart().phase, "WAIT_POSTCHECK")
        fixture.drive.create_blob(
            fixture.postcheck_parent_id,
            fixture.postcheck_name,
            core_fixture.postcheck_bytes("PASS"),
            label="external.postcheck.pass",
        )
        fixture.drive.fault = FaultInjector("drive.master.change-1.commit.displace_old.after")
        with self.assertRaises(InjectedCrash):
            runtime.restart()

        fixture.drive.fault = FaultInjector()
        recovered = DriveRuntime(fixture.drive, fixture.bundle.hub_root_id).restart()
        self.assertEqual(recovered.phase, "COMMITTED")

    def test_recovery_blocked_restart_is_terminal_and_keeps_locator(self) -> None:
        fixture = self.build()
        active = self.add_control_active(fixture)
        runtime = DriveRuntime(fixture.drive, fixture.bundle.hub_root_id)
        runtime.prepare(fixture.bundle)
        self.assertEqual(runtime.restart().phase, "WAIT_POSTCHECK")
        snapshot_id = fixture.bundle.snapshot_plan.entries[0].snapshot_id
        fixture.drive.update_content(snapshot_id, b"damaged snapshot", label="external.damage-snapshot")

        blocked = DriveRuntime(fixture.drive, fixture.bundle.hub_root_id).restart()
        self.assertEqual(blocked.phase, "RECOVERY_BLOCKED")
        again = DriveRuntime(fixture.drive, fixture.bundle.hub_root_id).restart()
        self.assertEqual(again.phase, "RECOVERY_BLOCKED")
        self.assertEqual(len(fixture.drive.list_children(active.file_id, name=LOCATOR_NAME)), 1)
        with self.assertRaises(DriveRuntimeBlocked):
            DriveRuntime(fixture.drive, fixture.bundle.hub_root_id).cleanup_ready_locator()

    def test_locator_cleanup_lost_response_recovers_as_ready_clean(self) -> None:
        fixture = self.build(decision="PASS")
        self.add_control_active(fixture)
        runtime = DriveRuntime(fixture.drive, fixture.bundle.hub_root_id)
        binding = runtime.prepare(fixture.bundle)
        self.assertEqual(DriveCoreRunner(fixture.drive, fixture.bundle).run_until_quiescent().phase, "COMMITTED")

        failing = GoogleDriveBackend(
            "token",
            http=ModelDriveHttp(fixture.drive, fail_after_mutation=1),
        )
        with self.assertRaises(DriveUncertainMutation):
            DriveRuntime(failing, fixture.bundle.hub_root_id).cleanup_ready_locator()

        restarted = GoogleDriveBackend("token", http=ModelDriveHttp(fixture.drive))
        cleaned = DriveRuntime(restarted, fixture.bundle.hub_root_id).cleanup_ready_locator()
        self.assertEqual(cleaned.phase, "READY_CLEAN")
        archived = restarted.get(binding.locator_id, include_trashed=False)
        self.assertEqual(archived.parent_id, fixture.bundle.bundle_parent_id)
        self.assertEqual(
            archived.name,
            f"{fixture.bundle.change_id}.ACTIVE_TRANSACTION.archived.json",
        )

    def test_duplicate_locator_blocks_restart_instead_of_selecting_one(self) -> None:
        fixture = self.build()
        active = self.add_control_active(fixture)
        runtime = DriveRuntime(fixture.drive, fixture.bundle.hub_root_id)
        binding = runtime.prepare(fixture.bundle)
        fixture.drive.create_blob(
            active.file_id,
            LOCATOR_NAME,
            binding.to_bytes(),
            label="external.duplicate-locator",
        )
        with self.assertRaises(DriveRuntimeBlocked):
            DriveRuntime(fixture.drive, fixture.bundle.hub_root_id).restart()


if __name__ == "__main__":
    unittest.main(verbosity=2)
