from __future__ import annotations

from dataclasses import dataclass

from .drive_backend import DriveBackend, DriveItem
from .drive_bundle import DriveBundleStore, DriveTransactionBundle
from .drive_core import DriveCoreRunner
from .drive_execution_rollback import DriveExecutionRollbackBinding
from .drive_ingestion import DriveChangePlanner, DriveReadyChange, DriveReadyChangeBlocked, DriveReadyChangeLoader
from .drive_master import DriveMasterTransition
from .drive_postcheck import DrivePostcheckBinding
from .drive_snapshot import DriveSnapshotPlan
from .protocol import ProtocolError, canonical_json_bytes, strict_json_bytes, validate_master


class DriveTransactionFactoryBlocked(ProtocolError):
    """A Ready Change cannot be converted into one exact Drive transaction bundle."""


@dataclass(frozen=True)
class DriveHubLayout:
    hub_root_id: str
    canonical_root_id: str
    changes_parent_id: str
    postcheck_parent_id: str
    history_root_id: str


@dataclass(frozen=True)
class DriveRecoveryLayout:
    bundle_parent_id: str
    stage_parent_id: str
    originals_parent_id: str
    rejected_parent_id: str
    snapshots_parent_id: str
    receipts_parent_id: str
    markers_parent_id: str
    transitions_parent_id: str


class DriveTransactionFactory:
    """Build or recover the immutable Drive transaction authority for one Ready Change.

    All folder creation performed here is still pre-activation preparation under a
    READY/SAFE MASTER. Deterministic names make a lost folder-create response
    re-observable without making those folders transaction authority. The immutable
    bundle and active locator become authority only in the later DriveRuntime layer.
    """

    RECOVERY_FOLDERS = (
        "stage",
        "originals",
        "rejected",
        "snapshots",
        "receipts",
        "markers",
        "master-transitions",
    )

    def __init__(self, drive: DriveBackend, hub_root_id: str):
        self.drive = drive
        self.hub_root_id = hub_root_id

    def _unique_folder(self, parent_id: str, name: str) -> DriveItem:
        matches = self.drive.list_children(parent_id, name=name)
        if len(matches) != 1:
            raise DriveTransactionFactoryBlocked(
                f"expected exactly one live folder {parent_id}/{name}, found {len(matches)}"
            )
        item = matches[0]
        if item.trashed or not item.is_folder:
            raise DriveTransactionFactoryBlocked(f"required path is not a live folder: {parent_id}/{name}")
        return item

    def _ensure_folder(self, parent_id: str, name: str, *, label: str) -> DriveItem:
        matches = self.drive.list_children(parent_id, name=name)
        if len(matches) > 1:
            raise DriveTransactionFactoryBlocked(f"duplicate Core preparation folder: {parent_id}/{name}")
        if len(matches) == 1:
            item = matches[0]
            if item.trashed or not item.is_folder:
                raise DriveTransactionFactoryBlocked(f"Core preparation path is not a live folder: {parent_id}/{name}")
            return item

        reserved = self.drive.generate_ids(1)[0]
        self.drive.create_folder(
            parent_id,
            name,
            file_id=reserved,
            label=label,
        )
        matches = self.drive.list_children(parent_id, name=name)
        if len(matches) != 1:
            raise DriveTransactionFactoryBlocked(
                f"Core preparation folder did not become uniquely observable: {parent_id}/{name}"
            )
        item = matches[0]
        if item.file_id != reserved or item.trashed or not item.is_folder:
            raise DriveTransactionFactoryBlocked(f"Core preparation folder identity mismatch: {parent_id}/{name}")
        return item

    def resolve_layout(self) -> DriveHubLayout:
        canonical = self._unique_folder(self.hub_root_id, "canonical")
        work = self._unique_folder(self.hub_root_id, "work")
        reconciliation = self._unique_folder(work.file_id, "reconciliation")
        changes = self._unique_folder(reconciliation.file_id, "changes")
        postcheck = self._unique_folder(reconciliation.file_id, "postcheck")
        history = self._unique_folder(self.hub_root_id, "history")
        return DriveHubLayout(
            hub_root_id=self.hub_root_id,
            canonical_root_id=canonical.file_id,
            changes_parent_id=changes.file_id,
            postcheck_parent_id=postcheck.file_id,
            history_root_id=history.file_id,
        )

    def _ready_master(self) -> tuple[DriveItem, bytes, dict]:
        try:
            item, raw = DriveMasterTransition.read_unique_master(self.drive, self.hub_root_id)
            master = validate_master(strict_json_bytes(raw, label="MASTER.factory"))
        except ProtocolError as exc:
            raise DriveTransactionFactoryBlocked(f"cannot resolve exact MASTER for transaction factory: {exc}") from exc
        if not (
            master["state"] == "READY"
            and master["canonical_read_status"] == "SAFE"
            and master["active_change"] is None
            and master["current_stage"] is None
        ):
            raise DriveTransactionFactoryBlocked("transaction factory requires clean READY/SAFE MASTER")
        return item, raw, master

    def _ensure_recovery_layout(self, layout: DriveHubLayout, ready: DriveReadyChange) -> DriveRecoveryLayout:
        change_root = self._ensure_folder(
            layout.history_root_id,
            ready.change_id,
            label=f"drive.factory.{ready.change_id}.history.create",
        )

        allowed = set(self.RECOVERY_FOLDERS) | {
            f"{ready.change_id}.DRIVE_BUNDLE.json",
            f"{ready.change_id}.ACTIVE_TRANSACTION.archived.json",
        }
        for child in self.drive.list_children(change_root.file_id):
            if child.name not in allowed:
                raise DriveTransactionFactoryBlocked(
                    f"unexpected material in Core recovery root {ready.change_id}: {child.name}"
                )

        folders: dict[str, DriveItem] = {}
        for name in self.RECOVERY_FOLDERS:
            folders[name] = self._ensure_folder(
                change_root.file_id,
                name,
                label=f"drive.factory.{ready.change_id}.{name}.create",
            )

        return DriveRecoveryLayout(
            bundle_parent_id=change_root.file_id,
            stage_parent_id=folders["stage"].file_id,
            originals_parent_id=folders["originals"].file_id,
            rejected_parent_id=folders["rejected"].file_id,
            snapshots_parent_id=folders["snapshots"].file_id,
            receipts_parent_id=folders["receipts"].file_id,
            markers_parent_id=folders["markers"].file_id,
            transitions_parent_id=folders["master-transitions"].file_id,
        )

    @staticmethod
    def _active_master_bytes(master: dict, ready: DriveReadyChange, *, unsafe: bool) -> bytes:
        value = dict(master)
        value["state"] = "ACTIVE"
        value["canonical_read_status"] = "UNSAFE" if unsafe else "SAFE"
        value["active_change"] = {
            "change_id": ready.change_id,
            "change_sha256": ready.change_sha256,
            "base_canonical_epoch": ready.base_canonical_epoch,
        }
        value["current_stage"] = "APPLY" if unsafe else "SNAPSHOT"
        return canonical_json_bytes(value)

    @staticmethod
    def _final_master_bytes(master: dict, ready: DriveReadyChange, outcome: str) -> bytes:
        value = dict(master)
        value["state"] = "READY"
        value["canonical_read_status"] = "SAFE"
        value["canonical_epoch"] = ready.base_canonical_epoch + 1
        value["active_change"] = None
        value["current_stage"] = None
        value["last_completed_change"] = {
            "change_id": ready.change_id,
            "change_sha256": ready.change_sha256,
            "outcome": outcome,
            "completed_epoch": ready.base_canonical_epoch + 1,
        }
        return canonical_json_bytes(value)

    def _existing_bundle(
        self,
        ready: DriveReadyChange,
        layout: DriveHubLayout,
        recovery: DriveRecoveryLayout,
    ) -> DriveTransactionBundle | None:
        name = f"{ready.change_id}.DRIVE_BUNDLE.json"
        matches = self.drive.list_children(recovery.bundle_parent_id, name=name)
        if len(matches) > 1:
            raise DriveTransactionFactoryBlocked("multiple immutable Drive bundles for one change_id")
        if not matches:
            return None
        item = matches[0]
        if item.trashed or item.is_folder:
            raise DriveTransactionFactoryBlocked("existing Drive bundle path is not a live blob")
        try:
            bundle = DriveTransactionBundle.from_bytes(self.drive.download(item.file_id))
            DriveBundleStore(self.drive, bundle).verify()
        except ProtocolError as exc:
            raise DriveTransactionFactoryBlocked(f"existing Drive bundle is invalid: {exc}") from exc
        if (
            bundle.bundle_file_id != item.file_id
            or bundle.bundle_parent_id != recovery.bundle_parent_id
            or bundle.hub_root_id != self.hub_root_id
            or bundle.change_id != ready.change_id
            or bundle.change_sha256 != ready.change_sha256
            or bundle.base_canonical_epoch != ready.base_canonical_epoch
        ):
            raise DriveTransactionFactoryBlocked("existing Drive bundle does not bind the current Ready Change")
        control = bundle.control
        if (
            control.canonical_root_id != layout.canonical_root_id
            or control.history_original_parent_id != recovery.originals_parent_id
            or control.rejected_parent_id != recovery.rejected_parent_id
            or bundle.snapshot_plan.snapshot_parent_id != recovery.snapshots_parent_id
            or bundle.postcheck_binding.source_parent_id != layout.postcheck_parent_id
            or bundle.postcheck_binding.receipt_parent_id != recovery.receipts_parent_id
            or bundle.execution_rollback_binding.marker_parent_id != recovery.markers_parent_id
            or bundle.recovery_block_binding.record_parent_id != recovery.markers_parent_id
            or bundle.master_transition_parent_id != recovery.transitions_parent_id
        ):
            raise DriveTransactionFactoryBlocked("existing Drive bundle structural IDs do not match Hub layout")
        for operation in control.operations:
            if operation.staged_parent_id is not None and operation.staged_parent_id != recovery.stage_parent_id:
                raise DriveTransactionFactoryBlocked("existing Drive bundle staged object parent mismatch")

        try:
            phase = DriveCoreRunner(self.drive, bundle).phase()
        except ProtocolError as exc:
            raise DriveTransactionFactoryBlocked(f"existing Drive bundle cannot be classified: {exc}") from exc
        if phase != "BASE_READY":
            raise DriveTransactionFactoryBlocked(
                f"Ready Change has existing bundle in non-preactivation phase {phase}; automatic replay forbidden"
            )
        return bundle

    def build_or_resume(self) -> DriveTransactionBundle | None:
        layout = self.resolve_layout()
        _, _, master = self._ready_master()
        loader = DriveReadyChangeLoader(self.drive, layout.changes_parent_id)
        try:
            ready = loader.find_one_ready()
        except DriveReadyChangeBlocked as exc:
            raise DriveTransactionFactoryBlocked(str(exc)) from exc
        if ready is None:
            return None
        if master["canonical_epoch"] != ready.base_canonical_epoch:
            raise DriveTransactionFactoryBlocked(
                f"Ready Change base epoch {ready.base_canonical_epoch} != current {master['canonical_epoch']}"
            )

        recovery = self._ensure_recovery_layout(layout, ready)
        existing = self._existing_bundle(ready, layout, recovery)
        if existing is not None:
            return existing

        planner = DriveChangePlanner(
            self.drive,
            hub_root_id=self.hub_root_id,
            canonical_root_id=layout.canonical_root_id,
            stage_parent_id=recovery.stage_parent_id,
            history_original_parent_id=recovery.originals_parent_id,
            rejected_parent_id=recovery.rejected_parent_id,
        )
        try:
            control = planner.plan(ready, loader)
        except DriveReadyChangeBlocked as exc:
            raise DriveTransactionFactoryBlocked(str(exc)) from exc

        snapshots = DriveSnapshotPlan.plan(self.drive, control, recovery.snapshots_parent_id)
        postcheck = DrivePostcheckBinding.plan(
            self.drive,
            change_id=ready.change_id,
            change_sha256=ready.change_sha256,
            base_canonical_epoch=ready.base_canonical_epoch,
            source_parent_id=layout.postcheck_parent_id,
            source_name=f"{ready.change_id}.json",
            receipt_parent_id=recovery.receipts_parent_id,
        )
        execution = DriveExecutionRollbackBinding.plan(
            self.drive,
            change_id=ready.change_id,
            change_sha256=ready.change_sha256,
            base_canonical_epoch=ready.base_canonical_epoch,
            marker_parent_id=recovery.markers_parent_id,
        )

        # Bundle planning re-reads the unique READY MASTER and refuses a stale epoch.
        try:
            bundle = DriveTransactionBundle.plan(
                self.drive,
                change_sha256=ready.change_sha256,
                base_canonical_epoch=ready.base_canonical_epoch,
                bundle_parent_id=recovery.bundle_parent_id,
                master_transition_parent_id=recovery.transitions_parent_id,
                control=control,
                snapshot_plan=snapshots,
                postcheck_binding=postcheck,
                execution_rollback_binding=execution,
                active_safe_master_bytes=self._active_master_bytes(master, ready, unsafe=False),
                active_unsafe_master_bytes=self._active_master_bytes(master, ready, unsafe=True),
                committed_master_bytes=self._final_master_bytes(master, ready, "COMMITTED"),
                rolled_back_master_bytes=self._final_master_bytes(master, ready, "ROLLED_BACK"),
            )
        except ProtocolError as exc:
            raise DriveTransactionFactoryBlocked(f"cannot build immutable Drive transaction bundle: {exc}") from exc
        return bundle


__all__ = [
    "DriveHubLayout",
    "DriveRecoveryLayout",
    "DriveTransactionFactory",
    "DriveTransactionFactoryBlocked",
]
