from __future__ import annotations

import sys
import unittest
from hashlib import sha256
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from keelaryn_core.drive_bootstrap import DriveHubBootstrap
from keelaryn_core.drive_discovery import DriveRestartDiscovery
from keelaryn_core.drive_master import DriveMasterTransition
from keelaryn_core.drive_model import DriveModel
from keelaryn_core.drive_service import DrivePollingService
from keelaryn_core.drive_workflow import (
    DriveProjectWorkflow,
    DriveResultClaimService,
    DriveWorkflowLayoutResolver,
)
from keelaryn_core.protocol import canonical_json_bytes, strict_json_bytes, validate_master


ABSENT = {"state": "ABSENT"}


def present(raw: bytes) -> dict[str, object]:
    return {"state": "PRESENT", "sha256": sha256(raw).hexdigest(), "size": len(raw)}


class DriveProjectEndToEndTests(unittest.TestCase):
    PROJECT = "project-a"
    RESULT = "result-1"
    CHANGE = "change-1"
    TARGET = "project-a.md"

    def build(self):
        drive = DriveModel()
        hub = drive.create_folder("root", "Hub", label="setup.hub")
        bootstrap = DriveHubBootstrap(drive, hub.file_id).run()
        workflow_layout = DriveWorkflowLayoutResolver(drive, hub.file_id).resolve()

        project = DriveProjectWorkflow(drive, workflow_layout.projects_parent_id)
        project.initialize_project(self.PROJECT, b"# Project state\n\nready to hand off\n")
        result = project.publish_result(
            project_id=self.PROJECT,
            result_id=self.RESULT,
            result_markdown=b"# Finding\n\nThe reconciled value is 42.\n",
            base_canonical_epoch=0,
            canonical_inputs=[{"path": self.TARGET, "observed": ABSENT}],
            expected_canonical_targets=[self.TARGET],
        )
        claim = DriveResultClaimService(drive, workflow_layout.claims_parent_id).claim(result)
        return drive, hub.file_id, bootstrap.layout, claim

    def prepare_ready_change_from_claim(self, drive, layout, claim):
        # Test-only Reconciliation fixture: semantic work consumes only the claimed
        # independent RESULT copy, never the mutable Project source area.
        claimed_md_id = claim.claim["claimed"]["result_markdown_id"]
        claimed_raw = drive.download(claimed_md_id)
        canonical_raw = b"# Canonical project A\n\n" + claimed_raw

        change_folder = drive.create_folder(layout.changes_parent_id, self.CHANGE, label="reconciliation.change.folder")
        prepared = drive.create_folder(change_folder.file_id, "prepared", label="reconciliation.prepared.folder")
        drive.create_blob(prepared.file_id, "project-a.bin", canonical_raw, label="reconciliation.prepared.blob")
        change = {
            "schema": "keelaryn.change.v1",
            "change_id": self.CHANGE,
            "base_canonical_epoch": 0,
            "operations": [
                {
                    "operation_id": "publish-project-a",
                    "kind": "ADD",
                    "target": self.TARGET,
                    "old": ABSENT,
                    "new": present(canonical_raw),
                    "prepared_path": "prepared/project-a.bin",
                }
            ],
        }
        change_raw = canonical_json_bytes(change)
        drive.create_blob(change_folder.file_id, "CHANGE.json", change_raw, label="reconciliation.change.json")
        # Ready marker is deliberately last: after this point Reconciliation must
        # not mutate the package.
        ready_raw = canonical_json_bytes(
            {
                "schema": "keelaryn.ready.v1",
                "state": "READY_FOR_COMMIT",
                "change_id": self.CHANGE,
                "change_sha256": sha256(change_raw).hexdigest(),
            }
        )
        drive.create_blob(change_folder.file_id, "READY.json", ready_raw, label="reconciliation.ready.last")
        return change_folder.file_id, canonical_raw

    @staticmethod
    def master(drive, hub_id):
        _, raw = DriveMasterTransition.read_unique_master(drive, hub_id)
        return validate_master(strict_json_bytes(raw, label="MASTER.e2e"))

    def publish_postcheck(self, drive, layout, hub_id, decision: str):
        found = DriveRestartDiscovery.from_hub_root(drive, hub_id).discover()
        self.assertIsNotNone(found.bundle)
        bundle = found.bundle
        raw = canonical_json_bytes(
            {
                "schema": "keelaryn.postcheck.v1",
                "change_id": bundle.change_id,
                "change_sha256": bundle.change_sha256,
                "base_canonical_epoch": bundle.base_canonical_epoch,
                "decision": decision,
                "reason": f"disposable end-to-end semantic check {decision}",
            }
        )
        drive.create_blob(layout.postcheck_parent_id, f"{self.CHANGE}.json", raw, label=f"reconciliation.postcheck.{decision.lower()}")

    def test_project_result_claim_ready_change_pass_commits_clean_ready(self) -> None:
        drive, hub_id, layout, claim = self.build()
        change_folder_id, canonical_raw = self.prepare_ready_change_from_claim(drive, layout, claim)

        first = DrivePollingService(drive, hub_id).run_once()
        self.assertEqual(first.phase, "WAIT_POSTCHECK")
        during = self.master(drive, hub_id)
        self.assertEqual(during["state"], "ACTIVE")
        self.assertEqual(during["canonical_read_status"], "UNSAFE")
        published = drive.exact_name(layout.canonical_root_id, self.TARGET)
        self.assertIsNotNone(published)
        self.assertEqual(drive.download(published.file_id), canonical_raw)

        self.publish_postcheck(drive, layout, hub_id, "PASS")
        final = DrivePollingService(drive, hub_id).run_once()
        self.assertEqual(final.phase, "COMMITTED")
        self.assertTrue(final.ready_clean)
        completed = self.master(drive, hub_id)
        self.assertEqual(completed["state"], "READY")
        self.assertEqual(completed["canonical_read_status"], "SAFE")
        self.assertEqual(completed["canonical_epoch"], 1)
        self.assertEqual(completed["last_completed_change"]["outcome"], "COMMITTED")
        self.assertEqual(drive.download(drive.exact_name(layout.canonical_root_id, self.TARGET).file_id), canonical_raw)
        self.assertIsNone(drive.exact_name(change_folder_id, "READY.json"))
        self.assertEqual(DrivePollingService(drive, hub_id).run_once().phase, "IDLE")

    def test_project_result_claim_ready_change_fail_rolls_back_clean_ready(self) -> None:
        drive, hub_id, layout, claim = self.build()
        change_folder_id, _ = self.prepare_ready_change_from_claim(drive, layout, claim)

        first = DrivePollingService(drive, hub_id).run_once()
        self.assertEqual(first.phase, "WAIT_POSTCHECK")
        self.assertEqual(self.master(drive, hub_id)["canonical_read_status"], "UNSAFE")
        self.assertIsNotNone(drive.exact_name(layout.canonical_root_id, self.TARGET))

        self.publish_postcheck(drive, layout, hub_id, "FAIL")
        final = DrivePollingService(drive, hub_id).run_once()
        self.assertEqual(final.phase, "ROLLED_BACK")
        self.assertTrue(final.ready_clean)
        completed = self.master(drive, hub_id)
        self.assertEqual(completed["state"], "READY")
        self.assertEqual(completed["canonical_read_status"], "SAFE")
        self.assertEqual(completed["canonical_epoch"], 1)
        self.assertEqual(completed["last_completed_change"]["outcome"], "ROLLED_BACK")
        self.assertIsNone(drive.exact_name(layout.canonical_root_id, self.TARGET))
        self.assertIsNone(drive.exact_name(change_folder_id, "READY.json"))
        self.assertEqual(DrivePollingService(drive, hub_id).run_once().phase, "IDLE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
