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
from keelaryn_core.drive_workflow import (
    DriveProjectResultLoader,
    DriveProjectWorkflow,
    DriveResultClaimService,
    DriveWorkflowLayoutResolver,
)


class DriveWorkflowRestTests(unittest.TestCase):
    PROJECT = "project-a"
    RESULT = "result-1"

    @staticmethod
    def base_model():
        drive = DriveModel()
        hub = drive.create_folder("root", "Hub", label="setup.hub")
        DriveHubBootstrap(drive, hub.file_id).run()
        layout = DriveWorkflowLayoutResolver(drive, hub.file_id).resolve()
        return drive, layout

    @classmethod
    def publish_args(cls):
        return {
            "project_id": cls.PROJECT,
            "result_id": cls.RESULT,
            "result_markdown": b"# Result\n\nproposal\n",
            "base_canonical_epoch": 0,
            "canonical_inputs": [{"path": "profile.md", "observed": {"state": "ABSENT"}}],
            "expected_canonical_targets": ["profile.md"],
        }

    @classmethod
    def create_result(cls, backend, layout):
        project = DriveProjectWorkflow(backend, layout.projects_parent_id)
        project.initialize_project(cls.PROJECT, b"# Project\n\nstate\n")
        return project.publish_result(**cls.publish_args())

    def project_mutation_count(self) -> int:
        drive, layout = self.base_model()
        http = ModelDriveHttp(drive)
        backend = GoogleDriveBackend("token", http=http)
        result = self.create_result(backend, layout)
        self.assertEqual(result.project_id, self.PROJECT)
        self.assertGreater(http.mutation_count, 0)
        return http.mutation_count

    def claim_mutation_count(self) -> int:
        drive, layout = self.base_model()
        setup_backend = GoogleDriveBackend("token", http=ModelDriveHttp(drive))
        result = self.create_result(setup_backend, layout)
        http = ModelDriveHttp(drive)
        backend = GoogleDriveBackend("token", http=http)
        claim = DriveResultClaimService(backend, layout.claims_parent_id).claim(result)
        self.assertEqual(claim.claim["project_id"], self.PROJECT)
        self.assertGreater(http.mutation_count, 0)
        return http.mutation_count

    def test_project_result_lost_response_after_every_mutation_recovers_exactly(self) -> None:
        count = self.project_mutation_count()
        for mutation_number in range(1, count + 1):
            with self.subTest(mutation_number=mutation_number, total=count):
                drive, layout = self.base_model()
                failing = GoogleDriveBackend(
                    "token",
                    http=ModelDriveHttp(drive, fail_after_mutation=mutation_number),
                )
                with self.assertRaises(DriveUncertainMutation):
                    self.create_result(failing, layout)

                restarted = GoogleDriveBackend("token", http=ModelDriveHttp(drive))
                result = self.create_result(restarted, layout)
                loaded = DriveProjectResultLoader(restarted, layout.projects_parent_id).load(self.PROJECT, self.RESULT)
                self.assertEqual(result.result_folder_id, loaded.result_folder_id)
                self.assertEqual(result.result_markdown_id, loaded.result_markdown_id)
                self.assertEqual(result.result_marker_id, loaded.result_marker_id)
                self.assertEqual(result.result_marker_raw, loaded.result_marker_raw)

    def test_claim_lost_response_after_every_mutation_recovers_from_drive_state(self) -> None:
        count = self.claim_mutation_count()
        for mutation_number in range(1, count + 1):
            with self.subTest(mutation_number=mutation_number, total=count):
                drive, layout = self.base_model()
                setup_backend = GoogleDriveBackend("token", http=ModelDriveHttp(drive))
                self.create_result(setup_backend, layout)

                failing = GoogleDriveBackend(
                    "token",
                    http=ModelDriveHttp(drive, fail_after_mutation=mutation_number),
                )
                durable_result = DriveProjectResultLoader(failing, layout.projects_parent_id).load(self.PROJECT, self.RESULT)
                with self.assertRaises(DriveUncertainMutation):
                    DriveResultClaimService(failing, layout.claims_parent_id).claim(durable_result)

                restarted = GoogleDriveBackend("token", http=ModelDriveHttp(drive))
                reloaded_result = DriveProjectResultLoader(restarted, layout.projects_parent_id).load(self.PROJECT, self.RESULT)
                service = DriveResultClaimService(restarted, layout.claims_parent_id)
                claim = service.claim(reloaded_result)
                loaded = service.load_claim(self.PROJECT, self.RESULT)
                self.assertEqual(claim.claim_folder_id, loaded.claim_folder_id)
                self.assertEqual(claim.plan_file_id, loaded.plan_file_id)
                self.assertEqual(claim.claim_file_id, loaded.claim_file_id)
                self.assertEqual(claim.claim_raw, loaded.claim_raw)
                self.assertEqual(claim.claim["source"]["result_markdown_id"], reloaded_result.result_markdown_id)
                self.assertEqual(claim.claim["source"]["result_marker_id"], reloaded_result.result_marker_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
