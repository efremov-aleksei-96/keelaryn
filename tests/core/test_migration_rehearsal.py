from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT / "tests" / "live"
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(LIVE))

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
from keelaryn_core.migration_rehearsal import (  # noqa: E402
    DriveMigrationDisposableRehearsal,
    DriveMigrationRehearsalBlocked,
)
from keelaryn_core.protocol import FaultInjector, InjectedCrash, canonical_json_bytes  # noqa: E402
from run_migration_disposable_read_only_finalizer import ReadOnlyDriveProxy  # noqa: E402


class DriveMigrationDisposableRehearsalTests(unittest.TestCase):
    def build_pack(
        self,
        root: Path,
        *,
        candidate_id: str = "migration-rehearsal",
        with_root_index: bool = True,
    ):
        source = root / "source"
        source.mkdir()
        (source / "profile.md").write_bytes(b"# Migrated profile\r\n")
        (source / "value.json").write_bytes(b'{"value":1}\r\n')
        (source / "project-note.md").write_bytes(b"legacy project note\r\n")
        (source / "archive.txt").write_bytes(b"historical only\r\n")
        if with_root_index:
            (source / "router.md").write_bytes(b"legacy router source\r\n")

        sources = ["archive.txt", "profile.md", "project-note.md", "value.json"]
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
        state_raw = b"# Project 1\r\n\r\nInitial migrated state.\r\n"
        (states / "project-1.md").write_bytes(state_raw)
        root_index_raw = (
            b"# Migrated INDEX\r\n\r\n"
            b"- Profile: `canonical/identity/profile.md`\r\n"
            b"- Value: `canonical/data/nested/value.json`\r\n"
        )
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
            {"source": "value.json", "classification": "CANONICAL_IMPORT"},
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

    def test_full_rehearsal_passes_exact_acceptance_and_replay_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack, state_raw, root_index_raw = self.build_pack(Path(tmp))
            drive, hub_id = self.build_drive()
            service = DriveMigrationDisposableRehearsal(drive, hub_id)

            first = service.run(pack.root)
            index_after_first = drive.exact_name(hub_id, "INDEX.md")
            assert index_after_first is not None
            second = service.run(pack.root)
            index_after_second = drive.exact_name(hub_id, "INDEX.md")
            assert index_after_second is not None

            self.assertEqual(second, first)
            self.assertEqual(first.outcome, "PASS")
            self.assertEqual(first.candidate_id, pack.candidate_id)
            self.assertEqual(first.pack_sha256, pack.pack_sha256)
            self.assertEqual(first.canonical_epoch, 1)
            self.assertEqual(first.reader_epoch, 1)
            self.assertEqual(first.canonical_file_count, 2)
            self.assertEqual(first.canonical_total_bytes, pack.canonical_total_bytes)
            self.assertEqual(first.preserved_file_count, 2)
            self.assertEqual(first.preserved_total_bytes, pack.preserved_total_bytes)
            self.assertEqual(first.project_count, 1)
            self.assertEqual(first.router_outcome, "COMMITTED")
            self.assertEqual(first.no_op_phase, "IDLE")
            self.assertEqual(first.restart_state, "READY_CLEAN")
            self.assertEqual(len(first.canonical_inventory_sha256), 64)
            self.assertEqual(len(first.preservation_inventory_sha256), 64)
            self.assertEqual(len(first.reconciliation_state_sha256), 64)
            self.assertEqual(len(first.root_index_sha256), 64)

            # Rehearsal replay is acceptance-only once every child layer committed.
            self.assertEqual(index_after_second.file_id, index_after_first.file_id)
            self.assertEqual(index_after_second.version, index_after_first.version)
            self.assertEqual(drive.download(index_after_second.file_id), root_index_raw)

            project_state = self.resolve_path(drive, hub_id, "work/projects/project-1/STATE.md")
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
            self.assertIsNotNone(project_state)
            self.assertIsNotNone(project_note)
            self.assertIsNotNone(archive)
            assert project_state is not None and project_note is not None and archive is not None
            self.assertEqual(drive.download(project_state.file_id), state_raw)
            self.assertEqual(drive.download(project_note.file_id), b"legacy project note\r\n")
            self.assertEqual(drive.download(archive.file_id), b"historical only\r\n")

            master = DriveHubBootstrap(drive, hub_id).run().master
            self.assertEqual(master["state"], "READY")
            self.assertEqual(master["canonical_read_status"], "SAFE")
            self.assertEqual(master["canonical_epoch"], 1)
            self.assertEqual(master["last_completed_change"]["change_id"], pack.candidate_id)
            self.assertEqual(master["last_completed_change"]["outcome"], "COMMITTED")

    def test_completed_rehearsal_replay_is_strictly_read_only_under_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack, _, _ = self.build_pack(
                Path(tmp),
                candidate_id="migration-rehearsal-read-only-finalizer",
            )
            drive, hub_id = self.build_drive()
            first = DriveMigrationDisposableRehearsal(drive, hub_id).run(pack.root)

            def snapshot():
                return (
                    drive._next_id,
                    drive._next_revision,
                    dict(drive._items),
                    dict(drive._content),
                    set(drive._reserved_ids),
                    dict(drive._stale_get),
                    {key: list(value) for key, value in drive._stale_list.items()},
                )

            before = snapshot()
            guarded = ReadOnlyDriveProxy(drive)
            second = DriveMigrationDisposableRehearsal(
                guarded,
                hub_id,
            ).run(pack.root)
            after = snapshot()

            self.assertEqual(second, first)
            self.assertEqual(guarded.mutation_attempt_count, 0)
            self.assertEqual(after, before)

    def test_post_commit_replay_bounds_canonical_payload_download_amplification(self) -> None:
        class CountingDrive(DriveModel):
            def __init__(self):
                super().__init__(fault=FaultInjector())
                self.download_counts: dict[str, int] = {}

            def download(self, file_id: str) -> bytes:
                self.download_counts[file_id] = self.download_counts.get(file_id, 0) + 1
                return super().download(file_id)

        with tempfile.TemporaryDirectory() as tmp:
            pack, _, _ = self.build_pack(
                Path(tmp),
                candidate_id="migration-rehearsal-download-bound",
            )
            drive = CountingDrive()
            hub = drive.create_folder("root", "Disposable Migration Hub", label="setup.hub")
            hub_id = hub.file_id

            first = DriveMigrationDisposableRehearsal(drive, hub_id).run(pack.root)
            self.assertEqual(first.outcome, "PASS")

            layout = DriveHubBootstrap(drive, hub_id).run().layout
            canonical_ids: list[str] = []
            for entry in pack.canonical_outputs:
                item = self.resolve_path(drive, layout.canonical_root_id, entry.target)
                assert item is not None
                canonical_ids.append(item.file_id)

            drive.download_counts.clear()
            second = DriveMigrationDisposableRehearsal(drive, hub_id).run(pack.root)
            self.assertEqual(second.outcome, "PASS")

            for file_id in canonical_ids:
                with self.subTest(file_id=file_id):
                    self.assertLessEqual(
                        drive.download_counts.get(file_id, 0),
                        2,
                        "post-COMMIT replay must not repeatedly download canonical payload bytes",
                    )

    def test_rehearsal_exposes_post_commit_acceptance_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack, _, _ = self.build_pack(
                Path(tmp),
                candidate_id="migration-rehearsal-progress-after-commit",
            )
            drive, hub_id = self.build_drive()
            events: list[str] = []

            evidence = DriveMigrationDisposableRehearsal(
                drive,
                hub_id,
                progress=lambda phase, current=None, total=None: events.append(phase),
            ).run(pack.root)

            self.assertEqual(evidence.outcome, "PASS")
            expected = [
                "preservation",
                "router-precheck",
                "router-commit",
                "router-postcheck",
                "canonical-reader",
                "workflow-verification",
                "idle-restart",
                "final-master",
            ]
            positions = []
            for phase in expected:
                with self.subTest(phase=phase):
                    self.assertIn(phase, events)
                positions.append(events.index(phase))
            self.assertEqual(positions, sorted(positions))

    def test_rehearsal_recovers_across_publication_preservation_and_router_crashes(self) -> None:
        points = (
            "drive.migration.ready.create.after",
            "drive.migration.preserve.preserved-00001.create.after",
            "drive.migration.router.migration-rehearsal-restart.index.update.after",
        )
        for point in points:
            with self.subTest(point=point), tempfile.TemporaryDirectory() as tmp:
                pack, _, root_index_raw = self.build_pack(
                    Path(tmp),
                    candidate_id="migration-rehearsal-restart",
                )
                drive, hub_id = self.build_drive()
                drive.fault.point = point
                drive.fault.fired = False

                with self.assertRaises(InjectedCrash):
                    DriveMigrationDisposableRehearsal(drive, hub_id).run(pack.root)
                self.assertTrue(drive.fault.fired)

                drive.fault.point = None
                drive.fault.fired = False
                evidence = DriveMigrationDisposableRehearsal(drive, hub_id).run(pack.root)
                self.assertEqual(evidence.outcome, "PASS")
                self.assertEqual(evidence.no_op_phase, "IDLE")
                self.assertEqual(evidence.restart_state, "READY_CLEAN")
                index = drive.exact_name(hub_id, "INDEX.md")
                assert index is not None
                self.assertEqual(drive.download(index.file_id), root_index_raw)

    def test_rolled_back_canonical_candidate_cannot_be_accepted_as_rehearsal(self) -> None:
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
            pack, _, _ = self.build_pack(Path(tmp), candidate_id="migration-rehearsal-rollback")
            drive, hub_id = self.build_drive()
            rolled_back = ForcedPostcheckFailure(drive, hub_id).run(pack.root)
            self.assertEqual(rolled_back.outcome, "ROLLED_BACK")

            with self.assertRaisesRegex(
                DriveMigrationRehearsalBlocked,
                "requires COMMITTED epoch 1",
            ):
                DriveMigrationDisposableRehearsal(drive, hub_id).run(pack.root)
            self.assertIsNone(drive.exact_name(hub_id, "archive"))

    def test_replay_fails_closed_after_canonical_or_router_tamper(self) -> None:
        for tamper in ("canonical", "router"):
            with self.subTest(tamper=tamper), tempfile.TemporaryDirectory() as tmp:
                pack, _, _ = self.build_pack(
                    Path(tmp),
                    candidate_id=f"migration-rehearsal-tamper-{tamper}",
                )
                drive, hub_id = self.build_drive()
                DriveMigrationDisposableRehearsal(drive, hub_id).run(pack.root)

                if tamper == "canonical":
                    canonical = drive.exact_name(hub_id, "canonical")
                    assert canonical is not None
                    profile = self.resolve_path(drive, canonical.file_id, "identity/profile.md")
                    assert profile is not None
                    drive.update_content(profile.file_id, b"tampered canonical\r\n")
                    expected = "canonical migration publication failed during rehearsal"
                else:
                    index = drive.exact_name(hub_id, "INDEX.md")
                    assert index is not None
                    drive.update_content(index.file_id, b"# unrelated router\r\n")
                    expected = "root router publication failed during rehearsal"

                with self.assertRaisesRegex(DriveMigrationRehearsalBlocked, expected):
                    DriveMigrationDisposableRehearsal(drive, hub_id).run(pack.root)

    def test_final_reconciliation_tamper_is_detected_by_acceptance_layer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack, _, _ = self.build_pack(Path(tmp), candidate_id="migration-rehearsal-reconciliation")
            drive, hub_id = self.build_drive()
            DriveMigrationDisposableRehearsal(drive, hub_id).run(pack.root)

            work = drive.exact_name(hub_id, "work")
            assert work is not None
            reconciliation = drive.exact_name(work.file_id, "reconciliation")
            assert reconciliation is not None
            state = drive.exact_name(reconciliation.file_id, "STATE.md")
            assert state is not None
            drive.update_content(state.file_id, b"# altered reconciliation\r\n")

            with self.assertRaisesRegex(
                DriveMigrationRehearsalBlocked,
                "Reconciliation STATE changed",
            ):
                DriveMigrationDisposableRehearsal(drive, hub_id).run(pack.root)

    def test_candidate_without_root_router_passes_with_not_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack, _, _ = self.build_pack(
                Path(tmp),
                candidate_id="migration-rehearsal-no-router",
                with_root_index=False,
            )
            drive, hub_id = self.build_drive()
            expected_index = DriveHubBootstrap.initial_index_bytes()

            evidence = DriveMigrationDisposableRehearsal(drive, hub_id).run(pack.root)

            self.assertEqual(evidence.outcome, "PASS")
            self.assertEqual(evidence.router_outcome, "NOT_REQUIRED")
            self.assertEqual(evidence.no_op_phase, "IDLE")
            self.assertEqual(evidence.restart_state, "READY_CLEAN")
            index = drive.exact_name(hub_id, "INDEX.md")
            assert index is not None
            self.assertEqual(drive.download(index.file_id), expected_index)


if __name__ == "__main__":
    unittest.main(verbosity=2)
