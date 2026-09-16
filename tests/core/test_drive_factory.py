from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "core"))
sys.path.insert(0, str(TESTS))

import test_drive_ingestion as ingestion_fixture
from keelaryn_core.drive_bundle import DriveBundleStore
from keelaryn_core.drive_factory import DriveTransactionFactory, DriveTransactionFactoryBlocked
from keelaryn_core.drive_model import DriveModel
from keelaryn_core.drive_runtime import DriveRuntime
from keelaryn_core.protocol import FaultInjector, InjectedCrash, canonical_json_bytes


class DriveFactoryTests(unittest.TestCase):
    @staticmethod
    def build():
        fixture = ingestion_fixture.DriveIngestionTests().build()
        work = fixture.drive.exact_name(fixture.hub_id, "work")
        reconciliation = fixture.drive.exact_name(work.file_id, "reconciliation")
        fixture.drive.create_folder(reconciliation.file_id, "postcheck", label="setup.postcheck")
        control = fixture.drive.create_folder(fixture.hub_id, "control", label="setup.control")
        fixture.drive.create_folder(control.file_id, "active", label="setup.active")
        return fixture

    @staticmethod
    def postcheck_bytes(bundle, decision: str) -> bytes:
        return canonical_json_bytes(
            {
                "schema": "keelaryn.postcheck.v1",
                "change_id": bundle.change_id,
                "change_sha256": bundle.change_sha256,
                "base_canonical_epoch": bundle.base_canonical_epoch,
                "decision": decision,
                "reason": f"factory integration {decision}",
            }
        )

    @staticmethod
    def postcheck_parent(fixture):
        work = fixture.drive.exact_name(fixture.hub_id, "work")
        reconciliation = fixture.drive.exact_name(work.file_id, "reconciliation")
        return fixture.drive.exact_name(reconciliation.file_id, "postcheck")

    def assert_new(self, fixture, bundle) -> None:
        control = bundle.control
        by_id = {op.operation_id: op for op in control.operations}
        self.assertEqual(
            fixture.drive.exact_name(fixture.canonical_id, "added.txt").file_id,
            by_id["add"].staged_new_id,
        )
        self.assertEqual(
            fixture.drive.exact_name(fixture.canonical_id, "replace.txt").file_id,
            by_id["replace"].staged_new_id,
        )
        self.assertIsNone(fixture.drive.exact_name(fixture.canonical_id, "delete.txt"))

    def assert_old(self, fixture) -> None:
        self.assertIsNone(fixture.drive.exact_name(fixture.canonical_id, "added.txt"))
        self.assertEqual(
            fixture.drive.exact_name(fixture.canonical_id, "replace.txt").file_id,
            fixture.replace_old_id,
        )
        self.assertEqual(
            fixture.drive.exact_name(fixture.canonical_id, "delete.txt").file_id,
            fixture.delete_old_id,
        )

    def test_ready_change_builds_complete_bundle_and_pass_lifecycle(self) -> None:
        fixture = self.build()
        factory = DriveTransactionFactory(fixture.drive, fixture.hub_id)
        bundle = factory.build_or_resume()
        self.assertIsNotNone(bundle)
        self.assertEqual(bundle.change_sha256, __import__("hashlib").sha256(fixture.change_raw).hexdigest())
        self.assertEqual([op.kind for op in bundle.control.operations], ["ADD", "REPLACE", "DELETE"])

        runtime = DriveRuntime(fixture.drive, fixture.hub_id)
        self.assertEqual(runtime.run_new(bundle).phase, "WAIT_POSTCHECK")
        postcheck_parent = self.postcheck_parent(fixture)
        fixture.drive.create_blob(
            postcheck_parent.file_id,
            "change-1.json",
            self.postcheck_bytes(bundle, "PASS"),
            label="external.postcheck.pass",
        )
        self.assertEqual(DriveRuntime(fixture.drive, fixture.hub_id).restart().phase, "COMMITTED")
        self.assert_new(fixture, bundle)

    def test_ready_change_fail_lifecycle_rolls_back(self) -> None:
        fixture = self.build()
        bundle = DriveTransactionFactory(fixture.drive, fixture.hub_id).build_or_resume()
        self.assertIsNotNone(bundle)
        fixture.drive.create_blob(
            self.postcheck_parent(fixture).file_id,
            "change-1.json",
            self.postcheck_bytes(bundle, "FAIL"),
            label="external.postcheck.fail",
        )
        result = DriveRuntime(fixture.drive, fixture.hub_id).run_new(bundle)
        self.assertEqual(result.phase, "ROLLED_BACK")
        self.assert_old(fixture)

    def test_orphan_bundle_before_locator_is_reused_exactly(self) -> None:
        fixture = self.build()
        first = DriveTransactionFactory(fixture.drive, fixture.hub_id).build_or_resume()
        self.assertIsNotNone(first)
        DriveBundleStore(fixture.drive, first).ensure()

        # Simulate process loss before DriveRuntime could create ACTIVE_TRANSACTION.json.
        restored = DriveTransactionFactory(fixture.drive, fixture.hub_id).build_or_resume()
        self.assertIsNotNone(restored)
        self.assertEqual(restored.to_bytes(), first.to_bytes())
        self.assertEqual(DriveRuntime(fixture.drive, fixture.hub_id).run_new(restored).phase, "WAIT_POSTCHECK")

    def test_partial_recovery_tree_crash_is_reobservable_while_still_ready(self) -> None:
        fixture = self.build()
        fixture.drive.fault = FaultInjector("drive.factory.change-1.snapshots.create.after")
        with self.assertRaises(InjectedCrash):
            DriveTransactionFactory(fixture.drive, fixture.hub_id).build_or_resume()

        fixture.drive.fault = FaultInjector()
        bundle = DriveTransactionFactory(fixture.drive, fixture.hub_id).build_or_resume()
        self.assertIsNotNone(bundle)
        history = fixture.drive.exact_name(fixture.hub_id, "history")
        change_root = fixture.drive.exact_name(history.file_id, "change-1")
        self.assertEqual(len(fixture.drive.list_children(change_root.file_id, name="snapshots")), 1)

    def test_unknown_material_in_recovery_root_blocks_factory(self) -> None:
        fixture = self.build()
        history = fixture.drive.exact_name(fixture.hub_id, "history")
        change_root = fixture.drive.exact_name(history.file_id, "change-1")
        fixture.drive.create_blob(change_root.file_id, "mystery.bin", b"unknown", label="external.unknown-history")
        with self.assertRaises(DriveTransactionFactoryBlocked):
            DriveTransactionFactory(fixture.drive, fixture.hub_id).build_or_resume()

    def test_completed_change_is_not_replayed_from_stale_ready_marker(self) -> None:
        fixture = self.build()
        bundle = DriveTransactionFactory(fixture.drive, fixture.hub_id).build_or_resume()
        self.assertIsNotNone(bundle)
        fixture.drive.create_blob(
            self.postcheck_parent(fixture).file_id,
            "change-1.json",
            self.postcheck_bytes(bundle, "PASS"),
            label="external.postcheck.pass",
        )
        runtime = DriveRuntime(fixture.drive, fixture.hub_id)
        self.assertEqual(runtime.run_new(bundle).phase, "COMMITTED")
        self.assertEqual(runtime.cleanup_ready_locator().phase, "READY_CLEAN")

        with self.assertRaises(DriveTransactionFactoryBlocked):
            DriveTransactionFactory(fixture.drive, fixture.hub_id).build_or_resume()
        self.assert_new(fixture, bundle)


if __name__ == "__main__":
    unittest.main(verbosity=2)
