from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .drive_backend import DriveAlreadyExists, DriveBackend, DriveNotFound
from .drive_bundle import DriveBundleStore, DriveTransactionBundle
from .protocol import ProtocolError, canonical_json_bytes, strict_json_bytes


SCHEMA = "keelaryn.drive-consumption.v1"
NAME = "CONSUMED.json"


class DriveConsumptionBlocked(ProtocolError):
    """Durable Ready Change consumption provenance is missing or ambiguous."""


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise DriveConsumptionBlocked(f"{label}: invalid string")
    return value


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise DriveConsumptionBlocked(f"{label}: invalid sha256")
    return value


def _epoch(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise DriveConsumptionBlocked(f"{label}: invalid epoch")
    return value


@dataclass(frozen=True)
class DriveConsumptionReceipt:
    change_id: str
    change_sha256: str
    base_canonical_epoch: int
    bundle_file_id: str
    outcome: str
    completed_epoch: int

    def to_bytes(self) -> bytes:
        if self.outcome not in {"COMMITTED", "ROLLED_BACK"}:
            raise DriveConsumptionBlocked("consumption outcome must be COMMITTED or ROLLED_BACK")
        if self.completed_epoch != self.base_canonical_epoch + 1:
            raise DriveConsumptionBlocked("consumption completed_epoch must equal base epoch + 1")
        return canonical_json_bytes(
            {
                "schema": SCHEMA,
                "change_id": self.change_id,
                "change_sha256": self.change_sha256,
                "base_canonical_epoch": self.base_canonical_epoch,
                "bundle_file_id": self.bundle_file_id,
                "outcome": self.outcome,
                "completed_epoch": self.completed_epoch,
            }
        )

    @classmethod
    def from_bytes(cls, raw: bytes) -> "DriveConsumptionReceipt":
        try:
            value = strict_json_bytes(raw, label="DRIVE_CONSUMPTION")
        except ProtocolError as exc:
            raise DriveConsumptionBlocked(str(exc)) from exc
        expected = {
            "schema",
            "change_id",
            "change_sha256",
            "base_canonical_epoch",
            "bundle_file_id",
            "outcome",
            "completed_epoch",
        }
        if not isinstance(value, dict) or set(value) != expected or value["schema"] != SCHEMA:
            raise DriveConsumptionBlocked("DRIVE_CONSUMPTION: invalid root/schema")
        outcome = value["outcome"]
        if outcome not in {"COMMITTED", "ROLLED_BACK"}:
            raise DriveConsumptionBlocked("DRIVE_CONSUMPTION.outcome: invalid outcome")
        receipt = cls(
            change_id=_text(value["change_id"], "change_id"),
            change_sha256=_sha(value["change_sha256"], "change_sha256"),
            base_canonical_epoch=_epoch(value["base_canonical_epoch"], "base_canonical_epoch"),
            bundle_file_id=_text(value["bundle_file_id"], "bundle_file_id"),
            outcome=outcome,
            completed_epoch=_epoch(value["completed_epoch"], "completed_epoch"),
        )
        receipt.to_bytes()
        return receipt

    @classmethod
    def for_bundle(cls, bundle: DriveTransactionBundle, outcome: str) -> "DriveConsumptionReceipt":
        return cls(
            change_id=bundle.change_id,
            change_sha256=bundle.change_sha256,
            base_canonical_epoch=bundle.base_canonical_epoch,
            bundle_file_id=bundle.bundle_file_id,
            outcome=outcome,
            completed_epoch=bundle.base_canonical_epoch + 1,
        )


class DriveConsumptionStore:
    def __init__(self, drive: DriveBackend, bundle_parent_id: str):
        self.drive = drive
        self.bundle_parent_id = bundle_parent_id

    def read(self) -> DriveConsumptionReceipt | None:
        matches = self.drive.list_children(self.bundle_parent_id, name=NAME)
        if len(matches) > 1:
            raise DriveConsumptionBlocked("multiple CONSUMED.json receipts in one change history")
        if not matches:
            return None
        item = matches[0]
        if item.trashed or item.is_folder:
            raise DriveConsumptionBlocked("CONSUMED.json is not a live blob")
        return DriveConsumptionReceipt.from_bytes(self.drive.download(item.file_id))

    def ensure(self, bundle: DriveTransactionBundle, outcome: str) -> DriveConsumptionReceipt:
        if bundle.bundle_parent_id != self.bundle_parent_id:
            raise DriveConsumptionBlocked("consumption store parent does not match bundle parent")
        try:
            DriveBundleStore(self.drive, bundle).verify()
        except ProtocolError as exc:
            raise DriveConsumptionBlocked(f"cannot consume transaction with invalid bundle: {exc}") from exc
        expected = DriveConsumptionReceipt.for_bundle(bundle, outcome)
        existing = self.read()
        if existing is not None:
            if existing != expected:
                raise DriveConsumptionBlocked("existing consumption receipt conflicts with terminal bundle")
            return existing

        reserved = self.drive.generate_ids(1)[0]
        try:
            self.drive.create_blob(
                self.bundle_parent_id,
                NAME,
                expected.to_bytes(),
                mime_type="application/json",
                file_id=reserved,
                label=f"drive.consumption.{bundle.change_id}.create",
            )
        except DriveAlreadyExists as exc:
            raise DriveConsumptionBlocked("reserved consumption receipt ID collision") from exc

        created = self.read()
        if created != expected:
            raise DriveConsumptionBlocked("consumption receipt missing or changed after creation")
        return created


__all__ = [
    "NAME",
    "DriveConsumptionBlocked",
    "DriveConsumptionReceipt",
    "DriveConsumptionStore",
]
