from __future__ import annotations

from pathlib import Path

from .migration_common import MIGRATION_SOURCE_NAME, MigrationPackBlocked, small_file
from .migration_drive_source import (
    DriveMigrationSourceBlocked,
    verify_migration_source_against_drive,
)
from .migration_production_qualification import (
    DriveMigrationProductionQualificationBlocked,
    DriveMigrationProductionTargetQualification,
)
from .migration_source import parse_source


class DriveAuthoritativeMigrationProductionTargetQualification(
    DriveMigrationProductionTargetQualification
):
    """Production-target qualification against the authoritative legacy Drive Hub.

    The frozen MIGRATION_SOURCE content boundary remains the candidate authority.
    The Drive root ID is only the live source endpoint used for fresh pre- and
    post-construction revalidation; no local synchronized checkout participates in
    production qualification.
    """

    def __init__(
        self,
        drive,
        staging_root_id: str,
        legacy_source_root_id: str,
        *,
        progress=None,
    ) -> None:
        super().__init__(drive, staging_root_id, progress=progress)
        if not isinstance(legacy_source_root_id, str) or not legacy_source_root_id:
            raise DriveMigrationProductionQualificationBlocked(
                "legacy Drive source root ID is invalid"
            )
        self.legacy_source_root_id = legacy_source_root_id

    def _verify_live_source(
        self,
        pack,
        _unused_local_source_root,
        *,
        phase: str,
    ) -> None:
        source_raw = small_file(
            pack.root / "authority" / MIGRATION_SOURCE_NAME,
            "frozen migration source authority",
        )
        source = parse_source(source_raw)
        if source.candidate_id != pack.candidate_id:
            raise DriveMigrationProductionQualificationBlocked(
                "frozen source candidate identity disagrees with migration pack"
            )
        try:
            verify_migration_source_against_drive(
                self.drive,
                self.legacy_source_root_id,
                source,
                progress=self._source_progress,
                phase=phase,
            )
        except (DriveMigrationSourceBlocked, MigrationPackBlocked) as exc:
            raise DriveMigrationProductionQualificationBlocked(
                f"live legacy Drive source verification failed: {exc}"
            ) from exc

    def run_drive(
        self,
        pack_dir: str | Path,
        freeze_receipt: str | Path,
        repo_root: str | Path,
        target_authority_path: str | Path,
        qualification_evidence_path: str | Path,
    ):
        # The parent implementation invokes self._verify_live_source() at both
        # transaction boundaries. Pass a deliberately non-authoritative sentinel
        # local path so any future accidental filesystem use fails closed instead
        # of silently falling back to a synchronized checkout.
        unused_local_source = Path(repo_root) / ".keelaryn-drive-source-unused"
        return super().run(
            pack_dir,
            freeze_receipt,
            repo_root,
            unused_local_source,
            target_authority_path,
            qualification_evidence_path,
        )


__all__ = ["DriveAuthoritativeMigrationProductionTargetQualification"]
