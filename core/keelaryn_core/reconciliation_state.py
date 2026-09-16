from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .drive_backend import DriveBackend
from .drive_project import PROJECT_STATE_NAME, DriveWorkflowBlocked, _ensure_named_blob, _unique_folder
from .work_state import DriveWorkStateService

RECONCILIATION_OWNER_ID = "reconciliation"


@dataclass(frozen=True)
class DriveReconciliationState:
    reconciliation_folder_id: str
    state_file_id: str
    raw: bytes


@dataclass(frozen=True)
class DriveReconciliationStateUpdate:
    update_id: str
    update_folder_id: str
    plan_file_id: str
    done_file_id: str
    plan_raw: bytes
    done_raw: bytes
    plan: dict[str, Any]
    done: dict[str, Any]


class DriveReconciliationStateService:
    """Durable semantic Reconciliation STATE using the shared work-state COW engine."""

    def __init__(self, drive: DriveBackend, hub_root_id: str):
        self.drive = drive
        self.hub_root_id = hub_root_id

    def _reconciliation(self):
        work = _unique_folder(self.drive, self.hub_root_id, "work", "work")
        return _unique_folder(self.drive, work.file_id, RECONCILIATION_OWNER_ID, "work/reconciliation")

    def _engine(self) -> DriveWorkStateService:
        folder = self._reconciliation()
        return DriveWorkStateService(
            self.drive,
            owner_folder_id=folder.file_id,
            owner_kind="RECONCILIATION",
            owner_id=RECONCILIATION_OWNER_ID,
            label_base="drive.reconciliation-state",
        )

    def initialize(self, initial_state_markdown: bytes) -> DriveReconciliationState:
        if not isinstance(initial_state_markdown, bytes) or not initial_state_markdown:
            raise DriveWorkflowBlocked("Reconciliation STATE.md must be non-empty bytes")
        folder = self._reconciliation()
        _ensure_named_blob(
            self.drive,
            folder.file_id,
            PROJECT_STATE_NAME,
            initial_state_markdown,
            "drive.reconciliation-state.initialize",
        )
        return self.read()

    def read(self) -> DriveReconciliationState:
        state = self._engine().read()
        return DriveReconciliationState(state.owner_folder_id, state.state_file_id, state.raw)

    def update(self, update_id: str, new_state_markdown: bytes) -> DriveReconciliationStateUpdate:
        result = self._engine().update(update_id, new_state_markdown)
        return DriveReconciliationStateUpdate(
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
    "RECONCILIATION_OWNER_ID",
    "DriveReconciliationState",
    "DriveReconciliationStateUpdate",
    "DriveReconciliationStateService",
]
