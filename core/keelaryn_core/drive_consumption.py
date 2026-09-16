from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from .drive_backend import DriveBackend, DriveItem
from .drive_bundle import DriveBundleStore, DriveTransactionBundle
from .drive_core import DriveCoreRunner
from .protocol import ProtocolError, strict_json_bytes, validate_change, validate_ready


CHANGE_NAME = "CHANGE.json"
READY_NAME = "READY.json"


class DriveConsumptionBlocked(ProtocolError):
    """A completed transaction's external Ready marker cannot be consumed safely."""


@dataclass(frozen=True)
class DriveConsumptionStatus:
    state: str
    detail: str
    archive_file_id: str | None = None


class DriveReadyConsumption:
    """Move only an exact consumed READY.json marker into durable history.

    Reconciliation work is external to Core recovery authority after claim. Core
    therefore never deletes or rewrites the change folder or prepared blobs here.
    When the original READY marker is still exact after COMMITTED/ROLLED_BACK, it
    is moved into the already-bound per-change history folder. If the source work
    disappeared, no cleanup is required. If the marker or CHANGE identity changed,
    Core leaves it untouched and fails closed.
    """

    def __init__(self, drive: DriveBackend, changes_parent_id: str):
        self.drive = drive
        self.changes_parent_id = changes_parent_id

    @staticmethod
    def archive_name(change_id: str) -> str:
        return f"{change_id}.READY.consumed.json"

    def _change_folder(self, change_id: str) -> DriveItem | None:
        matches = self.drive.list_children(self.changes_parent_id, name=change_id)
        if len(matches) > 1:
            raise DriveConsumptionBlocked(f"multiple Reconciliation change folders for {change_id}")
        if not matches:
            return None
        folder = matches[0]
        if folder.trashed or not folder.is_folder:
            raise DriveConsumptionBlocked(f"Reconciliation change path is not a live folder: {change_id}")
        return folder

    def _single_blob(self, parent_id: str, name: str) -> DriveItem | None:
        matches = self.drive.list_children(parent_id, name=name)
        if len(matches) > 1:
            raise DriveConsumptionBlocked(f"multiple {name} objects in {parent_id}")
        if not matches:
            return None
        item = matches[0]
        if item.trashed or item.is_folder:
            raise DriveConsumptionBlocked(f"{name} in {parent_id} is not a live blob")
        return item

    def _verify_archived_ready(self, bundle: DriveTransactionBundle, item: DriveItem) -> bytes:
        if item.parent_id != bundle.bundle_parent_id or item.name != self.archive_name(bundle.change_id):
            raise DriveConsumptionBlocked("consumed READY archive location mismatch")
        raw = self.drive.download(item.file_id)
        try:
            ready = validate_ready(strict_json_bytes(raw, label="READY.consumed"))
        except ProtocolError as exc:
            raise DriveConsumptionBlocked(str(exc)) from exc
        if ready["change_id"] != bundle.change_id or ready["change_sha256"] != bundle.change_sha256:
            raise DriveConsumptionBlocked("consumed READY archive does not bind terminal bundle")
        return raw

    def _verify_source_ready(self, bundle: DriveTransactionBundle, folder: DriveItem) -> tuple[DriveItem, bytes]:
        change_item = self._single_blob(folder.file_id, CHANGE_NAME)
        ready_item = self._single_blob(folder.file_id, READY_NAME)
        if change_item is None or ready_item is None:
            raise DriveConsumptionBlocked("source Ready Change is incomplete during consumption")
        change_raw = self.drive.download(change_item.file_id)
        ready_raw = self.drive.download(ready_item.file_id)
        try:
            change = validate_change(strict_json_bytes(change_raw, label="CHANGE.consume"))
            ready = validate_ready(strict_json_bytes(ready_raw, label="READY.consume"))
        except ProtocolError as exc:
            raise DriveConsumptionBlocked(str(exc)) from exc
        if (
            change["change_id"] != bundle.change_id
            or change["base_canonical_epoch"] != bundle.base_canonical_epoch
            or sha256(change_raw).hexdigest() != bundle.change_sha256
            or ready["change_id"] != bundle.change_id
            or ready["change_sha256"] != bundle.change_sha256
        ):
            raise DriveConsumptionBlocked("source Ready Change no longer matches terminal bundle")
        return ready_item, ready_raw

    def _require_terminal(self, bundle: DriveTransactionBundle) -> str:
        try:
            DriveBundleStore(self.drive, bundle).verify()
            phase = DriveCoreRunner(self.drive, bundle).phase()
        except ProtocolError as exc:
            raise DriveConsumptionBlocked(f"cannot prove terminal bundle: {exc}") from exc
        if phase not in {"COMMITTED", "ROLLED_BACK"}:
            raise DriveConsumptionBlocked(f"Ready marker consumption requires terminal READY, observed {phase}")
        return phase

    def consume(self, bundle: DriveTransactionBundle) -> DriveConsumptionStatus:
        self._require_terminal(bundle)
        archive_name = self.archive_name(bundle.change_id)
        archived = self._single_blob(bundle.bundle_parent_id, archive_name)
        source_folder = self._change_folder(bundle.change_id)
        source_ready = None if source_folder is None else self._single_blob(source_folder.file_id, READY_NAME)

        if archived is not None:
            self._verify_archived_ready(bundle, archived)
            if source_ready is not None:
                raise DriveConsumptionBlocked("both source and archived READY markers exist")
            return DriveConsumptionStatus("CONSUMED", "exact READY marker already archived", archived.file_id)

        if source_folder is None or source_ready is None:
            return DriveConsumptionStatus("SOURCE_ABSENT", "external READY marker is already absent", None)

        ready_item, ready_raw = self._verify_source_ready(bundle, source_folder)

        # Freshly prove both terminal authority and exact source marker immediately
        # before the only mutation in this cleanup transaction.
        self._require_terminal(bundle)
        fresh_folder = self._change_folder(bundle.change_id)
        if fresh_folder is None or fresh_folder.file_id != source_folder.file_id:
            raise DriveConsumptionBlocked("source Ready Change folder changed before consumption boundary")
        fresh_item, fresh_raw = self._verify_source_ready(bundle, fresh_folder)
        if fresh_item.file_id != ready_item.file_id or fresh_raw != ready_raw:
            raise DriveConsumptionBlocked("source READY identity/bytes changed before consumption boundary")
        if self._single_blob(bundle.bundle_parent_id, archive_name) is not None:
            raise DriveConsumptionBlocked("READY archive appeared before consumption boundary")

        self.drive.move_rename(
            ready_item.file_id,
            bundle.bundle_parent_id,
            archive_name,
            label=f"drive.consumption.{bundle.change_id}.ready.archive",
        )

        archived = self._single_blob(bundle.bundle_parent_id, archive_name)
        if archived is None or archived.file_id != ready_item.file_id:
            raise DriveConsumptionBlocked("consumed READY marker missing after archive")
        if self._verify_archived_ready(bundle, archived) != ready_raw:
            raise DriveConsumptionBlocked("consumed READY bytes changed during archive")
        remaining = self._change_folder(bundle.change_id)
        if remaining is not None and self._single_blob(remaining.file_id, READY_NAME) is not None:
            raise DriveConsumptionBlocked("source READY marker remains after archive")
        return DriveConsumptionStatus("CONSUMED", "archived exact consumed READY marker", archived.file_id)


__all__ = [
    "DriveConsumptionBlocked",
    "DriveConsumptionStatus",
    "DriveReadyConsumption",
]
