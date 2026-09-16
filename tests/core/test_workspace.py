from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from keelaryn_core.drive_bootstrap import DriveHubBootstrap
from keelaryn_core.drive_model import DriveModel
from keelaryn_core.drive_workflow import DriveWorkflowBlocked
from keelaryn_core.workspace import DriveWorkspaceService


class DriveWorkspaceTests(unittest.TestCase):
    A = b"# Project State\n\nGoal: A\n\nNext action: inspect.\n"
    A2 = b"# Project State\n\nGoal: A\n\nNext action: publish result.\n"
    B = b"# Project State\n\nGoal: B\n\nNext action: inspect.\n"

    @staticmethod
    def build():
        drive = DriveModel()
        hub = drive.create_folder("root", "Hub", label="setup.hub")
        DriveHubBootstrap(drive, hub.file_id).run()
        return drive, hub.file_id

    @staticmethod
    def projects_parent(drive, hub_id):
        work = drive.exact_name(hub_id, "work")
        return drive.exact_name(work.file_id, "projects")

    def test_fresh_workspace_lists_no_projects(self) -> None:
        drive, hub_id = self.build()
        self.assertEqual(DriveWorkspaceService(drive, hub_id).list_projects(), ())

    def test_create_read_list_are_exact_idempotent_and_sorted(self) -> None:
        drive, hub_id = self.build()
        workspace = DriveWorkspaceService(drive, hub_id)
        beta = workspace.create_project("beta", self.B)
        alpha = workspace.create_project("alpha", self.A)
        replay = workspace.create_project("alpha", self.A)

        self.assertEqual(alpha, replay)
        self.assertEqual(workspace.read_project("alpha"), alpha)
        self.assertEqual(workspace.read_project("beta"), beta)
        listed = workspace.list_projects()
        self.assertEqual([item.project_id for item in listed], ["alpha", "beta"])
        self.assertEqual([item.state_raw for item in listed], [self.A, self.B])

        projects = self.projects_parent(drive, hub_id)
        self.assertEqual(len(drive.list_children(projects.file_id, name="alpha")), 1)
        self.assertEqual(len(drive.list_children(alpha.project_folder_id, name="STATE.md")), 1)
        self.assertEqual(len(drive.list_children(alpha.project_folder_id, name="results")), 1)

    def test_create_same_project_with_different_initial_state_fails_closed(self) -> None:
        drive, hub_id = self.build()
        workspace = DriveWorkspaceService(drive, hub_id)
        first = workspace.create_project("alpha", self.A)
        with self.assertRaises(DriveWorkflowBlocked):
            workspace.create_project("alpha", self.A2)
        self.assertEqual(workspace.read_project("alpha"), first)

    def test_list_blocks_nonfolder_invalid_duplicate_and_incomplete_projects(self) -> None:
        scenarios = ("nonfolder", "invalid", "duplicate", "missing-state", "missing-results")
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                drive, hub_id = self.build()
                projects = self.projects_parent(drive, hub_id)
                if scenario == "nonfolder":
                    drive.create_blob(projects.file_id, "junk", b"x", label="external.junk")
                elif scenario == "invalid":
                    drive.create_folder(projects.file_id, "bad/id", label="external.invalid")
                elif scenario == "duplicate":
                    drive.create_folder(projects.file_id, "alpha", label="external.alpha-1")
                    drive.create_folder(projects.file_id, "alpha", label="external.alpha-2")
                elif scenario == "missing-state":
                    project = drive.create_folder(projects.file_id, "alpha", label="external.alpha")
                    drive.create_folder(project.file_id, "results", label="external.results")
                else:
                    project = drive.create_folder(projects.file_id, "alpha", label="external.alpha")
                    drive.create_blob(project.file_id, "STATE.md", self.A, label="external.state")

                with self.assertRaises(DriveWorkflowBlocked):
                    DriveWorkspaceService(drive, hub_id).list_projects()

    def test_update_delegates_to_restart_safe_project_state_authority(self) -> None:
        drive, hub_id = self.build()
        workspace = DriveWorkspaceService(drive, hub_id)
        initial = workspace.create_project("alpha", self.A)
        changed = workspace.update_project("alpha", "u1", self.A2)
        self.assertEqual(changed.project.state_raw, self.A2)
        self.assertNotEqual(changed.project.state_file_id, initial.state_file_id)
        self.assertEqual(changed.state_update.plan["owner_kind"], "PROJECT")
        self.assertEqual(changed.state_update.plan["owner_id"], "alpha")
        self.assertEqual(changed.state_update.plan["new"]["file_id"], changed.project.state_file_id)
        replay = workspace.update_project("alpha", "u1", self.A2)
        self.assertEqual(replay.state_update.done_file_id, changed.state_update.done_file_id)
        self.assertEqual(replay.project, changed.project)


if __name__ == "__main__":
    unittest.main(verbosity=2)
