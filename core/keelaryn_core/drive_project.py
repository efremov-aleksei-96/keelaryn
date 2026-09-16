from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .drive_backend import DriveBackend, DriveItem, DriveNotFound
from .protocol import ID_RE, ProtocolError, canonical_json_bytes, fingerprint_bytes, strict_json_bytes
from .workflow_protocol import validate_result_marker

PROJECT_STATE_NAME = "STATE.md"
RESULTS_FOLDER_NAME = "results"
RESULT_MARKDOWN_NAME = "RESULT.md"
RESULT_MARKER_NAME = "RESULT.json"


class DriveWorkflowBlocked(ProtocolError):
    """Project/Reconciliation workflow state is ambiguous or violates protocol."""


@dataclass(frozen=True)
class DriveWorkflowLayout:
    projects_parent_id: str
    claims_parent_id: str


@dataclass(frozen=True)
class DriveProjectResult:
    project_id: str
    result_id: str
    project_folder_id: str
    result_folder_id: str
    result_markdown_id: str
    result_marker_id: str
    result_markdown_raw: bytes
    result_marker_raw: bytes
    marker: dict[str, Any]


def _identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise DriveWorkflowBlocked(f"{label}: invalid identifier")
    return value


def _fingerprint(raw: bytes) -> dict[str, Any]:
    return fingerprint_bytes(raw)


def _unique_folder(drive: DriveBackend, parent_id: str, name: str, label: str) -> DriveItem:
    matches = drive.list_children(parent_id, name=name)
    if len(matches) != 1:
        raise DriveWorkflowBlocked(f"{label}: expected exactly one folder, found {len(matches)}")
    item = matches[0]
    if item.trashed or not item.is_folder:
        raise DriveWorkflowBlocked(f"{label}: object is not a live folder")
    return item


def _unique_blob(drive: DriveBackend, parent_id: str, name: str, label: str) -> DriveItem:
    matches = drive.list_children(parent_id, name=name)
    if len(matches) != 1:
        raise DriveWorkflowBlocked(f"{label}: expected exactly one blob, found {len(matches)}")
    item = matches[0]
    if item.trashed or item.is_folder:
        raise DriveWorkflowBlocked(f"{label}: object is not a live blob")
    return item


def _optional_blob(drive: DriveBackend, parent_id: str, name: str, label: str) -> DriveItem | None:
    matches = drive.list_children(parent_id, name=name)
    if len(matches) > 1:
        raise DriveWorkflowBlocked(f"{label}: duplicate blobs")
    if not matches:
        return None
    item = matches[0]
    if item.trashed or item.is_folder:
        raise DriveWorkflowBlocked(f"{label}: object is not a live blob")
    return item


def _verify_item_bytes(drive: DriveBackend, item: DriveItem, expected: dict[str, Any], label: str) -> bytes:
    if item.trashed or item.is_folder:
        raise DriveWorkflowBlocked(f"{label}: expected live blob")
    raw = drive.download(item.file_id)
    actual = _fingerprint(raw)
    if actual != expected:
        raise DriveWorkflowBlocked(f"{label}: fingerprint mismatch")
    if item.size is not None and item.size != expected["size"]:
        raise DriveWorkflowBlocked(f"{label}: metadata size mismatch")
    if item.sha256_checksum is not None and item.sha256_checksum != expected["sha256"]:
        raise DriveWorkflowBlocked(f"{label}: metadata checksum mismatch")
    return raw


def _ensure_folder(drive: DriveBackend, parent_id: str, name: str, label: str) -> DriveItem:
    matches = drive.list_children(parent_id, name=name)
    if len(matches) > 1:
        raise DriveWorkflowBlocked(f"{label}: duplicate folders")
    if matches:
        item = matches[0]
        if item.trashed or not item.is_folder:
            raise DriveWorkflowBlocked(f"{label}: existing object is not a live folder")
        return item
    reserved = drive.generate_ids(1)[0]
    drive.create_folder(parent_id, name, file_id=reserved, label=label)
    matches = drive.list_children(parent_id, name=name)
    if len(matches) != 1 or matches[0].file_id != reserved or matches[0].trashed or not matches[0].is_folder:
        raise DriveWorkflowBlocked(f"{label}: folder did not become exact")
    return matches[0]


def _ensure_named_blob(drive: DriveBackend, parent_id: str, name: str, raw: bytes, label: str) -> DriveItem:
    matches = drive.list_children(parent_id, name=name)
    if len(matches) > 1:
        raise DriveWorkflowBlocked(f"{label}: duplicate blobs")
    expected = _fingerprint(raw)
    if matches:
        item = matches[0]
        _verify_item_bytes(drive, item, expected, label)
        return item
    reserved = drive.generate_ids(1)[0]
    drive.create_blob(parent_id, name, raw, file_id=reserved, label=label)
    matches = drive.list_children(parent_id, name=name)
    if len(matches) != 1 or matches[0].file_id != reserved:
        raise DriveWorkflowBlocked(f"{label}: blob did not become exact")
    _verify_item_bytes(drive, matches[0], expected, label)
    return matches[0]


def _get_live(drive: DriveBackend, file_id: str, label: str) -> DriveItem:
    try:
        item = drive.get(file_id, include_trashed=False)
    except DriveNotFound as exc:
        raise DriveWorkflowBlocked(f"{label}: exact Drive object missing") from exc
    if item.trashed:
        raise DriveWorkflowBlocked(f"{label}: exact Drive object is trashed")
    return item


class DriveWorkflowLayoutResolver:
    def __init__(self, drive: DriveBackend, hub_root_id: str):
        self.drive = drive
        self.hub_root_id = hub_root_id

    def resolve(self) -> DriveWorkflowLayout:
        work = _unique_folder(self.drive, self.hub_root_id, "work", "work")
        projects = _unique_folder(self.drive, work.file_id, "projects", "work/projects")
        reconciliation = _unique_folder(self.drive, work.file_id, "reconciliation", "work/reconciliation")
        claims = _unique_folder(self.drive, reconciliation.file_id, "claims", "work/reconciliation/claims")
        return DriveWorkflowLayout(projects.file_id, claims.file_id)


class DriveProjectWorkflow:
    """Deterministic structural helper for Project STATE and RESULT publication."""

    def __init__(self, drive: DriveBackend, projects_parent_id: str):
        self.drive = drive
        self.projects_parent_id = projects_parent_id

    def initialize_project(self, project_id: str, state_markdown: bytes) -> str:
        project_id = _identifier(project_id, "project_id")
        if not isinstance(state_markdown, bytes) or not state_markdown:
            raise DriveWorkflowBlocked("STATE.md must be non-empty bytes")
        project = _ensure_folder(self.drive, self.projects_parent_id, project_id, f"drive.project.{project_id}.folder.create")
        _ensure_folder(self.drive, project.file_id, RESULTS_FOLDER_NAME, f"drive.project.{project_id}.results.create")
        _ensure_named_blob(self.drive, project.file_id, PROJECT_STATE_NAME, state_markdown, f"drive.project.{project_id}.state.create")
        return project.file_id

    def publish_result(
        self,
        *,
        project_id: str,
        result_id: str,
        result_markdown: bytes,
        base_canonical_epoch: int,
        canonical_inputs: list[dict[str, Any]],
        expected_canonical_targets: list[str],
    ) -> DriveProjectResult:
        project_id = _identifier(project_id, "project_id")
        result_id = _identifier(result_id, "result_id")
        if not isinstance(result_markdown, bytes) or not result_markdown:
            raise DriveWorkflowBlocked("RESULT.md must be non-empty bytes")
        project = _unique_folder(self.drive, self.projects_parent_id, project_id, f"project {project_id}")
        _unique_blob(self.drive, project.file_id, PROJECT_STATE_NAME, f"project {project_id} STATE.md")
        results = _unique_folder(self.drive, project.file_id, RESULTS_FOLDER_NAME, f"project {project_id} results")
        result_folder = _ensure_folder(self.drive, results.file_id, result_id, f"drive.project.{project_id}.{result_id}.folder.create")
        marker_existing = _optional_blob(self.drive, result_folder.file_id, RESULT_MARKER_NAME, f"result {result_id} marker")
        _ensure_named_blob(self.drive, result_folder.file_id, RESULT_MARKDOWN_NAME, result_markdown, f"drive.project.{project_id}.{result_id}.markdown.create")
        marker_value = validate_result_marker(
            {
                "schema": "keelaryn.result.v1",
                "state": "READY_FOR_RECONCILIATION",
                "project_id": project_id,
                "result_id": result_id,
                "base_canonical_epoch": base_canonical_epoch,
                "result_markdown": _fingerprint(result_markdown),
                "canonical_inputs": canonical_inputs,
                "expected_canonical_targets": expected_canonical_targets,
            }
        )
        marker_raw = canonical_json_bytes(marker_value)
        if marker_existing is not None:
            if self.drive.download(marker_existing.file_id) != marker_raw:
                raise DriveWorkflowBlocked("RESULT.json already exists with different immutable bytes")
        else:
            _ensure_named_blob(self.drive, result_folder.file_id, RESULT_MARKER_NAME, marker_raw, f"drive.project.{project_id}.{result_id}.marker.create")
        return DriveProjectResultLoader(self.drive, self.projects_parent_id).load(project_id, result_id)


class DriveProjectResultLoader:
    def __init__(self, drive: DriveBackend, projects_parent_id: str):
        self.drive = drive
        self.projects_parent_id = projects_parent_id

    def load(self, project_id: str, result_id: str) -> DriveProjectResult:
        project_id = _identifier(project_id, "project_id")
        result_id = _identifier(result_id, "result_id")
        project = _unique_folder(self.drive, self.projects_parent_id, project_id, f"project {project_id}")
        results = _unique_folder(self.drive, project.file_id, RESULTS_FOLDER_NAME, f"project {project_id} results")
        result_folder = _unique_folder(self.drive, results.file_id, result_id, f"result {result_id}")
        md = _unique_blob(self.drive, result_folder.file_id, RESULT_MARKDOWN_NAME, f"result {result_id} RESULT.md")
        marker_item = _unique_blob(self.drive, result_folder.file_id, RESULT_MARKER_NAME, f"result {result_id} RESULT.json")
        md_raw = self.drive.download(md.file_id)
        marker_raw = self.drive.download(marker_item.file_id)
        try:
            marker = validate_result_marker(strict_json_bytes(marker_raw, label="RESULT"))
        except ProtocolError as exc:
            raise DriveWorkflowBlocked(str(exc)) from exc
        if marker["project_id"] != project_id or marker["result_id"] != result_id:
            raise DriveWorkflowBlocked("RESULT marker identity does not match enclosing folders")
        if _fingerprint(md_raw) != marker["result_markdown"]:
            raise DriveWorkflowBlocked("RESULT.md bytes do not match RESULT.json")
        _verify_item_bytes(self.drive, md, marker["result_markdown"], f"result {result_id} RESULT.md")
        return DriveProjectResult(project_id, result_id, project.file_id, result_folder.file_id, md.file_id, marker_item.file_id, md_raw, marker_raw, marker)


__all__ = [
    "PROJECT_STATE_NAME",
    "RESULTS_FOLDER_NAME",
    "RESULT_MARKDOWN_NAME",
    "RESULT_MARKER_NAME",
    "DriveWorkflowBlocked",
    "DriveWorkflowLayout",
    "DriveProjectResult",
    "DriveWorkflowLayoutResolver",
    "DriveProjectWorkflow",
    "DriveProjectResultLoader",
]
