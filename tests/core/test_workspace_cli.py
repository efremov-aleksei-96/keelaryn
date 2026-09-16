from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "core"))
sys.path.insert(0, str(TESTS))

from drive_http_model import ModelDriveHttp
from keelaryn_core.drive_bootstrap import DriveHubBootstrap
from keelaryn_core.drive_model import DriveModel
from keelaryn_core.drive_rest import GoogleDriveBackend
from keelaryn_core.workspace_cli import (
    DriveWorkspaceCommandSurface,
    WorkspaceCliError,
    _read_state_file,
)


class DriveWorkspaceCliTests(unittest.TestCase):
    INITIAL = "# Project State\n\nGoal: Пример\n\nNext action: inspect.\n".encode("utf-8")
    UPDATED = "# Project State\n\nGoal: Пример\n\nNext action: publish.\n".encode("utf-8")

    @staticmethod
    def build():
        drive = DriveModel()
        hub = drive.create_folder("root", "Hub", label="setup.hub")
        DriveHubBootstrap(drive, hub.file_id).run()
        backend = GoogleDriveBackend("token", http=ModelDriveHttp(drive))
        return drive, hub.file_id, DriveWorkspaceCommandSurface(backend, hub.file_id)

    def test_surface_exposes_human_state_without_internal_drive_ids(self) -> None:
        _, _, surface = self.build()
        created = surface.create("alpha", self.INITIAL)
        self.assertEqual(
            created,
            {
                "project": {
                    "project_id": "alpha",
                    "state_markdown": self.INITIAL.decode("utf-8"),
                }
            },
        )
        updated = surface.update("alpha", "u1", self.UPDATED)
        self.assertEqual(updated["update_id"], "u1")
        self.assertEqual(updated["project"]["state_markdown"], self.UPDATED.decode("utf-8"))
        self.assertEqual(surface.read("alpha")["project"], updated["project"])
        self.assertEqual(surface.list(), {"projects": [updated["project"]]})
        rendered = json.dumps(updated, ensure_ascii=False)
        self.assertNotIn("file_id", rendered)
        self.assertNotIn("folder_id", rendered)

    def test_non_utf8_state_blocks_before_project_mutation(self) -> None:
        drive, hub_id, surface = self.build()
        with self.assertRaises(WorkspaceCliError):
            surface.create("alpha", b"\xff\xfe")
        work = drive.exact_name(hub_id, "work")
        projects = drive.exact_name(work.file_id, "projects")
        self.assertEqual(drive.list_children(projects.file_id), [])

    def test_state_file_stdin_is_exact_nonempty_utf8(self) -> None:
        raw = "# State\n\nПривет\n".encode("utf-8")
        self.assertEqual(_read_state_file("-", stdin=io.BytesIO(raw)), raw)
        with self.assertRaises(WorkspaceCliError):
            _read_state_file("-", stdin=io.BytesIO(b""))
        with self.assertRaises(WorkspaceCliError):
            _read_state_file("-", stdin=io.BytesIO(b"\xff"))

    def test_invalid_hub_root_id_is_rejected_before_workspace_use(self) -> None:
        drive = DriveModel()
        backend = GoogleDriveBackend("token", http=ModelDriveHttp(drive))
        for value in ("", "  ", " root "):
            with self.subTest(value=value):
                with self.assertRaises(WorkspaceCliError):
                    DriveWorkspaceCommandSurface(backend, value)


if __name__ == "__main__":
    unittest.main(verbosity=2)
