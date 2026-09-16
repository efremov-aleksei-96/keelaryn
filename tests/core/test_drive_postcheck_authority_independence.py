from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from keelaryn_core.drive_bundle import DriveTransactionBundle
from keelaryn_core.drive_core import DriveCoreRunner
from keelaryn_core.drive_postcheck import DrivePostcheckReceipts
from test_drive_core import DriveCoreTests, postcheck_bytes


class DrivePostcheckAuthorityIndependenceTests(unittest.TestCase):
    @staticmethod
    def fixture():
        helper = DriveCoreTests(methodName="test_wait_then_pass_commits_from_bundle_only_restart")
        return helper.build()

    def _accept_then_remove_external_source(self, decision: str):
        fixture = self.fixture()
        raw_bundle = fixture.bundle.to_bytes()

        status = DriveCoreRunner(fixture.drive, fixture.bundle).run_until_quiescent()
        self.assertEqual(status.phase, "WAIT_POSTCHECK")

        source = fixture.drive.create_blob(
            fixture.postcheck_parent_id,
            fixture.postcheck_name,
            postcheck_bytes(decision),
            label=f"external.postcheck.{decision.lower()}",
        )
        receipts = DrivePostcheckReceipts(fixture.drive, fixture.bundle.postcheck_binding)
        self.assertEqual(receipts.accept(), decision)
        self.assertEqual(receipts.decision(), decision)

        archive = fixture.drive.create_folder("root", f"external-postcheck-archive-{decision.lower()}")
        fixture.drive.move_rename(source.file_id, archive.file_id, source.name, label="external.archive-postcheck")
        fixture.drive.delete(fixture.postcheck_parent_id, label="external.delete-postcheck-parent")

        restored = DriveTransactionBundle.from_bytes(raw_bundle)
        return fixture, DriveCoreRunner(fixture.drive, restored).run_until_quiescent()

    def test_pass_receipt_remains_authority_after_external_source_folder_disappears(self) -> None:
        fixture, status = self._accept_then_remove_external_source("PASS")
        self.assertEqual(status.phase, "COMMITTED")
        helper = DriveCoreTests(methodName="test_wait_then_pass_commits_from_bundle_only_restart")
        helper.assert_new(fixture)

    def test_fail_receipt_remains_authority_after_external_source_folder_disappears(self) -> None:
        fixture, status = self._accept_then_remove_external_source("FAIL")
        self.assertEqual(status.phase, "ROLLED_BACK")
        helper = DriveCoreTests(methodName="test_fail_decision_rolls_back_and_increments_epoch")
        helper.assert_old(fixture)


if __name__ == "__main__":
    unittest.main(verbosity=2)
