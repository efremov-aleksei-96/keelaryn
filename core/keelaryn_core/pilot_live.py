from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .drive_backend import (
    FOLDER_MIME,
    DriveAlreadyExists,
    DriveBackend,
    DriveItem,
    DriveNotFound,
    DriveUncertainMutation,
)
from .pilot_drive import DrivePilotEvidence, DrivePilotImportService
from .pilot_pack import PilotPack, verify_pilot_pack
from .protocol import ProtocolError


PILOT_ROOT_PREFIX = "Keelaryn__PRIVATE_SUBSET_PILOT_ROOT_"
PILOT_HUB_PREFIX = "Keelaryn__Disposable_Acceptance_"
SENTINEL_NAME = "README.md"
SENTINEL_MIME = "text/markdown"
SENTINEL_BYTES = (
    b"KEELARYN PRIVATE SUBSET PILOT ROOT\n"
    b"DISPOSABLE TEST DATA ONLY. NEVER USE A PRODUCTION HUB AS A TARGET.\n"
)


class DrivePrivatePilotLiveBlocked(ProtocolError):
    """Fresh disposable private-pilot Drive setup cannot be proven exact."""


@dataclass(frozen=True)
class DrivePrivatePilotLiveEvidence:
    pilot: DrivePilotEvidence
    safety_root_verified: bool
    sentinel_verified: bool
    disposable_hub_verified: bool

    def to_json_value(self) -> dict[str, Any]:
        return {
            "schema": "keelaryn.private-pilot-live-evidence.v1",
            "pilot": self.pilot.to_json_value(),
            "safety_root_verified": self.safety_root_verified,
            "sentinel_verified": self.sentinel_verified,
            "disposable_hub_verified": self.disposable_hub_verified,
        }


class DrivePrivatePilotLiveService:
    """Create one fresh disposable Drive scope and import one private pilot pack.

    The service deliberately does not depend on any pre-existing acceptance root.
    It creates a new top-level safety root through the Drive ``root`` alias using a
    caller-reserved ID, publishes an exact sentinel, creates one fresh Hub beneath
    it, then delegates canonical publication to :class:`DrivePilotImportService`.

    No private source bytes are emitted in evidence. A lost mutation response is
    resolved only by the exact pre-generated ID plus fresh observation; there is no
    name-based retry or hidden mutation retry.
    """

    def __init__(self, drive: DriveBackend):
        self.drive = drive

    @staticmethod
    def _folder_exact(item: DriveItem, *, file_id: str, name: str) -> bool:
        return (
            item.file_id == file_id
            and item.name == name
            and item.mime_type == FOLDER_MIME
            and item.is_folder
            and not item.trashed
        )

    def _observe_folder(self, file_id: str, parent_id: str, name: str) -> DriveItem:
        try:
            item = self.drive.get(file_id, include_trashed=False)
        except DriveNotFound as exc:
            raise DrivePrivatePilotLiveBlocked(f"reserved disposable folder is not observable: {name}") from exc
        if not self._folder_exact(item, file_id=file_id, name=name):
            raise DrivePrivatePilotLiveBlocked(f"reserved disposable folder metadata mismatch: {name}")

        # list_children() accepts the Drive root alias just as create_folder()
        # does. This proves the exact reserved object is actually reachable from
        # the requested parent without requiring files.get('root'), which is not
        # guaranteed under drive.file scope.
        matches = self.drive.list_children(parent_id, name=name)
        exact = [candidate for candidate in matches if candidate.file_id == file_id]
        if len(exact) != 1:
            raise DrivePrivatePilotLiveBlocked(f"reserved disposable folder is not exact under parent: {name}")
        if not self._folder_exact(exact[0], file_id=file_id, name=name):
            raise DrivePrivatePilotLiveBlocked(f"listed disposable folder metadata mismatch: {name}")
        return item

    def _create_folder_exact(self, parent_id: str, name: str, *, label: str) -> DriveItem:
        file_id = self.drive.generate_ids(1)[0]
        try:
            item = self.drive.create_folder(parent_id, name, file_id=file_id, label=label)
        except (DriveUncertainMutation, DriveAlreadyExists):
            return self._observe_folder(file_id, parent_id, name)
        if not self._folder_exact(item, file_id=file_id, name=name):
            raise DrivePrivatePilotLiveBlocked(f"Drive returned invalid disposable folder: {name}")
        return self._observe_folder(file_id, parent_id, name)

    def _observe_sentinel(self, file_id: str, parent_id: str) -> DriveItem:
        try:
            item = self.drive.get(file_id, include_trashed=False)
        except DriveNotFound as exc:
            raise DrivePrivatePilotLiveBlocked("reserved pilot sentinel is not observable") from exc
        if (
            item.file_id != file_id
            or item.parent_id != parent_id
            or item.name != SENTINEL_NAME
            or item.is_folder
            or item.trashed
            or item.mime_type != SENTINEL_MIME
        ):
            raise DrivePrivatePilotLiveBlocked("pilot sentinel metadata mismatch")
        if self.drive.download(file_id) != SENTINEL_BYTES:
            raise DrivePrivatePilotLiveBlocked("pilot sentinel exact bytes mismatch")
        matches = self.drive.list_children(parent_id, name=SENTINEL_NAME)
        exact = [candidate for candidate in matches if candidate.file_id == file_id]
        if len(exact) != 1:
            raise DrivePrivatePilotLiveBlocked("pilot sentinel is not exact under safety root")
        return item

    def _create_sentinel_exact(self, parent_id: str) -> DriveItem:
        file_id = self.drive.generate_ids(1)[0]
        try:
            item = self.drive.create_blob(
                parent_id,
                SENTINEL_NAME,
                SENTINEL_BYTES,
                mime_type=SENTINEL_MIME,
                file_id=file_id,
                label="drive.private-pilot.sentinel.create",
            )
        except (DriveUncertainMutation, DriveAlreadyExists):
            return self._observe_sentinel(file_id, parent_id)
        if item.file_id != file_id:
            raise DrivePrivatePilotLiveBlocked("Drive returned wrong reserved pilot sentinel ID")
        return self._observe_sentinel(file_id, parent_id)

    def run(self, pack: PilotPack) -> DrivePrivatePilotLiveEvidence:
        pack = verify_pilot_pack(pack.root)
        root_name = f"{PILOT_ROOT_PREFIX}{pack.pilot_id}"
        hub_name = f"{PILOT_HUB_PREFIX}{pack.pilot_id}_PILOT"

        safety_root = self._create_folder_exact(
            "root",
            root_name,
            label="drive.private-pilot.root.create",
        )
        sentinel = self._create_sentinel_exact(safety_root.file_id)

        initial_children = self.drive.list_children(safety_root.file_id)
        if len(initial_children) != 1 or initial_children[0].file_id != sentinel.file_id:
            raise DrivePrivatePilotLiveBlocked("fresh pilot safety root contains unexpected material")

        hub = self._create_folder_exact(
            safety_root.file_id,
            hub_name,
            label="drive.private-pilot.hub.create",
        )
        children = self.drive.list_children(safety_root.file_id)
        if {item.file_id for item in children} != {sentinel.file_id, hub.file_id}:
            raise DrivePrivatePilotLiveBlocked("pilot safety root changed before Hub import")

        pilot = DrivePilotImportService(self.drive, hub.file_id).run(pack)
        return DrivePrivatePilotLiveEvidence(
            pilot=pilot,
            safety_root_verified=True,
            sentinel_verified=True,
            disposable_hub_verified=True,
        )


__all__ = [
    "DrivePrivatePilotLiveBlocked",
    "DrivePrivatePilotLiveEvidence",
    "DrivePrivatePilotLiveService",
    "PILOT_HUB_PREFIX",
    "PILOT_ROOT_PREFIX",
    "SENTINEL_BYTES",
    "SENTINEL_MIME",
    "SENTINEL_NAME",
]
