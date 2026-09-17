from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from .drive_backend import DriveBackend, DriveNotFound
from .drive_bootstrap import DriveHubBootstrap, INDEX_NAME
from .drive_discovery import DriveDiscoveryBlocked, DriveRestartDiscovery
from .drive_master import DriveMasterTransition, DriveMasterUnavailable
from .drive_reader import DriveCanonicalReader, DriveReadBlocked
from .drive_transaction import BlobState
from .migration_common import MigrationPackBlocked, small_file, source_file
from .migration_freeze import verify_migration_candidate_freeze
from .migration_materialization import (
    DriveMigrationMaterializationBlocked,
    DriveMigrationPreservationMaterialization,
)
from .migration_pack import verify_migration_pack
from .migration_production_qualification import (
    STAGING_ROOT_NAME,
    STAGING_SENTINEL_BYTES,
    STAGING_SENTINEL_NAME,
    TARGET_AUTHORITY_SCHEMA,
    TARGET_EVIDENCE_SCHEMA,
    TARGET_PREFIX,
)
from .protocol import ProtocolError, canonical_json_bytes, strict_json_bytes, validate_master
from .reconciliation_state import DriveReconciliationStateService
from .workspace import DriveWorkspaceService
from .drive_project import DriveWorkflowBlocked


POST_CUTOVER_EVIDENCE_SCHEMA = "keelaryn.migration-post-cutover-read-only-acceptance.v1"


class DriveMigrationPostCutoverAcceptanceBlocked(ProtocolError):
    """Read-only production acceptance cannot prove one exact selected migrated Hub."""


def _sha(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise DriveMigrationPostCutoverAcceptanceBlocked(f"{label}: invalid SHA-256")
    return value


def _oid(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise DriveMigrationPostCutoverAcceptanceBlocked(f"{label}: invalid Git object ID")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise DriveMigrationPostCutoverAcceptanceBlocked(f"{label}: invalid string")
    return value


def _count(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise DriveMigrationPostCutoverAcceptanceBlocked(f"{label}: invalid non-negative integer")
    return value


def _strict_authority(raw: bytes) -> dict[str, Any]:
    try:
        value = strict_json_bytes(raw, label="MIGRATION_PRODUCTION_TARGET_AUTHORITY.acceptance")
    except ProtocolError as exc:
        raise DriveMigrationPostCutoverAcceptanceBlocked(str(exc)) from exc
    expected = {
        "schema",
        "candidate_id",
        "pack_sha256",
        "staging_root_id",
        "target_id",
        "target_name",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise DriveMigrationPostCutoverAcceptanceBlocked(
            "production target authority has invalid keys"
        )
    if value["schema"] != TARGET_AUTHORITY_SCHEMA:
        raise DriveMigrationPostCutoverAcceptanceBlocked(
            "production target authority schema mismatch"
        )
    _text(value["candidate_id"], "production target authority candidate_id")
    _sha(value["pack_sha256"], "production target authority pack_sha256")
    _text(value["staging_root_id"], "production target authority staging_root_id")
    _text(value["target_id"], "production target authority target_id")
    _text(value["target_name"], "production target authority target_name")
    if raw != canonical_json_bytes(value):
        raise DriveMigrationPostCutoverAcceptanceBlocked(
            "production target authority is not canonical JSON bytes"
        )
    return value


def _strict_qualification(raw: bytes) -> dict[str, Any]:
    try:
        value = strict_json_bytes(raw, label="MIGRATION_PRODUCTION_QUALIFICATION.acceptance")
    except ProtocolError as exc:
        raise DriveMigrationPostCutoverAcceptanceBlocked(str(exc)) from exc
    expected = {
        "schema",
        "candidate_id",
        "pack_sha256",
        "source_commit",
        "source_tree",
        "source_manifest_sha256",
        "mapping_manifest_sha256",
        "frozen_canonical_inventory_sha256",
        "frozen_project_state_inventory_sha256",
        "frozen_preservation_inventory_sha256",
        "frozen_root_index_sha256",
        "target_identity_sha256",
        "staging_identity_sha256",
        "canonical_epoch",
        "canonical_file_count",
        "canonical_total_bytes",
        "canonical_inventory_sha256",
        "preserved_file_count",
        "preserved_total_bytes",
        "preservation_inventory_sha256",
        "project_count",
        "reconciliation_state_sha256",
        "router_outcome",
        "root_index_sha256",
        "reader_epoch",
        "no_op_phase",
        "restart_state",
        "outcome",
        "cutover_authorized",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise DriveMigrationPostCutoverAcceptanceBlocked(
            "production qualification evidence has invalid keys"
        )
    if value["schema"] != TARGET_EVIDENCE_SCHEMA:
        raise DriveMigrationPostCutoverAcceptanceBlocked(
            "production qualification evidence schema mismatch"
        )
    _text(value["candidate_id"], "qualification candidate_id")
    for key in (
        "pack_sha256",
        "source_manifest_sha256",
        "mapping_manifest_sha256",
        "frozen_canonical_inventory_sha256",
        "frozen_project_state_inventory_sha256",
        "frozen_preservation_inventory_sha256",
        "target_identity_sha256",
        "staging_identity_sha256",
        "canonical_inventory_sha256",
        "preservation_inventory_sha256",
        "reconciliation_state_sha256",
        "root_index_sha256",
    ):
        _sha(value[key], f"qualification {key}")
    if value["frozen_root_index_sha256"] is not None:
        _sha(value["frozen_root_index_sha256"], "qualification frozen_root_index_sha256")
    _oid(value["source_commit"], "qualification source_commit")
    _oid(value["source_tree"], "qualification source_tree")
    for key in (
        "canonical_epoch",
        "canonical_file_count",
        "canonical_total_bytes",
        "preserved_file_count",
        "preserved_total_bytes",
        "project_count",
        "reader_epoch",
    ):
        _count(value[key], f"qualification {key}")
    if value["router_outcome"] not in {"COMMITTED", "NOT_REQUIRED"}:
        raise DriveMigrationPostCutoverAcceptanceBlocked(
            "production qualification router outcome is invalid"
        )
    if value["no_op_phase"] != "IDLE" or value["restart_state"] != "READY_CLEAN":
        raise DriveMigrationPostCutoverAcceptanceBlocked(
            "production qualification did not record IDLE/READY_CLEAN"
        )
    if value["outcome"] != "TARGET_QUALIFICATION_PASS" or value["cutover_authorized"] is not False:
        raise DriveMigrationPostCutoverAcceptanceBlocked(
            "production qualification evidence is not exact pre-cutover PASS"
        )
    if raw != canonical_json_bytes(value):
        raise DriveMigrationPostCutoverAcceptanceBlocked(
            "production qualification evidence is not canonical JSON bytes"
        )
    return value


@dataclass(frozen=True)
class DriveMigrationPostCutoverAcceptanceEvidence:
    candidate_id: str
    pack_sha256: str
    source_commit: str
    source_tree: str
    selector_identity_sha256: str
    target_identity_sha256: str
    staging_identity_sha256: str
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
    restart_state: str
    outcome: str

    def to_json_value(self) -> dict[str, Any]:
        return {
            "schema": POST_CUTOVER_EVIDENCE_SCHEMA,
            "candidate_id": self.candidate_id,
            "pack_sha256": self.pack_sha256,
            "source_commit": self.source_commit,
            "source_tree": self.source_tree,
            "selector_identity_sha256": self.selector_identity_sha256,
            "target_identity_sha256": self.target_identity_sha256,
            "staging_identity_sha256": self.staging_identity_sha256,
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
            "restart_state": self.restart_state,
            "outcome": self.outcome,
            "drive_mutations_performed": False,
            "hub_cutover_accept_allowed": True,
        }


class DriveMigrationPostCutoverReadOnlyAcceptance:
    """Fresh read-only acceptance for the Hub currently selected after cutover apply.

    The service intentionally has no writer/poller/bootstrap dependency and performs
    no Drive mutation. It binds the selected Hub identity to the private target
    authority and pre-cutover qualification evidence, then freshly re-observes the
    complete migrated state required for an external HubSelectorCutover.accept().
    """

    def __init__(self, drive: DriveBackend, selected_hub_root_id: str):
        self.drive = drive
        self.selected_hub_root_id = _text(selected_hub_root_id, "selected Hub root ID")

    def _verify_identity_chain(self, pack, freeze, authority, qualification) -> None:
        if authority["candidate_id"] != pack.candidate_id or authority["pack_sha256"] != pack.pack_sha256:
            raise DriveMigrationPostCutoverAcceptanceBlocked(
                "production target authority does not bind exact frozen pack"
            )
        if authority["target_name"] != TARGET_PREFIX + pack.candidate_id:
            raise DriveMigrationPostCutoverAcceptanceBlocked(
                "production target authority name disagrees with candidate"
            )
        if authority["target_id"] != self.selected_hub_root_id:
            raise DriveMigrationPostCutoverAcceptanceBlocked(
                "selected Hub identity does not match qualified production target authority"
            )

        expected_frozen = {
            "candidate_id": freeze["candidate_id"],
            "pack_sha256": freeze["pack_sha256"],
            "source_commit": freeze["source_commit"],
            "source_tree": freeze["source_tree"],
            "source_manifest_sha256": freeze["source_manifest_sha256"],
            "mapping_manifest_sha256": freeze["mapping_manifest_sha256"],
            "frozen_canonical_inventory_sha256": freeze["canonical_inventory_sha256"],
            "frozen_project_state_inventory_sha256": freeze["project_state_inventory_sha256"],
            "frozen_preservation_inventory_sha256": freeze["preservation_inventory_sha256"],
            "frozen_root_index_sha256": freeze["root_index_sha256"],
        }
        for key, expected in expected_frozen.items():
            if qualification[key] != expected:
                raise DriveMigrationPostCutoverAcceptanceBlocked(
                    f"production qualification evidence disagrees with frozen provenance: {key}"
                )

        selected_sha = sha256(self.selected_hub_root_id.encode("utf-8")).hexdigest()
        staging_sha = sha256(authority["staging_root_id"].encode("utf-8")).hexdigest()
        if qualification["target_identity_sha256"] != selected_sha:
            raise DriveMigrationPostCutoverAcceptanceBlocked(
                "production qualification target identity hash disagrees with selected Hub"
            )
        if qualification["staging_identity_sha256"] != staging_sha:
            raise DriveMigrationPostCutoverAcceptanceBlocked(
                "production qualification staging identity hash disagrees with target authority"
            )

    def _verify_target_and_staging(self, authority) -> None:
        try:
            target = self.drive.get(self.selected_hub_root_id, include_trashed=False)
            staging = self.drive.get(authority["staging_root_id"], include_trashed=False)
        except DriveNotFound as exc:
            raise DriveMigrationPostCutoverAcceptanceBlocked(
                "qualified production target or staging root is missing"
            ) from exc
        if (
            target.trashed
            or not target.is_folder
            or target.parent_id != authority["staging_root_id"]
            or target.name != authority["target_name"]
        ):
            raise DriveMigrationPostCutoverAcceptanceBlocked(
                "selected production target Drive identity/location/type changed"
            )
        if staging.trashed or not staging.is_folder or staging.name != STAGING_ROOT_NAME:
            raise DriveMigrationPostCutoverAcceptanceBlocked(
                "production migration staging root identity/type changed"
            )
        sentinels = self.drive.list_children(staging.file_id, name=STAGING_SENTINEL_NAME)
        if (
            len(sentinels) != 1
            or sentinels[0].trashed
            or sentinels[0].is_folder
            or self.drive.download(sentinels[0].file_id) != STAGING_SENTINEL_BYTES
        ):
            raise DriveMigrationPostCutoverAcceptanceBlocked(
                "production migration staging sentinel is not exact"
            )
        children = self.drive.list_children(staging.file_id)
        if {item.file_id for item in children} != {sentinels[0].file_id, target.file_id}:
            raise DriveMigrationPostCutoverAcceptanceBlocked(
                "production migration staging root contains unexpected objects"
            )

    def _verify_master_and_restart(self, pack) -> str:
        try:
            _, raw = DriveMasterTransition.read_unique_master(
                self.drive,
                self.selected_hub_root_id,
            )
            master = validate_master(strict_json_bytes(raw, label="MASTER.post-cutover-acceptance"))
        except (DriveMasterUnavailable, ProtocolError) as exc:
            raise DriveMigrationPostCutoverAcceptanceBlocked(
                f"post-cutover MASTER is not exact: {exc}"
            ) from exc
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
            or completed["completed_epoch"] != 1
        ):
            raise DriveMigrationPostCutoverAcceptanceBlocked(
                "post-cutover MASTER is not exact READY/SAFE epoch-1 COMMITTED candidate"
            )
        try:
            discovery = DriveRestartDiscovery.from_hub_root(
                self.drive,
                self.selected_hub_root_id,
            ).discover()
        except DriveDiscoveryBlocked as exc:
            raise DriveMigrationPostCutoverAcceptanceBlocked(
                f"post-cutover restart discovery failed: {exc}"
            ) from exc
        if discovery.state != "READY_CLEAN" or discovery.bundle is not None:
            raise DriveMigrationPostCutoverAcceptanceBlocked(
                "post-cutover restart discovery is not READY_CLEAN without active bundle"
            )
        return discovery.state

    def _verify_canonical(self, pack) -> tuple[int, int, int, str]:
        paths = tuple(entry.target for entry in pack.canonical_outputs)
        try:
            result = DriveCanonicalReader(
                self.drive,
                self.selected_hub_root_id,
            ).read_paths(paths)
        except (DriveReadBlocked, ValueError) as exc:
            raise DriveMigrationPostCutoverAcceptanceBlocked(
                f"post-cutover consistent canonical read failed: {exc}"
            ) from exc
        if result.canonical_epoch != 1 or len(result.items) != len(pack.canonical_outputs):
            raise DriveMigrationPostCutoverAcceptanceBlocked(
                "post-cutover canonical reader did not observe exact epoch-1 inventory"
            )
        by_path = result.by_path()
        inventory: list[dict[str, Any]] = []
        total = 0
        for entry in sorted(pack.canonical_outputs, key=lambda item: item.target):
            observed = by_path.get(entry.target)
            expected_raw = source_file(
                pack.root,
                entry.payload,
                f"post-cutover canonical payload {entry.operation_id}",
            )
            if (
                observed is None
                or observed.sha256 != entry.sha256
                or observed.size != entry.size
                or observed.content != expected_raw
            ):
                raise DriveMigrationPostCutoverAcceptanceBlocked(
                    f"post-cutover canonical bytes disagree with frozen pack: {entry.target}"
                )
            inventory.append({"target": entry.target, "sha256": entry.sha256, "size": entry.size})
            total += entry.size
        digest = sha256(
            canonical_json_bytes(
                {
                    "schema": "keelaryn.migration-rehearsal-canonical-inventory.v1",
                    "candidate_id": pack.candidate_id,
                    "entries": inventory,
                }
            )
        ).hexdigest()
        return result.canonical_epoch, len(inventory), total, digest

    def _verify_preservation(self, pack) -> tuple[int, int, str]:
        service = DriveMigrationPreservationMaterialization(
            self.drive,
            self.selected_hub_root_id,
        )
        try:
            _, _, destinations = service._authority(pack)
            service._require_committed_target(pack)
            raw_by_operation: dict[str, bytes] = {}
            for destination in destinations:
                raw = source_file(
                    pack.root,
                    destination.entry.payload,
                    f"post-cutover preserved payload {destination.entry.operation_id}",
                )
                expected = BlobState(destination.entry.sha256, destination.entry.size)
                if BlobState.from_bytes(raw) != expected:
                    raise DriveMigrationPostCutoverAcceptanceBlocked(
                        "frozen preservation payload changed during acceptance"
                    )
                raw_by_operation[destination.entry.operation_id] = raw
            service._project_scope(pack, destinations, raw_by_operation, complete=True)
            service._archive_scope(destinations, raw_by_operation, complete=True)
        except DriveMigrationPostCutoverAcceptanceBlocked:
            raise
        except (DriveMigrationMaterializationBlocked, MigrationPackBlocked) as exc:
            raise DriveMigrationPostCutoverAcceptanceBlocked(
                f"post-cutover preservation verification failed: {exc}"
            ) from exc
        raw = canonical_json_bytes(
            {
                "schema": "keelaryn.migration-preservation-inventory.v1",
                "candidate_id": pack.candidate_id,
                "entries": [
                    {
                        "destination": item.destination,
                        "classification": item.entry.classification,
                        "sha256": item.entry.sha256,
                        "size": item.entry.size,
                    }
                    for item in destinations
                ],
            }
        )
        return len(destinations), sum(item.entry.size for item in destinations), sha256(raw).hexdigest()

    def _verify_workflow_and_router(self, pack) -> tuple[int, str, str, str]:
        try:
            projects = DriveWorkspaceService(
                self.drive,
                self.selected_hub_root_id,
            ).list_projects()
            reconciliation = DriveReconciliationStateService(
                self.drive,
                self.selected_hub_root_id,
            ).read()
        except (DriveWorkflowBlocked, ProtocolError) as exc:
            raise DriveMigrationPostCutoverAcceptanceBlocked(
                f"post-cutover Workspace/Reconciliation verification failed: {exc}"
            ) from exc
        expected_states = {entry.project_id: entry for entry in pack.project_initial_states}
        if {project.project_id for project in projects} != set(expected_states):
            raise DriveMigrationPostCutoverAcceptanceBlocked(
                "post-cutover Project set disagrees with frozen migration pack"
            )
        for project in projects:
            entry = expected_states[project.project_id]
            expected_raw = source_file(
                pack.root,
                entry.payload,
                f"post-cutover Project STATE {project.project_id}",
            )
            if project.state_raw != expected_raw or self.drive.list_children(project.results_folder_id):
                raise DriveMigrationPostCutoverAcceptanceBlocked(
                    f"post-cutover Project state/results changed: {project.project_id}"
                )
        expected_reconciliation = DriveHubBootstrap.initial_reconciliation_state_bytes()
        if reconciliation.raw != expected_reconciliation:
            raise DriveMigrationPostCutoverAcceptanceBlocked(
                "post-cutover Reconciliation STATE changed"
            )

        matches = self.drive.list_children(self.selected_hub_root_id, name=INDEX_NAME)
        if len(matches) != 1 or matches[0].trashed or matches[0].is_folder:
            raise DriveMigrationPostCutoverAcceptanceBlocked(
                "post-cutover root INDEX is missing or ambiguous"
            )
        index_raw = self.drive.download(matches[0].file_id)
        if pack.root_index_size >= 0:
            expected_index = source_file(pack.root, "root/INDEX.md", "post-cutover packed root INDEX")
            router_outcome = "COMMITTED"
        else:
            expected_index = DriveHubBootstrap.initial_index_bytes()
            router_outcome = "NOT_REQUIRED"
        if index_raw != expected_index:
            raise DriveMigrationPostCutoverAcceptanceBlocked(
                "post-cutover root INDEX disagrees with frozen migration authority"
            )
        return (
            len(projects),
            sha256(reconciliation.raw).hexdigest(),
            router_outcome,
            sha256(index_raw).hexdigest(),
        )

    @staticmethod
    def _require_qualification_match(qualification, observed: dict[str, Any]) -> None:
        for key, value in observed.items():
            if qualification[key] != value:
                raise DriveMigrationPostCutoverAcceptanceBlocked(
                    f"fresh post-cutover observation disagrees with production qualification: {key}"
                )

    def run(
        self,
        pack_dir: str | Path,
        freeze_receipt: str | Path,
        repo_root: str | Path,
        target_authority_path: str | Path,
        qualification_evidence_path: str | Path,
    ) -> DriveMigrationPostCutoverAcceptanceEvidence:
        try:
            pack = verify_migration_pack(pack_dir)
            freeze = verify_migration_candidate_freeze(pack.root, freeze_receipt, repo_root)
        except MigrationPackBlocked as exc:
            raise DriveMigrationPostCutoverAcceptanceBlocked(
                f"post-cutover frozen candidate verification failed: {exc}"
            ) from exc
        authority = _strict_authority(
            small_file(Path(target_authority_path), "production target authority for acceptance")
        )
        qualification = _strict_qualification(
            small_file(Path(qualification_evidence_path), "production qualification evidence for acceptance")
        )
        self._verify_identity_chain(pack, freeze, authority, qualification)
        self._verify_target_and_staging(authority)
        restart_state = self._verify_master_and_restart(pack)
        canonical_epoch, canonical_count, canonical_bytes, canonical_digest = self._verify_canonical(pack)
        preserved_count, preserved_bytes, preservation_digest = self._verify_preservation(pack)
        project_count, reconciliation_digest, router_outcome, root_index_digest = (
            self._verify_workflow_and_router(pack)
        )

        observed = {
            "canonical_epoch": canonical_epoch,
            "canonical_file_count": canonical_count,
            "canonical_total_bytes": canonical_bytes,
            "canonical_inventory_sha256": canonical_digest,
            "preserved_file_count": preserved_count,
            "preserved_total_bytes": preserved_bytes,
            "preservation_inventory_sha256": preservation_digest,
            "project_count": project_count,
            "reconciliation_state_sha256": reconciliation_digest,
            "router_outcome": router_outcome,
            "root_index_sha256": root_index_digest,
            "reader_epoch": canonical_epoch,
            "restart_state": restart_state,
        }
        self._require_qualification_match(qualification, observed)

        # Freshly reverify immutable local authority at the acceptance boundary.
        try:
            final_pack = verify_migration_pack(pack.root)
            final_freeze = verify_migration_candidate_freeze(
                final_pack.root,
                freeze_receipt,
                repo_root,
            )
        except MigrationPackBlocked as exc:
            raise DriveMigrationPostCutoverAcceptanceBlocked(
                f"frozen candidate changed during post-cutover acceptance: {exc}"
            ) from exc
        if final_pack.pack_sha256 != pack.pack_sha256 or final_freeze != freeze:
            raise DriveMigrationPostCutoverAcceptanceBlocked(
                "frozen candidate identity changed during post-cutover acceptance"
            )
        final_authority = _strict_authority(
            small_file(Path(target_authority_path), "production target authority final acceptance")
        )
        final_qualification = _strict_qualification(
            small_file(Path(qualification_evidence_path), "production qualification evidence final acceptance")
        )
        if final_authority != authority or final_qualification != qualification:
            raise DriveMigrationPostCutoverAcceptanceBlocked(
                "production target authority/evidence changed during acceptance"
            )

        selected_digest = sha256(self.selected_hub_root_id.encode("utf-8")).hexdigest()
        return DriveMigrationPostCutoverAcceptanceEvidence(
            candidate_id=pack.candidate_id,
            pack_sha256=pack.pack_sha256,
            source_commit=freeze["source_commit"],
            source_tree=freeze["source_tree"],
            selector_identity_sha256=selected_digest,
            target_identity_sha256=qualification["target_identity_sha256"],
            staging_identity_sha256=qualification["staging_identity_sha256"],
            canonical_epoch=canonical_epoch,
            canonical_file_count=canonical_count,
            canonical_total_bytes=canonical_bytes,
            canonical_inventory_sha256=canonical_digest,
            preserved_file_count=preserved_count,
            preserved_total_bytes=preserved_bytes,
            preservation_inventory_sha256=preservation_digest,
            project_count=project_count,
            reconciliation_state_sha256=reconciliation_digest,
            router_outcome=router_outcome,
            root_index_sha256=root_index_digest,
            restart_state=restart_state,
            outcome="POST_CUTOVER_READ_ONLY_PASS",
        )


__all__ = [
    "DriveMigrationPostCutoverAcceptanceBlocked",
    "DriveMigrationPostCutoverAcceptanceEvidence",
    "DriveMigrationPostCutoverReadOnlyAcceptance",
    "POST_CUTOVER_EVIDENCE_SCHEMA",
]
