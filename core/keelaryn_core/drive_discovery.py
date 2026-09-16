from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from .drive_backend import DriveAlreadyExists, DriveBackend, DriveItem, DriveNotFound
from .drive_bundle import DriveBundleStore, DriveTransactionBundle
from .drive_master import MASTER_NAME
from .protocol import ProtocolError, strict_json_bytes, validate_master, canonical_json_bytes


SCHEMA = "keelaryn.drive-active-locator.v1"
LOCATOR_NAME = "ACTIVE_TRANSACTION.json"


class DriveDiscoveryBlocked(ProtocolError):
    """Restart discovery cannot identify one exact transaction authority."""


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
class DriveActiveLocatorBinding:
    locator_id: str
    locator_parent_id: str
    change_id: str
    change_sha256: str
    base_canonical_epoch: int
    bundle_file_id: str
    bundle_parent_id: str
    bundle_name: str
    bundle_sha256: str
    bundle_size: int

    @classmethod
    def plan(
        cls,
        drive: DriveBackend,
        bundle: DriveTransactionBundle,
        locator_parent_id: str,
    ) -> "DriveActiveLocatorBinding":
        raw = bundle.to_bytes()
        return cls(
            locator_id=drive.generate_ids(1)[0],
            locator_parent_id=_text(locator_parent_id, "locator_parent_id"),
            change_id=bundle.change_id,
            change_sha256=bundle.change_sha256,
            base_canonical_epoch=bundle.base_canonical_epoch,
            bundle_file_id=bundle.bundle_file_id,
            bundle_parent_id=bundle.bundle_parent_id,
            bundle_name=bundle.bundle_name,
            bundle_sha256=sha256(raw).hexdigest(),
            bundle_size=len(raw),
        )

    def to_bytes(self) -> bytes:
        if not isinstance(self.bundle_size, int) or isinstance(self.bundle_size, bool) or self.bundle_size < 0:
            raise ProtocolError("bundle_size: invalid size")
        return canonical_json_bytes(
            {
                "schema": SCHEMA,
                "locator_id": _text(self.locator_id, "locator_id"),
                "locator_parent_id": _text(self.locator_parent_id, "locator_parent_id"),
                "change_id": _text(self.change_id, "change_id"),
                "change_sha256": _sha(self.change_sha256, "change_sha256"),
                "base_canonical_epoch": _epoch(self.base_canonical_epoch, "base_canonical_epoch"),
                "bundle_file_id": _text(self.bundle_file_id, "bundle_file_id"),
                "bundle_parent_id": _text(self.bundle_parent_id, "bundle_parent_id"),
                "bundle_name": _text(self.bundle_name, "bundle_name"),
                "bundle_sha256": _sha(self.bundle_sha256, "bundle_sha256"),
                "bundle_size": self.bundle_size,
            }
        )

    @classmethod
    def from_bytes(cls, raw: bytes) -> "DriveActiveLocatorBinding":
        value = strict_json_bytes(raw, label="DRIVE_ACTIVE_LOCATOR")
        expected = {
            "schema",
            "locator_id",
            "locator_parent_id",
            "change_id",
            "change_sha256",
            "base_canonical_epoch",
            "bundle_file_id",
            "bundle_parent_id",
            "bundle_name",
            "bundle_sha256",
            "bundle_size",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise DriveDiscoveryBlocked("active locator has invalid root")
        if value["schema"] != SCHEMA:
            raise DriveDiscoveryBlocked("active locator schema is unsupported")
        size = value["bundle_size"]
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise DriveDiscoveryBlocked("active locator bundle_size is invalid")
        return cls(
            locator_id=_text(value["locator_id"], "locator_id"),
            locator_parent_id=_text(value["locator_parent_id"], "locator_parent_id"),
            change_id=_text(value["change_id"], "change_id"),
            change_sha256=_sha(value["change_sha256"], "change_sha256"),
            base_canonical_epoch=_epoch(value["base_canonical_epoch"], "base_canonical_epoch"),
            bundle_file_id=_text(value["bundle_file_id"], "bundle_file_id"),
            bundle_parent_id=_text(value["bundle_parent_id"], "bundle_parent_id"),
            bundle_name=_text(value["bundle_name"], "bundle_name"),
            bundle_sha256=_sha(value["bundle_sha256"], "bundle_sha256"),
            bundle_size=size,
        )


class DriveActiveLocatorStore:
    def __init__(self, drive: DriveBackend, binding: DriveActiveLocatorBinding):
        self.drive = drive
        self.binding = binding

    def _get_live(self) -> DriveItem | None:
        try:
            return self.drive.get(self.binding.locator_id, include_trashed=False)
        except DriveNotFound:
            return None

    def verify(self) -> DriveItem:
        item = self._get_live()
        if item is None:
            raise DriveDiscoveryBlocked("active locator object is missing")
        b = self.binding
        if (
            item.parent_id != b.locator_parent_id
            or item.name != LOCATOR_NAME
            or item.is_folder
            or item.trashed
        ):
            raise DriveDiscoveryBlocked("active locator identity/location/type mismatch")
        raw = self.drive.download(item.file_id)
        restored = DriveActiveLocatorBinding.from_bytes(raw)
        if restored != b or restored.locator_id != item.file_id:
            raise DriveDiscoveryBlocked("active locator bytes do not match expected binding")
        matches = self.drive.list_children(b.locator_parent_id, name=LOCATOR_NAME)
        if len(matches) != 1 or matches[0].file_id != b.locator_id:
            raise DriveDiscoveryBlocked("active locator name is not unique")
        return item

    def ensure(self) -> DriveItem:
        matches = self.drive.list_children(self.binding.locator_parent_id, name=LOCATOR_NAME)
        if len(matches) > 1:
            raise DriveDiscoveryBlocked("multiple active locator objects")
        if len(matches) == 1:
            if matches[0].file_id != self.binding.locator_id:
                raise DriveDiscoveryBlocked("control/active already contains another locator")
            return self.verify()
        raw = self.binding.to_bytes()
        try:
            self.drive.create_blob(
                self.binding.locator_parent_id,
                LOCATOR_NAME,
                raw,
                mime_type="application/json",
                file_id=self.binding.locator_id,
                label=f"drive.discovery.{self.binding.change_id}.locator.create",
            )
        except DriveAlreadyExists:
            # Reserved-ID collision is observed, never retried with a new identity.
            pass
        return self.verify()


@dataclass(frozen=True)
class DriveDiscoveryResult:
    state: str
    master_state: str
    runner_phase: str | None
    bundle: DriveTransactionBundle | None
    locator: DriveActiveLocatorBinding | None


class DriveRestartDiscovery:
    def __init__(self, drive: DriveBackend, hub_root_id: str, active_parent_id: str):
        self.drive = drive
        self.hub_root_id = _text(hub_root_id, "hub_root_id")
        self.active_parent_id = _text(active_parent_id, "active_parent_id")

    @staticmethod
    def _require_unique_folder(drive: DriveBackend, parent_id: str, name: str) -> DriveItem:
        matches = drive.list_children(parent_id, name=name)
        if len(matches) != 1:
            raise DriveDiscoveryBlocked(f"expected exactly one folder {name!r}, found {len(matches)}")
        item = matches[0]
        if not item.is_folder or item.trashed:
            raise DriveDiscoveryBlocked(f"required structural object {name!r} is not a live folder")
        return item

    @classmethod
    def from_hub_root(cls, drive: DriveBackend, hub_root_id: str) -> "DriveRestartDiscovery":
        control = cls._require_unique_folder(drive, hub_root_id, "control")
        active = cls._require_unique_folder(drive, control.file_id, "active")
        return cls(drive, hub_root_id, active.file_id)

    def _locator_item(self) -> DriveItem | None:
        matches = self.drive.list_children(self.active_parent_id, name=LOCATOR_NAME)
        if len(matches) > 1:
            raise DriveDiscoveryBlocked("multiple active locator objects")
        return matches[0] if matches else None

    def _load_locator_bundle(
        self,
        item: DriveItem,
    ) -> tuple[DriveActiveLocatorBinding, DriveTransactionBundle]:
        if item.parent_id != self.active_parent_id or item.name != LOCATOR_NAME or item.is_folder or item.trashed:
            raise DriveDiscoveryBlocked("active locator metadata is invalid")
        locator = DriveActiveLocatorBinding.from_bytes(self.drive.download(item.file_id))
        if locator.locator_id != item.file_id or locator.locator_parent_id != self.active_parent_id:
            raise DriveDiscoveryBlocked("active locator self-identity mismatch")
        try:
            bundle_item = self.drive.get(locator.bundle_file_id, include_trashed=False)
        except DriveNotFound as exc:
            raise DriveDiscoveryBlocked("locator-bound transaction bundle is missing") from exc
        if (
            bundle_item.parent_id != locator.bundle_parent_id
            or bundle_item.name != locator.bundle_name
            or bundle_item.is_folder
            or bundle_item.trashed
        ):
            raise DriveDiscoveryBlocked("locator-bound bundle metadata/location mismatch")
        raw = self.drive.download(bundle_item.file_id)
        if len(raw) != locator.bundle_size or sha256(raw).hexdigest() != locator.bundle_sha256:
            raise DriveDiscoveryBlocked("locator-bound bundle fingerprint mismatch")
        bundle = DriveTransactionBundle.from_bytes(raw)
        if (
            bundle.bundle_file_id != locator.bundle_file_id
            or bundle.bundle_parent_id != locator.bundle_parent_id
            or bundle.bundle_name != locator.bundle_name
            or bundle.change_id != locator.change_id
            or bundle.change_sha256 != locator.change_sha256
            or bundle.base_canonical_epoch != locator.base_canonical_epoch
            or bundle.hub_root_id != self.hub_root_id
        ):
            raise DriveDiscoveryBlocked("locator/bundle transaction identity mismatch")
        DriveBundleStore(self.drive, bundle).verify()
        return locator, bundle

    def _root_item(self) -> DriveItem | None:
        matches = self.drive.list_children(self.hub_root_id, name=MASTER_NAME)
        if len(matches) > 1:
            raise DriveDiscoveryBlocked("multiple root MASTER.json objects")
        return matches[0] if matches else None

    @staticmethod
    def _master_value(raw: bytes) -> dict[str, Any]:
        try:
            return validate_master(strict_json_bytes(raw, label="MASTER.discovery"))
        except ProtocolError as exc:
            raise DriveDiscoveryBlocked(f"root MASTER.json is invalid: {exc}") from exc

    @staticmethod
    def _active_identity(master: dict[str, Any]) -> tuple[str, str, int] | None:
        active = master["active_change"]
        if active is None:
            return None
        return (
            active["change_id"],
            active["change_sha256"],
            active["base_canonical_epoch"],
        )

    def discover(self) -> DriveDiscoveryResult:
        locator_item = self._locator_item()
        root = self._root_item()

        if locator_item is None:
            if root is None:
                raise DriveDiscoveryBlocked("zero-MASTER state has no active locator")
            master = self._master_value(self.drive.download(root.file_id))
            if master["state"] == "READY" and master["canonical_read_status"] == "SAFE":
                return DriveDiscoveryResult("READY_CLEAN", "READY", None, None, None)
            raise DriveDiscoveryBlocked(f"{master['state']} MASTER has no active locator")

        locator, bundle = self._load_locator_bundle(locator_item)
        # Import lazily to keep the primitive locator/bundle layer independent of
        # orchestration module import order.
        from .drive_core import DriveCoreBlocked, DriveCoreRunner

        runner = DriveCoreRunner(self.drive, bundle)
        if root is None:
            try:
                phase = runner.phase()
            except DriveCoreBlocked as exc:
                raise DriveDiscoveryBlocked(f"locator bundle cannot attribute zero-MASTER gap: {exc}") from exc
            if not phase.startswith("GAP_"):
                raise DriveDiscoveryBlocked(f"zero-MASTER state resolved to non-gap phase {phase}")
            return DriveDiscoveryResult("RECOVERABLE_GAP", "MISSING", phase, bundle, locator)

        master = self._master_value(self.drive.download(root.file_id))
        state = master["state"]
        identity = self._active_identity(master)
        if state in {"ACTIVE", "RECOVERY_BLOCKED"}:
            expected = (locator.change_id, locator.change_sha256, locator.base_canonical_epoch)
            if identity != expected:
                raise DriveDiscoveryBlocked("MASTER.active_change does not match active locator")

        try:
            phase = runner.phase()
        except DriveCoreBlocked as exc:
            raise DriveDiscoveryBlocked(f"locator bundle cannot classify root MASTER: {exc}") from exc

        if state == "READY":
            if master["canonical_read_status"] != "SAFE":
                raise DriveDiscoveryBlocked("READY MASTER is not SAFE")
            return DriveDiscoveryResult("READY_WITH_LOCATOR", "READY", phase, bundle, locator)
        if state == "ACTIVE":
            return DriveDiscoveryResult("ACTIVE", "ACTIVE", phase, bundle, locator)
        if state == "RECOVERY_BLOCKED":
            return DriveDiscoveryResult("RECOVERY_BLOCKED", "RECOVERY_BLOCKED", phase, bundle, locator)
        raise DriveDiscoveryBlocked(f"unsupported MASTER state during discovery: {state}")


__all__ = [
    "DriveActiveLocatorBinding",
    "DriveActiveLocatorStore",
    "DriveDiscoveryBlocked",
    "DriveDiscoveryResult",
    "DriveRestartDiscovery",
    "LOCATOR_NAME",
]
