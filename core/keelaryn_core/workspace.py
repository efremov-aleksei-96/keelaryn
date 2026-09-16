from __future__ import annotations

from dataclasses import dataclass

from .drive_backend import DriveBackend
from .drive_project import (
    PROJECT_STATE_NAME,
    RESULTS_FOLDER_NAME,
    DriveProjectWorkflow,
    DriveWorkflowBlocked,
    DriveWorkflowLayoutResolver,
    _identifier,
    _unique_folder,
)
from .project_state import DriveProjectStateService, DriveProjectStateUpdate


@dataclass(frozen=True)
class DriveWorkspaceProject:
    project_id: str
    project_folder_id: str
    results_folder_id: str
    state_file_id: str
    state_raw: bytes


@dataclass(frozen=True)
class DriveWorkspaceProjectUpdate:
    project: DriveWorkspaceProject
    state_update: DriveProjectStateUpdate


class DriveWorkspaceService:
    """Minimal deterministic Workspace navigation and Project lifecycle surface.

    Workspace is a semantic initiator/navigator, not a canonical writer. This layer
    therefore owns no new durable authority: project creation delegates to the
    existing deterministic Project workflow, and mutable STATE delegates to the
    shared restart-safe work-state transaction.
    """

    def __init__(self, drive: DriveBackend, hub_root_id: str):
        self.drive = drive
        self.hub_root_id = hub_root_id

    def _projects_parent_id(self) -> str:
        return DriveWorkflowLayoutResolver(self.drive, self.hub_root_id).resolve().projects_parent_id

    def _project(self, projects_parent_id: str, project_id: str) -> DriveWorkspaceProject:
        project_id = _identifier(project_id, "project_id")
        project = _unique_folder(self.drive, projects_parent_id, project_id, f"project {project_id}")
        results = _unique_folder(
            self.drive,
            project.file_id,
            RESULTS_FOLDER_NAME,
            f"project {project_id} results",
        )
        state = DriveProjectStateService(self.drive, projects_parent_id).read(project_id)
        if state.project_folder_id != project.file_id:
            raise DriveWorkflowBlocked("Workspace Project STATE resolved to a different project folder")
        return DriveWorkspaceProject(
            project_id,
            project.file_id,
            results.file_id,
            state.state_file_id,
            state.raw,
        )

    def list_projects(self) -> tuple[DriveWorkspaceProject, ...]:
        projects_parent_id = self._projects_parent_id()
        names: set[str] = set()
        for child in self.drive.list_children(projects_parent_id):
            if child.trashed or not child.is_folder:
                raise DriveWorkflowBlocked("work/projects contains non-folder material")
            project_id = _identifier(child.name, "project_id")
            if project_id in names:
                raise DriveWorkflowBlocked(f"duplicate project folder: {project_id}")
            names.add(project_id)
        return tuple(self._project(projects_parent_id, project_id) for project_id in sorted(names))

    def create_project(self, project_id: str, initial_state_markdown: bytes) -> DriveWorkspaceProject:
        project_id = _identifier(project_id, "project_id")
        projects_parent_id = self._projects_parent_id()
        DriveProjectWorkflow(self.drive, projects_parent_id).initialize_project(project_id, initial_state_markdown)
        return self._project(projects_parent_id, project_id)

    def read_project(self, project_id: str) -> DriveWorkspaceProject:
        projects_parent_id = self._projects_parent_id()
        return self._project(projects_parent_id, project_id)

    def update_project(
        self,
        project_id: str,
        update_id: str,
        new_state_markdown: bytes,
    ) -> DriveWorkspaceProjectUpdate:
        project_id = _identifier(project_id, "project_id")
        projects_parent_id = self._projects_parent_id()
        state_update = DriveProjectStateService(self.drive, projects_parent_id).update(
            project_id,
            update_id,
            new_state_markdown,
        )
        return DriveWorkspaceProjectUpdate(
            self._project(projects_parent_id, project_id),
            state_update,
        )


__all__ = [
    "DriveWorkspaceProject",
    "DriveWorkspaceProjectUpdate",
    "DriveWorkspaceService",
]
