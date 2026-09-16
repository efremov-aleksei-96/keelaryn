from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from .drive_backend import DriveBackend, DriveItem
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
    staged_parent_id: str | None = None
    old_original_id: str | None = None


class DrivePublicationTransaction:
    """Crash-restartable publication primitive over a DriveBackend.

    This models canonical object movement and rollback only. MASTER, semantic
    post-check, durable control serialization and REST transport remain later
    layers. The internal substates exist only to recover crashes between Drive
    mutations; the outer protocol still exposes OLD / NEW / UNKNOWN semantics.
    """

    def __init__(self, drive: DriveBackend, history_original_parent_id: str, rejected_parent_id: str):
        self.drive = drive
        self.history_original_parent_id = history_original_parent_id
        self.rejected_parent_id = rejected_parent_id

    def _unique_live(self, parent_id: str, name: str) -> DriveItem | None:
        matches = self.drive.list_children(parent_id, name=name)
        if len(matches) > 1:
            raise DriveRecoveryBlocked(f"ambiguous canonical target {parent_id}/{name}")
        return matches[0] if matches else None

    def _get_live(self, file_id: str | None) -> DriveItem | None:
        if file_id is None:
            return None
        try:
            return self.drive.get(file_id, include_trashed=False)
        except ProtocolError:
            return None

    def _require_exact(
        self,
        file_id: str,
        state: BlobState,
        *,
        parent_id: str | None = None,
        name: str | None = None,
    ) -> DriveItem:
        item = self._get_live(file_id)
        if item is None:
            raise DriveRecoveryBlocked(f"expected object missing: {file_id}")
        if not state.matches(item):
            raise DriveRecoveryBlocked(f"object bytes changed: {file_id}")
        if parent_id is not None and item.parent_id != parent_id:
            raise DriveRecoveryBlocked(f"object parent changed: {file_id}")
        if name is not None and item.name != name:
            raise DriveRecoveryBlocked(f"object name changed: {file_id}")
        return item

    def _old_in_history(self, op: DriveOperation) -> DriveItem | None:
        if op.old_original_id is None or op.old is None:
            return None
        item = self._get_live(op.old_original_id)
        if item is None or not op.old.matches(item) or item.parent_id != self.history_original_parent_id:
            return None
        return item

    def _new_item(self, op: DriveOperation) -> DriveItem | None:
        if op.staged_new_id is None or op.new is None:
            return None
        item = self._get_live(op.staged_new_id)
        if item is None or not op.new.matches(item):
            return None
        return item

    def classify(self, op: DriveOperation) -> str:
        """Return semantic OLD/NEW/UNKNOWN or an internal recoverable substate."""
        target = self._unique_live(op.canonical_parent_id, op.target_name)
        old_history = self._old_in_history(op)
        new_item = self._new_item(op)

        if op.kind == "ADD":
            if target is None:
                return "OLD"
            if new_item is not None and target.file_id == new_item.file_id:
                return "NEW"
            return "UNKNOWN"

        if op.kind == "DELETE":
            if (
                target is not None
                and op.old is not None
                and op.old_original_id in {None, target.file_id}
                and op.old.matches(target)
            ):
                return "OLD"
            if target is None and old_history is not None:
                return "NEW"
            return "UNKNOWN"

        if op.kind == "REPLACE":
            if (
                target is not None
                and op.old is not None
                and op.old_original_id in {None, target.file_id}
                and op.old.matches(target)
            ):
                return "OLD"
            if (
                target is not None
                and new_item is not None
                and target.file_id == new_item.file_id
                and old_history is not None
            ):
                return "NEW"
            if target is None and old_history is not None and new_item is not None:
                if op.staged_parent_id is not None and new_item.parent_id == op.staged_parent_id:
                    return "OLD_DISPLACED"
                if new_item.parent_id == self.rejected_parent_id:
                    return "NEW_REJECTED"
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
        if op.staged_new_id is None or op.staged_parent_id is None or op.new is None:
            raise ProtocolError("new object identity or staging parent missing")
        self._require_exact(op.staged_new_id, op.new, parent_id=op.staged_parent_id)

    def apply(self, op: DriveOperation) -> None:
        state = self.classify(op)
        if state == "NEW":
            return
        if state not in {"OLD", "OLD_DISPLACED"}:
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
            self._require_exact(
                op.old_original_id,
                op.old,
                parent_id=op.canonical_parent_id,
                name=op.target_name,
            )
            self.drive.move_rename(
                op.old_original_id,
                self.history_original_parent_id,
                f"{op.operation_id}.old",
                label=f"drive.tx.{op.operation_id}.delete.displace_old",
            )

        elif op.kind == "REPLACE":
            if op.old is None or op.new is None or op.old_original_id is None or op.staged_new_id is None:
                raise ProtocolError("REPLACE identities incomplete")
            if state == "OLD":
                self._require_exact(
                    op.old_original_id,
                    op.old,
                    parent_id=op.canonical_parent_id,
                    name=op.target_name,
                )
                self.verify_staged_new(op)
                self.drive.move_rename(
                    op.old_original_id,
                    self.history_original_parent_id,
                    f"{op.operation_id}.old",
                    label=f"drive.tx.{op.operation_id}.replace.displace_old",
                )
            # Crash restart may arrive here with OLD already displaced.
            if self._unique_live(op.canonical_parent_id, op.target_name) is not None:
                raise DriveRecoveryBlocked("canonical target unexpectedly occupied after OLD displacement")
            if op.staged_parent_id is None:
                raise ProtocolError("REPLACE staging parent missing")
            self._require_exact(op.staged_new_id, op.new, parent_id=op.staged_parent_id)
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
        if state not in {"NEW", "OLD_DISPLACED", "NEW_REJECTED"}:
            raise DriveRecoveryBlocked(f"cannot rollback from {state}")

        if op.kind == "ADD":
            if state != "NEW" or op.staged_new_id is None or op.new is None:
                raise DriveRecoveryBlocked(f"invalid ADD rollback state: {state}")
            self._require_exact(
                op.staged_new_id,
                op.new,
                parent_id=op.canonical_parent_id,
                name=op.target_name,
            )
            self.drive.move_rename(
                op.staged_new_id,
                self.rejected_parent_id,
                f"{op.operation_id}.rejected",
                label=f"drive.tx.{op.operation_id}.add.rollback",
            )

        elif op.kind == "DELETE":
            if op.old_original_id is None or op.old is None:
                raise ProtocolError("DELETE old identity missing")
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
            if op.old_original_id is None or op.old is None or op.staged_new_id is None or op.new is None:
                raise ProtocolError("REPLACE identities incomplete")
            self._require_exact(op.old_original_id, op.old, parent_id=self.history_original_parent_id)
            if state == "NEW":
                self._require_exact(
                    op.staged_new_id,
                    op.new,
                    parent_id=op.canonical_parent_id,
                    name=op.target_name,
                )
                self.drive.move_rename(
                    op.staged_new_id,
                    self.rejected_parent_id,
                    f"{op.operation_id}.rejected",
                    label=f"drive.tx.{op.operation_id}.replace.reject_new",
                )
            elif state == "OLD_DISPLACED":
                # Apply crashed before NEW publication: OLD can be restored directly.
                if op.staged_parent_id is None:
                    raise ProtocolError("REPLACE staging parent missing")
                self._require_exact(op.staged_new_id, op.new, parent_id=op.staged_parent_id)
            elif state == "NEW_REJECTED":
                self._require_exact(op.staged_new_id, op.new, parent_id=self.rejected_parent_id)

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
