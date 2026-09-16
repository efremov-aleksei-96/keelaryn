from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from .drive_backend import DriveAlreadyExists, DriveBackend, DriveItem, DriveNotFound
from .drive_control import DriveControl
from .drive_master import DriveMasterTransition, DriveMasterUnavailable
from .drive_transaction import BlobState, DriveOperation
from .protocol import (
    ProtocolError,
    strict_json_bytes,
    validate_change,
    validate_master,
    validate_ready,
    validate_relative_path,
)


CHANGE_NAME = "CHANGE.json"
READY_NAME = "READY.json"


class DriveReadyChangeBlocked(ProtocolError):
    """A Drive Ready Change cannot be claimed deterministically."""


def _present_state(value: dict[str, Any], label: str) -> BlobState:
    if value.get("state") != "PRESENT":
        raise DriveReadyChangeBlocked(f"{label}: expected PRESENT state")
    return BlobState(value["sha256"], value["size"])


@dataclass(frozen=True)
class DriveReadyChange:
    folder_id: str
    folder_name: str
    change_raw: bytes
    ready_raw: bytes
    change: dict[str, Any]
    ready: dict[str, Any]

    @property
    def change_id(self) -> str:
        return self.change["change_id"]

    @property
    def change_sha256(self) -> str:
        return sha256(self.change_raw).hexdigest()

    @property
    def base_canonical_epoch(self) -> int:
        return self.change["base_canonical_epoch"]


class DriveReadyChangeLoader:
    def __init__(self, drive: DriveBackend, changes_parent_id: str):
        self.drive = drive
        self.changes_parent_id = changes_parent_id

    def _unique_blob(self, parent_id: str, name: str) -> DriveItem:
        matches = self.drive.list_children(parent_id, name=name)
        if len(matches) != 1:
            raise DriveReadyChangeBlocked(f"expected exactly one {name} in {parent_id}, found {len(matches)}")
        item = matches[0]
        if item.trashed or item.is_folder:
            raise DriveReadyChangeBlocked(f"{name} is not a live blob")
        return item

    def _load_folder(self, folder: DriveItem) -> DriveReadyChange:
        if folder.trashed or not folder.is_folder:
            raise DriveReadyChangeBlocked("Ready Change container is not a live folder")
        change_item = self._unique_blob(folder.file_id, CHANGE_NAME)
        ready_item = self._unique_blob(folder.file_id, READY_NAME)
        change_raw = self.drive.download(change_item.file_id)
        ready_raw = self.drive.download(ready_item.file_id)
        try:
            change = validate_change(strict_json_bytes(change_raw, label="CHANGE"))
            ready = validate_ready(strict_json_bytes(ready_raw, label="READY"))
        except ProtocolError as exc:
            raise DriveReadyChangeBlocked(str(exc)) from exc
        digest = sha256(change_raw).hexdigest()
        if ready["change_id"] != change["change_id"] or ready["change_sha256"] != digest:
            raise DriveReadyChangeBlocked("READY does not bind exact CHANGE identity")
        if folder.name != change["change_id"]:
            raise DriveReadyChangeBlocked("Ready Change folder name does not equal change_id")
        return DriveReadyChange(folder.file_id, folder.name, change_raw, ready_raw, change, ready)

    def find_one_ready(self) -> DriveReadyChange | None:
        children = self.drive.list_children(self.changes_parent_id)
        ready_folders: list[DriveItem] = []
        for child in children:
            if child.trashed or not child.is_folder:
                continue
            markers = self.drive.list_children(child.file_id, name=READY_NAME)
            if len(markers) > 1:
                raise DriveReadyChangeBlocked(f"multiple READY markers in {child.file_id}")
            if len(markers) == 1:
                if markers[0].is_folder or markers[0].trashed:
                    raise DriveReadyChangeBlocked(f"READY marker in {child.file_id} is not a live blob")
                ready_folders.append(child)
        if not ready_folders:
            return None
        if len(ready_folders) != 1:
            raise DriveReadyChangeBlocked(f"expected at most one Ready Change, found {len(ready_folders)}")
        return self._load_folder(ready_folders[0])

    def resolve_blob(self, ready: DriveReadyChange, relative_path: str) -> DriveItem:
        try:
            normalized = validate_relative_path(relative_path, "prepared_path")
        except ProtocolError as exc:
            raise DriveReadyChangeBlocked(str(exc)) from exc
        parent = ready.folder_id
        parts = normalized.split("/")
        for segment in parts[:-1]:
            matches = self.drive.list_children(parent, name=segment)
            if len(matches) != 1 or not matches[0].is_folder or matches[0].trashed:
                raise DriveReadyChangeBlocked(f"prepared path folder is not unique/live: {relative_path}")
            parent = matches[0].file_id
        matches = self.drive.list_children(parent, name=parts[-1])
        if len(matches) != 1 or matches[0].is_folder or matches[0].trashed:
            raise DriveReadyChangeBlocked(f"prepared blob is not unique/live: {relative_path}")
        return matches[0]


class DriveChangePlanner:
    def __init__(
        self,
        drive: DriveBackend,
        *,
        hub_root_id: str,
        canonical_root_id: str,
        stage_parent_id: str,
        history_original_parent_id: str,
        rejected_parent_id: str,
    ) -> None:
        self.drive = drive
        self.hub_root_id = hub_root_id
        self.canonical_root_id = canonical_root_id
        self.stage_parent_id = stage_parent_id
        self.history_original_parent_id = history_original_parent_id
        self.rejected_parent_id = rejected_parent_id

    def _require_folder(self, file_id: str, label: str) -> None:
        try:
            item = self.drive.get(file_id, include_trashed=False)
        except DriveNotFound as exc:
            raise DriveReadyChangeBlocked(f"required folder missing: {label}") from exc
        if item.trashed or not item.is_folder:
            raise DriveReadyChangeBlocked(f"required object is not a live folder: {label}")

    def _safe_epoch(self) -> int:
        try:
            _, raw = DriveMasterTransition.read_unique_master(self.drive, self.hub_root_id)
            master = validate_master(strict_json_bytes(raw, label="MASTER.ingestion"))
        except (DriveMasterUnavailable, ProtocolError) as exc:
            raise DriveReadyChangeBlocked(f"cannot resolve valid MASTER for Ready Change: {exc}") from exc
        if master["canonical_read_status"] != "SAFE":
            raise DriveReadyChangeBlocked("Ready Change planning requires SAFE MASTER")
        return master["canonical_epoch"]

    def _resolve_target_parent(self, target: str) -> tuple[str, str]:
        try:
            normalized = validate_relative_path(target, "CHANGE.target")
        except ProtocolError as exc:
            raise DriveReadyChangeBlocked(str(exc)) from exc
        parts = normalized.split("/")
        parent = self.canonical_root_id
        for segment in parts[:-1]:
            matches = self.drive.list_children(parent, name=segment)
            if len(matches) != 1 or not matches[0].is_folder or matches[0].trashed:
                raise DriveReadyChangeBlocked(f"canonical target parent is not unique/live: {target}")
            parent = matches[0].file_id
        return parent, parts[-1]

    def _current_target(self, parent_id: str, name: str) -> DriveItem | None:
        matches = self.drive.list_children(parent_id, name=name)
        if len(matches) > 1:
            raise DriveReadyChangeBlocked(f"canonical target is ambiguous: {parent_id}/{name}")
        if not matches:
            return None
        item = matches[0]
        if item.trashed or item.is_folder:
            raise DriveReadyChangeBlocked(f"canonical target is not a live blob: {parent_id}/{name}")
        return item

    def _verify_blob(self, item: DriveItem, state: BlobState, label: str) -> None:
        raw = self.drive.download(item.file_id)
        if not state.matches(item) or BlobState.from_bytes(raw) != state:
            raise DriveReadyChangeBlocked(f"{label} bytes/fingerprint mismatch")

    def _staged_name(self, operation_id: str) -> str:
        return f"{operation_id}.new.staged.bin"

    def _ensure_staged_copy(
        self,
        *,
        change_id: str,
        operation_id: str,
        prepared: DriveItem,
        expected: BlobState,
    ) -> DriveItem:
        name = self._staged_name(operation_id)
        matches = self.drive.list_children(self.stage_parent_id, name=name)
        if len(matches) > 1:
            raise DriveReadyChangeBlocked(f"multiple staged copies for operation {operation_id}")
        if len(matches) == 1:
            staged = matches[0]
            if staged.is_folder or staged.trashed or staged.file_id == prepared.file_id:
                raise DriveReadyChangeBlocked(f"invalid staged copy identity for operation {operation_id}")
            self._verify_blob(staged, expected, f"staged copy {operation_id}")
            return staged

        reserved = self.drive.generate_ids(1)[0]
        try:
            self.drive.copy_blob(
                prepared.file_id,
                self.stage_parent_id,
                name,
                file_id=reserved,
                label=f"drive.ingest.{change_id}.{operation_id}.copy",
            )
        except DriveAlreadyExists:
            # Observe only the exact reserved ID; do not allocate a replacement in
            # the same planning attempt.
            try:
                staged = self.drive.get(reserved, include_trashed=False)
            except DriveNotFound as exc:
                raise DriveReadyChangeBlocked(f"reserved staged ID collision for {operation_id}") from exc
            self._verify_blob(staged, expected, f"staged copy {operation_id}")
            return staged

        try:
            staged = self.drive.get(reserved, include_trashed=False)
        except DriveNotFound as exc:
            raise DriveReadyChangeBlocked(f"staged copy missing after creation: {operation_id}") from exc
        if staged.parent_id != self.stage_parent_id or staged.name != name:
            raise DriveReadyChangeBlocked(f"staged copy location mismatch: {operation_id}")
        self._verify_blob(staged, expected, f"staged copy {operation_id}")
        return staged

    def _verify_old_state(self, op: dict[str, Any], parent_id: str, name: str) -> DriveItem | None:
        current = self._current_target(parent_id, name)
        if op["kind"] == "ADD":
            if current is not None:
                raise DriveReadyChangeBlocked(f"ADD target already exists: {op['target']}")
            return None
        expected = _present_state(op["old"], f"{op['operation_id']}.old")
        if current is None:
            raise DriveReadyChangeBlocked(f"OLD target missing: {op['target']}")
        self._verify_blob(current, expected, f"OLD target {op['target']}")
        return current

    def plan(self, ready: DriveReadyChange, loader: DriveReadyChangeLoader) -> DriveControl:
        for label, file_id in (
            ("canonical_root", self.canonical_root_id),
            ("stage_parent", self.stage_parent_id),
            ("history_original", self.history_original_parent_id),
            ("rejected_parent", self.rejected_parent_id),
        ):
            self._require_folder(file_id, label)
        epoch = self._safe_epoch()
        if epoch != ready.base_canonical_epoch:
            raise DriveReadyChangeBlocked(
                f"Ready Change base epoch {ready.base_canonical_epoch} != current {epoch}"
            )

        operations: list[DriveOperation] = []
        target_bindings: list[tuple[dict[str, Any], str, str]] = []
        for op in ready.change["operations"]:
            parent_id, name = self._resolve_target_parent(op["target"])
            old_item = self._verify_old_state(op, parent_id, name)
            target_bindings.append((op, parent_id, name))

            kind = op["kind"]
            old_state = None if kind == "ADD" else _present_state(op["old"], f"{op['operation_id']}.old")
            new_state = None if kind == "DELETE" else _present_state(op["new"], f"{op['operation_id']}.new")
            staged_id = None
            staged_parent = None
            if kind in {"ADD", "REPLACE"}:
                prepared = loader.resolve_blob(ready, op["prepared_path"])
                assert new_state is not None
                self._verify_blob(prepared, new_state, f"prepared {op['prepared_path']}")
                staged = self._ensure_staged_copy(
                    change_id=ready.change_id,
                    operation_id=op["operation_id"],
                    prepared=prepared,
                    expected=new_state,
                )
                staged_id = staged.file_id
                staged_parent = self.stage_parent_id

            operations.append(
                DriveOperation(
                    operation_id=op["operation_id"],
                    kind=kind,
                    canonical_parent_id=parent_id,
                    target_name=name,
                    old=old_state,
                    new=new_state,
                    staged_new_id=staged_id,
                    staged_parent_id=staged_parent,
                    old_original_id=old_item.file_id if old_item is not None else None,
                )
            )

        # Fresh boundary validation after all failure-prone staging copies.
        if self._safe_epoch() != ready.base_canonical_epoch:
            raise DriveReadyChangeBlocked("MASTER epoch/status changed during Ready Change planning")
        for op, parent_id, name in target_bindings:
            self._verify_old_state(op, parent_id, name)
        for planned in operations:
            if planned.staged_new_id is not None and planned.new is not None:
                staged = self.drive.get(planned.staged_new_id, include_trashed=False)
                if staged.parent_id != self.stage_parent_id or staged.name != self._staged_name(planned.operation_id):
                    raise DriveReadyChangeBlocked(f"staged copy moved before planning commit: {planned.operation_id}")
                self._verify_blob(staged, planned.new, f"fresh staged copy {planned.operation_id}")

        return DriveControl(
            change_id=ready.change_id,
            hub_root_id=self.hub_root_id,
            canonical_root_id=self.canonical_root_id,
            history_original_parent_id=self.history_original_parent_id,
            rejected_parent_id=self.rejected_parent_id,
            operations=tuple(operations),
        )


__all__ = [
    "CHANGE_NAME",
    "READY_NAME",
    "DriveChangePlanner",
    "DriveReadyChange",
    "DriveReadyChangeBlocked",
    "DriveReadyChangeLoader",
]
