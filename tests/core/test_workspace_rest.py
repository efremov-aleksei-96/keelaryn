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
from keelaryn_core.workspace import DriveWorkspaceService


class DriveWorkspaceRestTests(unittest.TestCase):
    STATE = b"# Project State\n\nGoal: alpha\n\nNext action: inspect.\n"

    @staticmethod
    def build():
        drive = DriveModel()
        hub = drive.create_folder("root", "Hub", label="setup.hub")
        DriveHubBootstrap(drive, hub.file_id).run()
        return drive, hub.file_id

    def mutation_count(self) -> int:
        drive, hub_id = self.build()
        http = ModelDriveHttp(drive)
        backend = GoogleDriveBackend("token", http=http)
        project = DriveWorkspaceService(backend, hub_id).create_project("alpha", self.STATE)
        self.assertEqual(project.project_id, "alpha")
        self.assertGreaterEqual(http.mutation_count, 3)
        return http.mutation_count

    def test_create_project_recovers_after_every_uncertain_rest_mutation(self) -> None:
        count = self.mutation_count()
        for mutation_number in range(1, count + 1):
            with self.subTest(mutation_number=mutation_number, total=count):
                drive, hub_id = self.build()
                failing = GoogleDriveBackend(
                    "token",
                    http=ModelDriveHttp(drive, fail_after_mutation=mutation_number),
                )
                with self.assertRaises(DriveUncertainMutation):
                    DriveWorkspaceService(failing, hub_id).create_project("alpha", self.STATE)

                restarted = GoogleDriveBackend("token", http=ModelDriveHttp(drive))
                workspace = DriveWorkspaceService(restarted, hub_id)
                project = workspace.create_project("alpha", self.STATE)
                self.assertEqual(project.state_raw, self.STATE)
                self.assertEqual(workspace.list_projects(), (project,))

                work = restarted.exact_name(hub_id, "work")
                projects = restarted.exact_name(work.file_id, "projects")
                self.assertEqual(len(restarted.list_children(projects.file_id, name="alpha")), 1)
                self.assertEqual(len(restarted.list_children(project.project_folder_id, name="results")), 1)
                self.assertEqual(len(restarted.list_children(project.project_folder_id, name="STATE.md")), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
