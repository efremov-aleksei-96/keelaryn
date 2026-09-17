from __future__ import annotations

import copy
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
from keelaryn_core.migration_post_cutover_acceptance import (  # noqa: E402
    DriveMigrationPostCutoverAcceptanceBlocked,
    DriveMigrationPostCutoverReadOnlyAcceptance,
)
from keelaryn_core.migration_production_qualification import (  # noqa: E402
    DriveMigrationProductionTargetQualification,
    STAGING_ROOT_NAME,
    STAGING_SENTINEL_BYTES,
    STAGING_SENTINEL_NAME,
)
from keelaryn_core.protocol import canonical_json_bytes  # noqa: E402


class MigrationPostCutoverAcceptanceTests(unittest.TestCase):
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
        candidate_id = "migration-post-cutover-001"
        source = root / "legacy-source"
        source.mkdir()
        (source / "profile.md").write_bytes(b"# Migrated profile\r\n")
        (source / "value.json").write_bytes(b'{"value":1}\r\n')
        (source / "project-note.md").write_bytes(b"legacy project note\r\n")
        (source / "archive.txt").write_bytes(b"historical only\r\n")
        (source / "router.md").write_bytes(b"legacy router source\r\n")

        selection = root / "selection.json"
        selection.write_bytes(
            canonical_json_bytes(
                {
                    "schema": "keelaryn.migration-selection.v1",
                    "candidate_id": candidate_id,
                    "sources": [
                        "archive.txt",
                        "profile.md",
                        "project-note.md",
                        "router.md",
                        "value.json",
                    ],
                }
            )
        )
        source_manifest = root / "source.json"
        capture_migration_source(source, selection, source_manifest)

        prepared = root / "prepared"
        prepared.mkdir()
        states = prepared / "states"
        states.mkdir()
        (states / "project-1.md").write_bytes(
            b"# Project 1\r\n\r\nInitial migrated state.\r\n"
        )
        (prepared / "INDEX.md").write_bytes(
            b"# Migrated INDEX\r\n\r\n- Profile: `canonical/identity/profile.md`\r\n"
        )

        mapping = root / "mapping.json"
        mapping.write_bytes(
            canonical_json_bytes(
                {
                    "schema": "keelaryn.migration-mapping.v1",
                    "candidate_id": candidate_id,
                    "source_manifest_sha256": verify_migration_source(source_manifest).digest,
                    "source_actions": [
                        {
                            "source": "archive.txt",
                            "classification": "ARCHIVE_ONLY",
                            "destination": f"archive/migration/{candidate_id}/archive.txt",
                        },
                        {"source": "profile.md", "classification": "CANONICAL_IMPORT"},
                        {
                            "source": "project-note.md",
                            "classification": "PROJECT_WORK_IMPORT",
                            "destination": "work/projects/project-1/migration-import/project-note.md",
                        },
                        {"source": "router.md", "classification": "ROUTER_SOURCE"},
                        {"source": "value.json", "classification": "CANONICAL_IMPORT"},
                    ],
                    "project_initial_states": [
                        {"project_id": "project-1", "prepared_path": "states/project-1.md"}
                    ],
                    "canonical_outputs": [
                        {
                            "target": "data/nested/value.json",
                            "semantic_sources": ["value.json"],
                            "payload": {"kind": "SOURCE", "source": "value.json"},
                        },
                        {
                            "target": "identity/profile.md",
                            "semantic_sources": ["profile.md"],
                            "payload": {"kind": "SOURCE", "source": "profile.md"},
                        },
                    ],
                    "root_index": {
                        "semantic_sources": ["router.md"],
                        "prepared_path": "INDEX.md",
                    },
                }
            )
        )
        pack = build_migration_pack(
            source,
            source_manifest,
            mapping,
            root / "pack",
            prepared_root=prepared,
        )
        freeze = root / "freeze.json"
        freeze_migration_candidate(pack.root, repo, commit, tree, freeze)
        return source, pack, freeze

    @staticmethod
    def _staging(drive: DriveModel) -> str:
        staging = drive.create_folder("root", STAGING_ROOT_NAME, label="setup.staging")
        drive.create_blob(
            staging.file_id,
            STAGING_SENTINEL_NAME,
            STAGING_SENTINEL_BYTES,
            label="setup.sentinel",
        )
        return staging.file_id

    def _fixture(self, root: Path):
        repo, commit, tree = self._repo(root)
        source, pack, freeze = self._candidate(root, repo, commit, tree)
        drive = DriveModel()
        staging = self._staging(drive)
        authority = root / "target-authority.json"
        qualification = root / "qualification.json"
        result = DriveMigrationProductionTargetQualification(drive, staging).run(
            pack.root,
            freeze,
            repo,
            source,
            authority,
            qualification,
        )
        self.assertEqual(result.outcome, "TARGET_QUALIFICATION_PASS")
        target_id = json.loads(authority.read_text(encoding="utf-8"))["target_id"]
        return repo, pack, freeze, drive, staging, authority, qualification, target_id

    @staticmethod
    def _drive_snapshot(drive: DriveModel):
        return (
            drive._next_id,
            drive._next_revision,
            copy.deepcopy(drive._items),
            copy.deepcopy(drive._content),
            copy.deepcopy(drive._reserved_ids),
        )

    @staticmethod
    def _resolve(drive: DriveModel, parent_id: str, path: str):
        current = parent_id
        item = None
        for part in path.split("/"):
            item = drive.exact_name(current, part)
            if item is None:
                return None
            current = item.file_id
        return item

    def test_exact_post_cutover_pass_is_fully_read_only_and_sanitized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, pack, freeze, drive, staging, authority, qualification, target_id = self._fixture(root)
            before = self._drive_snapshot(drive)

            result = DriveMigrationPostCutoverReadOnlyAcceptance(drive, target_id).run(
                pack.root,
                freeze,
                repo,
                authority,
                qualification,
            )

            self.assertEqual(result.outcome, "POST_CUTOVER_READ_ONLY_PASS")
            self.assertEqual(result.canonical_epoch, 1)
            self.assertEqual(result.canonical_file_count, 2)
            self.assertEqual(result.preserved_file_count, 2)
            self.assertEqual(result.project_count, 1)
            self.assertEqual(result.router_outcome, "COMMITTED")
            self.assertEqual(result.restart_state, "READY_CLEAN")
            public = json.dumps(result.to_json_value(), sort_keys=True)
            self.assertTrue(result.to_json_value()["hub_cutover_accept_allowed"])
            self.assertFalse(result.to_json_value()["drive_mutations_performed"])
            self.assertNotIn(target_id, public)
            self.assertNotIn(staging, public)
            self.assertNotIn(str(pack.root), public)
            self.assertEqual(self._drive_snapshot(drive), before)

    def test_selected_identity_mismatch_blocks_before_any_drive_observation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, pack, freeze, drive, _, authority, qualification, _ = self._fixture(root)
            service = DriveMigrationPostCutoverReadOnlyAcceptance(drive, "different-selected-hub")
            with patch.object(drive, "get", side_effect=AssertionError("Drive must not be read")), patch.object(
                drive, "list_children", side_effect=AssertionError("Drive must not be read")
            ), patch.object(drive, "download", side_effect=AssertionError("Drive must not be read")):
                with self.assertRaisesRegex(
                    DriveMigrationPostCutoverAcceptanceBlocked,
                    "selected Hub identity does not match",
                ):
                    service.run(pack.root, freeze, repo, authority, qualification)

    def test_tampered_qualification_identity_blocks_before_drive_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, pack, freeze, drive, _, authority, qualification, target_id = self._fixture(root)
            value = json.loads(qualification.read_text(encoding="utf-8"))
            value["target_identity_sha256"] = "0" * 64
            qualification.write_bytes(canonical_json_bytes(value))
            with self.assertRaisesRegex(
                DriveMigrationPostCutoverAcceptanceBlocked,
                "target identity hash disagrees",
            ):
                DriveMigrationPostCutoverReadOnlyAcceptance(drive, target_id).run(
                    pack.root, freeze, repo, authority, qualification
                )

    def test_fresh_canonical_router_and_project_tamper_are_rejected(self) -> None:
        cases = ("canonical", "router", "project")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                repo, pack, freeze, drive, _, authority, qualification, target_id = self._fixture(root)
                if case == "canonical":
                    item = self._resolve(drive, target_id, "canonical/identity/profile.md")
                elif case == "router":
                    item = self._resolve(drive, target_id, "INDEX.md")
                else:
                    item = self._resolve(drive, target_id, "work/projects/project-1/STATE.md")
                assert item is not None
                drive.update_content(item.file_id, b"tampered after qualification\n", label="test.tamper")
                with self.assertRaises(DriveMigrationPostCutoverAcceptanceBlocked):
                    DriveMigrationPostCutoverReadOnlyAcceptance(drive, target_id).run(
                        pack.root, freeze, repo, authority, qualification
                    )

    def test_master_not_ready_clean_and_preservation_tamper_are_rejected(self) -> None:
        cases = ("master", "preservation")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                repo, pack, freeze, drive, _, authority, qualification, target_id = self._fixture(root)
                if case == "master":
                    master = self._resolve(drive, target_id, "MASTER.json")
                    assert master is not None
                    value = json.loads(drive.download(master.file_id).decode("utf-8"))
                    value["canonical_read_status"] = "UNSAFE"
                    drive.update_content(master.file_id, canonical_json_bytes(value), label="test.master-tamper")
                else:
                    preserved = self._resolve(
                        drive,
                        target_id,
                        "work/projects/project-1/migration-import/project-note.md",
                    )
                    assert preserved is not None
                    drive.update_content(
                        preserved.file_id,
                        b"tampered preservation\n",
                        label="test.preservation-tamper",
                    )
                with self.assertRaises(DriveMigrationPostCutoverAcceptanceBlocked):
                    DriveMigrationPostCutoverReadOnlyAcceptance(drive, target_id).run(
                        pack.root, freeze, repo, authority, qualification
                    )


if __name__ == "__main__":
    unittest.main(verbosity=2)
