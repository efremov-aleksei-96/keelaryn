from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from keelaryn_core.drive_bootstrap import DriveHubBootstrap
from keelaryn_core.drive_model import DriveModel
from keelaryn_core.drive_workflow import (
    DriveProjectWorkflow,
    DriveResultClaimService,
    DriveWorkflowBlocked,
    DriveWorkflowLayoutResolver,
)
from keelaryn_core.protocol import FaultInjector, InjectedCrash


class DriveWorkflowTests(unittest.TestCase):
    PROJECT_A = "project-a"
    PROJECT_B = "project-b"
    RESULT = "result-1"

    @staticmethod
    def setup_drive():
        drive = DriveModel()
        hub = drive.create_folder("root", "Hub", label="setup.hub")
        DriveHubBootstrap(drive, hub.file_id).run()
        layout = DriveWorkflowLayoutResolver(drive, hub.file_id).resolve()
        return drive, layout

    @staticmethod
    def publish(drive, layout, project_id: str, result_id: str = RESULT):
        project = DriveProjectWorkflow(drive, layout.projects_parent_id)
        project.initialize_project(project_id, f"# {project_id}\n\nstate\n".encode())
        return project.publish_result(
            project_id=project_id,
            result_id=result_id,
            result_markdown=f"# Result {project_id}\n\nproposal\n".encode(),
            base_canonical_epoch=0,
            canonical_inputs=[{"path": "profile.md", "observed": {"state": "ABSENT"}}],
            expected_canonical_targets=["profile.md"],
        )

    def test_claim_copies_exact_result_and_becomes_source_independent_authority(self) -> None:
        drive, layout = self.setup_drive()
        result = self.publish(drive, layout, self.PROJECT_A)
        service = DriveResultClaimService(drive, layout.claims_parent_id)
        claim = service.claim(result)

        self.assertNotEqual(claim.claim["source"]["folder_id"], claim.claim["claimed"]["folder_id"])
        self.assertNotEqual(claim.claim["source"]["result_markdown_id"], claim.claim["claimed"]["result_markdown_id"])
        self.assertNotEqual(claim.claim["source"]["result_marker_id"], claim.claim["claimed"]["result_marker_id"])
        self.assertEqual(claim.claim["source"]["result_markdown"], claim.claim["claimed"]["result_markdown"])
        self.assertEqual(claim.claim["source"]["result_marker"], claim.claim["claimed"]["result_marker"])

        # Once CLAIM.json exists, the Reconciliation-owned copies are authority.
        # Later Project-area changes cannot rewrite that authority.
        drive.update_content(result.result_markdown_id, b"external project mutation", label="test.source.mutate")
        loaded = service.load_claim(self.PROJECT_A, self.RESULT)
        self.assertEqual(loaded.claim_file_id, claim.claim_file_id)
        self.assertEqual(loaded.claim_raw, claim.claim_raw)

    def test_same_result_id_in_different_projects_cannot_cross_contaminate_claims(self) -> None:
        drive, layout = self.setup_drive()
        result_a = self.publish(drive, layout, self.PROJECT_A)
        result_b = self.publish(drive, layout, self.PROJECT_B)
        service = DriveResultClaimService(drive, layout.claims_parent_id)

        claim_a = service.claim(result_a)
        claim_b = service.claim(result_b)

        self.assertNotEqual(claim_a.claim_folder_id, claim_b.claim_folder_id)
        self.assertEqual(claim_a.claim["project_id"], self.PROJECT_A)
        self.assertEqual(claim_b.claim["project_id"], self.PROJECT_B)
        self.assertEqual(claim_a.claim["result_id"], self.RESULT)
        self.assertEqual(claim_b.claim["result_id"], self.RESULT)
        self.assertEqual(service.load_claim(self.PROJECT_A, self.RESULT).claim_file_id, claim_a.claim_file_id)
        self.assertEqual(service.load_claim(self.PROJECT_B, self.RESULT).claim_file_id, claim_b.claim_file_id)

    def test_source_change_after_durable_plan_blocks_before_claim_authority(self) -> None:
        drive, layout = self.setup_drive()
        result = self.publish(drive, layout, self.PROJECT_A)
        service = DriveResultClaimService(drive, layout.claims_parent_id)

        drive.fault = FaultInjector(f"drive.claim.{self.PROJECT_A}.{self.RESULT}.plan.create.after")
        with self.assertRaises(InjectedCrash):
            service.claim(result)
        drive.fault = FaultInjector()

        drive.update_content(result.result_markdown_id, b"changed after plan", label="test.source.change")
        with self.assertRaises(DriveWorkflowBlocked):
            service.claim(result)

        project_claims = drive.exact_name(layout.claims_parent_id, self.PROJECT_A)
        claim_folder = drive.exact_name(project_claims.file_id, self.RESULT)
        self.assertIsNone(drive.exact_name(claim_folder.file_id, "CLAIM.json"))

    def test_claimed_copy_tamper_blocks_claim_loading(self) -> None:
        drive, layout = self.setup_drive()
        result = self.publish(drive, layout, self.PROJECT_A)
        service = DriveResultClaimService(drive, layout.claims_parent_id)
        claim = service.claim(result)

        drive.update_content(
            claim.claim["claimed"]["result_markdown_id"],
            b"tampered claimed copy",
            label="test.claimed.tamper",
        )
        with self.assertRaises(DriveWorkflowBlocked):
            service.load_claim(self.PROJECT_A, self.RESULT)

    def test_result_marker_makes_project_result_immutable_by_exact_bytes(self) -> None:
        drive, layout = self.setup_drive()
        self.publish(drive, layout, self.PROJECT_A)
        project = DriveProjectWorkflow(drive, layout.projects_parent_id)
        with self.assertRaises(DriveWorkflowBlocked):
            project.publish_result(
                project_id=self.PROJECT_A,
                result_id=self.RESULT,
                result_markdown=b"different result bytes",
                base_canonical_epoch=0,
                canonical_inputs=[{"path": "profile.md", "observed": {"state": "ABSENT"}}],
                expected_canonical_targets=["profile.md"],
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
