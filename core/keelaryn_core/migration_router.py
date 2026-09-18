from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from collections.abc import Callable
from typing import Any

from .drive_backend import DriveBackend, DriveItem
from .drive_bootstrap import DriveHubBootstrap, INDEX_NAME
from .drive_transaction import BlobState
from .migration_common import MigrationPackBlocked, source_file
from .migration_materialization import (
    DriveMigrationMaterializationBlocked,
    DriveMigrationPreservationMaterialization,
)
from .migration_pack import verify_migration_pack
from .protocol import ProtocolError


class DriveMigrationRouterPublicationBlocked(ProtocolError):
    """Migration root INDEX publication cannot be proven safe."""


@dataclass(frozen=True)
class DriveMigrationRouterPublicationEvidence:
    candidate_id: str
    pack_sha256: str
    outcome: str
    index_sha256: str
    index_bytes: int
    previous_index_sha256: str

    def to_json_value(self) -> dict[str, Any]:
        return {
            "schema": "keelaryn.migration-router-publication-evidence.v1",
            "candidate_id": self.candidate_id,
            "pack_sha256": self.pack_sha256,
            "outcome": self.outcome,
            "index_sha256": self.index_sha256,
            "index_bytes": self.index_bytes,
            "previous_index_sha256": self.previous_index_sha256,
        }


class DriveMigrationRootIndexPublication:
    """Publish the frozen migration root INDEX after data construction is exact.

    Root ``INDEX.md`` is a human/router artifact, not canonical truth.  A fresh
    zero-based migration target therefore has exactly two acceptable INDEX states:

    * the deterministic bootstrap INDEX; or
    * the exact INDEX bytes frozen in the verified migration pack.

    Publication updates the one existing root blob in place.  That single-object
    content replacement avoids a duplicate/zero-INDEX window.  Crash recovery is
    observational: a rerun accepts the exact packed bytes as already committed and
    rejects every third state.  The deterministic bootstrap bytes are the rollback
    material for this fresh-target-only transition.

    This layer never writes canonical data, Project material, preservation
    namespaces, MASTER.json, README.md, or Reconciliation state.
    """

    def __init__(
        self,
        drive: DriveBackend,
        hub_root_id: str,
        *,
        progress: Callable[[str, int | None, int | None], None] | None = None,
    ):
        self.drive = drive
        self.hub_root_id = hub_root_id
        self.progress = progress

    def _progress(self, phase: str) -> None:
        if self.progress is not None:
            self.progress(phase, None, None)

    @staticmethod
    def _reload_same_pack(pack):
        try:
            refreshed = verify_migration_pack(pack.root)
        except MigrationPackBlocked as exc:
            raise DriveMigrationRouterPublicationBlocked(
                f"private migration pack verification failed during router publication: {exc}"
            ) from exc
        if refreshed.manifest_raw != pack.manifest_raw or refreshed.pack_sha256 != pack.pack_sha256:
            raise DriveMigrationRouterPublicationBlocked(
                "migration pack identity changed during router publication"
            )
        return refreshed

    def _verify_preservation_complete(self, pack):
        """Read-only verification of the exact post-COMMITTED preservation state."""

        service = DriveMigrationPreservationMaterialization(self.drive, self.hub_root_id)
        try:
            source_raw, mapping_raw, destinations = service._authority(pack)
            service._require_committed_target(pack)

            raw_by_operation: dict[str, bytes] = {}
            for destination in destinations:
                raw = source_file(
                    pack.root,
                    destination.entry.payload,
                    f"migration preserved payload {destination.entry.operation_id}",
                )
                expected = BlobState(destination.entry.sha256, destination.entry.size)
                if BlobState.from_bytes(raw) != expected:
                    raise DriveMigrationRouterPublicationBlocked(
                        f"migration preserved payload changed: {destination.entry.operation_id}"
                    )
                raw_by_operation[destination.entry.operation_id] = raw

            service._project_scope(
                pack,
                destinations,
                raw_by_operation,
                complete=True,
            )
            service._archive_scope(
                destinations,
                raw_by_operation,
                complete=True,
            )

            refreshed = self._reload_same_pack(pack)
            refreshed_source_raw, refreshed_mapping_raw, refreshed_destinations = service._authority(
                refreshed
            )
            if (
                refreshed_source_raw != source_raw
                or refreshed_mapping_raw != mapping_raw
                or refreshed_destinations != destinations
            ):
                raise DriveMigrationRouterPublicationBlocked(
                    "migration pack/authority identity changed during preservation verification"
                )
            service._require_committed_target(refreshed)
            return refreshed
        except DriveMigrationRouterPublicationBlocked:
            raise
        except (DriveMigrationMaterializationBlocked, MigrationPackBlocked) as exc:
            raise DriveMigrationRouterPublicationBlocked(
                f"migration preservation is not exact before router publication: {exc}"
            ) from exc

    def _observe_index(self) -> tuple[DriveItem, bytes, BlobState]:
        matches = self.drive.list_children(self.hub_root_id, name=INDEX_NAME)
        if len(matches) != 1:
            raise DriveMigrationRouterPublicationBlocked(
                f"migration target must contain exactly one root {INDEX_NAME}, found {len(matches)}"
            )
        item = matches[0]
        if item.trashed or item.is_folder or item.parent_id != self.hub_root_id:
            raise DriveMigrationRouterPublicationBlocked(
                f"migration root {INDEX_NAME} is not one live root blob"
            )
        raw = self.drive.download(item.file_id)
        state = BlobState.from_bytes(raw)
        if not state.matches(item):
            raise DriveMigrationRouterPublicationBlocked(
                f"migration root {INDEX_NAME} metadata/content fingerprint mismatch"
            )
        return item, raw, state

    @staticmethod
    def _packed_index(pack) -> bytes | None:
        if pack.root_index_size < 0:
            return None
        raw = source_file(pack.root, "root/INDEX.md", "migration packed root INDEX")
        if len(raw) != pack.root_index_size:
            raise DriveMigrationRouterPublicationBlocked(
                "migration packed root INDEX size changed after pack verification"
            )
        return raw

    @staticmethod
    def _evidence(pack, outcome: str, index_raw: bytes) -> DriveMigrationRouterPublicationEvidence:
        bootstrap_raw = DriveHubBootstrap.initial_index_bytes()
        return DriveMigrationRouterPublicationEvidence(
            candidate_id=pack.candidate_id,
            pack_sha256=pack.pack_sha256,
            outcome=outcome,
            index_sha256=sha256(index_raw).hexdigest(),
            index_bytes=len(index_raw),
            previous_index_sha256=sha256(bootstrap_raw).hexdigest(),
        )

    def run(self, pack_dir: str | Path) -> DriveMigrationRouterPublicationEvidence:
        try:
            pack = verify_migration_pack(pack_dir)
        except MigrationPackBlocked as exc:
            raise DriveMigrationRouterPublicationBlocked(
                f"private migration pack verification failed before router publication: {exc}"
            ) from exc

        # The router is the final migration-target data-construction surface.  It
        # may not point at a target whose canonical or preservation material is
        # incomplete, rolled back, ambiguous, or changed after COMMIT.
        self._progress("router-precheck")
        pack = self._verify_preservation_complete(pack)
        target_raw = self._packed_index(pack)
        bootstrap_raw = DriveHubBootstrap.initial_index_bytes()
        item, current_raw, _ = self._observe_index()

        if target_raw is None:
            if current_raw != bootstrap_raw:
                raise DriveMigrationRouterPublicationBlocked(
                    "migration without root INDEX requires unchanged bootstrap INDEX"
                )
            # No mutation, but still re-observe all authority once before claiming
            # the candidate needs no router publication.
            pack = self._verify_preservation_complete(pack)
            current_item, current_raw, _ = self._observe_index()
            if current_item.file_id != item.file_id or current_raw != bootstrap_raw:
                raise DriveMigrationRouterPublicationBlocked(
                    "migration root INDEX changed during no-op router verification"
                )
            return self._evidence(pack, "NOT_REQUIRED", current_raw)

        if current_raw == target_raw:
            # Restart after a response-loss/crash post-update lands here.  Exact
            # bytes plus exact target state are sufficient; no process-local flag
            # is authority.
            pack = self._verify_preservation_complete(pack)
            current_item, current_raw, _ = self._observe_index()
            if current_raw != target_raw:
                raise DriveMigrationRouterPublicationBlocked(
                    "migration root INDEX changed during committed router verification"
                )
            return self._evidence(pack, "COMMITTED", current_raw)

        if current_raw != bootstrap_raw:
            raise DriveMigrationRouterPublicationBlocked(
                "migration root INDEX is neither bootstrap nor exact packed router bytes"
            )

        # Fresh validation at the commit boundary.  Besides pack/target identity,
        # require the exact same INDEX object observation so a same-byte external
        # rewrite or replacement cannot be silently blessed by this run.
        pack = self._verify_preservation_complete(pack)
        target_raw = self._packed_index(pack)
        assert target_raw is not None
        commit_item, commit_raw, _ = self._observe_index()
        if commit_item != item or commit_raw != bootstrap_raw:
            raise DriveMigrationRouterPublicationBlocked(
                "migration root INDEX identity changed before router commit"
            )

        self._progress("router-commit")
        self.drive.replace_blob_content(
            commit_item,
            target_raw,
            label=f"drive.migration.router.{pack.candidate_id}.index.update",
        )

        committed_item, committed_raw, _ = self._observe_index()
        if committed_item.file_id != item.file_id or committed_raw != target_raw:
            raise DriveMigrationRouterPublicationBlocked(
                "migration root INDEX durable update did not become exact"
            )

        # A failure below is explicitly post-commit: the INDEX update has already
        # become durable.  Do not pretend it did not happen or overwrite it with
        # guessed rollback state; a rerun re-observes COMMITTED bytes safely.
        self._progress("router-postcheck")
        try:
            pack = self._verify_preservation_complete(pack)
            final_item, final_raw, _ = self._observe_index()
            if final_item.file_id != item.file_id or final_raw != target_raw:
                raise DriveMigrationRouterPublicationBlocked(
                    "migration root INDEX changed after durable router commit"
                )
        except DriveMigrationRouterPublicationBlocked as exc:
            raise DriveMigrationRouterPublicationBlocked(
                "migration root INDEX durable commit succeeded but post-commit verification failed: "
                f"{exc}"
            ) from exc

        return self._evidence(pack, "COMMITTED", final_raw)


__all__ = [
    "DriveMigrationRootIndexPublication",
    "DriveMigrationRouterPublicationBlocked",
    "DriveMigrationRouterPublicationEvidence",
]
