from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from keelaryn_core.drive_bootstrap import DriveHubBootstrap
from keelaryn_core.drive_model import DriveModel
from keelaryn_core.pilot_drive import DrivePilotImportService
from keelaryn_core.pilot_pack import build_pilot_pack
from keelaryn_core.protocol import FaultInjector, InjectedCrash, canonical_json_bytes


class DrivePilotImportTests(unittest.TestCase):
    def build_pack(self, root: Path, *, pilot_id: str = "pilot-test"):
        source = root / "source"
        source.mkdir()
        (source / "profile.md").write_bytes(b"# Profile\n\nLimited pilot material.\n")
        (source / "notes.txt").write_bytes(b"second pilot file\n")
        manifest = root / "PILOT_SOURCE.json"
        manifest.write_bytes(
            canonical_json_bytes(
                {
                    "schema": "keelaryn.pilot-source.v1",
                    "pilot_id": pilot_id,
                    "entries": [
                        {"source": "profile.md", "target": "profile.md"},
                        {"source": "notes.txt", "target": "notes.txt"},
                    ],
                }
            )
        )
        return build_pilot_pack(source, manifest, root / "pack")

    def build_drive(self):
        drive = DriveModel(fault=FaultInjector())
        hub = drive.create_folder("root", "Disposable Pilot Hub", label="setup.hub")
        return drive, hub.file_id

    def assert_committed_exact(self, drive: DriveModel, hub_id: str, pack) -> None:
        evidence = DrivePilotImportService(drive, hub_id).run(pack)
        self.assertEqual(evidence.pilot_id, pack.pilot_id)
        self.assertEqual(evidence.pack_sha256, pack.pack_sha256)
        self.assertEqual(evidence.file_count, 2)
        self.assertEqual(evidence.total_bytes, pack.total_bytes)
        self.assertEqual(evidence.outcome, "COMMITTED")
        self.assertEqual(evidence.canonical_epoch, 1)

        layout = DriveHubBootstrap(drive, hub_id).run().layout
        for entry in pack.entries:
            item = drive.exact_name(layout.canonical_root_id, entry.target)
            self.assertIsNotNone(item)
            assert item is not None
            self.assertEqual(drive.download(item.file_id), pack.payload_bytes(entry))
        self.assertEqual(len(drive.list_children(layout.canonical_root_id)), len(pack.entries))

    def test_fresh_pack_commits_exactly_and_replay_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack = self.build_pack(Path(tmp))
            drive, hub_id = self.build_drive()
            self.assert_committed_exact(drive, hub_id, pack)

            first = DrivePilotImportService(drive, hub_id).run(pack)
            second = DrivePilotImportService(drive, hub_id).run(pack)
            self.assertEqual(second, first)
            self.assertEqual(second.outcome, "COMMITTED")
            self.assertEqual(second.canonical_epoch, 1)

    def test_pilot_specific_mutation_crash_matrix_recovers_from_drive_state(self) -> None:
        points = (
            "drive.pilot.change-folder.create.after",
            "drive.pilot.prepared-folder.create.after",
            "drive.pilot.import-001.prepared.create.after",
            "drive.pilot.import-002.prepared.create.after",
            "drive.pilot.change.create.after",
            "drive.pilot.ready.create.after",
            "drive.pilot.postcheck.create.after",
        )
        for point in points:
            with self.subTest(point=point), tempfile.TemporaryDirectory() as tmp:
                pack = self.build_pack(Path(tmp))
                drive, hub_id = self.build_drive()
                drive.fault.point = point
                drive.fault.fired = False
                with self.assertRaises(InjectedCrash):
                    DrivePilotImportService(drive, hub_id).run(pack)

                drive.fault.point = None
                drive.fault.fired = False
                self.assert_committed_exact(drive, hub_id, pack)

    def test_core_zero_master_gap_recovers_without_rebootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack = self.build_pack(Path(tmp), pilot_id="pilot-gap")
            drive, hub_id = self.build_drive()
            drive.fault.point = "drive.master.pilot-gap.unsafe.displace_old.after"
            drive.fault.fired = False

            with self.assertRaises(InjectedCrash):
                DrivePilotImportService(drive, hub_id).run(pack)

            self.assertEqual(drive.list_children(hub_id, name="MASTER.json"), [])
            drive.fault.point = None
            drive.fault.fired = False
            self.assert_committed_exact(drive, hub_id, pack)


if __name__ == "__main__":
    unittest.main(verbosity=2)
