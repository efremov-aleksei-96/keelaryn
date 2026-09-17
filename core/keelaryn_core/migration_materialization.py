from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from .drive_backend import DriveBackend, DriveItem
from .drive_discovery import DriveDiscoveryBlocked, DriveRestartDiscovery
from .drive_factory import DriveTransactionFactory, DriveTransactionFactoryBlocked
from .drive_master import DriveMasterTransition, DriveMasterUnavailable
from .drive_transaction import BlobState
from .migration_common import (
    MIGRATION_MAPPING_NAME,
    MIGRATION_SOURCE_NAME,
    MigrationPackBlocked,
    PreservedEntry,
    small_file,
    source_file,
)
from .migration_mapping import parse_mapping
from .migration_pack import verify_migration_pack
from .migration_publication import DriveMigrationCanonicalPublication
from .migration_source import parse_source
from .protocol import (
    ProtocolError,
    canonical_json_bytes,
    strict_json_bytes,
    validate_master,
)


class DriveMigrationMaterializationBlocked(ProtocolError):
    """Post-COMMITTED migration preservation cannot be materialized safely."""


@dataclass(frozen=True)
class DriveMigrationMaterializationEvidence:
    candidate_id: str
    pack_sha256: str
    preserved_file_count: int
    preserved_total_bytes: int
    project_file_count: int
    archive_file_count: int
    inventory_sha256: str

    def to_json_value(self) -> dict[str, Any]:
        return {
            "schema": "keelaryn.migration-materialization-evidence.v1",
            "candidate_id": self.candidate_id,
            "pack_sha256": self.pack_sha256,
            "preserved_file_count": self.preserved_file_count,
            "preserved_total_bytes": self.preserved_total_bytes,
            "project_file_count": self.project_file_count,
            "archive_file_count": self.archive_file_count,
            "inventory_sha256": self.inventory_sha256,
        }


@dataclass(frozen=True)
class _DestinationEntry:
    destination: str
    entry: PreservedEntry


class DriveMigrationPreservationMaterialization:
    """Materialize frozen non-canonical preservation after exact Core COMMIT.

    The service owns only the migration preservation namespaces defined by the
    frozen mapping authority:

    - ``work/projects/<project_id>/migration-import/...``
    - ``archive/migration/<candidate_id>/...``

    It never writes canonical bytes, Project STATE/results, or root INDEX.md.
    Re-running after an interrupted create is safe because every expected path,
    byte fingerprint and destination is re-derived from the immutable private
    pack plus its packed mapping authority. Any unrelated or conflicting object
    inside the controlled migration scopes fails closed.
    """

    def __init__(self, drive: DriveBackend, hub_root_id: str):
        self.drive = drive
        self.hub_root_id = hub_root_id

    def _master(self) -> dict[str, Any]:
        try:
            _, raw = DriveMasterTransition.read_unique_master(self.drive, self.hub_root_id)
            return validate_master(strict_json_bytes(raw, label="MASTER.migration-materialization"))
        except (DriveMasterUnavailable, ProtocolError) as exc:
            raise DriveMigrationMaterializationBlocked(
                f"migration materialization cannot resolve exact MASTER: {exc}"
            ) from exc

    def _require_committed_target(self, pack):
        try:
            discovery = DriveRestartDiscovery.from_hub_root(
                self.drive,
                self.hub_root_id,
            ).discover()
        except DriveDiscoveryBlocked as exc:
            raise DriveMigrationMaterializationBlocked(
                f"migration materialization restart discovery failed: {exc}"
            ) from exc
        if discovery.state != "READY_CLEAN" or discovery.bundle is not None:
            raise DriveMigrationMaterializationBlocked(
                "migration preservation requires clean READY state without active locator"
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
            or completed["outcome"] != "COMMITTED"
        ):
            raise DriveMigrationMaterializationBlocked(
                "migration preservation requires exact READY/SAFE epoch-1 COMMITTED candidate"
            )

        try:
            layout = DriveTransactionFactory(self.drive, self.hub_root_id).resolve_layout()
        except DriveTransactionFactoryBlocked as exc:
            raise DriveMigrationMaterializationBlocked(
                f"migration materialization layout resolution failed: {exc}"
            ) from exc
        publication = DriveMigrationCanonicalPublication(self.drive, self.hub_root_id)
        if not publication._canonical_matches(  # package-internal invariant reuse
            pack,
            layout.canonical_root_id,
            include_payloads=True,
        ):
            raise DriveMigrationMaterializationBlocked(
                "migration committed canonical inventory no longer matches private pack"
            )
        return layout

    @staticmethod
    def _authority(pack):
        authority = pack.root / "authority"
        source_raw = small_file(
            authority / MIGRATION_SOURCE_NAME,
            "packed migration source authority for materialization",
        )
        mapping_raw = small_file(
            authority / MIGRATION_MAPPING_NAME,
            "packed migration mapping authority for materialization",
        )
        source = parse_source(source_raw)
        mapping = parse_mapping(mapping_raw, source)
        if (
            source.candidate_id != pack.candidate_id
            or mapping.candidate_id != pack.candidate_id
            or source.digest != pack.source_manifest_sha256
            or mapping.digest != pack.mapping_manifest_sha256
        ):
            raise DriveMigrationMaterializationBlocked(
                "migration packed authority identity disagrees with private pack"
            )

        destinations = dict(mapping.preservation_destinations)
        actions = dict(mapping.actions)
        packed_sources = {entry.source for entry in pack.preserved_outputs}
        if packed_sources != set(destinations):
            raise DriveMigrationMaterializationBlocked(
                "migration preservation destination coverage disagrees with private pack"
            )
        result: list[_DestinationEntry] = []
        for entry in pack.preserved_outputs:
            if actions.get(entry.source) != entry.classification:
                raise DriveMigrationMaterializationBlocked(
                    f"migration preservation classification changed for {entry.source}"
                )
            result.append(_DestinationEntry(destinations[entry.source], entry))
        return source_raw, mapping_raw, tuple(sorted(result, key=lambda item: item.destination))

    def _unique_live(self, parent_id: str, name: str, *, label: str) -> DriveItem | None:
        matches = self.drive.list_children(parent_id, name=name)
        if len(matches) > 1:
            raise DriveMigrationMaterializationBlocked(f"{label} is ambiguous")
        if not matches:
            return None
        item = matches[0]
        if item.trashed:
            raise DriveMigrationMaterializationBlocked(f"{label} is trashed")
        return item

    def _require_folder(self, parent_id: str, name: str, *, label: str) -> DriveItem:
        item = self._unique_live(parent_id, name, label=label)
        if item is None or not item.is_folder:
            raise DriveMigrationMaterializationBlocked(f"{label} is not one live folder")
        return item

    def _ensure_folder(self, parent_id: str, name: str, *, logical: str) -> DriveItem:
        item = self._unique_live(parent_id, name, label=f"migration folder {logical}")
        if item is not None:
            if not item.is_folder:
                raise DriveMigrationMaterializationBlocked(
                    f"migration preservation path is not a folder: {logical}"
                )
            return item
        reserved = self.drive.generate_ids(1)[0]
        self.drive.create_folder(
            parent_id,
            name,
            file_id=reserved,
            label=f"drive.migration.preserve.folder.{logical.replace('/', '.')}.create",
        )
        item = self._unique_live(parent_id, name, label=f"migration folder {logical}")
        if item is None or item.file_id != reserved or not item.is_folder:
            raise DriveMigrationMaterializationBlocked(
                f"migration preservation folder did not become exact: {logical}"
            )
        return item

    def _verify_blob(
        self,
        item: DriveItem,
        raw: bytes,
        entry: PreservedEntry,
        *,
        logical: str,
    ) -> None:
        expected = BlobState(entry.sha256, entry.size)
        if item.is_folder or not expected.matches(item):
            raise DriveMigrationMaterializationBlocked(
                f"migration preservation metadata mismatch: {logical}"
            )
        observed = self.drive.download(item.file_id)
        if observed != raw or BlobState.from_bytes(observed) != expected:
            raise DriveMigrationMaterializationBlocked(
                f"migration preservation bytes mismatch: {logical}"
            )

    def _ensure_blob(
        self,
        parent_id: str,
        name: str,
        raw: bytes,
        entry: PreservedEntry,
        *,
        logical: str,
    ) -> DriveItem:
        item = self._unique_live(parent_id, name, label=f"migration blob {logical}")
        if item is not None:
            self._verify_blob(item, raw, entry, logical=logical)
            return item
        reserved = self.drive.generate_ids(1)[0]
        self.drive.create_blob(
            parent_id,
            name,
            raw,
            file_id=reserved,
            label=f"drive.migration.preserve.{entry.operation_id}.create",
        )
        item = self._unique_live(parent_id, name, label=f"migration blob {logical}")
        if item is None or item.file_id != reserved:
            raise DriveMigrationMaterializationBlocked(
                f"migration preservation blob did not become exact: {logical}"
            )
        self._verify_blob(item, raw, entry, logical=logical)
        return item

    @staticmethod
    def _expected_tree(entries: list[tuple[str, PreservedEntry]]) -> tuple[set[str], dict[str, PreservedEntry]]:
        directories: set[str] = set()
        files: dict[str, PreservedEntry] = {}
        for relative, entry in entries:
            if relative in files:
                raise DriveMigrationMaterializationBlocked(
                    f"duplicate migration preservation target: {relative}"
                )
            files[relative] = entry
            parts = relative.split("/")
            for end in range(1, len(parts)):
                directories.add("/".join(parts[:end]))
        if directories & set(files):
            raise DriveMigrationMaterializationBlocked(
                "migration preservation target is both file and directory"
            )
        return directories, files

    def _observe_tree(
        self,
        root_id: str,
        entries: list[tuple[str, PreservedEntry]],
        raw_by_operation: dict[str, bytes],
        *,
        scope: str,
        complete: bool,
    ) -> None:
        expected_dirs, expected_files = self._expected_tree(entries)
        seen_dirs: set[str] = set()
        seen_files: set[str] = set()

        def walk(parent_id: str, prefix: str) -> None:
            seen_names: set[str] = set()
            for item in self.drive.list_children(parent_id):
                if item.name in seen_names:
                    raise DriveMigrationMaterializationBlocked(
                        f"migration preservation duplicate under {scope}/{prefix}: {item.name}"
                    )
                seen_names.add(item.name)
                relative = f"{prefix}/{item.name}" if prefix else item.name
                if item.is_folder:
                    if relative not in expected_dirs:
                        raise DriveMigrationMaterializationBlocked(
                            f"migration preservation unexpected directory: {scope}/{relative}"
                        )
                    seen_dirs.add(relative)
                    walk(item.file_id, relative)
                    continue
                entry = expected_files.get(relative)
                if entry is None:
                    raise DriveMigrationMaterializationBlocked(
                        f"migration preservation unexpected blob: {scope}/{relative}"
                    )
                self._verify_blob(
                    item,
                    raw_by_operation[entry.operation_id],
                    entry,
                    logical=f"{scope}/{relative}",
                )
                seen_files.add(relative)

        walk(root_id, "")
        if complete and (seen_dirs != expected_dirs or seen_files != set(expected_files)):
            raise DriveMigrationMaterializationBlocked(
                f"migration preservation scope is incomplete: {scope}"
            )

    def _ensure_relative_parent(
        self,
        root_id: str,
        relative_file: str,
        *,
        scope: str,
    ) -> tuple[str, str]:
        parts = relative_file.split("/")
        parent_id = root_id
        prefix: list[str] = []
        for part in parts[:-1]:
            prefix.append(part)
            logical = f"{scope}/{'/'.join(prefix)}"
            parent_id = self._ensure_folder(parent_id, part, logical=logical).file_id
        return parent_id, parts[-1]

    def _project_scope(
        self,
        pack,
        destinations: tuple[_DestinationEntry, ...],
        raw_by_operation: dict[str, bytes],
        *,
        complete: bool,
    ) -> dict[str, DriveItem]:
        work = self._require_folder(self.hub_root_id, "work", label="migration work/")
        projects = self._require_folder(work.file_id, "projects", label="migration work/projects/")
        state_by_project = {entry.project_id: entry for entry in pack.project_initial_states}
        expected_projects = set(state_by_project)
        observed_projects = self.drive.list_children(projects.file_id)
        if len({item.name for item in observed_projects}) != len(observed_projects):
            raise DriveMigrationMaterializationBlocked("migration Projects area is ambiguous")
        if {item.name for item in observed_projects} != expected_projects:
            raise DriveMigrationMaterializationBlocked(
                "migration Projects area no longer matches frozen Project authority"
            )

        project_destinations: dict[str, list[tuple[str, PreservedEntry]]] = {
            project_id: [] for project_id in expected_projects
        }
        for destination in destinations:
            if destination.entry.classification != "PROJECT_WORK_IMPORT":
                continue
            parts = destination.destination.split("/")
            project_id = parts[2]
            relative = "/".join(parts[4:])
            project_destinations[project_id].append((relative, destination.entry))

        result: dict[str, DriveItem] = {}
        for project in observed_projects:
            if project.trashed or not project.is_folder:
                raise DriveMigrationMaterializationBlocked(
                    f"migration Project is not a live folder: {project.name}"
                )
            result[project.name] = project
            state_entry = state_by_project[project.name]
            state_raw = source_file(
                pack.root,
                state_entry.payload,
                f"migration packed Project STATE {project.name}",
            )
            children = self.drive.list_children(project.file_id)
            if len({item.name for item in children}) != len(children):
                raise DriveMigrationMaterializationBlocked(
                    f"migration Project contains duplicate child: {project.name}"
                )
            allowed = {"STATE.md", "results"}
            if project_destinations[project.name]:
                allowed.add("migration-import")
            if not {item.name for item in children}.issubset(allowed):
                raise DriveMigrationMaterializationBlocked(
                    f"migration Project contains unrelated material: {project.name}"
                )
            state = self._unique_live(
                project.file_id,
                "STATE.md",
                label=f"migration Project STATE {project.name}",
            )
            results = self._unique_live(
                project.file_id,
                "results",
                label=f"migration Project results {project.name}",
            )
            expected_state = BlobState(state_entry.sha256, state_entry.size)
            if (
                state is None
                or state.is_folder
                or not expected_state.matches(state)
                or self.drive.download(state.file_id) != state_raw
            ):
                raise DriveMigrationMaterializationBlocked(
                    f"migration Project STATE changed before preservation: {project.name}"
                )
            if results is None or not results.is_folder or self.drive.list_children(results.file_id):
                raise DriveMigrationMaterializationBlocked(
                    f"migration Project results changed before preservation: {project.name}"
                )

            expected = project_destinations[project.name]
            migration_import = self._unique_live(
                project.file_id,
                "migration-import",
                label=f"migration Project import {project.name}",
            )
            if expected:
                if migration_import is not None:
                    if not migration_import.is_folder:
                        raise DriveMigrationMaterializationBlocked(
                            f"migration-import is not a folder: {project.name}"
                        )
                    self._observe_tree(
                        migration_import.file_id,
                        expected,
                        raw_by_operation,
                        scope=f"work/projects/{project.name}/migration-import",
                        complete=complete,
                    )
                elif complete:
                    raise DriveMigrationMaterializationBlocked(
                        f"migration-import is missing: {project.name}"
                    )
            elif migration_import is not None:
                raise DriveMigrationMaterializationBlocked(
                    f"unexpected migration-import folder: {project.name}"
                )
        return result

    def _archive_scope(
        self,
        destinations: tuple[_DestinationEntry, ...],
        raw_by_operation: dict[str, bytes],
        *,
        complete: bool,
    ) -> DriveItem | None:
        entries = [
            ("/".join(item.destination.split("/")[1:]), item.entry)
            for item in destinations
            if item.entry.classification == "ARCHIVE_ONLY"
        ]
        archive = self._unique_live(self.hub_root_id, "archive", label="migration archive/")
        if not entries:
            if archive is not None:
                raise DriveMigrationMaterializationBlocked(
                    "migration target contains unexpected archive/ namespace"
                )
            return None
        if archive is None:
            if complete:
                raise DriveMigrationMaterializationBlocked("migration archive/ namespace is missing")
            return None
        if not archive.is_folder:
            raise DriveMigrationMaterializationBlocked("migration archive/ is not a folder")
        self._observe_tree(
            archive.file_id,
            entries,
            raw_by_operation,
            scope="archive",
            complete=complete,
        )
        return archive

    def run(self, pack_dir: str | Path) -> DriveMigrationMaterializationEvidence:
        try:
            pack = verify_migration_pack(pack_dir)
            source_raw, mapping_raw, destinations = self._authority(pack)
        except MigrationPackBlocked as exc:
            raise DriveMigrationMaterializationBlocked(
                f"private migration pack verification failed before preservation: {exc}"
            ) from exc

        self._require_committed_target(pack)
        raw_by_operation: dict[str, bytes] = {}
        for destination in destinations:
            raw = source_file(
                pack.root,
                destination.entry.payload,
                f"migration preserved payload {destination.entry.operation_id}",
            )
            expected = BlobState(destination.entry.sha256, destination.entry.size)
            if BlobState.from_bytes(raw) != expected:
                raise DriveMigrationMaterializationBlocked(
                    f"migration preserved payload changed: {destination.entry.operation_id}"
                )
            raw_by_operation[destination.entry.operation_id] = raw

        projects = self._project_scope(
            pack,
            destinations,
            raw_by_operation,
            complete=False,
        )
        self._archive_scope(
            destinations,
            raw_by_operation,
            complete=False,
        )

        for destination in destinations:
            parts = destination.destination.split("/")
            if destination.entry.classification == "PROJECT_WORK_IMPORT":
                project_id = parts[2]
                project = projects[project_id]
                migration_import = self._ensure_folder(
                    project.file_id,
                    "migration-import",
                    logical=f"work/projects/{project_id}/migration-import",
                )
                relative = "/".join(parts[4:])
                parent_id, name = self._ensure_relative_parent(
                    migration_import.file_id,
                    relative,
                    scope=f"work/projects/{project_id}/migration-import",
                )
            elif destination.entry.classification == "ARCHIVE_ONLY":
                archive = self._ensure_folder(
                    self.hub_root_id,
                    "archive",
                    logical="archive",
                )
                relative = "/".join(parts[1:])
                parent_id, name = self._ensure_relative_parent(
                    archive.file_id,
                    relative,
                    scope="archive",
                )
            else:
                raise DriveMigrationMaterializationBlocked(
                    f"unsupported preservation classification: {destination.entry.classification}"
                )
            self._ensure_blob(
                parent_id,
                name,
                raw_by_operation[destination.entry.operation_id],
                destination.entry,
                logical=destination.destination,
            )

        self._project_scope(
            pack,
            destinations,
            raw_by_operation,
            complete=True,
        )
        self._archive_scope(
            destinations,
            raw_by_operation,
            complete=True,
        )

        try:
            refreshed = verify_migration_pack(pack.root)
            refreshed_source_raw, refreshed_mapping_raw, refreshed_destinations = self._authority(refreshed)
        except MigrationPackBlocked as exc:
            raise DriveMigrationMaterializationBlocked(
                f"private migration pack changed during preservation: {exc}"
            ) from exc
        if (
            refreshed.manifest_raw != pack.manifest_raw
            or refreshed_source_raw != source_raw
            or refreshed_mapping_raw != mapping_raw
            or refreshed_destinations != destinations
        ):
            raise DriveMigrationMaterializationBlocked(
                "migration pack/authority identity changed during preservation"
            )
        self._require_committed_target(refreshed)

        inventory_raw = canonical_json_bytes(
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
        return DriveMigrationMaterializationEvidence(
            candidate_id=pack.candidate_id,
            pack_sha256=pack.pack_sha256,
            preserved_file_count=len(destinations),
            preserved_total_bytes=pack.preserved_total_bytes,
            project_file_count=sum(
                1 for item in destinations if item.entry.classification == "PROJECT_WORK_IMPORT"
            ),
            archive_file_count=sum(
                1 for item in destinations if item.entry.classification == "ARCHIVE_ONLY"
            ),
            inventory_sha256=sha256(inventory_raw).hexdigest(),
        )


__all__ = [
    "DriveMigrationMaterializationBlocked",
    "DriveMigrationMaterializationEvidence",
    "DriveMigrationPreservationMaterialization",
]
