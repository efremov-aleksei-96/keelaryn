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
from keelaryn_core.migration_production_qualification import (  # noqa: E402
    DriveMigrationProductionPostConstructionBlocked,
    DriveMigrationProductionQualificationBlocked,
    DriveMigrationProductionTargetQualification,
    STAGING_ROOT_NAME,
    STAGING_SENTINEL_BYTES,
    STAGING_SENTINEL_NAME,
    TARGET_PREFIX,
)
from keelaryn_core.migration_rehearsal import DriveMigrationDisposableRehearsal  # noqa: E402
from keelaryn_core.protocol import FaultInjector, InjectedCrash, canonical_json_bytes  # noqa: E402


class MigrationProductionQualificationTests(unittest.TestCase):
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
        source = root / "legacy-source"
        source.mkdir()
        (source / "identity.md").write_bytes(b"legacy identity\r\n")

        selection = root / "selection.json"
        selection.write_bytes(
            canonical_json_bytes(
                {
                    "schema": "keelaryn.migration-selection.v1",
                    "candidate_id": "migration-production-001",
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
                    "candidate_id": "migration-production-001",
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
        return source, pack, freeze

    @staticmethod
    def _staging(drive: DriveModel) -> str:
        root = drive.create_folder("root", STAGING_ROOT_NAME)
        drive.create_blob(root.file_id, STAGING_SENTINEL_NAME, STAGING_SENTINEL_BYTES)
        return root.file_id

    def _fixture(self, root: Path, *, fault: FaultInjector | None = None):
        repo, commit, tree = self._repo(root)
        source, pack, freeze = self._candidate(root, repo, commit, tree)
        drive = DriveModel(fault=fault)
        staging = self._staging(drive)
        authority = root / "target-authority.json"
        evidence = root / "target-evidence.json"
        return repo, source, pack, freeze, drive, staging, authority, evidence

    def test_constructs_exact_target_and_replays_without_cutover_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, source, pack, freeze, drive, staging, authority, evidence = self._fixture(root)
            gate = DriveMigrationProductionTargetQualification(drive, staging)

            first = gate.run(pack.root, freeze, repo, source, authority, evidence)
            self.assertEqual(first.outcome, "TARGET_QUALIFICATION_PASS")
            self.assertEqual(first.canonical_epoch, 1)
            self.assertEqual(first.reader_epoch, 1)
            self.assertEqual(first.no_op_phase, "IDLE")
            self.assertEqual(first.restart_state, "READY_CLEAN")
            self.assertEqual(first.canonical_file_count, 1)
            self.assertEqual(first.preserved_file_count, 0)

            authority_value = json.loads(authority.read_text(encoding="utf-8"))
            target_id = authority_value["target_id"]
            target = drive.get(target_id, include_trashed=False)
            self.assertEqual(target.parent_id, staging)
            self.assertEqual(target.name, TARGET_PREFIX + pack.candidate_id)

            public = evidence.read_text(encoding="utf-8")
            self.assertNotIn(target_id, public)
            self.assertNotIn(staging, public)
            self.assertNotIn("identity.md", public)
            self.assertNotIn("identity/profile.md", public)
            self.assertFalse(json.loads(public)["cutover_authorized"])

            first_raw = evidence.read_bytes()
            second = gate.run(pack.root, freeze, repo, source, authority, evidence)
            self.assertEqual(second, first)
            self.assertEqual(evidence.read_bytes(), first_raw)
            children = [
                child for child in drive.list_children(staging)
                if child.name.startswith(TARGET_PREFIX)
            ]
            self.assertEqual([item.file_id for item in children], [target_id])

    def test_source_drift_blocks_before_target_authority_or_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, source, pack, freeze, drive, staging, authority, evidence = self._fixture(root)
            (source / "identity.md").write_bytes(b"changed after freeze\n")

            with self.assertRaisesRegex(
                DriveMigrationProductionQualificationBlocked,
                "live legacy source no longer matches",
            ):
                DriveMigrationProductionTargetQualification(drive, staging).run(
                    pack.root, freeze, repo, source, authority, evidence
                )
            self.assertFalse(authority.exists())
            self.assertFalse(evidence.exists())
            self.assertEqual(len(drive.list_children(staging)), 1)

    def test_staging_root_must_be_exact_and_empty_except_sentinel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, source, pack, freeze, drive, staging, authority, evidence = self._fixture(root)
            drive.create_blob(staging, "unrelated.txt", b"must block\n")

            with self.assertRaisesRegex(
                DriveMigrationProductionQualificationBlocked,
                "unexpected object exists",
            ):
                DriveMigrationProductionTargetQualification(drive, staging).run(
                    pack.root, freeze, repo, source, authority, evidence
                )
            self.assertFalse(authority.exists())
            self.assertFalse(evidence.exists())

    def test_crash_after_target_creation_recovers_from_private_reserved_id_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fault = FaultInjector("drive.migration.production-target.create.after")
            repo, source, pack, freeze, drive, staging, authority, evidence = self._fixture(
                root, fault=fault
            )
            gate = DriveMigrationProductionTargetQualification(drive, staging)

            with self.assertRaises(InjectedCrash):
                gate.run(pack.root, freeze, repo, source, authority, evidence)
            self.assertTrue(authority.is_file())
            self.assertFalse(evidence.exists())
            authority_value = json.loads(authority.read_text(encoding="utf-8"))
            target_id = authority_value["target_id"]
            self.assertEqual(drive.get(target_id).name, TARGET_PREFIX + pack.candidate_id)

            result = gate.run(pack.root, freeze, repo, source, authority, evidence)
            self.assertEqual(result.outcome, "TARGET_QUALIFICATION_PASS")
            self.assertEqual(
                [
                    child.file_id
                    for child in drive.list_children(staging)
                    if child.name.startswith(TARGET_PREFIX)
                ],
                [target_id],
            )

    def test_post_construction_source_drift_is_distinguished_and_never_publishes_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, source, pack, freeze, drive, staging, authority, evidence = self._fixture(root)
            original = DriveMigrationDisposableRehearsal.run

            def run_then_drift(service, pack_dir):
                value = original(service, pack_dir)
                (source / "identity.md").write_bytes(b"changed after construction\n")
                return value

            with patch.object(DriveMigrationDisposableRehearsal, "run", new=run_then_drift):
                with self.assertRaisesRegex(
                    DriveMigrationProductionPostConstructionBlocked,
                    "durably constructed",
                ):
                    DriveMigrationProductionTargetQualification(drive, staging).run(
                        pack.root, freeze, repo, source, authority, evidence
                    )

            self.assertTrue(authority.is_file())
            self.assertFalse(evidence.exists())
            target_id = json.loads(authority.read_text(encoding="utf-8"))["target_id"]
            target = drive.get(target_id, include_trashed=False)
            self.assertTrue(target.is_folder)
            canonical = drive.exact_name(target_id, "canonical")
            self.assertIsNotNone(canonical)
            profile_parent = drive.exact_name(canonical.file_id, "identity")
            self.assertIsNotNone(profile_parent)
            self.assertIsNotNone(drive.exact_name(profile_parent.file_id, "profile.md"))

    def test_authority_and_evidence_cannot_be_written_into_repo_or_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, source, pack, freeze, drive, staging, authority, evidence = self._fixture(root)
            gate = DriveMigrationProductionTargetQualification(drive, staging)

            with self.assertRaisesRegex(
                DriveMigrationProductionQualificationBlocked,
                "outside the Git worktree",
            ):
                gate.run(pack.root, freeze, repo, source, repo / "authority.json", evidence)
            with self.assertRaisesRegex(
                DriveMigrationProductionQualificationBlocked,
                "outside the immutable migration pack",
            ):
                gate.run(
                    pack.root,
                    freeze,
                    repo,
                    source,
                    authority,
                    pack.root / "evidence.json",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
