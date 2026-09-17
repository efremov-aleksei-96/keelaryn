from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from .drive_backend import DriveBackend, DriveItem
from .drive_bootstrap import DriveHubBootstrap
from .drive_master import DriveMasterTransition, DriveMasterUnavailable
from .drive_project import (
    PROJECT_STATE_NAME,
    RESULTS_FOLDER_NAME,
    DriveProjectWorkflow,
    DriveWorkflowBlocked,
    DriveWorkflowLayoutResolver,
)
from .migration_common import source_file
from .migration_pack import MigrationPackBlocked, verify_migration_pack
from .protocol import ProtocolError, strict_json_bytes, validate_master


class DriveMigrationPreparationBlocked(ProtocolError):
    """A disposable/production migration target cannot be prepared safely."""


@dataclass(frozen=True)
class DriveMigrationTopologyEvidence:
    candidate_id: str
    pack_sha256: str
    canonical_directory_count: int

    def to_json_value(self) -> dict[str, Any]:
        return {
            "schema": "keelaryn.migration-topology-evidence.v1",
            "candidate_id": self.candidate_id,
            "pack_sha256": self.pack_sha256,
            "canonical_directory_count": self.canonical_directory_count,
        }


@dataclass(frozen=True)
class DriveMigrationProjectEvidence:
    candidate_id: str
    pack_sha256: str
    project_count: int
    project_state_total_bytes: int

    def to_json_value(self) -> dict[str, Any]:
        return {
            "schema": "keelaryn.migration-project-evidence.v1",
            "candidate_id": self.candidate_id,
            "pack_sha256": self.pack_sha256,
            "project_count": self.project_count,
            "project_state_total_bytes": self.project_state_total_bytes,
        }


class DriveMigrationTopologyPreparation:
    """Prepare only empty canonical parent directories for one frozen migration pack.

    This layer is intentionally mechanical. It never writes canonical payload bytes,
    never mutates root INDEX/work/archive material, and only operates while the target
    Hub is the untouched READY/SAFE epoch-0 Hub. Re-running after an interrupted
    folder creation is safe because the complete expected directory closure is
    derived from the verified immutable migration pack and freshly re-observed.
    """

    def __init__(self, drive: DriveBackend, hub_root_id: str):
        self.drive = drive
        self.hub_root_id = hub_root_id

    def _master(self) -> dict[str, Any]:
        try:
            _, raw = DriveMasterTransition.read_unique_master(self.drive, self.hub_root_id)
            return validate_master(strict_json_bytes(raw, label="MASTER.migration-topology"))
        except (DriveMasterUnavailable, ProtocolError) as exc:
            raise DriveMigrationPreparationBlocked(
                f"migration topology cannot resolve exact MASTER: {exc}"
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

    @staticmethod
    def _required_directories(pack) -> tuple[str, ...]:
        required: set[str] = set()
        for entry in pack.canonical_outputs:
            parts = entry.target.split("/")
            for end in range(1, len(parts)):
                required.add("/".join(parts[:end]))
        return tuple(sorted(required, key=lambda value: (value.count("/"), value)))

    def _observe_exact_tree(
        self,
        canonical_root_id: str,
        required: set[str],
    ) -> dict[str, DriveItem]:
        observed: dict[str, DriveItem] = {}

        def walk(parent_id: str, prefix: str) -> None:
            children = self.drive.list_children(parent_id)
            seen_names: set[str] = set()
            for child in children:
                if child.name in seen_names:
                    raise DriveMigrationPreparationBlocked(
                        f"migration canonical topology is ambiguous under {prefix or 'canonical/'}: {child.name}"
                    )
                seen_names.add(child.name)
                logical = f"{prefix}/{child.name}" if prefix else child.name
                if child.trashed or not child.is_folder:
                    raise DriveMigrationPreparationBlocked(
                        f"migration canonical topology contains non-directory material before Core publication: {logical}"
                    )
                if logical not in required:
                    raise DriveMigrationPreparationBlocked(
                        f"migration canonical topology contains unexpected directory: {logical}"
                    )
                observed[logical] = child
                walk(child.file_id, logical)

        walk(canonical_root_id, "")
        return observed

    def _ensure_folder(
        self,
        parent_id: str,
        name: str,
        *,
        logical: str,
    ) -> DriveItem:
        matches = self.drive.list_children(parent_id, name=name)
        if len(matches) > 1:
            raise DriveMigrationPreparationBlocked(
                f"migration canonical directory is ambiguous: {logical}"
            )
        if matches:
            item = matches[0]
            if item.trashed or not item.is_folder:
                raise DriveMigrationPreparationBlocked(
                    f"migration canonical path is not a live directory: {logical}"
                )
            return item
        reserved = self.drive.generate_ids(1)[0]
        self.drive.create_folder(
            parent_id,
            name,
            file_id=reserved,
            label=f"drive.migration.topology.{logical.replace('/', '.')}.create",
        )
        matches = self.drive.list_children(parent_id, name=name)
        if (
            len(matches) != 1
            or matches[0].file_id != reserved
            or matches[0].trashed
            or not matches[0].is_folder
        ):
            raise DriveMigrationPreparationBlocked(
                f"migration canonical directory did not become exact: {logical}"
            )
        return matches[0]

    def prepare(self, pack_dir: str | Path) -> DriveMigrationTopologyEvidence:
        try:
            pack = verify_migration_pack(pack_dir)
        except MigrationPackBlocked as exc:
            raise DriveMigrationPreparationBlocked(
                f"migration pack verification failed before topology preparation: {exc}"
            ) from exc

        try:
            bootstrap = DriveHubBootstrap(self.drive, self.hub_root_id).run()
        except ProtocolError as exc:
            raise DriveMigrationPreparationBlocked(
                f"migration target bootstrap/verification failed: {exc}"
            ) from exc
        if not self._initial_master(self._master()):
            raise DriveMigrationPreparationBlocked(
                "migration topology preparation requires untouched READY/SAFE epoch 0"
            )

        required_tuple = self._required_directories(pack)
        required = set(required_tuple)
        observed = self._observe_exact_tree(bootstrap.layout.canonical_root_id, required)

        by_path: dict[str, DriveItem] = dict(observed)
        for logical in required_tuple:
            parts = logical.split("/")
            parent_id = bootstrap.layout.canonical_root_id
            if len(parts) > 1:
                parent = "/".join(parts[:-1])
                parent_item = by_path.get(parent)
                if parent_item is None:
                    raise DriveMigrationPreparationBlocked(
                        f"migration canonical parent preparation order is invalid: {logical}"
                    )
                parent_id = parent_item.file_id
            by_path[logical] = self._ensure_folder(
                parent_id,
                parts[-1],
                logical=logical,
            )

        if not self._initial_master(self._master()):
            raise DriveMigrationPreparationBlocked(
                "migration target MASTER changed during topology preparation"
            )
        final = self._observe_exact_tree(bootstrap.layout.canonical_root_id, required)
        if set(final) != required:
            raise DriveMigrationPreparationBlocked(
                "migration canonical topology is incomplete after preparation"
            )

        try:
            refreshed = verify_migration_pack(pack_dir)
        except MigrationPackBlocked as exc:
            raise DriveMigrationPreparationBlocked(
                f"migration pack changed during topology preparation: {exc}"
            ) from exc
        if refreshed.manifest_raw != pack.manifest_raw:
            raise DriveMigrationPreparationBlocked(
                "migration pack identity changed during topology preparation"
            )

        return DriveMigrationTopologyEvidence(
            pack.candidate_id,
            pack.pack_sha256,
            len(required_tuple),
        )


class DriveMigrationProjectPreparation:
    """Initialize exact migration Projects and their frozen initial STATE.md bytes.

    This is an epoch-0 preparation layer, not canonical publication. It accepts only
    the Project set bound by ``project_initial_states`` in the verified migration
    pack. Crash-restart recovery may observe a prefix of the deterministic Project
    structure, but unrelated Projects or unexpected Project children fail closed.
    ``migration-import/`` payloads are deliberately excluded here and are
    materialized only after canonical publication has committed.
    """

    def __init__(self, drive: DriveBackend, hub_root_id: str):
        self.drive = drive
        self.hub_root_id = hub_root_id

    def _master(self) -> dict[str, Any]:
        try:
            _, raw = DriveMasterTransition.read_unique_master(self.drive, self.hub_root_id)
            return validate_master(strict_json_bytes(raw, label="MASTER.migration-projects"))
        except (DriveMasterUnavailable, ProtocolError) as exc:
            raise DriveMigrationPreparationBlocked(
                f"migration Project preparation cannot resolve exact MASTER: {exc}"
            ) from exc

    @staticmethod
    def _initial_master(master: dict[str, Any]) -> bool:
        return DriveMigrationTopologyPreparation._initial_master(master)

    def _verify_blob(self, item: DriveItem, raw: bytes, *, label: str) -> None:
        if item.trashed or item.is_folder:
            raise DriveMigrationPreparationBlocked(f"{label} is not a live blob")
        if self.drive.download(item.file_id) != raw:
            raise DriveMigrationPreparationBlocked(f"{label} bytes do not match migration pack")
        digest = sha256(raw).hexdigest()
        if item.size is not None and item.size != len(raw):
            raise DriveMigrationPreparationBlocked(f"{label} metadata size mismatch")
        if item.sha256_checksum is not None and item.sha256_checksum != digest:
            raise DriveMigrationPreparationBlocked(f"{label} metadata checksum mismatch")

    def _verify_project(
        self,
        project: DriveItem,
        state_raw: bytes,
        *,
        allow_partial: bool,
    ) -> bool:
        if project.trashed or not project.is_folder:
            raise DriveMigrationPreparationBlocked(
                f"migration Project is not a live folder: {project.name}"
            )
        children = self.drive.list_children(project.file_id)
        names: set[str] = set()
        for child in children:
            if child.name in names:
                raise DriveMigrationPreparationBlocked(
                    f"migration Project contains duplicate child: {project.name}/{child.name}"
                )
            names.add(child.name)
            if child.name not in {PROJECT_STATE_NAME, RESULTS_FOLDER_NAME}:
                raise DriveMigrationPreparationBlocked(
                    f"migration Project contains unexpected material before preservation: "
                    f"{project.name}/{child.name}"
                )

        state_matches = [item for item in children if item.name == PROJECT_STATE_NAME]
        results_matches = [item for item in children if item.name == RESULTS_FOLDER_NAME]
        if not allow_partial and (len(state_matches) != 1 or len(results_matches) != 1):
            raise DriveMigrationPreparationBlocked(
                f"migration Project structure is incomplete: {project.name}"
            )
        if state_matches:
            if len(state_matches) != 1:
                raise DriveMigrationPreparationBlocked(
                    f"migration Project STATE is ambiguous: {project.name}"
                )
            self._verify_blob(
                state_matches[0],
                state_raw,
                label=f"migration Project STATE {project.name}",
            )
        if results_matches:
            if len(results_matches) != 1:
                raise DriveMigrationPreparationBlocked(
                    f"migration Project results is ambiguous: {project.name}"
                )
            results = results_matches[0]
            if results.trashed or not results.is_folder:
                raise DriveMigrationPreparationBlocked(
                    f"migration Project results is not a live folder: {project.name}"
                )
            if self.drive.list_children(results.file_id):
                raise DriveMigrationPreparationBlocked(
                    f"migration Project results must be empty during initial preparation: {project.name}"
                )
        return len(state_matches) == 1 and len(results_matches) == 1

    def _observe_projects(
        self,
        projects_parent_id: str,
        expected: dict[str, bytes],
        *,
        allow_partial: bool,
    ) -> tuple[dict[str, DriveItem], set[str]]:
        observed: dict[str, DriveItem] = {}
        incomplete: set[str] = set()
        for project in self.drive.list_children(projects_parent_id):
            if project.name in observed:
                raise DriveMigrationPreparationBlocked(
                    f"migration Projects area contains duplicate project: {project.name}"
                )
            if project.name not in expected:
                raise DriveMigrationPreparationBlocked(
                    f"migration Projects area contains unexpected project: {project.name}"
                )
            complete = self._verify_project(
                project,
                expected[project.name],
                allow_partial=allow_partial,
            )
            observed[project.name] = project
            if not complete:
                incomplete.add(project.name)
        return observed, incomplete

    def prepare(self, pack_dir: str | Path) -> DriveMigrationProjectEvidence:
        try:
            pack = verify_migration_pack(pack_dir)
        except MigrationPackBlocked as exc:
            raise DriveMigrationPreparationBlocked(
                f"migration pack verification failed before Project preparation: {exc}"
            ) from exc

        try:
            DriveHubBootstrap(self.drive, self.hub_root_id).run()
            layout = DriveWorkflowLayoutResolver(self.drive, self.hub_root_id).resolve()
        except (ProtocolError, DriveWorkflowBlocked) as exc:
            raise DriveMigrationPreparationBlocked(
                f"migration Project target bootstrap/layout verification failed: {exc}"
            ) from exc
        if not self._initial_master(self._master()):
            raise DriveMigrationPreparationBlocked(
                "migration Project preparation requires untouched READY/SAFE epoch 0"
            )

        expected: dict[str, bytes] = {}
        for entry in pack.project_initial_states:
            raw = source_file(
                pack.root,
                entry.payload,
                f"migration packed Project STATE {entry.project_id}",
            )
            if sha256(raw).hexdigest() != entry.sha256 or len(raw) != entry.size:
                raise DriveMigrationPreparationBlocked(
                    f"migration packed Project STATE fingerprint changed: {entry.project_id}"
                )
            if entry.project_id in expected:
                raise DriveMigrationPreparationBlocked(
                    f"migration pack contains duplicate Project STATE: {entry.project_id}"
                )
            expected[entry.project_id] = raw

        observed, incomplete = self._observe_projects(
            layout.projects_parent_id,
            expected,
            allow_partial=True,
        )
        workflow = DriveProjectWorkflow(self.drive, layout.projects_parent_id)
        for project_id in sorted(expected):
            if project_id in observed and project_id not in incomplete:
                continue
            try:
                workflow.initialize_project(project_id, expected[project_id])
            except DriveWorkflowBlocked as exc:
                raise DriveMigrationPreparationBlocked(
                    f"migration Project initialization failed for {project_id}: {exc}"
                ) from exc

        if not self._initial_master(self._master()):
            raise DriveMigrationPreparationBlocked(
                "migration target MASTER changed during Project preparation"
            )
        final, incomplete_final = self._observe_projects(
            layout.projects_parent_id,
            expected,
            allow_partial=False,
        )
        if incomplete_final or set(final) != set(expected):
            raise DriveMigrationPreparationBlocked(
                "migration Project set is incomplete after preparation"
            )

        try:
            refreshed = verify_migration_pack(pack_dir)
        except MigrationPackBlocked as exc:
            raise DriveMigrationPreparationBlocked(
                f"migration pack changed during Project preparation: {exc}"
            ) from exc
        if (
            refreshed.manifest_raw != pack.manifest_raw
            or refreshed.project_initial_states != pack.project_initial_states
        ):
            raise DriveMigrationPreparationBlocked(
                "migration pack identity changed during Project preparation"
            )

        return DriveMigrationProjectEvidence(
            pack.candidate_id,
            pack.pack_sha256,
            len(expected),
            sum(len(raw) for raw in expected.values()),
        )


__all__ = [
    "DriveMigrationPreparationBlocked",
    "DriveMigrationProjectEvidence",
    "DriveMigrationProjectPreparation",
    "DriveMigrationTopologyEvidence",
    "DriveMigrationTopologyPreparation",
]
