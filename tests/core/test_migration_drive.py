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


if __name__ == "__main__":
    unittest.main()
