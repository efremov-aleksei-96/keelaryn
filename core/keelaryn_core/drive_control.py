from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .drive_transaction import BlobState, DriveOperation
from .protocol import ProtocolError, canonical_json_bytes, strict_json_bytes


SCHEMA = "keelaryn.drive-control.v1"


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ProtocolError(
            f"{label}: keys mismatch missing={sorted(expected - set(value))} extra={sorted(set(value) - expected)}"
        )


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise ProtocolError(f"{label}: invalid string")
    return value


def _blob_state(value: Any, label: str, *, allow_none: bool) -> BlobState | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, dict):
        raise ProtocolError(f"{label}: expected object")
    _exact_keys(value, {"sha256", "size"}, label)
    digest = value["sha256"]
    size = value["size"]
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ProtocolError(f"{label}.sha256: invalid digest")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise ProtocolError(f"{label}.size: invalid size")
    return BlobState(digest, size)


def _state_json(value: BlobState | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {"sha256": value.sha256, "size": value.size}


@dataclass(frozen=True)
class DriveControl:
    change_id: str
    hub_root_id: str
    canonical_root_id: str
    history_original_parent_id: str
    rejected_parent_id: str
    operations: tuple[DriveOperation, ...]

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(
            {
                "schema": SCHEMA,
                "change_id": self.change_id,
                "hub_root_id": self.hub_root_id,
                "canonical_root_id": self.canonical_root_id,
                "history_original_parent_id": self.history_original_parent_id,
                "rejected_parent_id": self.rejected_parent_id,
                "operations": [
                    {
                        "operation_id": op.operation_id,
                        "kind": op.kind,
                        "canonical_parent_id": op.canonical_parent_id,
                        "target_name": op.target_name,
                        "old": _state_json(op.old),
                        "new": _state_json(op.new),
                        "staged_new_id": op.staged_new_id,
                        "staged_parent_id": op.staged_parent_id,
                        "old_original_id": op.old_original_id,
                    }
                    for op in self.operations
                ],
            }
        )

    @classmethod
    def from_bytes(cls, raw: bytes) -> "DriveControl":
        value = strict_json_bytes(raw, label="DRIVE_CONTROL")
        if not isinstance(value, dict):
            raise ProtocolError("DRIVE_CONTROL: root must be object")
        _exact_keys(
            value,
            {
                "schema",
                "change_id",
                "hub_root_id",
                "canonical_root_id",
                "history_original_parent_id",
                "rejected_parent_id",
                "operations",
            },
            "DRIVE_CONTROL",
        )
        if value["schema"] != SCHEMA:
            raise ProtocolError("DRIVE_CONTROL.schema: unsupported schema")
        operations_raw = value["operations"]
        if not isinstance(operations_raw, list) or not operations_raw:
            raise ProtocolError("DRIVE_CONTROL.operations: non-empty array required")

        operations: list[DriveOperation] = []
        operation_ids: set[str] = set()
        logical_targets: set[tuple[str, str]] = set()
        for index, item in enumerate(operations_raw):
            label = f"DRIVE_CONTROL.operations[{index}]"
            if not isinstance(item, dict):
                raise ProtocolError(f"{label}: expected object")
            _exact_keys(
                item,
                {
                    "operation_id",
                    "kind",
                    "canonical_parent_id",
                    "target_name",
                    "old",
                    "new",
                    "staged_new_id",
                    "staged_parent_id",
                    "old_original_id",
                },
                label,
            )
            operation_id = _text(item["operation_id"], f"{label}.operation_id")
            if operation_id in operation_ids:
                raise ProtocolError(f"{label}: duplicate operation_id")
            operation_ids.add(operation_id)
            kind = item["kind"]
            if kind not in {"ADD", "REPLACE", "DELETE"}:
                raise ProtocolError(f"{label}.kind: invalid kind")
            canonical_parent_id = _text(item["canonical_parent_id"], f"{label}.canonical_parent_id")
            target_name = _text(item["target_name"], f"{label}.target_name")
            target_key = (canonical_parent_id, target_name)
            if target_key in logical_targets:
                raise ProtocolError(f"{label}: duplicate logical target")
            logical_targets.add(target_key)
            old = _blob_state(item["old"], f"{label}.old", allow_none=True)
            new = _blob_state(item["new"], f"{label}.new", allow_none=True)

            staged_new_id = item["staged_new_id"]
            staged_parent_id = item["staged_parent_id"]
            old_original_id = item["old_original_id"]
            for field_name, field_value in (
                ("staged_new_id", staged_new_id),
                ("staged_parent_id", staged_parent_id),
                ("old_original_id", old_original_id),
            ):
                if field_value is not None:
                    _text(field_value, f"{label}.{field_name}")

            if kind == "ADD":
                if old is not None or new is None or staged_new_id is None or staged_parent_id is None or old_original_id is not None:
                    raise ProtocolError(f"{label}: illegal ADD identities")
            elif kind == "REPLACE":
                if old is None or new is None or staged_new_id is None or staged_parent_id is None or old_original_id is None:
                    raise ProtocolError(f"{label}: incomplete REPLACE identities")
            elif kind == "DELETE":
                if old is None or new is not None or staged_new_id is not None or staged_parent_id is not None or old_original_id is None:
                    raise ProtocolError(f"{label}: illegal DELETE identities")

            operations.append(
                DriveOperation(
                    operation_id=operation_id,
                    kind=kind,
                    canonical_parent_id=canonical_parent_id,
                    target_name=target_name,
                    old=old,
                    new=new,
                    staged_new_id=staged_new_id,
                    staged_parent_id=staged_parent_id,
                    old_original_id=old_original_id,
                )
            )

        return cls(
            change_id=_text(value["change_id"], "DRIVE_CONTROL.change_id"),
            hub_root_id=_text(value["hub_root_id"], "DRIVE_CONTROL.hub_root_id"),
            canonical_root_id=_text(value["canonical_root_id"], "DRIVE_CONTROL.canonical_root_id"),
            history_original_parent_id=_text(
                value["history_original_parent_id"], "DRIVE_CONTROL.history_original_parent_id"
            ),
            rejected_parent_id=_text(value["rejected_parent_id"], "DRIVE_CONTROL.rejected_parent_id"),
            operations=tuple(operations),
        )
