from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .drive_backend import DriveAlreadyExists, DriveBackend, DriveItem, DriveNotFound
from .drive_control import DriveControl
from .drive_transaction import BlobState
from .protocol import ProtocolError, canonical_json_bytes, strict_json_bytes


SCHEMA = "keelaryn.drive-snapshot-plan.v1"


class DriveSnapshotBlocked(ProtocolError):
    """A required pre-UNSAFE Drive snapshot cannot be proven exact."""


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise ProtocolError(f"{label}: invalid string")
    return value


def _state_json(state: BlobState) -> dict[str, Any]:
    return {"sha256": state.sha256, "size": state.size}


def _state(value: Any, label: str) -> BlobState:
    if not isinstance(value, dict) or set(value) != {"sha256", "size"}:
        raise ProtocolError(f"{label}: invalid fingerprint")
    digest = value["sha256"]
    size = value["size"]
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ProtocolError(f"{label}.sha256: invalid digest")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise ProtocolError(f"{label}.size: invalid size")
    return BlobState(digest, size)


@dataclass(frozen=True)
class DriveSnapshotEntry:
    operation_id: str
    source_id: str
    source_parent_id: str
    source_name: str
    source_state: BlobState
    snapshot_id: str
    snapshot_name: str


@dataclass(frozen=True)
class DriveSnapshotPlan:
    change_id: str
    snapshot_parent_id: str
    entries: tuple[DriveSnapshotEntry, ...]

    @classmethod
    def plan(cls, drive: DriveBackend, control: DriveControl, snapshot_parent_id: str) -> "DriveSnapshotPlan":
        targets = [op for op in control.operations if op.kind in {"REPLACE", "DELETE"}]
        ids = drive.generate_ids(len(targets)) if targets else []
        entries: list[DriveSnapshotEntry] = []
        for op, snapshot_id in zip(targets, ids, strict=True):
            if op.old is None or op.old_original_id is None:
                raise ProtocolError(f"snapshot source identity missing for {op.operation_id}")
            entries.append(
                DriveSnapshotEntry(
                    operation_id=op.operation_id,
                    source_id=op.old_original_id,
                    source_parent_id=op.canonical_parent_id,
                    source_name=op.target_name,
                    source_state=op.old,
                    snapshot_id=snapshot_id,
                    snapshot_name=f"{op.operation_id}.old.snapshot.bin",
                )
            )
        return cls(control.change_id, snapshot_parent_id, tuple(entries))

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(
            {
                "schema": SCHEMA,
                "change_id": self.change_id,
                "snapshot_parent_id": self.snapshot_parent_id,
                "entries": [
                    {
                        "operation_id": entry.operation_id,
                        "source_id": entry.source_id,
                        "source_parent_id": entry.source_parent_id,
                        "source_name": entry.source_name,
                        "source_state": _state_json(entry.source_state),
                        "snapshot_id": entry.snapshot_id,
                        "snapshot_name": entry.snapshot_name,
                    }
                    for entry in self.entries
                ],
            }
        )

    @classmethod
    def from_bytes(cls, raw: bytes) -> "DriveSnapshotPlan":
        value = strict_json_bytes(raw, label="DRIVE_SNAPSHOT_PLAN")
        if not isinstance(value, dict) or set(value) != {"schema", "change_id", "snapshot_parent_id", "entries"}:
            raise ProtocolError("DRIVE_SNAPSHOT_PLAN: invalid root")
        if value["schema"] != SCHEMA:
            raise ProtocolError("DRIVE_SNAPSHOT_PLAN.schema: unsupported schema")
        entries_raw = value["entries"]
        if not isinstance(entries_raw, list):
            raise ProtocolError("DRIVE_SNAPSHOT_PLAN.entries: expected array")
        entries: list[DriveSnapshotEntry] = []
        operation_ids: set[str] = set()
        snapshot_ids: set[str] = set()
        for index, item in enumerate(entries_raw):
            label = f"DRIVE_SNAPSHOT_PLAN.entries[{index}]"
            expected = {
                "operation_id",
                "source_id",
                "source_parent_id",
                "source_name",
                "source_state",
                "snapshot_id",
                "snapshot_name",
            }
            if not isinstance(item, dict) or set(item) != expected:
                raise ProtocolError(f"{label}: invalid entry")
            operation_id = _text(item["operation_id"], f"{label}.operation_id")
            snapshot_id = _text(item["snapshot_id"], f"{label}.snapshot_id")
            if operation_id in operation_ids:
                raise ProtocolError(f"{label}: duplicate operation_id")
            if snapshot_id in snapshot_ids:
                raise ProtocolError(f"{label}: duplicate snapshot_id")
            operation_ids.add(operation_id)
            snapshot_ids.add(snapshot_id)
            entries.append(
                DriveSnapshotEntry(
                    operation_id=operation_id,
                    source_id=_text(item["source_id"], f"{label}.source_id"),
                    source_parent_id=_text(item["source_parent_id"], f"{label}.source_parent_id"),
                    source_name=_text(item["source_name"], f"{label}.source_name"),
                    source_state=_state(item["source_state"], f"{label}.source_state"),
                    snapshot_id=snapshot_id,
                    snapshot_name=_text(item["snapshot_name"], f"{label}.snapshot_name"),
                )
            )
        return cls(
            change_id=_text(value["change_id"], "DRIVE_SNAPSHOT_PLAN.change_id"),
            snapshot_parent_id=_text(value["snapshot_parent_id"], "DRIVE_SNAPSHOT_PLAN.snapshot_parent_id"),
            entries=tuple(entries),
        )


class DriveSnapshotter:
    def __init__(self, drive: DriveBackend, plan: DriveSnapshotPlan):
        self.drive = drive
        self.plan = plan

    def _get_live(self, file_id: str) -> DriveItem | None:
        try:
            return self.drive.get(file_id, include_trashed=False)
        except DriveNotFound:
            return None

    def _verify_exact(
        self,
        item: DriveItem,
        state: BlobState,
        *,
        parent_id: str,
        name: str,
    ) -> DriveItem:
        if item.parent_id != parent_id or item.name != name or not state.matches(item):
            raise DriveSnapshotBlocked(f"Drive snapshot identity/location mismatch: {item.file_id}")
        raw = self.drive.download(item.file_id)
        if BlobState.from_bytes(raw) != state:
            raise DriveSnapshotBlocked(f"Drive snapshot bytes mismatch: {item.file_id}")
        return item

    def ensure_entry(self, entry: DriveSnapshotEntry) -> DriveItem:
        source = self._get_live(entry.source_id)
        if source is None:
            raise DriveSnapshotBlocked(f"snapshot source missing: {entry.operation_id}")
        self._verify_exact(
            source,
            entry.source_state,
            parent_id=entry.source_parent_id,
            name=entry.source_name,
        )

        existing = self._get_live(entry.snapshot_id)
        if existing is not None:
            if existing.file_id == entry.source_id:
                raise DriveSnapshotBlocked("snapshot must have distinct Drive file ID")
            return self._verify_exact(
                existing,
                entry.source_state,
                parent_id=self.plan.snapshot_parent_id,
                name=entry.snapshot_name,
            )

        try:
            self.drive.copy_blob(
                entry.source_id,
                self.plan.snapshot_parent_id,
                entry.snapshot_name,
                file_id=entry.snapshot_id,
                label=f"drive.snapshot.{self.plan.change_id}.{entry.operation_id}.copy",
            )
        except DriveAlreadyExists:
            # Not a mutation retry. Observe the exact reserved destination ID and
            # accept it only if it is the exact planned snapshot.
            pass

        created = self._get_live(entry.snapshot_id)
        if created is None or created.file_id == entry.source_id:
            raise DriveSnapshotBlocked(f"snapshot copy missing after creation: {entry.operation_id}")
        return self._verify_exact(
            created,
            entry.source_state,
            parent_id=self.plan.snapshot_parent_id,
            name=entry.snapshot_name,
        )

    def ensure_all(self) -> tuple[DriveItem, ...]:
        return tuple(self.ensure_entry(entry) for entry in self.plan.entries)

    def verify_all(self) -> tuple[DriveItem, ...]:
        verified: list[DriveItem] = []
        for entry in self.plan.entries:
            source = self._get_live(entry.source_id)
            snapshot = self._get_live(entry.snapshot_id)
            if source is None or snapshot is None:
                raise DriveSnapshotBlocked(f"source/snapshot missing: {entry.operation_id}")
            self._verify_exact(
                source,
                entry.source_state,
                parent_id=entry.source_parent_id,
                name=entry.source_name,
            )
            if snapshot.file_id == source.file_id:
                raise DriveSnapshotBlocked("snapshot must have distinct Drive file ID")
            verified.append(
                self._verify_exact(
                    snapshot,
                    entry.source_state,
                    parent_id=self.plan.snapshot_parent_id,
                    name=entry.snapshot_name,
                )
            )
        return tuple(verified)


__all__ = [
    "DriveSnapshotBlocked",
    "DriveSnapshotEntry",
    "DriveSnapshotPlan",
    "DriveSnapshotter",
]
