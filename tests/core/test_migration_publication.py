from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))

from keelaryn_core.drive_bootstrap import DriveHubBootstrap  # noqa: E402
from keelaryn_core.drive_model import DriveModel  # noqa: E402
from keelaryn_core.migration_pack import (  # noqa: E402
    build_migration_pack,
    capture_migration_source,
    verify_migration_source,
)
from keelaryn_core.migration_publication import (  # noqa: E402
    DriveMigrationCanonicalPublication,
)
from keelaryn_core.protocol import FaultInjector, InjectedCrash, canonical_json_bytes  # noqa: E402


class DriveMigrationCanonicalPublicationTests(unittest.TestCase):
    def build_pack(self, root: Path, *, candidate_id: str = "migration-publish"):
        source = root / "source"
        source.mkdir()
        (source / "profile.md").write_bytes(b"# Migrated profile\r\n")
        (source / "value.json").write_bytes(b'{"value":1}\r\n')
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
                        "value.json",
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
                        {"source": "value.json", "classification": "CANONICAL_IMPORT"},
                    ],
                    "project_initial_states": [
                        {
                            "project_id": "project-1",
                            "prepared_path": "states/project-1.md",
                        }
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

    def assert_committed_exact(self, drive: DriveModel, hub_id: str, pack, state_raw: bytes) -> None:
        evidence = DriveMigrationCanonicalPublication(drive, hub_id).run(pack.root)
        self.assertEqual(evidence.candidate_id, pack.candidate_id)
        self.assertEqual(evidence.pack_sha256, pack.pack_sha256)
        self.assertEqual(evidence.canonical_file_count, len(pack.canonical_outputs))
        self.assertEqual(evidence.canonical_total_bytes, pack.canonical_total_bytes)
        self.assertEqual(evidence.outcome, "COMMITTED")
        self.assertEqual(evidence.canonical_epoch, 1)

        layout = DriveHubBootstrap(drive, hub_id).run().layout
        for entry in pack.canonical_outputs:
            item = self.resolve_path(drive, layout.canonical_root_id, entry.target)
            self.assertIsNotNone(item)
            assert item is not None
            self.assertFalse(item.is_folder)
            self.assertEqual(drive.download(item.file_id), (pack.root / entry.payload).read_bytes())

        work = drive.exact_name(hub_id, "work")
        assert work is not None
        projects = drive.exact_name(work.file_id, "projects")
        assert projects is not None
        project = drive.exact_name(projects.file_id, "project-1")
        assert project is not None
        state = drive.exact_name(project.file_id, "STATE.md")
        results = drive.exact_name(project.file_id, "results")
        assert state is not None and results is not None
        self.assertEqual(drive.download(state.file_id), state_raw)
        self.assertEqual(drive.list_children(results.file_id), [])

        # Canonical publication must not cross the later materialization boundary.
        self.assertIsNone(drive.exact_name(project.file_id, "migration-import"))
        self.assertIsNone(drive.exact_name(hub_id, "archive"))

    def test_fresh_migration_commits_nested_canonical_inventory_and_replay_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack, state_raw, root_index_raw = self.build_pack(Path(tmp))
            drive, hub_id = self.build_drive()
            bootstrap = DriveHubBootstrap(drive, hub_id).run()
            root_index = drive.exact_name(hub_id, "INDEX.md")
            assert root_index is not None
            bootstrap_index_raw = drive.download(root_index.file_id)

            self.assert_committed_exact(drive, hub_id, pack, state_raw)
            first = DriveMigrationCanonicalPublication(drive, hub_id).run(pack.root)
            second = DriveMigrationCanonicalPublication(drive, hub_id).run(pack.root)
            self.assertEqual(second, first)
            self.assertEqual(second.outcome, "COMMITTED")

            # The packed migration router is deliberately not published by the
            # canonical transaction layer.
            self.assertNotEqual(bootstrap_index_raw, root_index_raw)
            current_index = drive.exact_name(hub_id, "INDEX.md")
            assert current_index is not None
            self.assertEqual(drive.download(current_index.file_id), bootstrap_index_raw)
            self.assertIsNotNone(bootstrap.layout.canonical_root_id)


    def test_publication_emits_bounded_progress_across_long_drive_phases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack, _, _ = self.build_pack(Path(tmp), candidate_id="migration-progress")
            drive, hub_id = self.build_drive()
            events: list[tuple[str, int | None, int | None]] = []

            class ObservedPublication(DriveMigrationCanonicalPublication):
                def _progress(
                    self,
                    phase: str,
                    current: int | None = None,
                    total: int | None = None,
                ) -> None:
                    events.append((phase, current, total))

            evidence = ObservedPublication(drive, hub_id).run(pack.root)

            self.assertEqual(evidence.outcome, "COMMITTED")
            self.assertIn(("topology", None, None), events)
            self.assertIn(("projects", None, None), events)
            self.assertIn(("ready-change", None, None), events)
            self.assertIn(("ready-change-prepared", 1, 2), events)
            self.assertIn(("ready-change-prepared", 2, 2), events)
            self.assertIn(("ready-change-reverify", 1, 2), events)
            self.assertIn(("ready-change-reverify", 2, 2), events)
            self.assertTrue(
                any(phase == "core-iteration" for phase, _, _ in events),
                "Core orchestration must expose progress while polling the transaction",
            )
            self.assertEqual(events[-1], ("final-verification", None, None))


    def test_publication_specific_mutation_crash_matrix_recovers_from_drive_state(self) -> None:
        points = (
            "drive.migration.change-folder.create.after",
            "drive.migration.prepared-folder.create.after",
            "drive.migration.canonical-00001.prepared.create.after",
            "drive.migration.canonical-00002.prepared.create.after",
            "drive.migration.change.create.after",
            "drive.migration.ready.create.after",
            "drive.migration.postcheck.create.after",
        )
        for point in points:
            with self.subTest(point=point), tempfile.TemporaryDirectory() as tmp:
                pack, state_raw, _ = self.build_pack(Path(tmp))
                drive, hub_id = self.build_drive()
                drive.fault.point = point
                drive.fault.fired = False
                with self.assertRaises(InjectedCrash):
                    DriveMigrationCanonicalPublication(drive, hub_id).run(pack.root)

                drive.fault.point = None
                drive.fault.fired = False
                self.assert_committed_exact(drive, hub_id, pack, state_raw)

    def test_core_zero_master_gap_recovers_without_rebootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack, state_raw, _ = self.build_pack(Path(tmp), candidate_id="migration-gap")
            drive, hub_id = self.build_drive()
            drive.fault.point = "drive.master.migration-gap.unsafe.displace_old.after"
            drive.fault.fired = False

            with self.assertRaises(InjectedCrash):
                DriveMigrationCanonicalPublication(drive, hub_id).run(pack.root)

            self.assertEqual(drive.list_children(hub_id, name="MASTER.json"), [])
            drive.fault.point = None
            drive.fault.fired = False
            self.assert_committed_exact(drive, hub_id, pack, state_raw)

    def test_failed_full_inventory_postcheck_rolls_back_canonical_payloads(self) -> None:
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
            pack, state_raw, _ = self.build_pack(Path(tmp), candidate_id="migration-rollback")
            drive, hub_id = self.build_drive()
            evidence = ForcedPostcheckFailure(drive, hub_id).run(pack.root)

            self.assertEqual(evidence.outcome, "ROLLED_BACK")
            self.assertEqual(evidence.canonical_epoch, 1)
            layout = DriveHubBootstrap(drive, hub_id).run().layout
            for entry in pack.canonical_outputs:
                self.assertIsNone(self.resolve_path(drive, layout.canonical_root_id, entry.target))

            work = drive.exact_name(hub_id, "work")
            assert work is not None
            projects = drive.exact_name(work.file_id, "projects")
            assert projects is not None
            project = drive.exact_name(projects.file_id, "project-1")
            assert project is not None
            state = drive.exact_name(project.file_id, "STATE.md")
            assert state is not None
            self.assertEqual(drive.download(state.file_id), state_raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
