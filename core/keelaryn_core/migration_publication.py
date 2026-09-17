from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from .drive_backend import DriveBackend, DriveItem
from .drive_bootstrap import DriveHubBootstrap
from .drive_discovery import LOCATOR_NAME, DriveDiscoveryBlocked, DriveRestartDiscovery
from .drive_factory import DriveHubLayout, DriveTransactionFactory, DriveTransactionFactoryBlocked
from .drive_master import MASTER_NAME, DriveMasterTransition, DriveMasterUnavailable
from .drive_service import DrivePollingService, DriveServiceBlocked
from .drive_transaction import BlobState
from .migration_common import source_file
from .migration_drive import (
    DriveMigrationPreparationBlocked,
    DriveMigrationProjectPreparation,
    DriveMigrationTopologyPreparation,
)
from .migration_pack import MigrationPackBlocked, verify_migration_pack
from .protocol import ProtocolError, canonical_json_bytes, strict_json_bytes, validate_master


class DriveMigrationPublicationBlocked(ProtocolError):
    """A verified migration pack cannot be published safely through Core."""


@dataclass(frozen=True)
class DriveMigrationPublicationEvidence:
    candidate_id: str
    pack_sha256: str
    canonical_file_count: int
    canonical_total_bytes: int
    outcome: str
    canonical_epoch: int

    def to_json_value(self) -> dict[str, Any]:
        return {
            "schema": "keelaryn.migration-publication-evidence.v1",
            "candidate_id": self.candidate_id,
            "pack_sha256": self.pack_sha256,
            "canonical_file_count": self.canonical_file_count,
            "canonical_total_bytes": self.canonical_total_bytes,
            "outcome": self.outcome,
            "canonical_epoch": self.canonical_epoch,
        }


class DriveMigrationCanonicalPublication:
    """Publish one frozen migration canonical set through the ordinary Core path.

    The service is deliberately limited to the canonical transaction. Project
    initial STATE preparation happens at untouched epoch 0, while root INDEX and
    preservation material are outside this transaction and are handled by later
    migration-specific layers. Canonical bytes are staged only as a normal Ready
    Change and are never written directly to ``canonical/`` by this service.
    """

    def __init__(self, drive: DriveBackend, hub_root_id: str):
        self.drive = drive
        self.hub_root_id = hub_root_id

    def _progress(
        self,
        phase: str,
        current: int | None = None,
        total: int | None = None,
    ) -> None:
        return None

    def _bootstrap(self) -> None:
        try:
            DriveHubBootstrap(self.drive, self.hub_root_id).run()
        except ProtocolError as exc:
            raise DriveMigrationPublicationBlocked(
                f"migration Hub bootstrap/verification failed: {exc}"
            ) from exc

    def _master(self) -> dict[str, Any]:
        try:
            _, raw = DriveMasterTransition.read_unique_master(self.drive, self.hub_root_id)
            return validate_master(strict_json_bytes(raw, label="MASTER.migration-publication"))
        except (DriveMasterUnavailable, ProtocolError) as exc:
            raise DriveMigrationPublicationBlocked(
                f"migration publication cannot resolve exact MASTER: {exc}"
            ) from exc

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

    def _active_locator_present(self) -> bool:
        controls = self.drive.list_children(self.hub_root_id, name="control")
        if len(controls) > 1:
            raise DriveMigrationPublicationBlocked("migration Hub has ambiguous control/ folder")
        if not controls:
            return False
        control = controls[0]
        if control.trashed or not control.is_folder:
            raise DriveMigrationPublicationBlocked("migration Hub control path is not a live folder")
        actives = self.drive.list_children(control.file_id, name="active")
        if len(actives) > 1:
            raise DriveMigrationPublicationBlocked("migration Hub has ambiguous control/active folder")
        if not actives:
            return False
        active = actives[0]
        if active.trashed or not active.is_folder:
            raise DriveMigrationPublicationBlocked("migration Hub control/active path is not a live folder")
        locators = self.drive.list_children(active.file_id, name=LOCATOR_NAME)
        if len(locators) > 1:
            raise DriveMigrationPublicationBlocked("migration Hub has multiple active transaction locators")
        if not locators:
            return False
        locator = locators[0]
        if locator.trashed or locator.is_folder:
            raise DriveMigrationPublicationBlocked("migration active transaction locator is not a live blob")
        return True

    def _resolve_runtime_state(self) -> tuple[DriveHubLayout, Any]:
        masters = self.drive.list_children(self.hub_root_id, name=MASTER_NAME)
        if len(masters) > 1:
            raise DriveMigrationPublicationBlocked("migration Hub has multiple root MASTER.json objects")

        # A missing MASTER with an active locator is the ordinary Core copy-on-write
        # gap. Bootstrap is not allowed to reinterpret that active transaction as a
        # partially initialized Hub.
        if masters:
            self._bootstrap()
        elif not self._active_locator_present():
            self._bootstrap()

        try:
            layout = DriveTransactionFactory(self.drive, self.hub_root_id).resolve_layout()
            discovery = DriveRestartDiscovery.from_hub_root(self.drive, self.hub_root_id).discover()
        except (DriveTransactionFactoryBlocked, DriveDiscoveryBlocked) as exc:
            raise DriveMigrationPublicationBlocked(
                f"migration runtime discovery failed: {exc}"
            ) from exc
        return layout, discovery

    def _ensure_folder(self, parent_id: str, name: str, *, label: str) -> DriveItem:
        matches = self.drive.list_children(parent_id, name=name)
        if len(matches) > 1:
            raise DriveMigrationPublicationBlocked(f"migration folder is ambiguous: {parent_id}/{name}")
        if matches:
            item = matches[0]
            if item.trashed or not item.is_folder:
                raise DriveMigrationPublicationBlocked(
                    f"migration path is not a live folder: {parent_id}/{name}"
                )
            return item
        reserved = self.drive.generate_ids(1)[0]
        self.drive.create_folder(parent_id, name, file_id=reserved, label=label)
        matches = self.drive.list_children(parent_id, name=name)
        if (
            len(matches) != 1
            or matches[0].file_id != reserved
            or matches[0].trashed
            or not matches[0].is_folder
        ):
            raise DriveMigrationPublicationBlocked(
                f"migration folder did not become exact: {parent_id}/{name}"
            )
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
            raise DriveMigrationPublicationBlocked(f"migration blob is ambiguous: {parent_id}/{name}")
        if matches:
            item = matches[0]
            if item.trashed or item.is_folder:
                raise DriveMigrationPublicationBlocked(
                    f"migration path is not a live blob: {parent_id}/{name}"
                )
            if self.drive.download(item.file_id) != raw:
                raise DriveMigrationPublicationBlocked(
                    f"migration blob bytes conflict with existing object: {parent_id}/{name}"
                )
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
        if (
            len(matches) != 1
            or matches[0].file_id != reserved
            or matches[0].trashed
            or matches[0].is_folder
        ):
            raise DriveMigrationPublicationBlocked(
                f"migration blob did not become exact: {parent_id}/{name}"
            )
        if self.drive.download(matches[0].file_id) != raw:
            raise DriveMigrationPublicationBlocked(
                f"migration blob bytes changed during publication: {parent_id}/{name}"
            )
        return matches[0]

    @staticmethod
    def _required_directories(pack) -> set[str]:
        required: set[str] = set()
        for entry in pack.canonical_outputs:
            parts = entry.target.split("/")
            for end in range(1, len(parts)):
                required.add("/".join(parts[:end]))
        return required

    def _canonical_matches(self, pack, canonical_root_id: str, *, include_payloads: bool) -> bool:
        expected_directories = self._required_directories(pack)
        expected_files = {entry.target: entry for entry in pack.canonical_outputs}
        seen_directories: set[str] = set()
        seen_files: set[str] = set()

        def walk(parent_id: str, prefix: str) -> bool:
            children = self.drive.list_children(parent_id)
            seen_names: set[str] = set()
            for item in children:
                if item.name in seen_names or item.trashed:
                    return False
                seen_names.add(item.name)
                logical = f"{prefix}/{item.name}" if prefix else item.name
                if item.is_folder:
                    if logical not in expected_directories:
                        return False
                    seen_directories.add(logical)
                    if not walk(item.file_id, logical):
                        return False
                    continue
                if not include_payloads or logical not in expected_files:
                    return False
                entry = expected_files[logical]
                raw = self.drive.download(item.file_id)
                expected = BlobState(entry.sha256, entry.size)
                if BlobState.from_bytes(raw) != expected or not expected.matches(item):
                    return False
                seen_files.add(logical)
            return True

        if not walk(canonical_root_id, ""):
            return False
        if seen_directories != expected_directories:
            return False
        return seen_files == (set(expected_files) if include_payloads else set())

    def _assert_fresh_scope(self, pack, layout: DriveHubLayout) -> None:
        if not self._canonical_matches(pack, layout.canonical_root_id, include_payloads=False):
            raise DriveMigrationPublicationBlocked(
                "migration canonical area is not the exact prepared empty topology"
            )
        changes = self.drive.list_children(layout.changes_parent_id)
        unexpected = [item for item in changes if item.name != pack.candidate_id]
        if unexpected:
            raise DriveMigrationPublicationBlocked(
                "migration changes area contains unrelated material"
            )
        if any(item.trashed or not item.is_folder for item in changes):
            raise DriveMigrationPublicationBlocked(
                "migration change container is not a live folder"
            )
        if self.drive.list_children(layout.postcheck_parent_id):
            raise DriveMigrationPublicationBlocked(
                "migration requires an empty postcheck area before Core starts"
            )

    @staticmethod
    def _change_bytes(pack) -> bytes:
        operations = []
        for entry in pack.canonical_outputs:
            operations.append(
                {
                    "operation_id": entry.operation_id,
                    "kind": "ADD",
                    "target": entry.target,
                    "old": {"state": "ABSENT"},
                    "new": {
                        "state": "PRESENT",
                        "sha256": entry.sha256,
                        "size": entry.size,
                    },
                    "prepared_path": f"prepared/{entry.operation_id}.bin",
                }
            )
        return canonical_json_bytes(
            {
                "schema": "keelaryn.change.v1",
                "change_id": pack.candidate_id,
                "base_canonical_epoch": 0,
                "operations": operations,
            }
        )

    def _prepare_ready_change(self, pack, layout: DriveHubLayout) -> None:
        if not self._initial_master(self._master()):
            raise DriveMigrationPublicationBlocked(
                "migration Ready Change preparation requires untouched READY/SAFE epoch 0"
            )
        self._assert_fresh_scope(pack, layout)

        change_folder = self._ensure_folder(
            layout.changes_parent_id,
            pack.candidate_id,
            label="drive.migration.change-folder.create",
        )
        prepared = self._ensure_folder(
            change_folder.file_id,
            "prepared",
            label="drive.migration.prepared-folder.create",
        )

        expected_prepared: set[str] = set()
        total_prepared = len(pack.canonical_outputs)
        for current, entry in enumerate(pack.canonical_outputs, start=1):
            self._progress("ready-change-prepared", current, total_prepared)
            raw = source_file(
                pack.root,
                entry.payload,
                f"migration packed canonical payload {entry.operation_id}",
            )
            if BlobState.from_bytes(raw) != BlobState(entry.sha256, entry.size):
                raise DriveMigrationPublicationBlocked(
                    f"migration packed canonical payload fingerprint changed: {entry.operation_id}"
                )
            name = f"{entry.operation_id}.bin"
            expected_prepared.add(name)
            self._ensure_blob(
                prepared.file_id,
                name,
                raw,
                mime_type="application/octet-stream",
                label=f"drive.migration.{entry.operation_id}.prepared.create",
            )
        observed_prepared = self.drive.list_children(prepared.file_id)
        if {item.name for item in observed_prepared} != expected_prepared or any(
            item.trashed or item.is_folder for item in observed_prepared
        ):
            raise DriveMigrationPublicationBlocked(
                "migration prepared/ contains missing or unexpected material"
            )

        change_raw = self._change_bytes(pack)
        self._ensure_blob(
            change_folder.file_id,
            "CHANGE.json",
            change_raw,
            mime_type="application/json",
            label="drive.migration.change.create",
        )

        try:
            refreshed = verify_migration_pack(pack.root)
        except MigrationPackBlocked as exc:
            raise DriveMigrationPublicationBlocked(
                f"migration pack changed before Ready publication: {exc}"
            ) from exc
        if refreshed.manifest_raw != pack.manifest_raw:
            raise DriveMigrationPublicationBlocked(
                "migration pack identity changed before Ready publication"
            )
        total_reverify = len(refreshed.canonical_outputs)
        for current, entry in enumerate(refreshed.canonical_outputs, start=1):
            self._progress("ready-change-reverify", current, total_reverify)
            raw = source_file(
                refreshed.root,
                entry.payload,
                f"migration refreshed canonical payload {entry.operation_id}",
            )
            staged = self.drive.list_children(
                prepared.file_id,
                name=f"{entry.operation_id}.bin",
            )
            if len(staged) != 1 or staged[0].trashed or staged[0].is_folder:
                raise DriveMigrationPublicationBlocked(
                    f"migration prepared blob disappeared before Ready: {entry.operation_id}"
                )
            if self.drive.download(staged[0].file_id) != raw:
                raise DriveMigrationPublicationBlocked(
                    f"migration prepared blob changed before Ready: {entry.operation_id}"
                )
        if not self._initial_master(self._master()) or not self._canonical_matches(
            refreshed,
            layout.canonical_root_id,
            include_payloads=False,
        ):
            raise DriveMigrationPublicationBlocked(
                "migration target changed before Ready publication"
            )

        ready_raw = canonical_json_bytes(
            {
                "schema": "keelaryn.ready.v1",
                "state": "READY_FOR_COMMIT",
                "change_id": pack.candidate_id,
                "change_sha256": sha256(change_raw).hexdigest(),
            }
        )
        self._ensure_blob(
            change_folder.file_id,
            "READY.json",
            ready_raw,
            mime_type="application/json",
            label="drive.migration.ready.create",
        )
        allowed = {"prepared", "CHANGE.json", "READY.json"}
        if {item.name for item in self.drive.list_children(change_folder.file_id)} != allowed:
            raise DriveMigrationPublicationBlocked(
                "migration change folder contains unexpected material"
            )

    def _ensure_postcheck(self, pack, layout: DriveHubLayout) -> str:
        master = self._master()
        active = master["active_change"]
        if (
            master["state"] != "ACTIVE"
            or master["canonical_read_status"] != "UNSAFE"
            or active is None
            or active["change_id"] != pack.candidate_id
            or active["base_canonical_epoch"] != 0
        ):
            raise DriveMigrationPublicationBlocked(
                "migration postcheck requires exact ACTIVE/UNSAFE candidate identity"
            )
        decision = (
            "PASS"
            if self._canonical_matches(pack, layout.canonical_root_id, include_payloads=True)
            else "FAIL"
        )
        raw = canonical_json_bytes(
            {
                "schema": "keelaryn.postcheck.v1",
                "change_id": pack.candidate_id,
                "change_sha256": active["change_sha256"],
                "base_canonical_epoch": 0,
                "decision": decision,
                "reason": (
                    "migration deterministic full canonical inventory "
                    f"{decision.lower()}"
                ),
            }
        )
        self._ensure_blob(
            layout.postcheck_parent_id,
            f"{pack.candidate_id}.json",
            raw,
            mime_type="application/json",
            label="drive.migration.postcheck.create",
        )
        return decision

    def _final_evidence(self, pack, layout: DriveHubLayout) -> DriveMigrationPublicationEvidence:
        try:
            discovery = DriveRestartDiscovery.from_hub_root(
                self.drive,
                self.hub_root_id,
            ).discover()
        except DriveDiscoveryBlocked as exc:
            raise DriveMigrationPublicationBlocked(
                f"migration final restart discovery failed: {exc}"
            ) from exc
        if discovery.state != "READY_CLEAN" or discovery.bundle is not None:
            raise DriveMigrationPublicationBlocked(
                "migration final state is not clean READY without locator"
            )

        master = self._master()
        completed = master["last_completed_change"]
        if (
            master["state"] != "READY"
            or master["canonical_read_status"] != "SAFE"
            or master["canonical_epoch"] != 1
            or master["active_change"] is not None
            or master["current_stage"] is not None
            or completed is None
            or completed["change_id"] != pack.candidate_id
            or completed["outcome"] not in {"COMMITTED", "ROLLED_BACK"}
        ):
            raise DriveMigrationPublicationBlocked(
                "migration final MASTER provenance is invalid"
            )
        outcome = completed["outcome"]
        if outcome == "COMMITTED":
            if not self._canonical_matches(pack, layout.canonical_root_id, include_payloads=True):
                raise DriveMigrationPublicationBlocked(
                    "committed migration canonical inventory does not match the private pack"
                )
        elif not self._canonical_matches(pack, layout.canonical_root_id, include_payloads=False):
            raise DriveMigrationPublicationBlocked(
                "rolled-back migration did not restore the prepared empty canonical topology"
            )

        change_folders = self.drive.list_children(
            layout.changes_parent_id,
            name=pack.candidate_id,
        )
        if (
            len(change_folders) != 1
            or change_folders[0].trashed
            or not change_folders[0].is_folder
        ):
            raise DriveMigrationPublicationBlocked(
                "migration change provenance folder is missing/ambiguous"
            )
        if self.drive.list_children(change_folders[0].file_id, name="READY.json"):
            raise DriveMigrationPublicationBlocked(
                "migration READY marker was not consumed"
            )

        return DriveMigrationPublicationEvidence(
            candidate_id=pack.candidate_id,
            pack_sha256=pack.pack_sha256,
            canonical_file_count=len(pack.canonical_outputs),
            canonical_total_bytes=pack.canonical_total_bytes,
            outcome=outcome,
            canonical_epoch=master["canonical_epoch"],
        )

    def run(
        self,
        pack_dir: str | Path,
        *,
        max_iterations: int = 8,
    ) -> DriveMigrationPublicationEvidence:
        try:
            pack = verify_migration_pack(pack_dir)
        except MigrationPackBlocked as exc:
            raise DriveMigrationPublicationBlocked(
                f"private migration pack verification failed: {exc}"
            ) from exc

        layout, discovery = self._resolve_runtime_state()
        if discovery.bundle is not None and discovery.bundle.change_id != pack.candidate_id:
            raise DriveMigrationPublicationBlocked(
                "another transaction is active in the migration target Hub"
            )

        if discovery.state == "READY_CLEAN":
            master = self._master()
            completed = master["last_completed_change"]
            if completed is not None:
                if completed["change_id"] != pack.candidate_id:
                    raise DriveMigrationPublicationBlocked(
                        "migration target Hub was already used by another change"
                    )
                self._progress("final-verification")
                return self._final_evidence(pack, layout)
            if not self._initial_master(master):
                raise DriveMigrationPublicationBlocked(
                    "migration target Hub is not untouched READY/SAFE epoch 0"
                )
            try:
                self._progress("topology")
                DriveMigrationTopologyPreparation(
                    self.drive,
                    self.hub_root_id,
                ).prepare(pack.root)
                self._progress("projects")
                DriveMigrationProjectPreparation(
                    self.drive,
                    self.hub_root_id,
                ).prepare(pack.root)
            except DriveMigrationPreparationBlocked as exc:
                raise DriveMigrationPublicationBlocked(
                    f"migration epoch-0 preparation failed: {exc}"
                ) from exc
            layout = DriveTransactionFactory(self.drive, self.hub_root_id).resolve_layout()
            self._progress("ready-change")
            self._prepare_ready_change(pack, layout)

        service = DrivePollingService(self.drive, self.hub_root_id)
        for current_iteration in range(1, max_iterations + 1):
            self._progress("core-iteration", current_iteration, max_iterations)
            try:
                status = service.run_once()
            except DriveServiceBlocked as exc:
                raise DriveMigrationPublicationBlocked(
                    f"migration Core service blocked: {exc}"
                ) from exc
            if status.phase == "WAIT_POSTCHECK":
                self._ensure_postcheck(pack, layout)
                continue
            if status.phase in {"COMMITTED", "ROLLED_BACK"}:
                continue
            if status.phase == "IDLE":
                self._progress("final-verification")
                return self._final_evidence(pack, layout)
            if status.phase in {"RECOVERY_BLOCKED", "ABORTED_SAFE"}:
                raise DriveMigrationPublicationBlocked(
                    f"migration Core stopped in {status.phase}: {status.detail}"
                )
            raise DriveMigrationPublicationBlocked(
                f"migration Core returned unexpected phase: {status.phase}"
            )
        raise DriveMigrationPublicationBlocked(
            "migration publication exceeded bounded orchestration iterations"
        )


__all__ = [
    "DriveMigrationCanonicalPublication",
    "DriveMigrationPublicationBlocked",
    "DriveMigrationPublicationEvidence",
]
