from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .drive_backend import DriveAlreadyExists, DriveBackend, DriveItem, DriveNotFound
from .protocol import ProtocolError, canonical_json_bytes, strict_json_bytes, validate_postcheck


SCHEMA = "keelaryn.drive-postcheck-binding.v1"


class DrivePostcheckBlocked(ProtocolError):
    """Accepted decision state is ambiguous or a Core-owned receipt is invalid."""


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024:
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
class DrivePostcheckBinding:
    change_id: str
    change_sha256: str
    base_canonical_epoch: int
    source_parent_id: str
    source_name: str
    receipt_parent_id: str
    pass_receipt_id: str
    fail_receipt_id: str

    @property
    def pass_receipt_name(self) -> str:
        return f"{self.change_id}.PASS.postcheck.json"

    @property
    def fail_receipt_name(self) -> str:
        return f"{self.change_id}.FAIL.postcheck.json"

    @classmethod
    def plan(
        cls,
        drive: DriveBackend,
        *,
        change_id: str,
        change_sha256: str,
        base_canonical_epoch: int,
        source_parent_id: str,
        source_name: str,
        receipt_parent_id: str,
    ) -> "DrivePostcheckBinding":
        ids = drive.generate_ids(2)
        return cls(
            change_id=_text(change_id, "change_id"),
            change_sha256=_sha(change_sha256, "change_sha256"),
            base_canonical_epoch=_epoch(base_canonical_epoch, "base_canonical_epoch"),
            source_parent_id=_text(source_parent_id, "source_parent_id"),
            source_name=_text(source_name, "source_name"),
            receipt_parent_id=_text(receipt_parent_id, "receipt_parent_id"),
            pass_receipt_id=ids[0],
            fail_receipt_id=ids[1],
        )

    def to_bytes(self) -> bytes:
        if self.pass_receipt_id == self.fail_receipt_id:
            raise ProtocolError("PASS and FAIL receipt IDs must differ")
        return canonical_json_bytes(
            {
                "schema": SCHEMA,
                "change_id": self.change_id,
                "change_sha256": self.change_sha256,
                "base_canonical_epoch": self.base_canonical_epoch,
                "source_parent_id": self.source_parent_id,
                "source_name": self.source_name,
                "receipt_parent_id": self.receipt_parent_id,
                "pass_receipt_id": self.pass_receipt_id,
                "fail_receipt_id": self.fail_receipt_id,
            }
        )

    @classmethod
    def from_bytes(cls, raw: bytes) -> "DrivePostcheckBinding":
        value = strict_json_bytes(raw, label="DRIVE_POSTCHECK_BINDING")
        expected = {
            "schema",
            "change_id",
            "change_sha256",
            "base_canonical_epoch",
            "source_parent_id",
            "source_name",
            "receipt_parent_id",
            "pass_receipt_id",
            "fail_receipt_id",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ProtocolError("DRIVE_POSTCHECK_BINDING: invalid root")
        if value["schema"] != SCHEMA:
            raise ProtocolError("DRIVE_POSTCHECK_BINDING.schema: unsupported schema")
        binding = cls(
            change_id=_text(value["change_id"], "change_id"),
            change_sha256=_sha(value["change_sha256"], "change_sha256"),
            base_canonical_epoch=_epoch(value["base_canonical_epoch"], "base_canonical_epoch"),
            source_parent_id=_text(value["source_parent_id"], "source_parent_id"),
            source_name=_text(value["source_name"], "source_name"),
            receipt_parent_id=_text(value["receipt_parent_id"], "receipt_parent_id"),
            pass_receipt_id=_text(value["pass_receipt_id"], "pass_receipt_id"),
            fail_receipt_id=_text(value["fail_receipt_id"], "fail_receipt_id"),
        )
        if binding.pass_receipt_id == binding.fail_receipt_id:
            raise ProtocolError("PASS and FAIL receipt IDs must differ")
        return binding


class DrivePostcheckReceipts:
    def __init__(self, drive: DriveBackend, binding: DrivePostcheckBinding):
        self.drive = drive
        self.binding = binding

    def _get_live(self, file_id: str) -> DriveItem | None:
        try:
            return self.drive.get(file_id, include_trashed=False)
        except DriveNotFound:
            return None

    def _parse_matching(self, raw: bytes, *, expected_decision: str | None, owned: bool) -> dict[str, Any] | None:
        try:
            value = strict_json_bytes(raw, label="DRIVE_POSTCHECK")
            post = validate_postcheck(value)
        except ProtocolError:
            if owned:
                raise DrivePostcheckBlocked("Core-owned postcheck receipt is malformed")
            return None
        b = self.binding
        if (
            post["change_id"] != b.change_id
            or post["change_sha256"] != b.change_sha256
            or post["base_canonical_epoch"] != b.base_canonical_epoch
        ):
            if owned:
                raise DrivePostcheckBlocked("Core-owned postcheck receipt identity mismatch")
            return None
        if expected_decision is not None and post["decision"] != expected_decision:
            if owned:
                raise DrivePostcheckBlocked(
                    f"{expected_decision}-bound receipt contains {post['decision']} decision"
                )
            return None
        return post

    def _verify_receipt(self, item: DriveItem, *, expected_decision: str) -> dict[str, Any]:
        b = self.binding
        expected_id = b.pass_receipt_id if expected_decision == "PASS" else b.fail_receipt_id
        expected_name = b.pass_receipt_name if expected_decision == "PASS" else b.fail_receipt_name
        if (
            item.file_id != expected_id
            or item.parent_id != b.receipt_parent_id
            or item.name != expected_name
            or item.is_folder
            or item.trashed
        ):
            raise DrivePostcheckBlocked(f"{expected_decision}-bound receipt location/type mismatch")
        raw = self.drive.download(item.file_id)
        post = self._parse_matching(raw, expected_decision=expected_decision, owned=True)
        assert post is not None
        return post

    def decision(self) -> str | None:
        b = self.binding
        pass_item = self._get_live(b.pass_receipt_id)
        fail_item = self._get_live(b.fail_receipt_id)
        if pass_item is not None and fail_item is not None:
            raise DrivePostcheckBlocked("both PASS and FAIL receipt IDs exist")
        if pass_item is not None:
            self._verify_receipt(pass_item, expected_decision="PASS")
            return "PASS"
        if fail_item is not None:
            self._verify_receipt(fail_item, expected_decision="FAIL")
            return "FAIL"
        return None

    def _source_bytes(self) -> bytes | None:
        b = self.binding
        matches = self.drive.list_children(b.source_parent_id, name=b.source_name)
        if not matches:
            return None
        if len(matches) != 1:
            raise DrivePostcheckBlocked("multiple postcheck source objects")
        item = matches[0]
        if item.is_folder or item.trashed:
            return None
        return self.drive.download(item.file_id)

    def accept(self) -> str | None:
        accepted = self.decision()
        if accepted is not None:
            return accepted

        raw = self._source_bytes()
        if raw is None:
            return None
        post = self._parse_matching(raw, expected_decision=None, owned=False)
        if post is None:
            return None
        decision = post["decision"]
        b = self.binding
        if decision == "PASS":
            receipt_id = b.pass_receipt_id
            receipt_name = b.pass_receipt_name
        else:
            receipt_id = b.fail_receipt_id
            receipt_name = b.fail_receipt_name

        try:
            self.drive.create_blob(
                b.receipt_parent_id,
                receipt_name,
                raw,
                mime_type="application/json",
                file_id=receipt_id,
                label=f"drive.postcheck.{b.change_id}.{decision}.receipt.create",
            )
        except DriveAlreadyExists:
            # Observe the exact pre-bound ID. Never allocate or create the opposite
            # decision receipt as a recovery shortcut.
            pass

        accepted = self.decision()
        if accepted != decision:
            raise DrivePostcheckBlocked("accepted receipt did not preserve validated decision")
        return accepted


__all__ = [
    "DrivePostcheckBinding",
    "DrivePostcheckBlocked",
    "DrivePostcheckReceipts",
]
