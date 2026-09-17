from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))

from keelaryn_core.drive_bootstrap import DriveHubBootstrap  # noqa: E402
from keelaryn_core.drive_model import DriveModel  # noqa: E402
from keelaryn_core.migration_drive import (  # noqa: E402
    DriveMigrationPreparationBlocked,
    DriveMigrationProjectPreparation,
    DriveMigrationTopologyPreparation,
)
from keelaryn_core.migration_pack import (  # noqa: E402
    build_migration_pack,
    capture_migration_source,
    verify_migration_source,
)
from keelaryn_core.protocol import FaultInjector, InjectedCrash, canonical_json_bytes  # noqa: E402


class DriveMigrationTopologyTests(unittest.TestCase):
    def _pack(self, root: Path) -> Path:
        source = root / "source"
        source.mkdir()
        (source / "alpha.md").write_bytes(b"alpha\r\n")
        nested = source / "nested"
        nested.mkdir()
        (nested / "beta.json").write_bytes(b'{"beta":2}\r\n')

        selection = root / "MIGRATION_SELECTION.json"
        selection.write_bytes(
            canonical_json_bytes(
                {
                    "schema": "keelaryn.migration-selection.v1",
                    "candidate_id": "migration-topology",
                    "sources": ["alpha.md", "nested/beta.json"],
                }
            )
        )
        source_manifest = root / "MIGRATION_SOURCE.json"
        capture_migration_source(source, selection, source_manifest)

        mapping = root / "MIGRATION_MAPPING.json"
        mapping.write_bytes(
            canonical_json_bytes(
                {
                    "schema": "keelaryn.migration-mapping.v1",
                    "candidate_id": "migration-topology",
                    "source_manifest_sha256": verify_migration_source(source_manifest).digest,
                    "source_actions": [
                        {"source": "alpha.md", "classification": "CANONICAL_IMPORT"},
                        {"source": "nested/beta.json", "classification": "CANONICAL_IMPORT"},
                    ],
                    "canonical_outputs": [
                        {
                            "target": "data/nested/beta.json",
                            "semantic_sources": ["nested/beta.json"],
                            "payload": {"kind": "SOURCE", "source": "nested/beta.json"},
                        },
                        {
                            "target": "identity/alpha.md",
                            "semantic_sources": ["alpha.md"],
                            "payload": {"kind": "SOURCE", "source": "alpha.md"},
                        },
                    ],
                    "root_index": None,
                }
            )
        )
        pack = build_migration_pack(source, source_manifest, mapping, root / "pack")
        return pack.root

    def test_prepare_creates_only_required_empty_parent_directories_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack_dir = self._pack(Path(tmp))
            drive = DriveModel()
            service = DriveMigrationTopologyPreparation(drive, "root")

            first = service.prepare(pack_dir)
            second = service.prepare(pack_dir)

            self.assertEqual(first, second)
            self.assertEqual(first.candidate_id, "migration-topology")
            self.assertEqual(first.canonical_directory_count, 3)

            canonical = drive.exact_name("root", "canonical")
            assert canonical is not None
            top = drive.list_children(canonical.file_id)
            self.assertEqual([item.name for item in top], ["data", "identity"])
            self.assertTrue(all(item.is_folder for item in top))

            data = drive.exact_name(canonical.file_id, "data")
            identity = drive.exact_name(canonical.file_id, "identity")
            assert data is not None and identity is not None
            nested = drive.exact_name(data.file_id, "nested")
            assert nested is not None
            self.assertEqual(drive.list_children(nested.file_id), [])
            self.assertEqual(drive.list_children(identity.file_id), [])

            master = drive.exact_name("root", "MASTER.json")
            assert master is not None
            self.assertIn(b'"canonical_epoch": 0', drive.download(master.file_id))
            self.assertIn(b'"canonical_read_status": "SAFE"', drive.download(master.file_id))

    def test_prepare_rejects_unexpected_canonical_blob_or_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack_dir = self._pack(Path(tmp))

            with self.subTest("blob"):
                drive = DriveModel()
                layout = DriveHubBootstrap(drive, "root").run().layout
                drive.create_blob(layout.canonical_root_id, "intruder.bin", b"x")
                with self.assertRaisesRegex(
                    DriveMigrationPreparationBlocked,
                    "non-directory material before Core publication",
                ):
                    DriveMigrationTopologyPreparation(drive, "root").prepare(pack_dir)

            with self.subTest("directory"):
                drive = DriveModel()
                layout = DriveHubBootstrap(drive, "root").run().layout
                drive.create_folder(layout.canonical_root_id, "other")
                with self.assertRaisesRegex(
                    DriveMigrationPreparationBlocked,
                    "unexpected directory",
                ):
                    DriveMigrationTopologyPreparation(drive, "root").prepare(pack_dir)

    def test_prepare_recovers_by_reobservation_after_crash_post_folder_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack_dir = self._pack(Path(tmp))
            fault = FaultInjector("drive.migration.topology.data.create.after")
            drive = DriveModel(fault=fault)
            service = DriveMigrationTopologyPreparation(drive, "root")

            with self.assertRaises(InjectedCrash):
                service.prepare(pack_dir)
            self.assertTrue(fault.fired)

            evidence = service.prepare(pack_dir)
            self.assertEqual(evidence.canonical_directory_count, 3)
            canonical = drive.exact_name("root", "canonical")
            assert canonical is not None
            self.assertEqual(len(drive.list_children(canonical.file_id, name="data")), 1)

    def test_prepare_rejects_noninitial_master(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack_dir = self._pack(Path(tmp))
            drive = DriveModel()
            bootstrap = DriveHubBootstrap(drive, "root").run()
            master = drive.exact_name("root", "MASTER.json")
            assert master is not None
            changed = DriveHubBootstrap.initial_master_bytes().replace(
                b'"canonical_epoch": 0', b'"canonical_epoch": 1'
            )
            drive.update_content(master.file_id, changed)
            with self.assertRaisesRegex(
                DriveMigrationPreparationBlocked,
                "untouched READY/SAFE epoch 0",
            ):
                DriveMigrationTopologyPreparation(drive, "root").prepare(pack_dir)
            self.assertIsNotNone(bootstrap.layout.canonical_root_id)


class DriveMigrationProjectPreparationTests(unittest.TestCase):
    def _pack(self, root: Path) -> tuple[Path, bytes]:
        source = root / "source"
        source.mkdir()
        (source / "canonical.md").write_bytes(b"canonical\r\n")
        (source / "project-note.md").write_bytes(b"legacy project note\r\n")

        selection = root / "MIGRATION_SELECTION.json"
        selection.write_bytes(
            canonical_json_bytes(
                {
                    "schema": "keelaryn.migration-selection.v1",
                    "candidate_id": "migration-projects",
                    "sources": ["canonical.md", "project-note.md"],
                }
            )
        )
        source_manifest = root / "MIGRATION_SOURCE.json"
        capture_migration_source(source, selection, source_manifest)

        state_raw = b"# Project 1\r\n\r\nInitial migrated state.\r\n"
        prepared = root / "prepared"
        prepared.mkdir()
        states = prepared / "states"
        states.mkdir()
        (states / "project-1.md").write_bytes(state_raw)

        mapping = root / "MIGRATION_MAPPING.json"
        mapping.write_bytes(
            canonical_json_bytes(
                {
                    "schema": "keelaryn.migration-mapping.v1",
                    "candidate_id": "migration-projects",
                    "source_manifest_sha256": verify_migration_source(source_manifest).digest,
                    "source_actions": [
                        {"source": "canonical.md", "classification": "CANONICAL_IMPORT"},
                        {
                            "source": "project-note.md",
                            "classification": "PROJECT_WORK_IMPORT",
                            "destination": "work/projects/project-1/migration-import/project-note.md",
                        },
                    ],
                    "project_initial_states": [
                        {"project_id": "project-1", "prepared_path": "states/project-1.md"}
                    ],
                    "canonical_outputs": [
                        {
                            "target": "identity/canonical.md",
                            "semantic_sources": ["canonical.md"],
                            "payload": {"kind": "SOURCE", "source": "canonical.md"},
                        }
                    ],
                    "root_index": None,
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
        return pack.root, state_raw

    @staticmethod
    def _projects_parent(drive: DriveModel):
        work = drive.exact_name("root", "work")
        assert work is not None
        projects = drive.exact_name(work.file_id, "projects")
        assert projects is not None
        return projects

    def test_prepare_initializes_exact_project_state_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack_dir, state_raw = self._pack(Path(tmp))
            drive = DriveModel()
            service = DriveMigrationProjectPreparation(drive, "root")

            first = service.prepare(pack_dir)
            second = service.prepare(pack_dir)

            self.assertEqual(first, second)
            self.assertEqual(first.candidate_id, "migration-projects")
            self.assertEqual(first.project_count, 1)
            self.assertEqual(first.project_state_total_bytes, len(state_raw))

            projects = self._projects_parent(drive)
            project = drive.exact_name(projects.file_id, "project-1")
            assert project is not None
            self.assertTrue(project.is_folder)
            self.assertEqual(
                {item.name for item in drive.list_children(project.file_id)},
                {"STATE.md", "results"},
            )
            state = drive.exact_name(project.file_id, "STATE.md")
            results = drive.exact_name(project.file_id, "results")
            assert state is not None and results is not None
            self.assertEqual(drive.download(state.file_id), state_raw)
            self.assertEqual(drive.list_children(results.file_id), [])
            self.assertIsNone(drive.exact_name(project.file_id, "migration-import"))

    def test_prepare_recovers_after_crash_post_state_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack_dir, state_raw = self._pack(Path(tmp))
            fault = FaultInjector("drive.project.project-1.state.create.after")
            drive = DriveModel(fault=fault)
            service = DriveMigrationProjectPreparation(drive, "root")

            with self.assertRaises(InjectedCrash):
                service.prepare(pack_dir)
            self.assertTrue(fault.fired)

            evidence = service.prepare(pack_dir)
            self.assertEqual(evidence.project_count, 1)
            project = drive.exact_name(self._projects_parent(drive).file_id, "project-1")
            assert project is not None
            state = drive.exact_name(project.file_id, "STATE.md")
            assert state is not None
            self.assertEqual(drive.download(state.file_id), state_raw)

    def test_prepare_rejects_unexpected_project_or_child_material(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack_dir, _ = self._pack(Path(tmp))

            with self.subTest("unexpected project"):
                drive = DriveModel()
                DriveHubBootstrap(drive, "root").run()
                projects = self._projects_parent(drive)
                drive.create_folder(projects.file_id, "other-project")
                with self.assertRaisesRegex(
                    DriveMigrationPreparationBlocked,
                    "unexpected project",
                ):
                    DriveMigrationProjectPreparation(drive, "root").prepare(pack_dir)

            with self.subTest("unexpected child"):
                drive = DriveModel()
                DriveHubBootstrap(drive, "root").run()
                projects = self._projects_parent(drive)
                project_id = drive.generate_ids(1)[0]
                drive.create_folder(projects.file_id, "project-1", file_id=project_id)
                drive.create_blob(project_id, "intruder.bin", b"x")
                with self.assertRaisesRegex(
                    DriveMigrationPreparationBlocked,
                    "unexpected material before preservation",
                ):
                    DriveMigrationProjectPreparation(drive, "root").prepare(pack_dir)

    def test_prepare_rejects_conflicting_existing_state_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack_dir, _ = self._pack(Path(tmp))
            drive = DriveModel()
            DriveHubBootstrap(drive, "root").run()
            projects = self._projects_parent(drive)
            project_id = drive.generate_ids(1)[0]
            drive.create_folder(projects.file_id, "project-1", file_id=project_id)
            drive.create_blob(project_id, "STATE.md", b"wrong\r\n")

            with self.assertRaisesRegex(
                DriveMigrationPreparationBlocked,
                "bytes do not match migration pack",
            ):
                DriveMigrationProjectPreparation(drive, "root").prepare(pack_dir)

    def test_prepare_empty_project_authority_requires_empty_projects_area(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack_dir = DriveMigrationTopologyTests()._pack(Path(tmp))
            drive = DriveModel()
            evidence = DriveMigrationProjectPreparation(drive, "root").prepare(pack_dir)
            self.assertEqual(evidence.project_count, 0)
            self.assertEqual(drive.list_children(self._projects_parent(drive).file_id), [])


class DriveMigrationProjectPreparationPerformanceTests(DriveMigrationProjectPreparationTests):
    def test_repeat_prepare_does_not_reinitialize_exact_project(self) -> None:
        class CountingDrive(DriveModel):
            def __init__(self) -> None:
                super().__init__()
                self.list_calls: list[tuple[str, str | None]] = []
                self.download_calls: list[str] = []

            def list_children(
                self,
                parent_id: str,
                *,
                name: str | None = None,
                include_trashed: bool = False,
            ):
                self.list_calls.append((parent_id, name))
                return super().list_children(
                    parent_id,
                    name=name,
                    include_trashed=include_trashed,
                )

            def download(self, file_id: str) -> bytes:
                self.download_calls.append(file_id)
                return super().download(file_id)

            def reset_observation_counts(self) -> None:
                self.list_calls.clear()
                self.download_calls.clear()

        with tempfile.TemporaryDirectory() as tmp:
            pack_dir, _ = self._pack(Path(tmp))
            drive = CountingDrive()
            service = DriveMigrationProjectPreparation(drive, "root")

            service.prepare(pack_dir)

            projects = self._projects_parent(drive)
            project = drive.exact_name(projects.file_id, "project-1")
            assert project is not None
            state = drive.exact_name(project.file_id, "STATE.md")
            assert state is not None

            drive.reset_observation_counts()
            service.prepare(pack_dir)

            project_child_lists = [
                call
                for call in drive.list_calls
                if call[0] == project.file_id
            ]
            state_downloads = [
                file_id
                for file_id in drive.download_calls
                if file_id == state.file_id
            ]

            self.assertLessEqual(
                len(project_child_lists),
                2,
                "exact Projects must be freshly observed before and after preparation "
                "without re-entering the initialization path",
            )
            self.assertLessEqual(
                len(state_downloads),
                2,
                "exact STATE.md bytes must be validated at the two observation boundaries "
                "without a redundant initialization-path download",
            )


if __name__ == "__main__":
    unittest.main()
