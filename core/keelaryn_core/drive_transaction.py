from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from .drive_model import DriveItem, DriveModel
from .protocol import ProtocolError


class DriveRecoveryBlocked(ProtocolError):
    pass


@dataclass(frozen=True)
class BlobState:
    sha256: str
    size: int

    @classmethod
    def from_bytes(cls, content: bytes) -> "BlobState":
        return cls(sha256(content).hexdigest(), len(content))

    def matches(self, item: DriveItem | None) -> bool:
        return (
            item is not None
            and not item.trashed
            and not item.is_folder
            and item.sha256_checksum == self.sha256
            and item.size == self.size
        )


@dataclass
class DriveOperation:
    operation_id: str
    kind: str
    canonical_parent_id: str
    target_name: str
    old: BlobState | None
    new: BlobState | None
    staged_new_id: str | None = None
    old_original_id: str | None = None


class DrivePublicationTransaction:
    """Crash-restartable publication primitive over DriveModel.

    This intentionally models only canonical object movement and rollback. MASTER,
    semantic post-check, durable control serialization and REST transport remain the
    responsibility of later layers. The simulator proves the copy-on-write object
    choreography required by spec/DRIVE_BACKEND.md.
    """

    def __init__(self, drive: DriveModel, history_original_parent_id: str, rejected_parent_id: str):
        self.drive = drive
        self.history_original_parent_id = history_original_parent_id
        self.rejected_parent_id = rejected_parent_id

    def _unique_live(self, parent_id: str, name: str) -> DriveItem | None:
        matches = self.drive.list_children(parent_id, name=name)
        if len(matches) > 1:
            raise DriveRecoveryBlocked(f"ambiguous canonical target {parent_id}/{name}")
        return matches[0] if matches else None

    def _require_exact(self, file_id: str, state: BlobState, *, parent_id: str | None = None, name: str | None = None) -> DriveItem:
        try:
            item = self.drive.get(file_id, include_trashed=False)
        except ProtocolError as exc:
            raise DriveRecoveryBlocked(f"expected object missing: {file_id}") from exc
        if not state.matches(item):
            raise DriveRecoveryBlocked(f"object bytes changed: {file_id}")
        if parent_id is not None and item.parent_id != parent_id:
            raise DriveRecoveryBlocked(f"object parent changed: {file_id}")
        if name is not None and item.name != name:
            raise DriveRecoveryBlocked(f"object name changed: {file_id}")
        return item

    def classify(self, op: DriveOperation) -> str:
        target = self._unique_live(op.canonical_parent_id, op.target_name)
        old_at_history = None
        if op.old_original_id is not None and op.old is not None:
            try:
                candidate = self.drive.get(op.old_original_id, include_trashed=False)
            except ProtocolError:
                candidate = None
            if candidate is not None and op.old.matches(candidate) and candidate.parent_id == self.history_original_parent_id:
                old_at_history = candidate

        if op.kind == "ADD":
            if target is None:
                return "OLD"
            if op.new and op.staged_new_id == target.file_id and op.new.matches(target):
                return "NEW"
            return "UNKNOWN"

        if op.kind == "DELETE":
            if target is not None and op.old and op.old_original_id in {None, target.file_id} and op.old.matches(target):
                return "OLD"
            if target is None and old_at_history is not None:
                return "NEW"
            return "UNKNOWN"

        if op.kind == "REPLACE":
            if target is not None and op.old and op.old_original_id in {None, target.file_id} and op.old.matches(target):
                return "OLD"
            if target is not None and op.new and op.staged_new_id == target.file_id and op.new.matches(target) and old_at_history is not None:
                return "NEW"
            return "UNKNOWN"

        raise ProtocolError(f"unsupported Drive operation kind: {op.kind}")

    def capture_old_identity(self, op: DriveOperation) -> None:
        if op.kind == "ADD":
            if self._unique_live(op.canonical_parent_id, op.target_name) is not None:
                raise ProtocolError("ADD target already exists")
            return
        target = self._unique_live(op.canonical_parent_id, op.target_name)
        if target is None or op.old is None or not op.old.matches(target):
            raise ProtocolError(f"{op.kind} target does not match OLD")
        if op.old_original_id is not None and op.old_original_id != target.file_id:
            raise DriveRecoveryBlocked("recorded OLD identity disagrees with canonical target")
        op.old_original_id = target.file_id

    def verify_staged_new(self, op: DriveOperation) -> None:
        if op.kind == "DELETE":
            return
        if op.staged_new_id is None or op.new is None:
            raise ProtocolError("new object identity missing")
        self._require_exact(op.staged_new_id, op.new)

    def apply(self, op: DriveOperation) -> None:
        state = self.classify(op)
        if state == "NEW":
            return
        if state != "OLD":
            raise DriveRecoveryBlocked(f"cannot apply from {state}")

        if op.kind == "ADD":
            self.verify_staged_new(op)
            assert op.staged_new_id is not None
            self.drive.move_rename(
                op.staged_new_id,
                op.canonical_parent_id,
                op.target_name,
                label=f"drive.tx.{op.operation_id}.add.publish",
            )

        elif op.kind == "DELETE":
            if op.old is None or op.old_original_id is None:
                raise ProtocolError("DELETE old identity missing")
            self._require_exact(op.old_original_id, op.old, parent_id=op.canonical_parent_id, name=op.target_name)
            self.drive.move_rename(
                op.old_original_id,
                self.history_original_parent_id,
                f"{op.operation_id}.old",
                label=f"drive.tx.{op.operation_id}.delete.displace_old",
            )

        elif op.kind == "REPLACE":
            if op.old is None or op.new is None or op.old_original_id is None or op.staged_new_id is None:
                raise ProtocolError("REPLACE identities incomplete")
            self._require_exact(op.old_original_id, op.old, parent_id=op.canonical_parent_id, name=op.target_name)
            self.verify_staged_new(op)
            self.drive.move_rename(
                op.old_original_id,
                self.history_original_parent_id,
                f"{op.operation_id}.old",
                label=f"drive.tx.{op.operation_id}.replace.displace_old",
            )
            if self._unique_live(op.canonical_parent_id, op.target_name) is not None:
                raise DriveRecoveryBlocked("canonical target unexpectedly occupied after OLD displacement")
            self.drive.move_rename(
                op.staged_new_id,
                op.canonical_parent_id,
                op.target_name,
                label=f"drive.tx.{op.operation_id}.replace.publish_new",
            )

        if self.classify(op) != "NEW":
            raise DriveRecoveryBlocked("operation did not reach exact NEW state")

    def rollback(self, op: DriveOperation) -> None:
        state = self.classify(op)
        if state == "OLD":
            return
        if state != "NEW":
            raise DriveRecoveryBlocked(f"cannot rollback from {state}")

        if op.kind == "ADD":
            assert op.staged_new_id is not None and op.new is not None
            self._require_exact(op.staged_new_id, op.new, parent_id=op.canonical_parent_id, name=op.target_name)
            self.drive.move_rename(
                op.staged_new_id,
                self.rejected_parent_id,
                f"{op.operation_id}.rejected",
                label=f"drive.tx.{op.operation_id}.add.rollback",
            )

        elif op.kind == "DELETE":
            assert op.old_original_id is not None and op.old is not None
            self._require_exact(op.old_original_id, op.old, parent_id=self.history_original_parent_id)
            if self._unique_live(op.canonical_parent_id, op.target_name) is not None:
                raise DriveRecoveryBlocked("DELETE rollback target occupied")
            self.drive.move_rename(
                op.old_original_id,
                op.canonical_parent_id,
                op.target_name,
                label=f"drive.tx.{op.operation_id}.delete.rollback",
            )

        elif op.kind == "REPLACE":
            assert op.old_original_id is not None and op.old is not None
            assert op.staged_new_id is not None and op.new is not None
            self._require_exact(op.staged_new_id, op.new, parent_id=op.canonical_parent_id, name=op.target_name)
            self._require_exact(op.old_original_id, op.old, parent_id=self.history_original_parent_id)
            self.drive.move_rename(
                op.staged_new_id,
                self.rejected_parent_id,
                f"{op.operation_id}.rejected",
                label=f"drive.tx.{op.operation_id}.replace.reject_new",
            )
            if self._unique_live(op.canonical_parent_id, op.target_name) is not None:
                raise DriveRecoveryBlocked("REPLACE rollback target occupied")
            self.drive.move_rename(
                op.old_original_id,
                op.canonical_parent_id,
                op.target_name,
                label=f"drive.tx.{op.operation_id}.replace.restore_old",
            )

        if self.classify(op) != "OLD":
            raise DriveRecoveryBlocked("rollback did not reach exact OLD state")
