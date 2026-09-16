from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .drive_backend import DriveBackend
from .drive_project import _identifier, _unique_folder
from .work_state import (
    STATE_DONE_NAME,
    STATE_HISTORY_NAME,
    STATE_NEW_NAME,
    STATE_OLD_NAME,
    STATE_PLAN_NAME,
    DriveWorkStateService,
)


@dataclass(frozen=True)
class DriveProjectState:
    project_id: str
    project_folder_id: str
    state_file_id: str
    raw: bytes


@dataclass(frozen=True)
class DriveProjectStateUpdate:
    project_id: str
    update_id: str
    update_folder_id: str
    plan_file_id: str
    done_file_id: str
    plan_raw: bytes
    done_raw: bytes
    plan: dict[str, Any]
    done: dict[str, Any]


class DriveProjectStateService:
    """Project-scoped adapter over the shared restart-safe work STATE engine."""

    def __init__(self, drive: DriveBackend, projects_parent_id: str):
        self.drive = drive
        self.projects_parent_id = projects_parent_id

    def _engine(self, project_id: str) -> DriveWorkStateService:
        project_id = _identifier(project_id, "project_id")
        project = _unique_folder(self.drive, self.projects_parent_id, project_id, f"project {project_id}")
        return DriveWorkStateService(
            self.drive,
            owner_folder_id=project.file_id,
            owner_kind="PROJECT",
            owner_id=project_id,
            label_base=f"drive.project-state.{project_id}",
        )

    def read(self, project_id: str) -> DriveProjectState:
        state = self._engine(project_id).read()
        return DriveProjectState(project_id, state.owner_folder_id, state.state_file_id, state.raw)

    def update(self, project_id: str, update_id: str, new_state_markdown: bytes) -> DriveProjectStateUpdate:
        result = self._engine(project_id).update(update_id, new_state_markdown)
        return DriveProjectStateUpdate(
            project_id,
            result.update_id,
            result.update_folder_id,
            result.plan_file_id,
            result.done_file_id,
            result.plan_raw,
            result.done_raw,
            result.plan,
            result.done,
        )


__all__ = [
    "STATE_HISTORY_NAME",
    "STATE_PLAN_NAME",
    "STATE_NEW_NAME",
    "STATE_OLD_NAME",
    "STATE_DONE_NAME",
    "DriveProjectState",
    "DriveProjectStateUpdate",
    "DriveProjectStateService",
]
