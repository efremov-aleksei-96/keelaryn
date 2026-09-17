from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))

from keelaryn_core.drive_model import DriveModel  # noqa: E402
from keelaryn_core.migration_freeze import freeze_migration_candidate  # noqa: E402
from keelaryn_core.migration_pack import (  # noqa: E402
    build_migration_pack,
    capture_migration_source,
    verify_migration_source,
)
from keelaryn_core.migration_production_drive_qualification import (  # noqa: E402
    DriveAuthoritativeMigrationProductionTargetQualification,
)
from keelaryn_core.migration_production_qualification import (  # noqa: E402
    DriveMigrationProductionPostConstructionBlocked,
    DriveMigrationProductionQualificationBlocked,
    STAGING_ROOT_NAME,
    STAGING_SENTINEL_BYTES,
    STAGING_SENTINEL_NAME,
)
from keelaryn_core.migration_rehearsal import DriveMigrationDisposableRehearsal  # noqa: E402
from keelaryn_core.protocol import canonical_json_bytes  # noqa: E402


class MigrationProductionDriveQualificationTests(unittest.TestCase):
    @staticmethod
    def _git(repo: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            encoding="utf-8",
        )
        return result.stdout.strip()

    def _repo(self, root: Path) -> tuple[Path, str, str]:
        repo = root / "repo"
        repo.mkdir()
        self._git(repo, "init")
        self._git(repo, "config", "user.name", "Keelaryn Test")
        self._git(repo, "config", "user.email", "keelaryn-test@example.invalid")
        (repo / "tracked.txt").write_bytes(b"exact source\n")
        self._git(repo, "add", "tracked.txt")
        self._git(repo, "commit", "-m", "exact source")
        return repo, self._git(repo, "rev-parse", "HEAD"), self._git(repo, "rev-parse", "HEAD^{tree}")

    def _candidate(self, root: Path, repo: Path, commit: str, tree: str):
        source = root / "source-materialization"
        source.mkdir()
        (source / "identity.md").write_bytes(b"legacy identity\r\n")
        selection = root / "selection.json"
        selection.write_bytes(
            canonical_json_bytes(
                {
                    "schema": "keelaryn.migration-selection.v1",
                    "candidate_id": "migration-drive-production-001",
                    "sources": ["identity.md"],
                }
            )
        )
        source_manifest = root / "source.json"
        capture_migration_source(source, selection, source_manifest)
        mapping = root / "mapping.json"
        mapping.write_bytes(
            canonical_json_bytes(
                {
                    "schema": "keelaryn.migration-mapping.v1",
                    "candidate_id": "migration-drive-production-001",
                    "source_manifest_sha256": verify_migration_source(source_manifest).digest,
                    "source_actions": [
                        {"source": "identity.md", "classification": "CANONICAL_IMPORT"}
                    ],
                    "canonical_outputs": [
                        {
                            "target": "identity/profile.md",
                            "semantic_sources": ["identity.md"],
                            "payload": {"kind": "SOURCE", "source": "identity.md"},
                        }
                    ],
                    "root_index": None,
                }
            )
        )
        pack = build_migration_pack(source, source_manifest, mapping, root / "pack")
        freeze = root / "freeze.json"
        freeze_migration_candidate(pack.root, repo, commit, tree, freeze)
        return pack, freeze

    @staticmethod
    def _drive_fixture(drive: DriveModel) -> tuple[str, str]:
        source_root = drive.create_folder("root", "legacy-hub").file_id
        drive.create_blob(source_root, "identity.md", b"legacy identity\r\n")
        staging = drive.create_folder("root", STAGING_ROOT_NAME).file_id
        drive.create_blob(staging, STAGING_SENTINEL_NAME, STAGING_SENTINEL_BYTES)
        return source_root, staging

    def _fixture(self, root: Path):
        repo, commit, tree = self._repo(root)
        pack, freeze = self._candidate(root, repo, commit, tree)
        drive = DriveModel()
        source_root, staging = self._drive_fixture(drive)
        authority = root / "target-authority.json"
        evidence = root / "qualification.json"
        gate = DriveAuthoritativeMigrationProductionTargetQualification(
            drive,
            staging,
            source_root,
        )
        return repo, pack, freeze, drive, source_root, staging, authority, evidence, gate

    def test_exact_drive_source_qualifies_without_local_source_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, pack, freeze, drive, source_root, _, authority, evidence, gate = self._fixture(root)
            source_item = drive.exact_name(source_root, "identity.md")
            assert source_item is not None
            source_before = drive.get(source_item.file_id)
            bytes_before = drive.download(source_item.file_id)

            result = gate.run_drive(pack.root, freeze, repo, authority, evidence)

            self.assertEqual(result.outcome, "TARGET_QUALIFICATION_PASS")
            self.assertEqual(drive.get(source_item.file_id), source_before)
            self.assertEqual(drive.download(source_item.file_id), bytes_before)
            self.assertNotIn(source_root, authority.read_text(encoding="utf-8"))
            self.assertNotIn(source_root, evidence.read_text(encoding="utf-8"))
            self.assertFalse((repo / ".keelaryn-drive-source-unused").exists())

    def test_drive_source_drift_blocks_before_target_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, pack, freeze, drive, source_root, staging, authority, evidence, gate = self._fixture(root)
            source_item = drive.exact_name(source_root, "identity.md")
            assert source_item is not None
            drive.update_content(source_item.file_id, b"changed before qualification\n")

            with self.assertRaisesRegex(
                DriveMigrationProductionQualificationBlocked,
                "legacy Drive source",
            ):
                gate.run_drive(pack.root, freeze, repo, authority, evidence)

            self.assertFalse(authority.exists())
            self.assertFalse(evidence.exists())
            self.assertEqual(len(drive.list_children(staging)), 1)

    def test_case_conflicting_drive_source_blocks_before_target_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, pack, freeze, drive, source_root, _, authority, evidence, gate = self._fixture(root)
            drive.create_blob(source_root, "Identity.md", b"conflict\n")

            with self.assertRaisesRegex(
                DriveMigrationProductionQualificationBlocked,
                "legacy Drive source",
            ):
                gate.run_drive(pack.root, freeze, repo, authority, evidence)

            self.assertFalse(authority.exists())
            self.assertFalse(evidence.exists())

    def test_post_construction_drive_source_drift_is_distinguished(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, pack, freeze, drive, source_root, _, authority, evidence, gate = self._fixture(root)
            source_item = drive.exact_name(source_root, "identity.md")
            assert source_item is not None
            original = DriveMigrationDisposableRehearsal.run

            def run_then_drift(service, pack_dir):
                value = original(service, pack_dir)
                drive.update_content(source_item.file_id, b"changed after construction\n")
                return value

            with patch.object(DriveMigrationDisposableRehearsal, "run", new=run_then_drift):
                with self.assertRaisesRegex(
                    DriveMigrationProductionPostConstructionBlocked,
                    "durably constructed",
                ):
                    gate.run_drive(pack.root, freeze, repo, authority, evidence)

            self.assertTrue(authority.is_file())
            self.assertFalse(evidence.exists())
            target_id = json.loads(authority.read_text(encoding="utf-8"))["target_id"]
            target = drive.get(target_id, include_trashed=False)
            self.assertTrue(target.is_folder)
            canonical = drive.exact_name(target_id, "canonical")
            self.assertIsNotNone(canonical)


if __name__ == "__main__":
    unittest.main(verbosity=2)
