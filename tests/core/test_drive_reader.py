from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "core"))
sys.path.insert(0, str(TESTS))

import test_drive_core as core_fixture
from drive_http_model import ModelDriveHttp
from keelaryn_core.drive_model import DriveModel
from keelaryn_core.drive_reader import DriveCanonicalReader, DriveReadBlocked
from keelaryn_core.drive_rest import GoogleDriveBackend
from keelaryn_core.protocol import canonical_json_bytes


class MutatingDownloadBackend:
    def __init__(self, inner, trigger_id, callback):
        self.inner = inner
        self.trigger_id = trigger_id
        self.callback = callback
        self.fired = False

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def download(self, file_id):
        raw = self.inner.download(file_id)
        if file_id == self.trigger_id and not self.fired:
            self.fired = True
            self.callback()
        return raw


class TamperedDownloadBackend:
    def __init__(self, inner, target_id):
        self.inner = inner
        self.target_id = target_id

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def download(self, file_id):
        if file_id == self.target_id:
            return b"tampered transport payload"
        return self.inner.download(file_id)


class DriveReaderTests(unittest.TestCase):
    def build(self):
        drive = DriveModel()
        hub = drive.create_folder("root", "Hub")
        canonical = drive.create_folder(hub.file_id, "canonical")
        nested = drive.create_folder(canonical.file_id, "profile")
        master = drive.create_blob(hub.file_id, "MASTER.json", core_fixture.ready_master())
        root_blob = drive.create_blob(canonical.file_id, "root.txt", b"root-value")
        nested_blob = drive.create_blob(nested.file_id, "name.txt", b"nested-value")
        return drive, hub, canonical, nested, master, root_blob, nested_blob

    @staticmethod
    def blocked_master_bytes() -> bytes:
        return canonical_json_bytes(
            {
                "schema": "keelaryn.master.v1",
                "state": "RECOVERY_BLOCKED",
                "canonical_read_status": "UNSAFE",
                "canonical_epoch": core_fixture.EPOCH,
                "active_change": {
                    "change_id": "change-1",
                    "change_sha256": core_fixture.CHANGE_SHA,
                    "base_canonical_epoch": core_fixture.EPOCH,
                },
                "current_stage": "RECOVERY_BLOCKED",
                "last_completed_change": None,
            }
        )

    def test_ready_reader_returns_stable_nested_snapshot(self) -> None:
        drive, hub, _, _, _, _, _ = self.build()
        result = DriveCanonicalReader(drive, hub.file_id).read_paths(("root.txt", "profile/name.txt"))
        self.assertEqual(result.canonical_epoch, core_fixture.EPOCH)
        by_path = result.by_path()
        self.assertEqual(by_path["root.txt"].content, b"root-value")
        self.assertEqual(by_path["profile/name.txt"].content, b"nested-value")

    def test_active_safe_master_allows_read(self) -> None:
        drive, hub, _, _, master, _, _ = self.build()
        drive.update_content(master.file_id, core_fixture.active_master(unsafe=False), label="setup.active-safe")
        item = DriveCanonicalReader(drive, hub.file_id).read_path("root.txt")
        self.assertEqual(item.content, b"root-value")

    def test_active_unsafe_master_blocks_read(self) -> None:
        drive, hub, _, _, master, _, _ = self.build()
        drive.update_content(master.file_id, core_fixture.active_master(unsafe=True), label="setup.active-unsafe")
        with self.assertRaises(DriveReadBlocked):
            DriveCanonicalReader(drive, hub.file_id).read_path("root.txt")

    def test_recovery_blocked_master_blocks_read(self) -> None:
        drive, hub, _, _, master, _, _ = self.build()
        drive.update_content(master.file_id, self.blocked_master_bytes(), label="setup.blocked")
        with self.assertRaises(DriveReadBlocked):
            DriveCanonicalReader(drive, hub.file_id).read_path("root.txt")

    def test_zero_master_gap_blocks_read(self) -> None:
        drive, hub, _, _, master, _, _ = self.build()
        transition = drive.create_folder(hub.file_id, "transitions")
        drive.move_rename(master.file_id, transition.file_id, "MASTER.old.json", label="setup.master-gap")
        with self.assertRaises(DriveReadBlocked):
            DriveCanonicalReader(drive, hub.file_id).read_path("root.txt")

    def test_duplicate_master_blocks_read(self) -> None:
        drive, hub, _, _, _, _, _ = self.build()
        drive.create_blob(hub.file_id, "MASTER.json", core_fixture.ready_master(), label="external.duplicate-master")
        with self.assertRaises(DriveReadBlocked):
            DriveCanonicalReader(drive, hub.file_id).read_path("root.txt")

    def test_epoch_change_during_payload_read_invalidates_entire_read(self) -> None:
        drive, hub, _, _, master, root_blob, _ = self.build()

        def mutate_master():
            drive.update_content(master.file_id, core_fixture.final_master("COMMITTED"), label="external.epoch-change")

        backend = MutatingDownloadBackend(drive, root_blob.file_id, mutate_master)
        with self.assertRaisesRegex(DriveReadBlocked, "epoch changed"):
            DriveCanonicalReader(backend, hub.file_id).read_path("root.txt")

    def test_safe_to_unsafe_change_during_payload_read_invalidates_entire_read(self) -> None:
        drive, hub, _, _, master, root_blob, _ = self.build()

        def mutate_master():
            drive.update_content(master.file_id, core_fixture.active_master(unsafe=True), label="external.enter-unsafe")

        backend = MutatingDownloadBackend(drive, root_blob.file_id, mutate_master)
        with self.assertRaises(DriveReadBlocked):
            DriveCanonicalReader(backend, hub.file_id).read_path("root.txt")

    def test_duplicate_canonical_target_blocks_read(self) -> None:
        drive, hub, canonical, _, _, _, _ = self.build()
        drive.create_blob(canonical.file_id, "root.txt", b"duplicate", label="external.duplicate-target")
        with self.assertRaises(DriveReadBlocked):
            DriveCanonicalReader(drive, hub.file_id).read_path("root.txt")

    def test_out_of_band_path_move_during_read_is_detected_even_without_epoch_change(self) -> None:
        drive, hub, canonical, _, _, root_blob, _ = self.build()
        elsewhere = drive.create_folder(canonical.file_id, "elsewhere")

        def move_target():
            drive.move_rename(root_blob.file_id, elsewhere.file_id, "root.txt", label="external.move-target")

        backend = MutatingDownloadBackend(drive, root_blob.file_id, move_target)
        with self.assertRaises(DriveReadBlocked):
            DriveCanonicalReader(backend, hub.file_id).read_path("root.txt")

    def test_metadata_content_mismatch_blocks_read(self) -> None:
        drive, hub, _, _, _, root_blob, _ = self.build()
        backend = TamperedDownloadBackend(drive, root_blob.file_id)
        with self.assertRaisesRegex(DriveReadBlocked, "metadata/content mismatch"):
            DriveCanonicalReader(backend, hub.file_id).read_path("root.txt")

    def test_multi_path_read_bounds_parent_listing_amplification(self) -> None:
        class CountingListBackend:
            def __init__(self, inner):
                self.inner = inner
                self.list_calls = 0

            def __getattr__(self, name):
                return getattr(self.inner, name)

            def list_children(self, parent_id, *, name=None, include_trashed=False):
                self.list_calls += 1
                return self.inner.list_children(
                    parent_id,
                    name=name,
                    include_trashed=include_trashed,
                )

        drive, hub, canonical, _, _, _, _ = self.build()
        paths = ["root.txt", "profile/name.txt"]
        for index in range(20):
            name = f"sibling-{index:02d}.txt"
            drive.create_blob(canonical.file_id, name, f"value-{index}".encode("utf-8"))
            paths.append(name)

        backend = CountingListBackend(drive)
        result = DriveCanonicalReader(backend, hub.file_id).read_paths(paths)

        self.assertEqual(len(result.items), len(paths))
        self.assertLessEqual(
            backend.list_calls,
            10,
            "multi-path reader must reuse parent listings within each pre/post snapshot",
        )

    def test_reader_works_through_real_rest_adapter_mapping(self) -> None:
        drive, hub, _, _, _, _, _ = self.build()
        backend = GoogleDriveBackend("token", http=ModelDriveHttp(drive))
        result = DriveCanonicalReader(backend, hub.file_id).read_paths(("root.txt", "profile/name.txt"))
        self.assertEqual(result.canonical_epoch, core_fixture.EPOCH)
        self.assertEqual(result.by_path()["profile/name.txt"].content, b"nested-value")


if __name__ == "__main__":
    unittest.main(verbosity=2)
