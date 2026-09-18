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
from keelaryn_core.migration_router import (  # noqa: E402
    DriveMigrationRootIndexPublication,
    DriveMigrationRouterPublicationBlocked,
)
from keelaryn_core.protocol import FaultInjector, InjectedCrash, ProtocolError, canonical_json_bytes  # noqa: E402


class DriveMigrationRootIndexPublicationTests(unittest.TestCase):
    def build_pack(
        self,
        root: Path,
        *,
        candidate_id: str = "migration-router",
        with_root_index: bool = True,
    ):
        source = root / "source"
        source.mkdir()
        (source / "profile.md").write_bytes(b"# Migrated profile\r\n")
        (source / "project-note.md").write_bytes(b"legacy project note\r\n")
        (source / "archive.txt").write_bytes(b"historical only\r\n")
        if with_root_index:
            (source / "router.md").write_bytes(b"legacy router source\r\n")

        sources = ["archive.txt", "profile.md", "project-note.md"]
        if with_root_index:
            sources.append("router.md")
        sources.sort()
        selection = root / "MIGRATION_SELECTION.json"
        selection.write_bytes(
            canonical_json_bytes(
                {
                    "schema": "keelaryn.migration-selection.v1",
                    "candidate_id": candidate_id,
                    "sources": sources,
                }
            )
        )
        source_manifest = root / "MIGRATION_SOURCE.json"
        capture_migration_source(source, selection, source_manifest)

        prepared = root / "prepared"
        prepared.mkdir()
        states = prepared / "states"
        states.mkdir()
        (states / "project-1.md").write_bytes(
            b"# Project 1\r\n\r\nInitial migrated state.\r\n"
        )
        root_index_raw = b"# Migrated INDEX\r\n\r\n- Profile: `canonical/identity/profile.md`\r\n"
        if with_root_index:
            (prepared / "INDEX.md").write_bytes(root_index_raw)

        source_actions = [
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
        ]
        if with_root_index:
            source_actions.append({"source": "router.md", "classification": "ROUTER_SOURCE"})
        source_actions.sort(key=lambda item: item["source"])

        mapping = root / "MIGRATION_MAPPING.json"
        mapping.write_bytes(
            canonical_json_bytes(
                {
                    "schema": "keelaryn.migration-mapping.v1",
                    "candidate_id": candidate_id,
                    "source_manifest_sha256": verify_migration_source(source_manifest).digest,
                    "source_actions": source_actions,
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
                    "root_index": (
                        {
                            "semantic_sources": ["router.md"],
                            "prepared_path": "INDEX.md",
                        }
                        if with_root_index
                        else None
                    ),
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
        return pack, root_index_raw

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

    def construct_data_target(self, drive: DriveModel, hub_id: str, pack) -> None:
        publication = DriveMigrationCanonicalPublication(drive, hub_id).run(pack.root)
        self.assertEqual(publication.outcome, "COMMITTED")
        preservation = DriveMigrationPreservationMaterialization(drive, hub_id).run(pack.root)
        self.assertEqual(preservation.candidate_id, pack.candidate_id)
        self.assertEqual(preservation.preserved_file_count, 2)

    def test_publishes_exact_root_index_and_replay_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack, target_index_raw = self.build_pack(Path(tmp))
            drive, hub_id = self.build_drive()
            bootstrap = DriveHubBootstrap(drive, hub_id).run()
            index_before = drive.exact_name(hub_id, "INDEX.md")
            assert index_before is not None
            index_before_raw = drive.download(index_before.file_id)
            master_before = drive.exact_name(hub_id, "MASTER.json")
            assert master_before is not None

            self.construct_data_target(drive, hub_id, pack)
            profile = self.resolve_path(
                drive,
                bootstrap.layout.canonical_root_id,
                "identity/profile.md",
            )
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
            assert profile is not None and project_note is not None and archive is not None
            profile_raw = drive.download(profile.file_id)
            project_note_raw = drive.download(project_note.file_id)
            archive_raw = drive.download(archive.file_id)
            master_raw = drive.download(master_before.file_id)

            service = DriveMigrationRootIndexPublication(drive, hub_id)
            first = service.run(pack.root)
            index_after_first = drive.exact_name(hub_id, "INDEX.md")
            assert index_after_first is not None
            second = service.run(pack.root)
            index_after_second = drive.exact_name(hub_id, "INDEX.md")
            assert index_after_second is not None

            self.assertEqual(first, second)
            self.assertEqual(first.outcome, "COMMITTED")
            self.assertEqual(first.candidate_id, pack.candidate_id)
            self.assertEqual(first.pack_sha256, pack.pack_sha256)
            self.assertEqual(first.index_bytes, len(target_index_raw))
            self.assertEqual(index_after_first.file_id, index_before.file_id)
            self.assertEqual(index_after_second.file_id, index_before.file_id)
            self.assertEqual(index_after_first.version, index_before.version + 1)
            self.assertEqual(index_after_second.version, index_after_first.version)
            self.assertNotEqual(index_before_raw, target_index_raw)
            self.assertEqual(drive.download(index_after_second.file_id), target_index_raw)

            # Router publication owns only root INDEX.md.
            self.assertEqual(drive.download(master_before.file_id), master_raw)
            self.assertEqual(drive.download(profile.file_id), profile_raw)
            self.assertEqual(drive.download(project_note.file_id), project_note_raw)
            self.assertEqual(drive.download(archive.file_id), archive_raw)

    def test_router_uses_exact_blob_replacement_not_generic_update(self) -> None:
        class ExactReplacementDrive(DriveModel):
            def update_content(self, file_id, content, *, label="drive.update_content"):
                raise ProtocolError("generic in-place update is forbidden")

            def replace_blob_content(self, expected, content, *, label="drive.replace_blob_content"):
                current = self.get(expected.file_id, include_trashed=False)
                if current != expected:
                    raise ProtocolError("exact blob observation changed before replacement")
                return DriveModel.update_content(
                    self,
                    expected.file_id,
                    content,
                    label=label,
                )

        with tempfile.TemporaryDirectory() as tmp:
            pack, target_index_raw = self.build_pack(
                Path(tmp),
                candidate_id="migration-router-exact-replace",
            )
            drive = ExactReplacementDrive(fault=FaultInjector())
            hub = drive.create_folder("root", "Disposable Migration Hub", label="setup.hub")
            hub_id = hub.file_id
            DriveHubBootstrap(drive, hub_id).run()
            self.construct_data_target(drive, hub_id, pack)

            before = drive.exact_name(hub_id, "INDEX.md")
            assert before is not None
            evidence = DriveMigrationRootIndexPublication(drive, hub_id).run(pack.root)
            after = drive.exact_name(hub_id, "INDEX.md")
            assert after is not None

            self.assertEqual(evidence.outcome, "COMMITTED")
            self.assertEqual(after.file_id, before.file_id)
            self.assertEqual(drive.download(after.file_id), target_index_raw)

    def test_requires_complete_preservation_before_router_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack, _ = self.build_pack(Path(tmp), candidate_id="migration-router-incomplete")
            drive, hub_id = self.build_drive()
            bootstrap = DriveHubBootstrap(drive, hub_id).run()
            index = drive.exact_name(hub_id, "INDEX.md")
            assert index is not None
            initial_raw = drive.download(index.file_id)

            publication = DriveMigrationCanonicalPublication(drive, hub_id).run(pack.root)
            self.assertEqual(publication.outcome, "COMMITTED")
            with self.assertRaisesRegex(
                DriveMigrationRouterPublicationBlocked,
                "preservation is not exact",
            ):
                DriveMigrationRootIndexPublication(drive, hub_id).run(pack.root)

            current = drive.exact_name(hub_id, "INDEX.md")
            assert current is not None
            self.assertEqual(current.file_id, index.file_id)
            self.assertEqual(current.version, index.version)
            self.assertEqual(drive.download(current.file_id), initial_raw)
            self.assertIsNotNone(bootstrap.layout.canonical_root_id)

    def test_crash_after_durable_index_update_recovers_without_second_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate_id = "migration-router-restart"
            pack, target_index_raw = self.build_pack(Path(tmp), candidate_id=candidate_id)
            drive, hub_id = self.build_drive()
            DriveHubBootstrap(drive, hub_id).run()
            self.construct_data_target(drive, hub_id, pack)
            before = drive.exact_name(hub_id, "INDEX.md")
            assert before is not None

            drive.fault.point = f"drive.migration.router.{candidate_id}.index.update.after"
            drive.fault.fired = False
            with self.assertRaises(InjectedCrash):
                DriveMigrationRootIndexPublication(drive, hub_id).run(pack.root)
            self.assertTrue(drive.fault.fired)

            committed = drive.exact_name(hub_id, "INDEX.md")
            assert committed is not None
            self.assertEqual(committed.file_id, before.file_id)
            self.assertEqual(committed.version, before.version + 1)
            self.assertEqual(drive.download(committed.file_id), target_index_raw)

            drive.fault.point = None
            drive.fault.fired = False
            evidence = DriveMigrationRootIndexPublication(drive, hub_id).run(pack.root)
            recovered = drive.exact_name(hub_id, "INDEX.md")
            assert recovered is not None
            self.assertEqual(evidence.outcome, "COMMITTED")
            self.assertEqual(recovered.version, committed.version)
            self.assertEqual(drive.download(recovered.file_id), target_index_raw)

    def test_unknown_or_duplicate_root_index_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack, _ = self.build_pack(Path(tmp), candidate_id="migration-router-conflict")

            with self.subTest("unknown bytes"):
                drive, hub_id = self.build_drive()
                DriveHubBootstrap(drive, hub_id).run()
                self.construct_data_target(drive, hub_id, pack)
                index = drive.exact_name(hub_id, "INDEX.md")
                assert index is not None
                drive.update_content(index.file_id, b"# Foreign router\r\n")
                with self.assertRaisesRegex(
                    DriveMigrationRouterPublicationBlocked,
                    "neither bootstrap nor exact packed router bytes",
                ):
                    DriveMigrationRootIndexPublication(drive, hub_id).run(pack.root)

            with self.subTest("duplicate"):
                drive, hub_id = self.build_drive()
                DriveHubBootstrap(drive, hub_id).run()
                self.construct_data_target(drive, hub_id, pack)
                drive.create_blob(hub_id, "INDEX.md", b"duplicate")
                with self.assertRaisesRegex(
                    DriveMigrationRouterPublicationBlocked,
                    "exactly one root INDEX.md",
                ):
                    DriveMigrationRootIndexPublication(drive, hub_id).run(pack.root)

    def test_preservation_tamper_after_materialization_blocks_router(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack, _ = self.build_pack(Path(tmp), candidate_id="migration-router-tamper")
            drive, hub_id = self.build_drive()
            DriveHubBootstrap(drive, hub_id).run()
            self.construct_data_target(drive, hub_id, pack)
            index = drive.exact_name(hub_id, "INDEX.md")
            assert index is not None
            initial_raw = drive.download(index.file_id)
            archive = self.resolve_path(
                drive,
                hub_id,
                f"archive/migration/{pack.candidate_id}/archive.txt",
            )
            assert archive is not None
            drive.update_content(archive.file_id, b"tampered\r\n")

            with self.assertRaisesRegex(
                DriveMigrationRouterPublicationBlocked,
                "preservation is not exact",
            ):
                DriveMigrationRootIndexPublication(drive, hub_id).run(pack.root)
            current = drive.exact_name(hub_id, "INDEX.md")
            assert current is not None
            self.assertEqual(drive.download(current.file_id), initial_raw)

    def test_candidate_without_root_index_is_verified_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack, _ = self.build_pack(
                Path(tmp),
                candidate_id="migration-router-none",
                with_root_index=False,
            )
            drive, hub_id = self.build_drive()
            DriveHubBootstrap(drive, hub_id).run()
            index = drive.exact_name(hub_id, "INDEX.md")
            assert index is not None
            initial_raw = drive.download(index.file_id)
            initial_version = index.version
            self.construct_data_target(drive, hub_id, pack)

            service = DriveMigrationRootIndexPublication(drive, hub_id)
            first = service.run(pack.root)
            second = service.run(pack.root)
            current = drive.exact_name(hub_id, "INDEX.md")
            assert current is not None

            self.assertEqual(first, second)
            self.assertEqual(first.outcome, "NOT_REQUIRED")
            self.assertEqual(first.index_bytes, len(initial_raw))
            self.assertEqual(current.version, initial_version)
            self.assertEqual(drive.download(current.file_id), initial_raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
