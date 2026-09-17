from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))

from keelaryn_core.drive_bootstrap import DriveHubBootstrap  # noqa: E402
from keelaryn_core.drive_model import DriveModel  # noqa: E402
from keelaryn_core.migration_materialization import (  # noqa: E402
    DriveMigrationMaterializationBlocked,
    DriveMigrationPreservationMaterialization,
)
from keelaryn_core.migration_pack import (  # noqa: E402
    build_migration_pack,
    capture_migration_source,
    verify_migration_source,
)
from keelaryn_core.migration_publication import (  # noqa: E402
    DriveMigrationCanonicalPublication,
)
from keelaryn_core.protocol import FaultInjector, InjectedCrash, canonical_json_bytes  # noqa: E402


class DriveMigrationPreservationMaterializationTests(unittest.TestCase):
    def build_pack(self, root: Path, *, candidate_id: str = "migration-preserve"):
        source = root / "source"
        source.mkdir()
        (source / "profile.md").write_bytes(b"# Migrated profile\r\n")
        (source / "project-note.md").write_bytes(b"legacy project note\r\n")
        (source / "archive.txt").write_bytes(b"historical only\r\n")
        (source / "router.md").write_bytes(b"legacy router source\r\n")

        selection = root / "MIGRATION_SELECTION.json"
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
                    ],
                }
            )
        )
        source_manifest = root / "MIGRATION_SOURCE.json"
        capture_migration_source(source, selection, source_manifest)

        prepared = root / "prepared"
        prepared.mkdir()
        states = prepared / "states"
        states.mkdir()
        state_raw = b"# Project 1\r\n\r\nInitial migrated state.\r\n"
        (states / "project-1.md").write_bytes(state_raw)
        root_index_raw = b"# Migrated INDEX\r\n"
        (prepared / "INDEX.md").write_bytes(root_index_raw)

        mapping = root / "MIGRATION_MAPPING.json"
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
                    ],
                    "project_initial_states": [
                        {
                            "project_id": "project-1",
                            "prepared_path": "states/project-1.md",
                        }
                    ],
                    "canonical_outputs": [
                        {
                            "target": "identity/profile.md",
                            "semantic_sources": ["profile.md"],
                            "payload": {"kind": "SOURCE", "source": "profile.md"},
                        }
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
        return pack, state_raw, root_index_raw

    @staticmethod
    def build_drive():
        drive = DriveModel(fault=FaultInjector())
        hub = drive.create_folder("root", "Disposable Migration Hub", label="setup.hub")
        return drive, hub.file_id

    @staticmethod
    def resolve_path(drive: DriveModel, parent_id: str, path: str):
        item = None
        current = parent_id
        for part in path.split("/"):
            item = drive.exact_name(current, part)
            if item is None:
                return None
            current = item.file_id
        return item

    def publish(self, drive: DriveModel, hub_id: str, pack) -> None:
        evidence = DriveMigrationCanonicalPublication(drive, hub_id).run(pack.root)
        self.assertEqual(evidence.outcome, "COMMITTED")
        self.assertEqual(evidence.canonical_epoch, 1)
        self.assertEqual(evidence.candidate_id, pack.candidate_id)

    def test_materializes_exact_preservation_and_replay_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack, state_raw, root_index_raw = self.build_pack(Path(tmp))
            drive, hub_id = self.build_drive()
            bootstrap = DriveHubBootstrap(drive, hub_id).run()
            bootstrap_index = drive.exact_name(hub_id, "INDEX.md")
            assert bootstrap_index is not None
            bootstrap_index_raw = drive.download(bootstrap_index.file_id)

            self.publish(drive, hub_id, pack)
            service = DriveMigrationPreservationMaterialization(drive, hub_id)
            first = service.run(pack.root)
            second = service.run(pack.root)

            self.assertEqual(second, first)
            self.assertEqual(first.candidate_id, pack.candidate_id)
            self.assertEqual(first.pack_sha256, pack.pack_sha256)
            self.assertEqual(first.preserved_file_count, 2)
            self.assertEqual(first.project_file_count, 1)
            self.assertEqual(first.archive_file_count, 1)
            self.assertEqual(first.preserved_total_bytes, pack.preserved_total_bytes)
            self.assertEqual(len(first.inventory_sha256), 64)

            project_note = self.resolve_path(
                drive,
                hub_id,
                "work/projects/project-1/migration-import/project-note.md",
            )
            archive = self.resolve_path(
                drive,
                hub_id,
                f"archive/migration/{pack.candidate_id}/archive.txt",
            )
            self.assertIsNotNone(project_note)
            self.assertIsNotNone(archive)
            assert project_note is not None and archive is not None
            self.assertEqual(drive.download(project_note.file_id), b"legacy project note\r\n")
            self.assertEqual(drive.download(archive.file_id), b"historical only\r\n")

            project_state = self.resolve_path(drive, hub_id, "work/projects/project-1/STATE.md")
            assert project_state is not None
            self.assertEqual(drive.download(project_state.file_id), state_raw)

            # Preservation owns neither canonical truth nor root routing.
            canonical_profile = self.resolve_path(
                drive,
                bootstrap.layout.canonical_root_id,
                "identity/profile.md",
            )
            assert canonical_profile is not None
            self.assertEqual(drive.download(canonical_profile.file_id), b"# Migrated profile\r\n")
            current_index = drive.exact_name(hub_id, "INDEX.md")
            assert current_index is not None
            self.assertNotEqual(bootstrap_index_raw, root_index_raw)
            self.assertEqual(drive.download(current_index.file_id), bootstrap_index_raw)

    def test_partial_preservation_crash_recovers_by_reobservation(self) -> None:
        for point in (
            "drive.migration.preserve.folder.archive.create.after",
            "drive.migration.preserve.preserved-00001.create.after",
            "drive.migration.preserve.preserved-00002.create.after",
        ):
            with self.subTest(point=point), tempfile.TemporaryDirectory() as tmp:
                pack, _, _ = self.build_pack(Path(tmp), candidate_id="migration-restart")
                drive, hub_id = self.build_drive()
                self.publish(drive, hub_id, pack)
                drive.fault.point = point
                drive.fault.fired = False

                with self.assertRaises(InjectedCrash):
                    DriveMigrationPreservationMaterialization(drive, hub_id).run(pack.root)
                self.assertTrue(drive.fault.fired)

                drive.fault.point = None
                drive.fault.fired = False
                evidence = DriveMigrationPreservationMaterialization(drive, hub_id).run(pack.root)
                self.assertEqual(evidence.preserved_file_count, 2)
                self.assertIsNotNone(
                    self.resolve_path(
                        drive,
                        hub_id,
                        "work/projects/project-1/migration-import/project-note.md",
                    )
                )
                self.assertIsNotNone(
                    self.resolve_path(
                        drive,
                        hub_id,
                        "archive/migration/migration-restart/archive.txt",
                    )
                )

    def test_requires_exact_committed_migration_outcome(self) -> None:
        class ForcedPostcheckFailure(DriveMigrationCanonicalPublication):
            def _canonical_matches(self, pack, canonical_root_id: str, *, include_payloads: bool) -> bool:
                if include_payloads:
                    return False
                return super()._canonical_matches(
                    pack,
                    canonical_root_id,
                    include_payloads=include_payloads,
                )

        with tempfile.TemporaryDirectory() as tmp:
            pack, _, _ = self.build_pack(Path(tmp), candidate_id="migration-outcome")

            with self.subTest("before publication"):
                drive, hub_id = self.build_drive()
                DriveHubBootstrap(drive, hub_id).run()
                with self.assertRaisesRegex(
                    DriveMigrationMaterializationBlocked,
                    "READY/SAFE epoch-1 COMMITTED candidate",
                ):
                    DriveMigrationPreservationMaterialization(drive, hub_id).run(pack.root)
                self.assertIsNone(drive.exact_name(hub_id, "archive"))

            with self.subTest("rolled back"):
                drive, hub_id = self.build_drive()
                rolled_back = ForcedPostcheckFailure(drive, hub_id).run(pack.root)
                self.assertEqual(rolled_back.outcome, "ROLLED_BACK")
                with self.assertRaisesRegex(
                    DriveMigrationMaterializationBlocked,
                    "READY/SAFE epoch-1 COMMITTED candidate",
                ):
                    DriveMigrationPreservationMaterialization(drive, hub_id).run(pack.root)
                self.assertIsNone(drive.exact_name(hub_id, "archive"))

    def test_conflicting_preservation_namespaces_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack, _, _ = self.build_pack(Path(tmp), candidate_id="migration-conflict")

            with self.subTest("archive is blob"):
                drive, hub_id = self.build_drive()
                self.publish(drive, hub_id, pack)
                drive.create_blob(hub_id, "archive", b"not-a-folder")
                with self.assertRaisesRegex(
                    DriveMigrationMaterializationBlocked,
                    "archive/ is not a folder",
                ):
                    DriveMigrationPreservationMaterialization(drive, hub_id).run(pack.root)

            with self.subTest("unexpected project import material"):
                drive, hub_id = self.build_drive()
                self.publish(drive, hub_id, pack)
                project = self.resolve_path(drive, hub_id, "work/projects/project-1")
                assert project is not None
                migration_import = drive.create_folder(project.file_id, "migration-import")
                drive.create_blob(migration_import.file_id, "intruder.bin", b"x")
                with self.assertRaisesRegex(
                    DriveMigrationMaterializationBlocked,
                    "unexpected blob",
                ):
                    DriveMigrationPreservationMaterialization(drive, hub_id).run(pack.root)

    def test_canonical_tamper_after_commit_blocks_preservation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack, _, _ = self.build_pack(Path(tmp), candidate_id="migration-tamper")
            drive, hub_id = self.build_drive()
            self.publish(drive, hub_id, pack)
            layout = DriveHubBootstrap(drive, hub_id).run().layout
            profile = self.resolve_path(drive, layout.canonical_root_id, "identity/profile.md")
            assert profile is not None
            drive.update_content(profile.file_id, b"tampered\r\n")

            with self.assertRaisesRegex(
                DriveMigrationMaterializationBlocked,
                "canonical inventory no longer matches private pack",
            ):
                DriveMigrationPreservationMaterialization(drive, hub_id).run(pack.root)
            self.assertIsNone(drive.exact_name(hub_id, "archive"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
