from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from keelaryn_core.drive_bootstrap import DriveHubBootstrap
from keelaryn_core.drive_model import DriveModel
from keelaryn_core.drive_workflow import DriveProjectWorkflow, DriveWorkflowBlocked, DriveWorkflowLayoutResolver
from keelaryn_core.project_state import (
    STATE_DONE_NAME,
    STATE_HISTORY_NAME,
    STATE_NEW_NAME,
    STATE_OLD_NAME,
    STATE_PLAN_NAME,
    DriveProjectStateService,
)
from keelaryn_core.protocol import FaultInjector, InjectedCrash


class ProjectStateTests(unittest.TestCase):
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

    @staticmethod
    def update_folder(drive, layout, project_id: str, update_id: str):
        project = drive.exact_name(layout.projects_parent_id, project_id)
        history = drive.exact_name(project.file_id, STATE_HISTORY_NAME)
        if history is None:
            return None
        return drive.exact_name(history.file_id, update_id)

    def test_normal_update_changes_exact_state_id_and_retains_old_bytes(self) -> None:
        drive, layout = self.build()
        service = DriveProjectStateService(drive, layout.projects_parent_id)
        before = service.read(self.PROJECT)
        update = service.update(self.PROJECT, "u1", self.NEW1)
        after = service.read(self.PROJECT)

        self.assertNotEqual(before.state_file_id, after.state_file_id)
        self.assertEqual(after.state_file_id, update.plan["new"]["file_id"])
        self.assertEqual(after.raw, self.NEW1)
        folder = self.update_folder(drive, layout, self.PROJECT, "u1")
        self.assertIsNotNone(folder)
        old = drive.exact_name(folder.file_id, STATE_OLD_NAME)
        self.assertEqual(old.file_id, before.state_file_id)
        self.assertEqual(drive.download(old.file_id), self.INITIAL)
        self.assertEqual(drive.exact_name(folder.file_id, STATE_PLAN_NAME).file_id, update.plan_file_id)
        self.assertEqual(drive.exact_name(folder.file_id, STATE_DONE_NAME).file_id, update.done_file_id)
        self.assertIsNone(drive.exact_name(folder.file_id, STATE_NEW_NAME))

    def test_repeat_same_update_is_exactly_idempotent(self) -> None:
        drive, layout = self.build()
        service = DriveProjectStateService(drive, layout.projects_parent_id)
        first = service.update(self.PROJECT, "u1", self.NEW1)
        state1 = service.read(self.PROJECT)
        second = DriveProjectStateService(drive, layout.projects_parent_id).update(self.PROJECT, "u1", self.NEW1)
        state2 = service.read(self.PROJECT)

        self.assertEqual(first.plan_file_id, second.plan_file_id)
        self.assertEqual(first.done_file_id, second.done_file_id)
        self.assertEqual(first.plan_raw, second.plan_raw)
        self.assertEqual(first.done_raw, second.done_raw)
        self.assertEqual(state1.state_file_id, state2.state_file_id)
        self.assertEqual(state2.raw, self.NEW1)

    def test_same_update_id_with_different_bytes_blocks(self) -> None:
        drive, layout = self.build()
        service = DriveProjectStateService(drive, layout.projects_parent_id)
        first = service.update(self.PROJECT, "u1", self.NEW1)
        current = service.read(self.PROJECT)
        with self.assertRaises(DriveWorkflowBlocked):
            service.update(self.PROJECT, "u1", self.NEW2)
        self.assertEqual(service.read(self.PROJECT), current)
        self.assertEqual(drive.exact_name(self.update_folder(drive, layout, self.PROJECT, "u1").file_id, STATE_DONE_NAME).file_id, first.done_file_id)

    def test_noop_blocks_before_state_history_creation(self) -> None:
        drive, layout = self.build()
        service = DriveProjectStateService(drive, layout.projects_parent_id)
        before = service.read(self.PROJECT)
        project = drive.exact_name(layout.projects_parent_id, self.PROJECT)
        self.assertIsNone(drive.exact_name(project.file_id, STATE_HISTORY_NAME))
        with self.assertRaises(DriveWorkflowBlocked):
            service.update(self.PROJECT, "noop", self.INITIAL)
        self.assertIsNone(drive.exact_name(project.file_id, STATE_HISTORY_NAME))
        self.assertEqual(service.read(self.PROJECT), before)

    def test_noop_new_id_after_history_exists_creates_no_update_folder(self) -> None:
        drive, layout = self.build()
        service = DriveProjectStateService(drive, layout.projects_parent_id)
        service.update(self.PROJECT, "u1", self.NEW1)
        with self.assertRaises(DriveWorkflowBlocked):
            service.update(self.PROJECT, "noop2", self.NEW1)
        self.assertIsNone(self.update_folder(drive, layout, self.PROJECT, "noop2"))
        self.assertEqual(service.read(self.PROJECT).raw, self.NEW1)

    def test_crash_matrix_recovers_to_same_exact_completed_update(self) -> None:
        points = (
            f"drive.project-state.{self.PROJECT}.history.create.after",
            f"drive.project-state.{self.PROJECT}.u1.folder.create.after",
            f"drive.project-state.{self.PROJECT}.u1.plan.create.after",
            f"drive.project-state.{self.PROJECT}.u1.new.create.after",
            f"drive.project-state.{self.PROJECT}.u1.archive-old.after",
            f"drive.project-state.{self.PROJECT}.u1.publish-new.after",
            f"drive.project-state.{self.PROJECT}.u1.done.create.after",
        )
        for point in points:
            with self.subTest(point=point):
                drive, layout = self.build()
                drive.fault = FaultInjector(point)
                with self.assertRaises(InjectedCrash):
                    DriveProjectStateService(drive, layout.projects_parent_id).update(self.PROJECT, "u1", self.NEW1)
                drive.fault = FaultInjector()
                recovered = DriveProjectStateService(drive, layout.projects_parent_id).update(self.PROJECT, "u1", self.NEW1)
                current = DriveProjectStateService(drive, layout.projects_parent_id).read(self.PROJECT)
                self.assertEqual(current.raw, self.NEW1)
                self.assertEqual(current.state_file_id, recovered.plan["new"]["file_id"])
                folder = self.update_folder(drive, layout, self.PROJECT, "u1")
                self.assertEqual(drive.exact_name(folder.file_id, STATE_OLD_NAME).file_id, recovered.plan["old"]["file_id"])
                self.assertEqual(drive.exact_name(folder.file_id, STATE_DONE_NAME).file_id, recovered.done_file_id)

    def test_read_fails_closed_during_gap_then_restart_completes(self) -> None:
        drive, layout = self.build()
        drive.fault = FaultInjector(f"drive.project-state.{self.PROJECT}.u1.archive-old.after")
        with self.assertRaises(InjectedCrash):
            DriveProjectStateService(drive, layout.projects_parent_id).update(self.PROJECT, "u1", self.NEW1)
        drive.fault = FaultInjector()
        with self.assertRaises(DriveWorkflowBlocked):
            DriveProjectStateService(drive, layout.projects_parent_id).read(self.PROJECT)
        DriveProjectStateService(drive, layout.projects_parent_id).update(self.PROJECT, "u1", self.NEW1)
        self.assertEqual(DriveProjectStateService(drive, layout.projects_parent_id).read(self.PROJECT).raw, self.NEW1)

    def test_source_old_tamper_after_completed_update_blocks_next_update(self) -> None:
        drive, layout = self.build()
        service = DriveProjectStateService(drive, layout.projects_parent_id)
        u1 = service.update(self.PROJECT, "u1", self.NEW1)
        drive.update_content(u1.plan["old"]["file_id"], b"tampered old", label="test.tamper.old")
        current = service.read(self.PROJECT)
        with self.assertRaises(DriveWorkflowBlocked):
            service.update(self.PROJECT, "u2", self.NEW2)
        self.assertEqual(service.read(self.PROJECT), current)
        self.assertIsNone(self.update_folder(drive, layout, self.PROJECT, "u2"))

    def test_tampered_historical_done_blocks_next_update(self) -> None:
        drive, layout = self.build()
        service = DriveProjectStateService(drive, layout.projects_parent_id)
        u1 = service.update(self.PROJECT, "u1", self.NEW1)
        drive.update_content(u1.done_file_id, b"{}\n", label="test.tamper.done")
        current = service.read(self.PROJECT)
        with self.assertRaises(DriveWorkflowBlocked):
            service.update(self.PROJECT, "u2", self.NEW2)
        self.assertEqual(service.read(self.PROJECT), current)
        self.assertIsNone(self.update_folder(drive, layout, self.PROJECT, "u2"))

    def test_tampered_current_plan_blocks_recovery(self) -> None:
        drive, layout = self.build()
        drive.fault = FaultInjector(f"drive.project-state.{self.PROJECT}.u1.plan.create.after")
        with self.assertRaises(InjectedCrash):
            DriveProjectStateService(drive, layout.projects_parent_id).update(self.PROJECT, "u1", self.NEW1)
        drive.fault = FaultInjector()
        folder = self.update_folder(drive, layout, self.PROJECT, "u1")
        plan = drive.exact_name(folder.file_id, STATE_PLAN_NAME)
        drive.update_content(plan.file_id, b"{}\n", label="test.tamper.plan")
        with self.assertRaises(DriveWorkflowBlocked):
            DriveProjectStateService(drive, layout.projects_parent_id).update(self.PROJECT, "u1", self.NEW1)
        self.assertEqual(DriveProjectStateService(drive, layout.projects_parent_id).read(self.PROJECT).raw, self.INITIAL)

    def test_unknown_old_location_blocks_instead_of_guessing(self) -> None:
        drive, layout = self.build()
        drive.fault = FaultInjector(f"drive.project-state.{self.PROJECT}.u1.new.create.after")
        with self.assertRaises(InjectedCrash):
            DriveProjectStateService(drive, layout.projects_parent_id).update(self.PROJECT, "u1", self.NEW1)
        drive.fault = FaultInjector()
        current = DriveProjectStateService(drive, layout.projects_parent_id).read(self.PROJECT)
        mystery = drive.create_folder("root", "mystery", label="test.mystery")
        drive.move_rename(current.state_file_id, mystery.file_id, "moved.md", label="test.move.old")
        with self.assertRaises(DriveWorkflowBlocked):
            DriveProjectStateService(drive, layout.projects_parent_id).update(self.PROJECT, "u1", self.NEW1)
        self.assertIsNone(drive.exact_name(drive.exact_name(layout.projects_parent_id, self.PROJECT).file_id, PROJECT_STATE_NAME if False else "STATE.md"))
        self.assertEqual(drive.get(current.state_file_id).parent_id, mystery.file_id)

    def test_other_incomplete_update_blocks_new_update(self) -> None:
        drive, layout = self.build()
        drive.fault = FaultInjector(f"drive.project-state.{self.PROJECT}.u1.plan.create.after")
        with self.assertRaises(InjectedCrash):
            DriveProjectStateService(drive, layout.projects_parent_id).update(self.PROJECT, "u1", self.NEW1)
        drive.fault = FaultInjector()
        with self.assertRaises(DriveWorkflowBlocked):
            DriveProjectStateService(drive, layout.projects_parent_id).update(self.PROJECT, "u2", self.NEW2)
        self.assertIsNone(self.update_folder(drive, layout, self.PROJECT, "u2"))
        self.assertEqual(DriveProjectStateService(drive, layout.projects_parent_id).read(self.PROJECT).raw, self.INITIAL)

    def test_two_completed_updates_form_exact_retained_chain(self) -> None:
        drive, layout = self.build()
        service = DriveProjectStateService(drive, layout.projects_parent_id)
        u1 = service.update(self.PROJECT, "u1", self.NEW1)
        u2 = service.update(self.PROJECT, "u2", self.NEW2)
        current = service.read(self.PROJECT)

        self.assertEqual(current.raw, self.NEW2)
        self.assertEqual(current.state_file_id, u2.plan["new"]["file_id"])
        self.assertEqual(u2.plan["old"]["file_id"], u1.plan["new"]["file_id"])
        folder1 = self.update_folder(drive, layout, self.PROJECT, "u1")
        folder2 = self.update_folder(drive, layout, self.PROJECT, "u2")
        self.assertEqual(drive.exact_name(folder1.file_id, STATE_OLD_NAME).file_id, u1.plan["old"]["file_id"])
        self.assertEqual(drive.exact_name(folder2.file_id, STATE_OLD_NAME).file_id, u1.plan["new"]["file_id"])
        self.assertEqual(drive.download(drive.exact_name(folder2.file_id, STATE_OLD_NAME).file_id), self.NEW1)
        self.assertEqual(service.update(self.PROJECT, "u2", self.NEW2).done_file_id, u2.done_file_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
