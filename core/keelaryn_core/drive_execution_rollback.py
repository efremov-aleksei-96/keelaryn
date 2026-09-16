from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .drive_backend import DriveAlreadyExists, DriveBackend, DriveItem, DriveNotFound
from .protocol import ProtocolError, canonical_json_bytes, strict_json_bytes


BINDING_SCHEMA = "keelaryn.drive-execution-rollback-binding.v1"
MARKER_SCHEMA = "keelaryn.drive-execution-rollback.v1"


class DriveExecutionRollbackBlocked(ProtocolError):
    """The Core-owned execution rollback marker is ambiguous or invalid."""


def _text(value: Any, label: str, *, max_len: int = 1024) -> str:
    if not isinstance(value, str) or not value or len(value) > max_len:
        raise ProtocolError(f"{label}: invalid string")
    return value


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ProtocolError(f"{label}: invalid sha256")
    return value


def _epoch(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ProtocolError(f"{label}: invalid epoch")
    return value


@dataclass(frozen=True)
class DriveExecutionRollbackBinding:
    change_id: str
    change_sha256: str
    base_canonical_epoch: int
    marker_parent_id: str
    marker_id: str

    @property
    def marker_name(self) -> str:
        return f"{self.change_id}.EXECUTION_ROLLBACK.json"

    @classmethod
    def plan(
        cls,
        drive: DriveBackend,
        *,
        change_id: str,
        change_sha256: str,
        base_canonical_epoch: int,
        marker_parent_id: str,
    ) -> "DriveExecutionRollbackBinding":
        return cls(
            change_id=_text(change_id, "change_id"),
            change_sha256=_sha(change_sha256, "change_sha256"),
            base_canonical_epoch=_epoch(base_canonical_epoch, "base_canonical_epoch"),
            marker_parent_id=_text(marker_parent_id, "marker_parent_id"),
            marker_id=drive.generate_ids(1)[0],
        )

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(
            {
                "schema": BINDING_SCHEMA,
                "change_id": self.change_id,
                "change_sha256": self.change_sha256,
                "base_canonical_epoch": self.base_canonical_epoch,
                "marker_parent_id": self.marker_parent_id,
                "marker_id": self.marker_id,
            }
        )

    @classmethod
    def from_bytes(cls, raw: bytes) -> "DriveExecutionRollbackBinding":
        value = strict_json_bytes(raw, label="DRIVE_EXECUTION_ROLLBACK_BINDING")
        expected = {
            "schema",
            "change_id",
            "change_sha256",
            "base_canonical_epoch",
            "marker_parent_id",
            "marker_id",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ProtocolError("DRIVE_EXECUTION_ROLLBACK_BINDING: invalid root")
        if value["schema"] != BINDING_SCHEMA:
            raise ProtocolError("DRIVE_EXECUTION_ROLLBACK_BINDING.schema: unsupported schema")
        return cls(
            change_id=_text(value["change_id"], "change_id"),
            change_sha256=_sha(value["change_sha256"], "change_sha256"),
            base_canonical_epoch=_epoch(value["base_canonical_epoch"], "base_canonical_epoch"),
            marker_parent_id=_text(value["marker_parent_id"], "marker_parent_id"),
            marker_id=_text(value["marker_id"], "marker_id"),
        )


class DriveExecutionRollbackMarker:
    def __init__(self, drive: DriveBackend, binding: DriveExecutionRollbackBinding):
        self.drive = drive
        self.binding = binding

    def _get_live(self) -> DriveItem | None:
        try:
            return self.drive.get(self.binding.marker_id, include_trashed=False)
        except DriveNotFound:
            return None

    def _parse_marker(self, raw: bytes) -> dict[str, Any]:
        value = strict_json_bytes(raw, label="DRIVE_EXECUTION_ROLLBACK")
        expected = {
            "schema",
            "change_id",
            "change_sha256",
            "base_canonical_epoch",
            "reason",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise DriveExecutionRollbackBlocked("execution rollback marker has invalid root")
        b = self.binding
        if (
            value["schema"] != MARKER_SCHEMA
            or value["change_id"] != b.change_id
            or value["change_sha256"] != b.change_sha256
            or value["base_canonical_epoch"] != b.base_canonical_epoch
        ):
            raise DriveExecutionRollbackBlocked("execution rollback marker identity mismatch")
        _text(value["reason"], "reason", max_len=16384)
        return value

    def active(self) -> bool:
        item = self._get_live()
        if item is None:
            return False
        b = self.binding
        if (
            item.parent_id != b.marker_parent_id
            or item.name != b.marker_name
            or item.is_folder
            or item.trashed
        ):
            raise DriveExecutionRollbackBlocked("execution rollback marker location/type mismatch")
        self._parse_marker(self.drive.download(item.file_id))
        return True

    def record(self, reason: str) -> bool:
        reason = _text(reason, "reason", max_len=16384)
        if self.active():
            return True
        b = self.binding
        raw = canonical_json_bytes(
            {
                "schema": MARKER_SCHEMA,
                "change_id": b.change_id,
                "change_sha256": b.change_sha256,
                "base_canonical_epoch": b.base_canonical_epoch,
                "reason": reason,
            }
        )
        try:
            self.drive.create_blob(
                b.marker_parent_id,
                b.marker_name,
                raw,
                mime_type="application/json",
                file_id=b.marker_id,
                label=f"drive.execution.{b.change_id}.rollback.create",
            )
        except DriveAlreadyExists:
            pass
        if not self.active():
            raise DriveExecutionRollbackBlocked("execution rollback marker missing after creation")
        return True


__all__ = [
    "DriveExecutionRollbackBinding",
    "DriveExecutionRollbackBlocked",
    "DriveExecutionRollbackMarker",
]
