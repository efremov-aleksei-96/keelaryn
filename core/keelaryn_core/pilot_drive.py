from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from .drive_backend import DriveBackend, DriveItem
from .drive_bootstrap import DriveBootstrapLayout, DriveHubBootstrap
from .drive_discovery import DriveDiscoveryBlocked, DriveRestartDiscovery
from .drive_master import DriveMasterTransition, DriveMasterUnavailable
from .drive_service import DrivePollingService, DriveServiceBlocked
from .drive_transaction import BlobState
from .pilot_pack import PilotPack, PilotPackBlocked, verify_pilot_pack
from .protocol import ProtocolError, canonical_json_bytes, fingerprint_bytes, strict_json_bytes, validate_master


class DrivePilotBlocked(ProtocolError):
    """A limited real-Hub-subset pilot cannot progress safely."""


@dataclass(frozen=True)
class DrivePilotEvidence:
    pilot_id: str
    pack_sha256: str
    file_count: int
    total_bytes: int
    outcome: str
    canonical_epoch: int

    def to_json_value(self) -> dict[str, Any]:
        return {
            "schema": "keelaryn.pilot-import-evidence.v1",
            "pilot_id": self.pilot_id,
            "pack_sha256": self.pack_sha256,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "outcome": self.outcome,
            "canonical_epoch": self.canonical_epoch,
        }


class DrivePilotImportService:
    """Import one verified private pilot pack into one fresh disposable Hub.

    The pack contains a deliberately limited allowlist copied from a real-Hub
    source. This service never reads the original source: only the verified local
    pack is allowed to cross into Drive. Publication itself uses the ordinary
    Ready Change -> Core -> postcheck -> terminal cleanup protocol.

    The MVP pilot is intentionally narrower than general reconciliation:
    every selected target is a canonical-root file and the fresh pilot Hub starts
    with an empty canonical directory, so every operation is ADD.
    """

    def __init__(self, drive: DriveBackend, hub_root_id: str):
        self.drive = drive
        self.hub_root_id = hub_root_id

    def _bootstrap(self):
        try:
            return DriveHubBootstrap(self.drive, self.hub_root_id).run()
        except ProtocolError as exc:
            raise DrivePilotBlocked(f"pilot Hub bootstrap/verification failed: {exc}") from exc

    def _master(self) -> dict[str, Any]:
        try:
            _, raw = DriveMasterTransition.read_unique_master(self.drive, self.hub_root_id)
            return validate_master(strict_json_bytes(raw, label="MASTER.pilot"))
        except (DriveMasterUnavailable, ProtocolError) as exc:
            raise DrivePilotBlocked(f"pilot cannot resolve exact MASTER: {exc}") from exc

    @staticmethod
    def _initial_master(master: dict[str, Any]) -> bool:
        return (
            master["state"] == "READY"
            and master["canonical_read_status"] == "SAFE"
            and master["canonical_epoch"] == 0
            and master["active_change"] is None
            and master["current_stage"] is None
            and master["last_completed_change"] is None
        )

    def _ensure_folder(self, parent_id: str, name: str, *, label: str) -> DriveItem:
        matches = self.drive.list_children(parent_id, name=name)
        if len(matches) > 1:
            raise DrivePilotBlocked(f"pilot folder is ambiguous: {parent_id}/{name}")
        if matches:
            item = matches[0]
            if item.trashed or not item.is_folder:
                raise DrivePilotBlocked(f"pilot path is not a live folder: {parent_id}/{name}")
            return item
        reserved = self.drive.generate_ids(1)[0]
        self.drive.create_folder(parent_id, name, file_id=reserved, label=label)
        matches = self.drive.list_children(parent_id, name=name)
        if len(matches) != 1 or matches[0].file_id != reserved or matches[0].trashed or not matches[0].is_folder:
            raise DrivePilotBlocked(f"pilot folder did not become exact: {parent_id}/{name}")
        return matches[0]

    def _ensure_blob(
        self,
        parent_id: str,
        name: str,
        raw: bytes,
        *,
        mime_type: str,
        label: str,
    ) -> DriveItem:
        matches = self.drive.list_children(parent_id, name=name)
        if len(matches) > 1:
            raise DrivePilotBlocked(f"pilot blob is ambiguous: {parent_id}/{name}")
        if matches:
            item = matches[0]
            if item.trashed or item.is_folder:
                raise DrivePilotBlocked(f"pilot path is not a live blob: {parent_id}/{name}")
            if self.drive.download(item.file_id) != raw:
                raise DrivePilotBlocked(f"pilot blob bytes conflict with existing object: {parent_id}/{name}")
            return item
        reserved = self.drive.generate_ids(1)[0]
        self.drive.create_blob(
            parent_id,
            name,
            raw,
            mime_type=mime_type,
            file_id=reserved,
            label=label,
        )
        matches = self.drive.list_children(parent_id, name=name)
        if len(matches) != 1 or matches[0].file_id != reserved or matches[0].trashed or matches[0].is_folder:
            raise DrivePilotBlocked(f"pilot blob did not become exact: {parent_id}/{name}")
        if self.drive.download(matches[0].file_id) != raw:
            raise DrivePilotBlocked(f"pilot blob bytes changed during publication: {parent_id}/{name}")
        return matches[0]

    def _assert_fresh_scope(self, layout: DriveBootstrapLayout, pilot_id: str) -> None:
        if self.drive.list_children(layout.canonical_root_id):
            raise DrivePilotBlocked("pilot requires an empty canonical directory")
        changes = self.drive.list_children(layout.changes_parent_id)
        unexpected = [item for item in changes if item.name != pilot_id]
        if unexpected:
            raise DrivePilotBlocked("pilot changes area contains unrelated material")
        if any(item.trashed or not item.is_folder for item in changes):
            raise DrivePilotBlocked("pilot change container is not a live folder")
        if self.drive.list_children(layout.postcheck_parent_id):
            raise DrivePilotBlocked("pilot requires an empty postcheck area before Core starts")

    def _change_bytes(self, pack: PilotPack) -> bytes:
        operations = []
        for entry in pack.entries:
            operations.append(
                {
                    "operation_id": entry.operation_id,
                    "kind": "ADD",
                    "target": entry.target,
                    "old": {"state": "ABSENT"},
                    "new": {"state": "PRESENT", "sha256": entry.sha256, "size": entry.size},
                    "prepared_path": f"prepared/{entry.operation_id}.bin",
                }
            )
        return canonical_json_bytes(
            {
                "schema": "keelaryn.change.v1",
                "change_id": pack.pilot_id,
                "base_canonical_epoch": 0,
                "operations": operations,
            }
        )

    def _prepare_ready_change(self, pack: PilotPack, layout: DriveBootstrapLayout) -> None:
        master = self._master()
        if not self._initial_master(master):
            raise DrivePilotBlocked("pilot Ready Change preparation requires untouched READY/SAFE epoch 0")
        self._assert_fresh_scope(layout, pack.pilot_id)

        change_folder = self._ensure_folder(
            layout.changes_parent_id,
            pack.pilot_id,
            label="drive.pilot.change-folder.create",
        )
        prepared = self._ensure_folder(
            change_folder.file_id,
            "prepared",
            label="drive.pilot.prepared-folder.create",
        )

        expected_prepared: set[str] = set()
        for entry in pack.entries:
            raw = pack.payload_bytes(entry)
            name = f"{entry.operation_id}.bin"
            expected_prepared.add(name)
            self._ensure_blob(
                prepared.file_id,
                name,
                raw,
                mime_type="application/octet-stream",
                label=f"drive.pilot.{entry.operation_id}.prepared.create",
            )
        observed_prepared = self.drive.list_children(prepared.file_id)
        if {item.name for item in observed_prepared} != expected_prepared or any(
            item.trashed or item.is_folder for item in observed_prepared
        ):
            raise DrivePilotBlocked("pilot prepared/ contains missing or unexpected material")

        change_raw = self._change_bytes(pack)
        self._ensure_blob(
            change_folder.file_id,
            "CHANGE.json",
            change_raw,
            mime_type="application/json",
            label="drive.pilot.change.create",
        )

        # Fresh private-pack verification immediately before Ready publication.
        refreshed = verify_pilot_pack(pack.root)
        if refreshed.manifest_raw != pack.manifest_raw:
            raise DrivePilotBlocked("pilot pack identity changed before Ready publication")
        for entry in refreshed.entries:
            raw = refreshed.payload_bytes(entry)
            staged = self.drive.list_children(prepared.file_id, name=f"{entry.operation_id}.bin")
            if len(staged) != 1 or staged[0].trashed or staged[0].is_folder:
                raise DrivePilotBlocked(f"pilot prepared blob disappeared before Ready: {entry.operation_id}")
            if self.drive.download(staged[0].file_id) != raw:
                raise DrivePilotBlocked(f"pilot prepared blob changed before Ready: {entry.operation_id}")
        if not self._initial_master(self._master()) or self.drive.list_children(layout.canonical_root_id):
            raise DrivePilotBlocked("pilot Hub changed before Ready publication")

        ready_raw = canonical_json_bytes(
            {
                "schema": "keelaryn.ready.v1",
                "state": "READY_FOR_COMMIT",
                "change_id": pack.pilot_id,
                "change_sha256": sha256(change_raw).hexdigest(),
            }
        )
        self._ensure_blob(
            change_folder.file_id,
            "READY.json",
            ready_raw,
            mime_type="application/json",
            label="drive.pilot.ready.create",
        )
        allowed = {"prepared", "CHANGE.json", "READY.json"}
        if {item.name for item in self.drive.list_children(change_folder.file_id)} != allowed:
            raise DrivePilotBlocked("pilot change folder contains unexpected material")

    def _canonical_matches(self, pack: PilotPack, canonical_root_id: str) -> bool:
        try:
            refreshed = verify_pilot_pack(pack.root)
        except PilotPackBlocked as exc:
            raise DrivePilotBlocked(f"private pilot pack no longer verifies: {exc}") from exc
        children = self.drive.list_children(canonical_root_id)
        expected = {entry.target: entry for entry in refreshed.entries}
        if len(children) != len(expected):
            return False
        by_name: dict[str, DriveItem] = {}
        for item in children:
            if item.trashed or item.is_folder or item.name in by_name or item.name not in expected:
                return False
            by_name[item.name] = item
        if set(by_name) != set(expected):
            return False
        for target, entry in expected.items():
            item = by_name[target]
            raw = self.drive.download(item.file_id)
            expected_state = BlobState(entry.sha256, entry.size)
            if BlobState.from_bytes(raw) != expected_state or not expected_state.matches(item):
                return False
        return True

    def _ensure_postcheck(self, pack: PilotPack, layout: DriveBootstrapLayout) -> str:
        master = self._master()
        active = master["active_change"]
        if (
            master["state"] != "ACTIVE"
            or master["canonical_read_status"] != "UNSAFE"
            or active is None
            or active["change_id"] != pack.pilot_id
            or active["base_canonical_epoch"] != 0
        ):
            raise DrivePilotBlocked("pilot postcheck requires exact ACTIVE/UNSAFE pilot identity")
        decision = "PASS" if self._canonical_matches(pack, layout.canonical_root_id) else "FAIL"
        raw = canonical_json_bytes(
            {
                "schema": "keelaryn.postcheck.v1",
                "change_id": pack.pilot_id,
                "change_sha256": active["change_sha256"],
                "base_canonical_epoch": 0,
                "decision": decision,
                "reason": f"limited real-Hub-subset pilot deterministic exact-byte {decision.lower()}",
            }
        )
        self._ensure_blob(
            layout.postcheck_parent_id,
            f"{pack.pilot_id}.json",
            raw,
            mime_type="application/json",
            label="drive.pilot.postcheck.create",
        )
        return decision

    def _final_evidence(self, pack: PilotPack, layout: DriveBootstrapLayout) -> DrivePilotEvidence:
        try:
            discovery = DriveRestartDiscovery.from_hub_root(self.drive, self.hub_root_id).discover()
        except DriveDiscoveryBlocked as exc:
            raise DrivePilotBlocked(f"pilot final restart discovery failed: {exc}") from exc
        if discovery.state != "READY_CLEAN" or discovery.bundle is not None:
            raise DrivePilotBlocked("pilot final state is not clean READY without locator")
        master = self._master()
        completed = master["last_completed_change"]
        if (
            master["state"] != "READY"
            or master["canonical_read_status"] != "SAFE"
            or master["canonical_epoch"] != 1
            or master["active_change"] is not None
            or master["current_stage"] is not None
            or completed is None
            or completed["change_id"] != pack.pilot_id
            or completed["outcome"] not in {"COMMITTED", "ROLLED_BACK"}
        ):
            raise DrivePilotBlocked("pilot final MASTER provenance is invalid")
        outcome = completed["outcome"]
        if outcome == "COMMITTED":
            if not self._canonical_matches(pack, layout.canonical_root_id):
                raise DrivePilotBlocked("committed pilot canonical bytes do not match the private pack")
        elif self.drive.list_children(layout.canonical_root_id):
            raise DrivePilotBlocked("rolled-back pilot did not restore empty canonical state")

        change_folders = self.drive.list_children(layout.changes_parent_id, name=pack.pilot_id)
        if len(change_folders) != 1 or change_folders[0].trashed or not change_folders[0].is_folder:
            raise DrivePilotBlocked("pilot change provenance folder is missing/ambiguous")
        if self.drive.list_children(change_folders[0].file_id, name="READY.json"):
            raise DrivePilotBlocked("pilot READY marker was not consumed")

        return DrivePilotEvidence(
            pilot_id=pack.pilot_id,
            pack_sha256=pack.pack_sha256,
            file_count=len(pack.entries),
            total_bytes=pack.total_bytes,
            outcome=outcome,
            canonical_epoch=master["canonical_epoch"],
        )

    def run(self, pack: PilotPack, *, max_iterations: int = 8) -> DrivePilotEvidence:
        try:
            pack = verify_pilot_pack(pack.root)
        except PilotPackBlocked as exc:
            raise DrivePilotBlocked(f"private pilot pack verification failed: {exc}") from exc

        bootstrap = self._bootstrap()
        layout = bootstrap.layout
        try:
            discovery = DriveRestartDiscovery.from_hub_root(self.drive, self.hub_root_id).discover()
        except DriveDiscoveryBlocked as exc:
            raise DrivePilotBlocked(f"pilot restart discovery failed: {exc}") from exc

        if discovery.bundle is not None and discovery.bundle.change_id != pack.pilot_id:
            raise DrivePilotBlocked("another transaction is active in the disposable pilot Hub")

        if discovery.state == "READY_CLEAN":
            master = bootstrap.master
            completed = master["last_completed_change"]
            if completed is not None:
                if completed["change_id"] != pack.pilot_id:
                    raise DrivePilotBlocked("disposable pilot Hub was already used by another change")
                return self._final_evidence(pack, layout)
            if not self._initial_master(master):
                raise DrivePilotBlocked("disposable pilot Hub is not untouched READY/SAFE epoch 0")
            self._prepare_ready_change(pack, layout)

        service = DrivePollingService(self.drive, self.hub_root_id)
        for _ in range(max_iterations):
            try:
                status = service.run_once()
            except DriveServiceBlocked as exc:
                raise DrivePilotBlocked(f"pilot Core service blocked: {exc}") from exc
            if status.phase == "WAIT_POSTCHECK":
                self._ensure_postcheck(pack, layout)
                continue
            if status.phase in {"COMMITTED", "ROLLED_BACK"}:
                continue
            if status.phase == "IDLE":
                return self._final_evidence(pack, layout)
            if status.phase in {"RECOVERY_BLOCKED", "ABORTED_SAFE"}:
                raise DrivePilotBlocked(f"pilot Core stopped in {status.phase}: {status.detail}")
            raise DrivePilotBlocked(f"pilot Core returned unexpected phase: {status.phase}")
        raise DrivePilotBlocked("pilot import exceeded bounded orchestration iterations")


__all__ = ["DrivePilotBlocked", "DrivePilotEvidence", "DrivePilotImportService"]
