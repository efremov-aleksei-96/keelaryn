from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .drive_backend import DriveBackend, DriveItem, DriveNotFound
from .drive_transaction import BlobState
from .protocol import ProtocolError, canonical_json_bytes, strict_json_bytes


SCHEMA = "keelaryn.drive-master-transition.v1"
MASTER_NAME = "MASTER.json"


class DriveMasterUnavailable(ProtocolError):
    """Normal readers cannot resolve one exact live MASTER.json."""


class DriveMasterRecoveryBlocked(ProtocolError):
    """MASTER transition state is ambiguous or contains unknown bytes/location."""


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise ProtocolError(f"{label}: invalid string")
    return value


def _state_json(value: BlobState) -> dict[str, Any]:
    return {"sha256": value.sha256, "size": value.size}


def _state(value: Any, label: str) -> BlobState:
    if not isinstance(value, dict) or set(value) != {"sha256", "size"}:
        raise ProtocolError(f"{label}: invalid fingerprint object")
    digest = value["sha256"]
    size = value["size"]
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ProtocolError(f"{label}.sha256: invalid digest")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise ProtocolError(f"{label}.size: invalid size")
    return BlobState(digest, size)


@dataclass(frozen=True)
class DriveMasterBinding:
    transition_id: str
    root_id: str
    transition_parent_id: str
    old_master_id: str
    old_state: BlobState
    candidate_master_id: str
    new_state: BlobState

    @property
    def candidate_name(self) -> str:
        return f"{self.transition_id}.MASTER.candidate.json"

    @property
    def old_name(self) -> str:
        return f"{self.transition_id}.MASTER.old.json"

    @property
    def rejected_name(self) -> str:
        return f"{self.transition_id}.MASTER.rejected.json"

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(
            {
                "schema": SCHEMA,
                "transition_id": self.transition_id,
                "root_id": self.root_id,
                "transition_parent_id": self.transition_parent_id,
                "old_master_id": self.old_master_id,
                "old_state": _state_json(self.old_state),
                "candidate_master_id": self.candidate_master_id,
                "new_state": _state_json(self.new_state),
            }
        )

    @classmethod
    def from_bytes(cls, raw: bytes) -> "DriveMasterBinding":
        value = strict_json_bytes(raw, label="DRIVE_MASTER_TRANSITION")
        if not isinstance(value, dict):
            raise ProtocolError("DRIVE_MASTER_TRANSITION: root must be object")
        expected = {
            "schema",
            "transition_id",
            "root_id",
            "transition_parent_id",
            "old_master_id",
            "old_state",
            "candidate_master_id",
            "new_state",
        }
        if set(value) != expected:
            raise ProtocolError("DRIVE_MASTER_TRANSITION: keys mismatch")
        if value["schema"] != SCHEMA:
            raise ProtocolError("DRIVE_MASTER_TRANSITION.schema: unsupported schema")
        transition_id = _text(value["transition_id"], "transition_id")
        if any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-" for ch in transition_id):
            raise ProtocolError("transition_id: unsafe transition identifier")
        return cls(
            transition_id=transition_id,
            root_id=_text(value["root_id"], "root_id"),
            transition_parent_id=_text(value["transition_parent_id"], "transition_parent_id"),
            old_master_id=_text(value["old_master_id"], "old_master_id"),
            old_state=_state(value["old_state"], "old_state"),
            candidate_master_id=_text(value["candidate_master_id"], "candidate_master_id"),
            new_state=_state(value["new_state"], "new_state"),
        )


class DriveMasterTransition:
    """Copy-on-write logical MASTER publication over a DriveBackend.

    The binding is expected to be durably persisted by the outer Core before any
    canonical MASTER movement. Recovery derives state solely from that binding and
    fresh Drive observations; process-local progress is never authority.
    """

    def __init__(self, drive: DriveBackend, binding: DriveMasterBinding):
        self.drive = drive
        self.binding = binding

    @classmethod
    def plan(
        cls,
        drive: DriveBackend,
        *,
        transition_id: str,
        root_id: str,
        transition_parent_id: str,
        expected_old: BlobState,
        new_bytes: bytes,
    ) -> DriveMasterBinding:
        matches = drive.list_children(root_id, name=MASTER_NAME)
        if len(matches) != 1:
            raise DriveMasterUnavailable(f"expected exactly one {MASTER_NAME}, found {len(matches)}")
        old = matches[0]
        cls._verify_exact_static(drive, old, expected_old, parent_id=root_id, name=MASTER_NAME)
        candidate_id = drive.generate_ids(1)[0]
        return DriveMasterBinding(
            transition_id=transition_id,
            root_id=root_id,
            transition_parent_id=transition_parent_id,
            old_master_id=old.file_id,
            old_state=expected_old,
            candidate_master_id=candidate_id,
            new_state=BlobState.from_bytes(bytes(new_bytes)),
        )

    @staticmethod
    def read_unique_master(drive: DriveBackend, root_id: str) -> tuple[DriveItem, bytes]:
        matches = drive.list_children(root_id, name=MASTER_NAME)
        if len(matches) != 1:
            raise DriveMasterUnavailable(f"expected exactly one {MASTER_NAME}, found {len(matches)}")
        item = matches[0]
        if item.is_folder or item.trashed:
            raise DriveMasterUnavailable("MASTER.json is not a live blob")
        raw = drive.download(item.file_id)
        actual = BlobState.from_bytes(raw)
        if not actual.matches(item):
            raise DriveMasterUnavailable("MASTER.json metadata/content fingerprint mismatch")
        return item, raw

    @staticmethod
    def _verify_exact_static(
        drive: DriveBackend,
        item: DriveItem,
        state: BlobState,
        *,
        parent_id: str | None = None,
        name: str | None = None,
    ) -> DriveItem:
        if not state.matches(item):
            raise DriveMasterRecoveryBlocked(f"MASTER object metadata changed: {item.file_id}")
        if parent_id is not None and item.parent_id != parent_id:
            raise DriveMasterRecoveryBlocked(f"MASTER object parent changed: {item.file_id}")
        if name is not None and item.name != name:
            raise DriveMasterRecoveryBlocked(f"MASTER object name changed: {item.file_id}")
        raw = drive.download(item.file_id)
        if BlobState.from_bytes(raw) != state:
            raise DriveMasterRecoveryBlocked(f"MASTER object bytes changed: {item.file_id}")
        return item

    def _get_live(self, file_id: str) -> DriveItem | None:
        try:
            return self.drive.get(file_id, include_trashed=False)
        except DriveNotFound:
            return None

    def _root_master(self) -> DriveItem | None:
        matches = self.drive.list_children(self.binding.root_id, name=MASTER_NAME)
        if len(matches) > 1:
            raise DriveMasterRecoveryBlocked("multiple live MASTER.json objects")
        return matches[0] if matches else None

    def _exact_known(
        self,
        file_id: str,
        state: BlobState,
        *,
        parent_id: str,
        name: str,
    ) -> DriveItem | None:
        item = self._get_live(file_id)
        if item is None:
            return None
        return self._verify_exact_static(self.drive, item, state, parent_id=parent_id, name=name)

    def classify(self) -> str:
        b = self.binding
        root = self._root_master()
        old_root = self._exact_known(b.old_master_id, b.old_state, parent_id=b.root_id, name=MASTER_NAME)
        old_staged = self._exact_known(
            b.old_master_id,
            b.old_state,
            parent_id=b.transition_parent_id,
            name=b.old_name,
        )
        candidate_staged = self._exact_known(
            b.candidate_master_id,
            b.new_state,
            parent_id=b.transition_parent_id,
            name=b.candidate_name,
        )
        candidate_root = self._exact_known(
            b.candidate_master_id,
            b.new_state,
            parent_id=b.root_id,
            name=MASTER_NAME,
        )
        candidate_rejected = self._exact_known(
            b.candidate_master_id,
            b.new_state,
            parent_id=b.transition_parent_id,
            name=b.rejected_name,
        )

        candidate_any = self._get_live(b.candidate_master_id)
        old_any = self._get_live(b.old_master_id)

        if root is not None and root.file_id == b.old_master_id and old_root is not None:
            if candidate_any is None:
                return "OLD_UNPREPARED"
            if candidate_staged is not None:
                return "OLD_PREPARED"
            if candidate_rejected is not None:
                return "OLD_ROLLED_BACK"
            return "UNKNOWN"

        if root is None and old_staged is not None:
            if candidate_staged is not None:
                return "OLD_DISPLACED"
            if candidate_rejected is not None:
                return "NEW_REJECTED"
            return "UNKNOWN"

        if (
            root is not None
            and root.file_id == b.candidate_master_id
            and candidate_root is not None
            and old_staged is not None
        ):
            return "NEW"

        # A known object disappeared, moved to an unexpected place, changed bytes,
        # or an unrelated object occupies MASTER.json. Never guess through this.
        if old_any is None or (candidate_any is None and root is not old_root):
            return "UNKNOWN"
        return "UNKNOWN"

    def prepare_candidate(self, new_bytes: bytes) -> str:
        b = self.binding
        raw = bytes(new_bytes)
        if BlobState.from_bytes(raw) != b.new_state:
            raise ProtocolError("candidate MASTER bytes do not match durable binding")
        state = self.classify()
        if state in {"OLD_PREPARED", "OLD_DISPLACED", "NEW", "NEW_REJECTED", "OLD_ROLLED_BACK"}:
            return state
        if state != "OLD_UNPREPARED":
            raise DriveMasterRecoveryBlocked(f"cannot prepare MASTER candidate from {state}")
        self.drive.create_blob(
            b.transition_parent_id,
            b.candidate_name,
            raw,
            file_id=b.candidate_master_id,
            label=f"drive.master.{b.transition_id}.candidate.create",
        )
        state = self.classify()
        if state != "OLD_PREPARED":
            raise DriveMasterRecoveryBlocked("candidate preparation did not reach OLD_PREPARED")
        return state

    def publish(self) -> str:
        b = self.binding
        state = self.classify()
        if state == "NEW":
            return state
        if state not in {"OLD_PREPARED", "OLD_DISPLACED"}:
            raise DriveMasterRecoveryBlocked(f"cannot publish MASTER from {state}")

        if state == "OLD_PREPARED":
            self.drive.move_rename(
                b.old_master_id,
                b.transition_parent_id,
                b.old_name,
                label=f"drive.master.{b.transition_id}.displace_old",
            )

        state = self.classify()
        if state == "NEW":
            return state
        if state != "OLD_DISPLACED":
            raise DriveMasterRecoveryBlocked(f"MASTER old displacement reached {state}")

        if self._root_master() is not None:
            raise DriveMasterRecoveryBlocked("MASTER root unexpectedly occupied before candidate publication")
        self.drive.move_rename(
            b.candidate_master_id,
            b.root_id,
            MASTER_NAME,
            label=f"drive.master.{b.transition_id}.publish_candidate",
        )
        state = self.classify()
        if state != "NEW":
            raise DriveMasterRecoveryBlocked(f"MASTER publication reached {state}")
        return state

    def rollback(self) -> str:
        b = self.binding
        state = self.classify()
        if state in {"OLD_UNPREPARED", "OLD_PREPARED", "OLD_ROLLED_BACK"}:
            return state
        if state not in {"OLD_DISPLACED", "NEW", "NEW_REJECTED"}:
            raise DriveMasterRecoveryBlocked(f"cannot rollback MASTER from {state}")

        if state == "NEW":
            self.drive.move_rename(
                b.candidate_master_id,
                b.transition_parent_id,
                b.rejected_name,
                label=f"drive.master.{b.transition_id}.reject_candidate",
            )
            state = self.classify()

        if state in {"OLD_DISPLACED", "NEW_REJECTED"}:
            if self._root_master() is not None:
                raise DriveMasterRecoveryBlocked("MASTER root unexpectedly occupied before OLD restoration")
            self.drive.move_rename(
                b.old_master_id,
                b.root_id,
                MASTER_NAME,
                label=f"drive.master.{b.transition_id}.restore_old",
            )
            state = self.classify()

        if state not in {"OLD_PREPARED", "OLD_ROLLED_BACK"}:
            raise DriveMasterRecoveryBlocked(f"MASTER rollback reached {state}")
        return state


__all__ = [
    "DriveMasterBinding",
    "DriveMasterRecoveryBlocked",
    "DriveMasterTransition",
    "DriveMasterUnavailable",
    "MASTER_NAME",
]
