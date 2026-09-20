from __future__ import annotations

import os
import stat
import uuid
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from .drive_backend import DriveBackend, DriveNotFound, DriveUncertainMutation
from .migration_common import (
    MIGRATION_SOURCE_NAME,
    MigrationPackBlocked,
    real_directory,
    small_file,
    source_file,
)
from .migration_freeze import verify_migration_candidate_freeze
from .migration_pack import verify_migration_pack
from .migration_rehearsal import (
    DriveMigrationDisposableRehearsal,
    DriveMigrationRehearsalBlocked,
)
from .migration_source import parse_source
from .protocol import ProtocolError, canonical_json_bytes, strict_json_bytes


STAGING_ROOT_NAME = "Keelaryn__PRODUCTION_MIGRATION_STAGING_ROOT"
STAGING_SENTINEL_NAME = "README.md"
STAGING_SENTINEL_BYTES = (
    b"KEELARYN PRODUCTION MIGRATION STAGING ROOT\n"
    b"NEW ZERO-BASED TARGETS ONLY. NEVER POINT THIS GATE AT AN EXISTING HUB.\n"
)
TARGET_PREFIX = "Keelaryn__ZeroBased_Migration_"
TARGET_AUTHORITY_SCHEMA = "keelaryn.migration-production-target-authority.v1"
TARGET_EVIDENCE_SCHEMA = "keelaryn.migration-production-target-qualification.v1"
PRIVATE_OUTPUT_MODE = 0o600


def _fsync_dir(path: Path) -> None:
    if os.name != "posix":
        return
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        # The file itself is fsync'd before publication. Directory fsync is a
        # best-effort durability reinforcement on filesystems that support it.
        pass


def _private_regular_file(path: Path, label: str) -> Path:
    candidate = path.absolute()
    try:
        info = candidate.stat(follow_symlinks=False)
    except OSError as exc:
        raise DriveMigrationProductionQualificationBlocked(
            f"{label} cannot be inspected"
        ) from exc
    if candidate.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise DriveMigrationProductionQualificationBlocked(
            f"{label} must be one regular file"
        )
    if os.name == "posix":
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != PRIVATE_OUTPUT_MODE:
            raise DriveMigrationProductionQualificationBlocked(
                f"{label} must be owner-controlled mode 0600"
            )
    return candidate


def _atomic_write_private_new(path: Path, raw: bytes, label: str) -> Path:
    output = path.absolute()
    parent = real_directory(output.parent, f"{label} parent")
    output = parent / output.name
    if output.exists() or output.is_symlink():
        raise DriveMigrationProductionQualificationBlocked(
            f"{label} already exists"
        )

    staging = parent / f".{output.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(staging, flags, PRIVATE_OUTPUT_MODE)
        try:
            if os.name == "posix":
                os.fchmod(fd, PRIVATE_OUTPUT_MODE)
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(fd)

        _private_regular_file(staging, f"{label} staging file")
        if output.exists() or output.is_symlink():
            raise DriveMigrationProductionQualificationBlocked(
                f"{label} appeared before publication"
            )

        if os.name == "posix":
            # Hard-link publication is same-directory and no-replace: if another
            # object appears at the final path, link() fails instead of replacing it.
            os.link(staging, output, follow_symlinks=False)
            _fsync_dir(parent)
            staging.unlink()
        else:
            # Windows rename fails when the destination already exists.
            staging.rename(output)
        _fsync_dir(parent)
        return _private_regular_file(output, label)
    except FileExistsError as exc:
        raise DriveMigrationProductionQualificationBlocked(
            f"{label} appeared before publication"
        ) from exc
    finally:
        try:
            staging.unlink(missing_ok=True)
        except OSError:
            pass


class DriveMigrationProductionQualificationBlocked(ProtocolError):
    """Production-target construction or qualification cannot proceed safely."""


class DriveMigrationProductionPostConstructionBlocked(
    DriveMigrationProductionQualificationBlocked
):
    """Target construction completed, but fresh post-construction qualification failed."""


@dataclass(frozen=True)
class DriveMigrationProductionQualificationEvidence:
    candidate_id: str
    pack_sha256: str
    source_commit: str
    source_tree: str
    source_manifest_sha256: str
    mapping_manifest_sha256: str
    frozen_canonical_inventory_sha256: str
    frozen_project_state_inventory_sha256: str
    frozen_preservation_inventory_sha256: str
    frozen_root_index_sha256: str | None
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
    reader_epoch: int
    no_op_phase: str
    restart_state: str
    outcome: str

    def to_json_value(self) -> dict[str, Any]:
        return {
            "schema": TARGET_EVIDENCE_SCHEMA,
            "candidate_id": self.candidate_id,
            "pack_sha256": self.pack_sha256,
            "source_commit": self.source_commit,
            "source_tree": self.source_tree,
            "source_manifest_sha256": self.source_manifest_sha256,
            "mapping_manifest_sha256": self.mapping_manifest_sha256,
            "frozen_canonical_inventory_sha256": self.frozen_canonical_inventory_sha256,
            "frozen_project_state_inventory_sha256": self.frozen_project_state_inventory_sha256,
            "frozen_preservation_inventory_sha256": self.frozen_preservation_inventory_sha256,
            "frozen_root_index_sha256": self.frozen_root_index_sha256,
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
            "reader_epoch": self.reader_epoch,
            "no_op_phase": self.no_op_phase,
            "restart_state": self.restart_state,
            "outcome": self.outcome,
            "cutover_authorized": False,
        }


class DriveMigrationProductionTargetQualification:
    """Construct and qualify one new production *target* without selecting it.

    The service is deliberately not a cutover mechanism. It accepts only a guarded
    staging root, persists the reserved Drive target ID in private local authority
    before creation, constructs the target through the existing restart-safe
    migration rehearsal path, and publishes sanitized qualification evidence only
    after fresh source/freeze/pack revalidation.
    """

    def __init__(
        self,
        drive: DriveBackend,
        staging_root_id: str,
        *,
        progress: Callable[[dict[str, object]], None] | None = None,
    ):
        self.drive = drive
        self.staging_root_id = staging_root_id
        self._progress_callback = progress
        self._mutation_state = "MUTATION_NOT_STARTED"
        self._authority_state = "ABSENT"
        self._target_state = "ABSENT"
        self._evidence_state = "ABSENT"

    def _emit(self, value: dict[str, object]) -> None:
        if self._progress_callback is None:
            return
        enriched = dict(value)
        enriched.setdefault("mutation_state", self._mutation_state)
        enriched.setdefault("authority_state", self._authority_state)
        enriched.setdefault("target_state", self._target_state)
        enriched.setdefault("evidence_state", self._evidence_state)
        self._progress_callback(enriched)

    def _source_progress(self, value: dict[str, int | str]) -> None:
        self._emit(dict(value))

    @staticmethod
    def _private_output_path(path: Path, repo: Path, pack_root: Path, label: str) -> Path:
        candidate = path.absolute().resolve(strict=False)
        repo_resolved = repo.resolve()
        pack_resolved = pack_root.resolve()
        if candidate == repo_resolved or repo_resolved in candidate.parents:
            raise DriveMigrationProductionQualificationBlocked(
                f"{label} must remain outside the Git worktree"
            )
        if candidate == pack_resolved or pack_resolved in candidate.parents:
            raise DriveMigrationProductionQualificationBlocked(
                f"{label} must remain outside the immutable migration pack"
            )
        return candidate

    def _verify_staging_root(
        self,
        target_id: str | None = None,
        target_name: str | None = None,
    ) -> None:
        try:
            root = self.drive.get(self.staging_root_id, include_trashed=False)
        except DriveNotFound as exc:
            raise DriveMigrationProductionQualificationBlocked(
                "production migration staging root does not exist"
            ) from exc
        if root.trashed or not root.is_folder or root.name != STAGING_ROOT_NAME:
            raise DriveMigrationProductionQualificationBlocked(
                "target is not the exact production migration staging root"
            )
        sentinels = self.drive.list_children(
            self.staging_root_id,
            name=STAGING_SENTINEL_NAME,
        )
        if len(sentinels) != 1 or sentinels[0].trashed or sentinels[0].is_folder:
            raise DriveMigrationProductionQualificationBlocked(
                "production migration staging sentinel is missing or ambiguous"
            )
        if self.drive.download(sentinels[0].file_id) != STAGING_SENTINEL_BYTES:
            raise DriveMigrationProductionQualificationBlocked(
                "production migration staging sentinel bytes do not match"
            )
        children = self.drive.list_children(self.staging_root_id)
        allowed = {sentinels[0].file_id}
        if target_id is not None:
            if not isinstance(target_name, str) or not target_name:
                raise DriveMigrationProductionQualificationBlocked(
                    "exact production target name is required with target identity"
                )
            target = next((child for child in children if child.file_id == target_id), None)
            if (
                target is None
                or target.trashed
                or not target.is_folder
                or target.parent_id != self.staging_root_id
                or target.name != target_name
            ):
                raise DriveMigrationProductionQualificationBlocked(
                    "reserved production target is no longer the exact staging child"
                )
            allowed.add(target_id)
        elif target_name is not None:
            raise DriveMigrationProductionQualificationBlocked(
                "production target name cannot be verified without target identity"
            )
        for child in children:
            if child.file_id not in allowed:
                raise DriveMigrationProductionQualificationBlocked(
                    "unexpected object exists in production migration staging root"
                )

    def _verify_live_source(
        self,
        pack,
        legacy_source_root: str | Path,
        *,
        phase: str,
    ) -> None:
        root = real_directory(Path(legacy_source_root), "live legacy migration source root")
        source_raw = small_file(
            pack.root / "authority" / MIGRATION_SOURCE_NAME,
            "frozen migration source authority",
        )
        source = parse_source(source_raw)
        if source.candidate_id != pack.candidate_id:
            raise DriveMigrationProductionQualificationBlocked(
                "frozen source candidate identity disagrees with migration pack"
            )
        item_total = len(source.entries)
        self._emit(
            {
                "phase": phase,
                "event": "SOURCE_PASS_BEGIN",
                "pass_index": 1,
                "pass_total": 1,
                "item_index": 0,
                "item_total": item_total,
            }
        )
        for item_index, entry in enumerate(source.entries, start=1):
            raw = source_file(root, entry.source, "live legacy migration source")
            if sha256(raw).hexdigest() != entry.sha256 or len(raw) != entry.size:
                raise DriveMigrationProductionQualificationBlocked(
                    "live legacy source no longer matches frozen migration source boundary"
                )
            self._emit(
                {
                    "phase": phase,
                    "event": "SOURCE_ITEM_COMPLETE",
                    "pass_index": 1,
                    "pass_total": 1,
                    "item_index": item_index,
                    "item_total": item_total,
                }
            )
        self._emit(
            {
                "phase": phase,
                "event": "SOURCE_VERIFY_COMPLETE",
                "pass_index": 1,
                "pass_total": 1,
                "item_index": item_total,
                "item_total": item_total,
            }
        )

    @staticmethod
    def _strict_authority(raw: bytes) -> dict[str, Any]:
        try:
            value = strict_json_bytes(raw, label="MIGRATION_PRODUCTION_TARGET_AUTHORITY")
        except ProtocolError as exc:
            raise DriveMigrationProductionQualificationBlocked(str(exc)) from exc
        if not isinstance(value, dict) or set(value) != {
            "schema",
            "candidate_id",
            "pack_sha256",
            "staging_root_id",
            "target_id",
            "target_name",
        }:
            raise DriveMigrationProductionQualificationBlocked(
                "MIGRATION_PRODUCTION_TARGET_AUTHORITY: keys mismatch"
            )
        if value["schema"] != TARGET_AUTHORITY_SCHEMA:
            raise DriveMigrationProductionQualificationBlocked(
                "MIGRATION_PRODUCTION_TARGET_AUTHORITY: schema mismatch"
            )
        for key in ("candidate_id", "pack_sha256", "staging_root_id", "target_id", "target_name"):
            if not isinstance(value[key], str) or not value[key]:
                raise DriveMigrationProductionQualificationBlocked(
                    f"MIGRATION_PRODUCTION_TARGET_AUTHORITY.{key}: invalid"
                )
        return value

    def _target_authority(self, pack, path: Path) -> dict[str, Any]:
        target_name = TARGET_PREFIX + pack.candidate_id
        if path.exists() or path.is_symlink():
            authority_file = _private_regular_file(
                path,
                "migration production target authority",
            )
            value = self._strict_authority(
                small_file(authority_file, "migration production target authority")
            )
            expected = {
                "schema": TARGET_AUTHORITY_SCHEMA,
                "candidate_id": pack.candidate_id,
                "pack_sha256": pack.pack_sha256,
                "staging_root_id": self.staging_root_id,
                "target_id": value["target_id"],
                "target_name": target_name,
            }
            if value != expected:
                raise DriveMigrationProductionQualificationBlocked(
                    "production target authority disagrees with exact candidate/staging identity"
                )
            return value

        self._verify_staging_root()
        target_id = self.drive.generate_ids(1)[0]
        value = {
            "schema": TARGET_AUTHORITY_SCHEMA,
            "candidate_id": pack.candidate_id,
            "pack_sha256": pack.pack_sha256,
            "staging_root_id": self.staging_root_id,
            "target_id": target_id,
            "target_name": target_name,
        }
        _atomic_write_private_new(
            path,
            canonical_json_bytes(value),
            "migration production target authority",
        )
        return value

    def _ensure_target(self, authority: dict[str, Any]):
        target_id = authority["target_id"]
        target_name = authority["target_name"]
        try:
            item = self.drive.get(target_id, include_trashed=True)
        except DriveNotFound:
            # Fresh validation at the mutation boundary is required even on restart
            # from an already durable target authority. A conflicting staging child
            # appearing after authority publication must block before target create.
            self._verify_staging_root()
            self._mutation_state = "MUTATION_ACTIVE"
            self._emit(
                {
                    "phase": "TARGET_CREATE",
                    "event": "MUTATION_BOUNDARY",
                }
            )
            try:
                self.drive.create_folder(
                    self.staging_root_id,
                    target_name,
                    file_id=target_id,
                    label="drive.migration.production-target.create",
                )
            except DriveUncertainMutation:
                pass
            try:
                item = self.drive.get(target_id, include_trashed=True)
            except DriveNotFound as exc:
                raise DriveMigrationProductionQualificationBlocked(
                    "reserved production target ID is not observable after creation attempt"
                ) from exc
        if (
            item.trashed
            or not item.is_folder
            or item.parent_id != self.staging_root_id
            or item.name != target_name
        ):
            raise DriveMigrationProductionQualificationBlocked(
                "reserved production target ID resolves to conflicting Drive object"
            )
        self._verify_staging_root(target_id, target_name)
        self._mutation_state = "MUTATION_COMMITTED"
        self._target_state = "PRESENT"
        self._emit(
            {
                "phase": "TARGET_CREATE",
                "event": "TARGET_OBSERVED",
            }
        )
        return item

    @staticmethod
    def _publish_evidence(path: Path, raw: bytes) -> None:
        try:
            if path.exists() or path.is_symlink():
                evidence_file = _private_regular_file(
                    path,
                    "migration production qualification evidence",
                )
                existing = small_file(
                    evidence_file,
                    "migration production qualification evidence",
                )
                if existing != raw:
                    raise MigrationPackBlocked(
                        "production qualification evidence already exists with different identity"
                    )
            else:
                _atomic_write_private_new(
                    path,
                    raw,
                    "migration production qualification evidence",
                )
        except (
            DriveMigrationProductionQualificationBlocked,
            MigrationPackBlocked,
            OSError,
        ) as exc:
            raise DriveMigrationProductionPostConstructionBlocked(
                "production target is durably constructed, but qualification evidence publication failed"
            ) from exc

    def run(
        self,
        pack_dir: str | Path,
        freeze_receipt: str | Path,
        repo_root: str | Path,
        legacy_source_root: str | Path,
        target_authority_path: str | Path,
        qualification_evidence_path: str | Path,
    ) -> DriveMigrationProductionQualificationEvidence:
        self._mutation_state = "MUTATION_NOT_STARTED"
        self._authority_state = "ABSENT"
        self._target_state = "ABSENT"
        self._evidence_state = "ABSENT"
        self._emit(
            {
                "phase": "PACK_FREEZE_VERIFY",
                "event": "PHASE_BEGIN",
            }
        )
        try:
            pack = verify_migration_pack(pack_dir)
            freeze = verify_migration_candidate_freeze(pack.root, freeze_receipt, repo_root)
        except MigrationPackBlocked as exc:
            raise DriveMigrationProductionQualificationBlocked(
                f"frozen migration candidate verification failed: {exc}"
            ) from exc
        self._emit(
            {
                "phase": "PACK_FREEZE_VERIFY",
                "event": "PHASE_COMPLETE",
            }
        )
        repo = real_directory(Path(repo_root), "migration qualification repository root")
        authority_path = self._private_output_path(
            Path(target_authority_path), repo, pack.root, "production target authority"
        )
        evidence_path = self._private_output_path(
            Path(qualification_evidence_path), repo, pack.root, "production qualification evidence"
        )
        if authority_path == evidence_path:
            raise DriveMigrationProductionQualificationBlocked(
                "production target authority and qualification evidence must be distinct files"
            )

        self._verify_live_source(
            pack,
            legacy_source_root,
            phase="SOURCE_VERIFY_PRE",
        )
        self._emit(
            {
                "phase": "TARGET_AUTHORITY",
                "event": "PHASE_BEGIN",
            }
        )
        authority = self._target_authority(pack, authority_path)
        self._authority_state = "PRESENT"
        self._emit(
            {
                "phase": "TARGET_AUTHORITY",
                "event": "AUTHORITY_DURABLE",
            }
        )
        target = self._ensure_target(authority)

        self._mutation_state = "MUTATION_ACTIVE"
        self._emit(
            {
                "phase": "REHEARSAL",
                "event": "PHASE_BEGIN",
            }
        )
        try:
            rehearsal = DriveMigrationDisposableRehearsal(self.drive, target.file_id).run(pack.root)
        except DriveMigrationRehearsalBlocked as exc:
            raise DriveMigrationProductionQualificationBlocked(
                f"production target construction/rehearsal failed: {exc}"
            ) from exc
        self._mutation_state = "MUTATION_COMMITTED"
        self._emit(
            {
                "phase": "REHEARSAL",
                "event": "PHASE_COMPLETE",
            }
        )

        self._emit(
            {
                "phase": "PACK_FREEZE_VERIFY_POST",
                "event": "PHASE_BEGIN",
            }
        )
        try:
            final_pack = verify_migration_pack(pack.root)
            final_freeze = verify_migration_candidate_freeze(
                final_pack.root,
                freeze_receipt,
                repo,
            )
            self._emit(
                {
                    "phase": "PACK_FREEZE_VERIFY_POST",
                    "event": "PHASE_COMPLETE",
                }
            )
            self._verify_live_source(
                final_pack,
                legacy_source_root,
                phase="SOURCE_VERIFY_POST",
            )
            self._emit(
                {
                    "phase": "STAGING_VERIFY_POST",
                    "event": "PHASE_BEGIN",
                }
            )
            self._verify_staging_root(target.file_id, authority["target_name"])
            self._emit(
                {
                    "phase": "STAGING_VERIFY_POST",
                    "event": "PHASE_COMPLETE",
                }
            )
        except (MigrationPackBlocked, DriveMigrationProductionQualificationBlocked) as exc:
            raise DriveMigrationProductionPostConstructionBlocked(
                "production target is durably constructed, but fresh post-construction qualification failed"
            ) from exc
        if final_pack.pack_sha256 != pack.pack_sha256 or final_freeze != freeze:
            raise DriveMigrationProductionPostConstructionBlocked(
                "production target is durably constructed, but frozen candidate identity changed"
            )

        evidence = DriveMigrationProductionQualificationEvidence(
            candidate_id=pack.candidate_id,
            pack_sha256=pack.pack_sha256,
            source_commit=freeze["source_commit"],
            source_tree=freeze["source_tree"],
            source_manifest_sha256=freeze["source_manifest_sha256"],
            mapping_manifest_sha256=freeze["mapping_manifest_sha256"],
            frozen_canonical_inventory_sha256=freeze["canonical_inventory_sha256"],
            frozen_project_state_inventory_sha256=freeze["project_state_inventory_sha256"],
            frozen_preservation_inventory_sha256=freeze["preservation_inventory_sha256"],
            frozen_root_index_sha256=freeze["root_index_sha256"],
            target_identity_sha256=sha256(target.file_id.encode("utf-8")).hexdigest(),
            staging_identity_sha256=sha256(self.staging_root_id.encode("utf-8")).hexdigest(),
            canonical_epoch=rehearsal.canonical_epoch,
            canonical_file_count=rehearsal.canonical_file_count,
            canonical_total_bytes=rehearsal.canonical_total_bytes,
            canonical_inventory_sha256=rehearsal.canonical_inventory_sha256,
            preserved_file_count=rehearsal.preserved_file_count,
            preserved_total_bytes=rehearsal.preserved_total_bytes,
            preservation_inventory_sha256=rehearsal.preservation_inventory_sha256,
            project_count=rehearsal.project_count,
            reconciliation_state_sha256=rehearsal.reconciliation_state_sha256,
            router_outcome=rehearsal.router_outcome,
            root_index_sha256=rehearsal.root_index_sha256,
            reader_epoch=rehearsal.reader_epoch,
            no_op_phase=rehearsal.no_op_phase,
            restart_state=rehearsal.restart_state,
            outcome="TARGET_QUALIFICATION_PASS",
        )
        self._emit(
            {
                "phase": "EVIDENCE_PUBLISH",
                "event": "PHASE_BEGIN",
            }
        )
        self._publish_evidence(evidence_path, canonical_json_bytes(evidence.to_json_value()))
        self._evidence_state = "PRESENT"
        self._emit(
            {
                "phase": "EVIDENCE_PUBLISH",
                "event": "EVIDENCE_DURABLE",
            }
        )
        self._emit(
            {
                "phase": "COMPLETE",
                "event": "QUALIFICATION_COMPLETE",
            }
        )
        return evidence


__all__ = [
    "DriveMigrationProductionQualificationBlocked",
    "DriveMigrationProductionPostConstructionBlocked",
    "DriveMigrationProductionQualificationEvidence",
    "DriveMigrationProductionTargetQualification",
    "STAGING_ROOT_NAME",
    "STAGING_SENTINEL_NAME",
    "STAGING_SENTINEL_BYTES",
    "TARGET_AUTHORITY_SCHEMA",
    "TARGET_EVIDENCE_SCHEMA",
    "TARGET_PREFIX",
]
