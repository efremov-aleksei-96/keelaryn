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
from keelaryn_core.drive_workflow import DriveProjectWorkflow, DriveWorkflowLayoutResolver
from keelaryn_core.project_state import DriveProjectStateService, STATE_HISTORY_NAME, STATE_DONE_NAME, STATE_OLD_NAME


class ProjectStateRestTests(unittest.TestCase):
    PROJECT = "project-a"
    INITIAL = b"# State\n\ninitial\n"
    NEW1 = b"# State\n\nfirst update\n"
    NEW2 = b"# State\n\nsecond update\n"

    @classmethod
    def build(cls):
        drive = DriveModel()
        hub = drive.create_folder("root", "Hub", label="setup.hub")
        DriveHubBootstrap(drive, hub.file_id).run()
        layout = DriveWorkflowLayoutResolver(drive, hub.file_id).resolve()
        DriveProjectWorkflow(drive, layout.projects_parent_id).initialize_project(cls.PROJECT, cls.INITIAL)
        return drive, layout

    @classmethod
    def completed_first_update(cls):
        drive, layout = cls.build()
        first = DriveProjectStateService(drive, layout.projects_parent_id).update(cls.PROJECT, "u1", cls.NEW1)
        return drive, layout, first

    @staticmethod
    def update_folder(drive, layout, project_id: str, update_id: str):
        project = drive.exact_name(layout.projects_parent_id, project_id)
        history = drive.exact_name(project.file_id, STATE_HISTORY_NAME)
        return None if history is None else drive.exact_name(history.file_id, update_id)

    def first_update_mutation_count(self) -> int:
        drive, layout = self.build()
        http = ModelDriveHttp(drive)
        backend = GoogleDriveBackend("token", http=http)
        DriveProjectStateService(backend, layout.projects_parent_id).update(self.PROJECT, "u1", self.NEW1)
        self.assertGreater(http.mutation_count, 0)
        return http.mutation_count

    def second_update_mutation_count(self) -> int:
        drive, layout, _ = self.completed_first_update()
        http = ModelDriveHttp(drive)
        backend = GoogleDriveBackend("token", http=http)
        DriveProjectStateService(backend, layout.projects_parent_id).update(self.PROJECT, "u2", self.NEW2)
        self.assertGreater(http.mutation_count, 0)
        return http.mutation_count

    def test_first_update_recovers_after_every_uncertain_rest_mutation(self) -> None:
        count = self.first_update_mutation_count()
        for mutation_number in range(1, count + 1):
            with self.subTest(mutation_number=mutation_number, total=count):
                drive, layout = self.build()
                failing = GoogleDriveBackend(
                    "token",
                    http=ModelDriveHttp(drive, fail_after_mutation=mutation_number),
                )
                with self.assertRaises(DriveUncertainMutation):
                    DriveProjectStateService(failing, layout.projects_parent_id).update(self.PROJECT, "u1", self.NEW1)

                restarted = GoogleDriveBackend("token", http=ModelDriveHttp(drive))
                service = DriveProjectStateService(restarted, layout.projects_parent_id)
                completed = service.update(self.PROJECT, "u1", self.NEW1)
                current = service.read(self.PROJECT)
                self.assertEqual(current.raw, self.NEW1)
                self.assertEqual(current.state_file_id, completed.plan["new"]["file_id"])
                folder = self.update_folder(drive, layout, self.PROJECT, "u1")
                self.assertEqual(drive.exact_name(folder.file_id, STATE_OLD_NAME).file_id, completed.plan["old"]["file_id"])
                self.assertEqual(drive.exact_name(folder.file_id, STATE_DONE_NAME).file_id, completed.done_file_id)
                self.assertEqual(service.update(self.PROJECT, "u1", self.NEW1).done_file_id, completed.done_file_id)

    def test_second_update_recovers_after_every_uncertain_rest_mutation(self) -> None:
        count = self.second_update_mutation_count()
        for mutation_number in range(1, count + 1):
            with self.subTest(mutation_number=mutation_number, total=count):
                drive, layout, first = self.completed_first_update()
                failing = GoogleDriveBackend(
                    "token",
                    http=ModelDriveHttp(drive, fail_after_mutation=mutation_number),
                )
                with self.assertRaises(DriveUncertainMutation):
                    DriveProjectStateService(failing, layout.projects_parent_id).update(self.PROJECT, "u2", self.NEW2)

                restarted = GoogleDriveBackend("token", http=ModelDriveHttp(drive))
                service = DriveProjectStateService(restarted, layout.projects_parent_id)
                second = service.update(self.PROJECT, "u2", self.NEW2)
                current = service.read(self.PROJECT)
                self.assertEqual(current.raw, self.NEW2)
                self.assertEqual(current.state_file_id, second.plan["new"]["file_id"])
                self.assertEqual(second.plan["old"]["file_id"], first.plan["new"]["file_id"])
                folder1 = self.update_folder(drive, layout, self.PROJECT, "u1")
                folder2 = self.update_folder(drive, layout, self.PROJECT, "u2")
                self.assertEqual(drive.exact_name(folder2.file_id, STATE_OLD_NAME).file_id, first.plan["new"]["file_id"])
                self.assertIsNotNone(drive.exact_name(folder1.file_id, STATE_DONE_NAME))
                self.assertIsNotNone(drive.exact_name(folder2.file_id, STATE_DONE_NAME))


if __name__ == "__main__":
    unittest.main(verbosity=2)
