from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .drive_backend import DriveAlreadyExists, DriveBackend, DriveItem, DriveNotFound
from .protocol import ProtocolError, canonical_json_bytes, strict_json_bytes


BINDING_SCHEMA = "keelaryn.drive-recovery-block-binding.v1"
RECORD_SCHEMA = "keelaryn.drive-recovery-block.v1"


class DriveRecoveryBlockCorrupt(ProtocolError):
    """The Core-owned recovery block record is missing, ambiguous or altered."""


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
class DriveRecoveryBlockBinding:
    change_id: str
    change_sha256: str
    base_canonical_epoch: int
    record_parent_id: str
    record_id: str

    @property
    def record_name(self) -> str:
        return f"{self.change_id}.RECOVERY_BLOCK.json"

    @classmethod
    def plan(
        cls,
        drive: DriveBackend,
        *,
        change_id: str,
        change_sha256: str,
        base_canonical_epoch: int,
        record_parent_id: str,
    ) -> "DriveRecoveryBlockBinding":
        return cls(
            change_id=_text(change_id, "change_id"),
            change_sha256=_sha(change_sha256, "change_sha256"),
            base_canonical_epoch=_epoch(base_canonical_epoch, "base_canonical_epoch"),
            record_parent_id=_text(record_parent_id, "record_parent_id"),
            record_id=drive.generate_ids(1)[0],
        )

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(
            {
                "schema": BINDING_SCHEMA,
                "change_id": self.change_id,
                "change_sha256": self.change_sha256,
                "base_canonical_epoch": self.base_canonical_epoch,
                "record_parent_id": self.record_parent_id,
                "record_id": self.record_id,
            }
        )

    @classmethod
    def from_bytes(cls, raw: bytes) -> "DriveRecoveryBlockBinding":
        value = strict_json_bytes(raw, label="DRIVE_RECOVERY_BLOCK_BINDING")
        expected = {
            "schema",
            "change_id",
            "change_sha256",
            "base_canonical_epoch",
            "record_parent_id",
            "record_id",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ProtocolError("DRIVE_RECOVERY_BLOCK_BINDING: invalid root")
        if value["schema"] != BINDING_SCHEMA:
            raise ProtocolError("DRIVE_RECOVERY_BLOCK_BINDING.schema: unsupported schema")
        return cls(
            change_id=_text(value["change_id"], "change_id"),
            change_sha256=_sha(value["change_sha256"], "change_sha256"),
            base_canonical_epoch=_epoch(value["base_canonical_epoch"], "base_canonical_epoch"),
            record_parent_id=_text(value["record_parent_id"], "record_parent_id"),
            record_id=_text(value["record_id"], "record_id"),
        )


class DriveRecoveryBlockRecord:
    def __init__(self, drive: DriveBackend, binding: DriveRecoveryBlockBinding):
        self.drive = drive
        self.binding = binding

    def _get_live(self) -> DriveItem | None:
        try:
            return self.drive.get(self.binding.record_id, include_trashed=False)
        except DriveNotFound:
            return None

    def _parse(self, raw: bytes) -> dict[str, Any]:
        value = strict_json_bytes(raw, label="DRIVE_RECOVERY_BLOCK")
        expected = {
            "schema",
            "change_id",
            "change_sha256",
            "base_canonical_epoch",
            "observed_phase",
            "reason",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise DriveRecoveryBlockCorrupt("recovery block record has invalid root")
        b = self.binding
        if (
            value["schema"] != RECORD_SCHEMA
            or value["change_id"] != b.change_id
            or value["change_sha256"] != b.change_sha256
            or value["base_canonical_epoch"] != b.base_canonical_epoch
            or value["observed_phase"] != "ACTIVE_UNSAFE"
        ):
            raise DriveRecoveryBlockCorrupt("recovery block record identity/phase mismatch")
        _text(value["reason"], "reason", max_len=16384)
        return value

    def read(self) -> dict[str, Any] | None:
        item = self._get_live()
        if item is None:
            return None
        b = self.binding
        if (
            item.parent_id != b.record_parent_id
            or item.name != b.record_name
            or item.is_folder
            or item.trashed
        ):
            raise DriveRecoveryBlockCorrupt("recovery block record location/type mismatch")
        return self._parse(self.drive.download(item.file_id))

    def record(self, reason: str) -> dict[str, Any]:
        reason = _text(reason, "reason", max_len=16384)
        existing = self.read()
        if existing is not None:
            return existing
        b = self.binding
        raw = canonical_json_bytes(
            {
                "schema": RECORD_SCHEMA,
                "change_id": b.change_id,
                "change_sha256": b.change_sha256,
                "base_canonical_epoch": b.base_canonical_epoch,
                "observed_phase": "ACTIVE_UNSAFE",
                "reason": reason,
            }
        )
        try:
            self.drive.create_blob(
                b.record_parent_id,
                b.record_name,
                raw,
                mime_type="application/json",
                file_id=b.record_id,
                label=f"drive.recovery.{b.change_id}.block-record.create",
            )
        except DriveAlreadyExists:
            pass
        created = self.read()
        if created is None:
            raise DriveRecoveryBlockCorrupt("recovery block record missing after creation")
        return created


__all__ = [
    "DriveRecoveryBlockBinding",
    "DriveRecoveryBlockCorrupt",
    "DriveRecoveryBlockRecord",
]
