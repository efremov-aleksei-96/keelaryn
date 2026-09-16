from __future__ import annotations

from dataclasses import dataclass

from .drive_backend import DriveBackend, DriveNotFound
from .drive_bundle import DriveBundleStore, DriveTransactionBundle
from .drive_core import DriveCoreRunner, DriveCoreStatus
from .drive_discovery import (
    DriveActiveLocatorBinding,
    DriveActiveLocatorStore,
    DriveDiscoveryBlocked,
    DriveRestartDiscovery,
    LOCATOR_NAME,
)
from .protocol import ProtocolError


class DriveRuntimeBlocked(ProtocolError):
    """The process-level Drive runtime cannot safely select or clean a transaction."""


@dataclass(frozen=True)
class DriveRuntimeStatus:
    phase: str
    detail: str
    core_status: DriveCoreStatus | None = None


class DriveRuntime:
    """High-level Drive process entrypoint for new work and restart recovery.

    `DriveCoreRunner` assumes an exact bundle is already known. This layer is the
    restart boundary that creates/discovers the active locator, loads the exact
    bundle after process loss, and performs SAFE post-terminal locator cleanup.
    """

    def __init__(self, drive: DriveBackend, hub_root_id: str):
        self.drive = drive
        self.hub_root_id = hub_root_id

    def _discovery(self) -> DriveRestartDiscovery:
        try:
            return DriveRestartDiscovery.from_hub_root(self.drive, self.hub_root_id)
        except DriveDiscoveryBlocked as exc:
            raise DriveRuntimeBlocked(str(exc)) from exc

    @staticmethod
    def _same_bundle(left: DriveTransactionBundle, right: DriveTransactionBundle) -> bool:
        return left.to_bytes() == right.to_bytes()

    def prepare(self, bundle: DriveTransactionBundle) -> DriveActiveLocatorBinding:
        if bundle.hub_root_id != self.hub_root_id:
            raise DriveRuntimeBlocked("bundle Hub root does not match runtime Hub root")
        discovery = self._discovery()
        try:
            current = discovery.discover()
        except DriveDiscoveryBlocked as exc:
            raise DriveRuntimeBlocked(str(exc)) from exc

        if current.state == "READY_WITH_LOCATOR":
            if current.bundle is None or current.locator is None or not self._same_bundle(current.bundle, bundle):
                raise DriveRuntimeBlocked("another prepared/stale locator occupies control/active")
            return current.locator
        if current.state != "READY_CLEAN":
            raise DriveRuntimeBlocked(f"cannot prepare new transaction while discovery state is {current.state}")

        # Bundle is durable before locator. Locator is durable before the first
        # activation MASTER mutation. If locator creation is uncertain, no MASTER
        # mutation is attempted in this call.
        try:
            DriveBundleStore(self.drive, bundle).ensure()
            binding = DriveActiveLocatorBinding.plan(self.drive, bundle, discovery.active_parent_id)
            DriveActiveLocatorStore(self.drive, binding).ensure()
            verified = discovery.discover()
        except DriveDiscoveryBlocked as exc:
            raise DriveRuntimeBlocked(str(exc)) from exc

        if (
            verified.state != "READY_WITH_LOCATOR"
            or verified.bundle is None
            or verified.locator != binding
            or not self._same_bundle(verified.bundle, bundle)
        ):
            raise DriveRuntimeBlocked("new locator/bundle preparation did not become exactly discoverable")
        return binding

    def run_new(self, bundle: DriveTransactionBundle, *, max_steps: int = 32) -> DriveRuntimeStatus:
        self.prepare(bundle)
        status = DriveCoreRunner(self.drive, bundle).run_until_quiescent(max_steps=max_steps)
        return DriveRuntimeStatus(status.phase, status.detail, status)

    def restart(self, *, max_steps: int = 32) -> DriveRuntimeStatus:
        discovery = self._discovery()
        try:
            found = discovery.discover()
        except DriveDiscoveryBlocked as exc:
            raise DriveRuntimeBlocked(str(exc)) from exc
        if found.state == "READY_CLEAN":
            return DriveRuntimeStatus("READY_CLEAN", "no active locator and READY/SAFE MASTER", None)
        if found.bundle is None:
            raise DriveRuntimeBlocked(f"discovery state {found.state} has no transaction bundle")
        status = DriveCoreRunner(self.drive, found.bundle).run_until_quiescent(max_steps=max_steps)
        return DriveRuntimeStatus(status.phase, status.detail, status)

    @staticmethod
    def _archive_name(change_id: str) -> str:
        return f"{change_id}.ACTIVE_TRANSACTION.archived.json"

    def cleanup_ready_locator(self) -> DriveRuntimeStatus:
        discovery = self._discovery()
        try:
            found = discovery.discover()
        except DriveDiscoveryBlocked as exc:
            raise DriveRuntimeBlocked(str(exc)) from exc

        if found.state == "READY_CLEAN":
            return DriveRuntimeStatus("READY_CLEAN", "active locator already absent", None)
        if found.state != "READY_WITH_LOCATOR" or found.bundle is None or found.locator is None:
            raise DriveRuntimeBlocked(f"locator cleanup requires READY_WITH_LOCATOR, observed {found.state}")
        if found.runner_phase not in {"COMMITTED", "ROLLED_BACK", "ABORTED_SAFE"}:
            raise DriveRuntimeBlocked(
                f"locator cleanup requires terminal/aborted READY proof, observed {found.runner_phase}"
            )

        bundle = found.bundle
        locator = found.locator
        store = DriveActiveLocatorStore(self.drive, locator)
        store.verify()
        DriveBundleStore(self.drive, bundle).verify()
        archive_name = self._archive_name(bundle.change_id)
        conflicts = self.drive.list_children(bundle.bundle_parent_id, name=archive_name)
        if conflicts:
            raise DriveRuntimeBlocked("locator archive destination name already exists")

        # Fresh discovery immediately before the only cleanup mutation.
        try:
            fresh = discovery.discover()
        except DriveDiscoveryBlocked as exc:
            raise DriveRuntimeBlocked(str(exc)) from exc
        if (
            fresh.state != "READY_WITH_LOCATOR"
            or fresh.runner_phase != found.runner_phase
            or fresh.locator != locator
            or fresh.bundle is None
            or not self._same_bundle(fresh.bundle, bundle)
        ):
            raise DriveRuntimeBlocked("READY/locator state changed before cleanup commit boundary")

        self.drive.move_rename(
            locator.locator_id,
            bundle.bundle_parent_id,
            archive_name,
            label=f"drive.discovery.{bundle.change_id}.locator.archive",
        )

        try:
            archived = self.drive.get(locator.locator_id, include_trashed=False)
        except DriveNotFound as exc:
            raise DriveRuntimeBlocked("archived locator disappeared after cleanup") from exc
        if archived.parent_id != bundle.bundle_parent_id or archived.name != archive_name or archived.is_folder:
            raise DriveRuntimeBlocked("archived locator location/type mismatch")
        if self.drive.download(archived.file_id) != locator.to_bytes():
            raise DriveRuntimeBlocked("archived locator bytes changed")
        if self.drive.list_children(discovery.active_parent_id, name=LOCATOR_NAME):
            raise DriveRuntimeBlocked("active locator name remains after archive")

        final = discovery.discover()
        if final.state != "READY_CLEAN":
            raise DriveRuntimeBlocked(f"locator cleanup ended in {final.state}, expected READY_CLEAN")
        return DriveRuntimeStatus("READY_CLEAN", f"archived locator for {bundle.change_id}", None)


__all__ = ["DriveRuntime", "DriveRuntimeBlocked", "DriveRuntimeStatus"]
