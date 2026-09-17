from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from .drive_backend import DriveBackend
from .drive_bootstrap import DriveHubBootstrap
from .drive_discovery import DriveDiscoveryBlocked, DriveRestartDiscovery
from .drive_reader import DriveCanonicalReader, DriveReadBlocked
from .drive_service import DrivePollingService, DriveServiceBlocked
from .migration_common import MigrationPackBlocked, source_file
from .migration_materialization import (
    DriveMigrationMaterializationBlocked,
    DriveMigrationPreservationMaterialization,
)
from .migration_pack import verify_migration_pack
from .migration_publication import (
    DriveMigrationCanonicalPublication,
    DriveMigrationPublicationBlocked,
)
from .migration_router import (
    DriveMigrationRootIndexPublication,
    DriveMigrationRouterPublicationBlocked,
)
from .protocol import ProtocolError, canonical_json_bytes
from .reconciliation_state import DriveReconciliationStateService
from .workspace import DriveWorkspaceService
from .drive_project import DriveWorkflowBlocked


class DriveMigrationRehearsalBlocked(ProtocolError):
    """Disposable full migration rehearsal cannot prove an exact accepted target."""


@dataclass(frozen=True)
class DriveMigrationRehearsalEvidence:
    candidate_id: str
    pack_sha256: str
    canonical_epoch: int
    canonical_file_count: int
    canonical_total_bytes: int
    canonical_inventory_sha256: str
    preserved_file_count: int
    preserved_total_bytes: int
    preservation_inventory_sha256: str
    project_count: int
    reconciliation_state_sha256: str
    router_outcome: str
    root_index_sha256: str
    reader_epoch: int
    no_op_phase: str
    restart_state: str
    outcome: str

    def to_json_value(self) -> dict[str, Any]:
        return {
            "schema": "keelaryn.migration-rehearsal-evidence.v1",
            "candidate_id": self.candidate_id,
            "pack_sha256": self.pack_sha256,
            "canonical_epoch": self.canonical_epoch,
            "canonical_file_count": self.canonical_file_count,
            "canonical_total_bytes": self.canonical_total_bytes,
            "canonical_inventory_sha256": self.canonical_inventory_sha256,
            "preserved_file_count": self.preserved_file_count,
            "preserved_total_bytes": self.preserved_total_bytes,
            "preservation_inventory_sha256": self.preservation_inventory_sha256,
            "project_count": self.project_count,
            "reconciliation_state_sha256": self.reconciliation_state_sha256,
            "router_outcome": self.router_outcome,
            "root_index_sha256": self.root_index_sha256,
            "reader_epoch": self.reader_epoch,
            "no_op_phase": self.no_op_phase,
            "restart_state": self.restart_state,
            "outcome": self.outcome,
        }


class DriveMigrationDisposableRehearsal:
    """Compose the complete migration data-construction path on a disposable Hub.

    This service intentionally adds no new publication primitive.  It composes the
    already restart-safe migration layers in their required order and then performs
    acceptance-only checks:

    * canonical publication through ordinary Core (including epoch-0 preparation);
    * post-COMMITTED preservation materialization;
    * root INDEX/router publication when required by the pack;
    * exact final MASTER provenance and full canonical reader verification;
    * Workspace/Project and Reconciliation structural verification;
    * one subsequent ordinary service iteration proving IDLE; and
    * restart discovery proving READY_CLEAN with no active bundle.

    Re-running after a crash is safe because every mutating child layer recovers by
    durable Drive state.  This orchestrator itself persists no process-local stage
    marker and never treats in-memory progress as authority.

    The class is for disposable rehearsal/qualification targets.  It is not a
    production cutover mechanism and it does not select or replace a production Hub.
    """

    def __init__(self, drive: DriveBackend, hub_root_id: str):
        self.drive = drive
        self.hub_root_id = hub_root_id

    @staticmethod
    def _same_pack(initial, current) -> None:
        if (
            current.manifest_raw != initial.manifest_raw
            or current.pack_sha256 != initial.pack_sha256
            or current.candidate_id != initial.candidate_id
        ):
            raise DriveMigrationRehearsalBlocked(
                "migration private pack identity changed during disposable rehearsal"
            )

    def _verify_master(self, pack):
        try:
            bootstrap = DriveHubBootstrap(self.drive, self.hub_root_id).run()
        except ProtocolError as exc:
            raise DriveMigrationRehearsalBlocked(
                f"final Hub bootstrap/structure verification failed: {exc}"
            ) from exc
        master = bootstrap.master
        completed = master["last_completed_change"]
        if (
            master["state"] != "READY"
            or master["canonical_read_status"] != "SAFE"
            or master["canonical_epoch"] != 1
            or master["active_change"] is not None
            or master["current_stage"] is not None
            or completed is None
            or completed["change_id"] != pack.candidate_id
            or completed["outcome"] != "COMMITTED"
        ):
            raise DriveMigrationRehearsalBlocked(
                "final migration MASTER is not exact READY/SAFE epoch-1 COMMITTED candidate"
            )
        return bootstrap

    def _verify_canonical_reader(self, pack) -> tuple[int, str]:
        paths = tuple(entry.target for entry in pack.canonical_outputs)
        try:
            result = DriveCanonicalReader(self.drive, self.hub_root_id).read_paths(paths)
        except (DriveReadBlocked, ValueError) as exc:
            raise DriveMigrationRehearsalBlocked(
                f"final consistent canonical read failed: {exc}"
            ) from exc
        if result.canonical_epoch != 1 or len(result.items) != len(pack.canonical_outputs):
            raise DriveMigrationRehearsalBlocked(
                "final consistent reader did not observe exact epoch-1 migration inventory"
            )

        by_path = result.by_path()
        inventory: list[dict[str, Any]] = []
        for entry in sorted(pack.canonical_outputs, key=lambda item: item.target):
            observed = by_path.get(entry.target)
            if observed is None:
                raise DriveMigrationRehearsalBlocked(
                    f"final consistent reader missed canonical target: {entry.target}"
                )
            expected_raw = source_file(
                pack.root,
                entry.payload,
                f"migration rehearsal canonical payload {entry.operation_id}",
            )
            if (
                observed.sha256 != entry.sha256
                or observed.size != entry.size
                or observed.content != expected_raw
            ):
                raise DriveMigrationRehearsalBlocked(
                    f"final consistent reader bytes disagree with migration pack: {entry.target}"
                )
            inventory.append(
                {
                    "target": entry.target,
                    "sha256": entry.sha256,
                    "size": entry.size,
                }
            )

        raw = canonical_json_bytes(
            {
                "schema": "keelaryn.migration-rehearsal-canonical-inventory.v1",
                "candidate_id": pack.candidate_id,
                "entries": inventory,
            }
        )
        return result.canonical_epoch, sha256(raw).hexdigest()

    def _verify_workflow_structure(self, pack) -> tuple[int, str]:
        expected_states: dict[str, bytes] = {}
        for entry in pack.project_initial_states:
            expected_states[entry.project_id] = source_file(
                pack.root,
                entry.payload,
                f"migration rehearsal Project STATE {entry.project_id}",
            )

        try:
            projects = DriveWorkspaceService(self.drive, self.hub_root_id).list_projects()
            reconciliation = DriveReconciliationStateService(
                self.drive,
                self.hub_root_id,
            ).read()
        except (DriveWorkflowBlocked, ProtocolError) as exc:
            raise DriveMigrationRehearsalBlocked(
                f"final Workspace/Project/Reconciliation structure is invalid: {exc}"
            ) from exc

        observed_ids = {project.project_id for project in projects}
        if observed_ids != set(expected_states):
            raise DriveMigrationRehearsalBlocked(
                "final Workspace Project set disagrees with frozen migration authority"
            )
        for project in projects:
            if project.state_raw != expected_states[project.project_id]:
                raise DriveMigrationRehearsalBlocked(
                    f"final Project STATE disagrees with frozen migration pack: {project.project_id}"
                )
            if self.drive.list_children(project.results_folder_id):
                raise DriveMigrationRehearsalBlocked(
                    f"final migration Project results are not empty: {project.project_id}"
                )

        expected_reconciliation = DriveHubBootstrap.initial_reconciliation_state_bytes()
        if reconciliation.raw != expected_reconciliation:
            raise DriveMigrationRehearsalBlocked(
                "final Reconciliation STATE changed during migration rehearsal"
            )
        return len(projects), sha256(reconciliation.raw).hexdigest()

    def _prove_idle_and_restart(self) -> tuple[str, str]:
        try:
            idle = DrivePollingService(self.drive, self.hub_root_id).run_once()
        except DriveServiceBlocked as exc:
            raise DriveMigrationRehearsalBlocked(
                f"post-migration no-op service iteration failed: {exc}"
            ) from exc
        if idle.phase != "IDLE" or not idle.ready_clean:
            raise DriveMigrationRehearsalBlocked(
                f"post-migration service iteration is not IDLE/clean: {idle.phase}"
            )

        try:
            discovery = DriveRestartDiscovery.from_hub_root(
                self.drive,
                self.hub_root_id,
            ).discover()
        except DriveDiscoveryBlocked as exc:
            raise DriveMigrationRehearsalBlocked(
                f"post-migration restart discovery failed: {exc}"
            ) from exc
        if discovery.state != "READY_CLEAN" or discovery.bundle is not None:
            raise DriveMigrationRehearsalBlocked(
                "post-migration restart discovery is not READY_CLEAN without active bundle"
            )
        return idle.phase, discovery.state

    def run(self, pack_dir: str | Path) -> DriveMigrationRehearsalEvidence:
        try:
            pack = verify_migration_pack(pack_dir)
        except MigrationPackBlocked as exc:
            raise DriveMigrationRehearsalBlocked(
                f"private migration pack verification failed before rehearsal: {exc}"
            ) from exc

        try:
            publication = DriveMigrationCanonicalPublication(
                self.drive,
                self.hub_root_id,
            ).run(pack.root)
        except DriveMigrationPublicationBlocked as exc:
            raise DriveMigrationRehearsalBlocked(
                f"canonical migration publication failed during rehearsal: {exc}"
            ) from exc
        if publication.outcome != "COMMITTED" or publication.canonical_epoch != 1:
            raise DriveMigrationRehearsalBlocked(
                f"migration rehearsal requires COMMITTED epoch 1, observed "
                f"{publication.outcome} epoch {publication.canonical_epoch}"
            )

        try:
            preservation = DriveMigrationPreservationMaterialization(
                self.drive,
                self.hub_root_id,
            ).run(pack.root)
        except DriveMigrationMaterializationBlocked as exc:
            raise DriveMigrationRehearsalBlocked(
                f"migration preservation materialization failed during rehearsal: {exc}"
            ) from exc

        try:
            router = DriveMigrationRootIndexPublication(
                self.drive,
                self.hub_root_id,
            ).run(pack.root)
        except DriveMigrationRouterPublicationBlocked as exc:
            raise DriveMigrationRehearsalBlocked(
                f"migration root router publication failed during rehearsal: {exc}"
            ) from exc

        try:
            refreshed = verify_migration_pack(pack.root)
        except MigrationPackBlocked as exc:
            raise DriveMigrationRehearsalBlocked(
                f"private migration pack verification failed after construction: {exc}"
            ) from exc
        self._same_pack(pack, refreshed)
        pack = refreshed

        self._verify_master(pack)
        reader_epoch, canonical_inventory_sha256 = self._verify_canonical_reader(pack)
        project_count, reconciliation_sha256 = self._verify_workflow_structure(pack)
        no_op_phase, restart_state = self._prove_idle_and_restart()

        try:
            final_pack = verify_migration_pack(pack.root)
        except MigrationPackBlocked as exc:
            raise DriveMigrationRehearsalBlocked(
                f"private migration pack verification failed after acceptance checks: {exc}"
            ) from exc
        self._same_pack(pack, final_pack)
        self._verify_master(final_pack)

        return DriveMigrationRehearsalEvidence(
            candidate_id=pack.candidate_id,
            pack_sha256=pack.pack_sha256,
            canonical_epoch=publication.canonical_epoch,
            canonical_file_count=publication.canonical_file_count,
            canonical_total_bytes=publication.canonical_total_bytes,
            canonical_inventory_sha256=canonical_inventory_sha256,
            preserved_file_count=preservation.preserved_file_count,
            preserved_total_bytes=preservation.preserved_total_bytes,
            preservation_inventory_sha256=preservation.inventory_sha256,
            project_count=project_count,
            reconciliation_state_sha256=reconciliation_sha256,
            router_outcome=router.outcome,
            root_index_sha256=router.index_sha256,
            reader_epoch=reader_epoch,
            no_op_phase=no_op_phase,
            restart_state=restart_state,
            outcome="PASS",
        )


__all__ = [
    "DriveMigrationDisposableRehearsal",
    "DriveMigrationRehearsalBlocked",
    "DriveMigrationRehearsalEvidence",
]
