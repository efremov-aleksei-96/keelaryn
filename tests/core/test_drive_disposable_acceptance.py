from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LIVE = REPO / "tests" / "live"
sys.path.insert(0, str(REPO / "core"))
sys.path.insert(0, str(LIVE))

from drive_disposable_acceptance import (
    ACCEPTANCE_ROOT_NAME,
    CHILD_PREFIX,
    SENTINEL_BYTES,
    DisposableAcceptanceBlocked,
    run_disposable_acceptance,
    verify_acceptance_root,
)
from keelaryn_core.drive_model import DriveModel


class DriveDisposableAcceptanceTests(unittest.TestCase):
    @staticmethod
    def guarded_root():
        drive = DriveModel()
        root = drive.create_folder("root", ACCEPTANCE_ROOT_NAME, label="setup.accept-root")
        drive.create_blob(root.file_id, "README.md", SENTINEL_BYTES, label="setup.sentinel")
        return drive, root.file_id

    def test_checked_in_sentinel_fixture_matches_guard_exactly(self) -> None:
        fixture = (LIVE / "fixtures" / "README.md").read_bytes()
        self.assertEqual(fixture, SENTINEL_BYTES)

    def test_exact_guarded_root_runs_pass_and_fail_in_fresh_child_hubs(self) -> None:
        drive, root_id = self.guarded_root()
        result = run_disposable_acceptance(drive, root_id, "model-1")
        self.assertEqual(result.pass_case.outcome, "COMMITTED")
        self.assertEqual(result.fail_case.outcome, "ROLLED_BACK")
        self.assertEqual(result.pass_case.canonical_epoch, 1)
        self.assertEqual(result.fail_case.canonical_epoch, 1)
        children = [item for item in drive.list_children(root_id) if item.name != "README.md"]
        self.assertEqual(len(children), 2)
        self.assertTrue(all(item.is_folder and item.name.startswith(CHILD_PREFIX) for item in children))

        public = json.loads(result.to_json())
        self.assertEqual(public["pass"]["outcome"], "COMMITTED")
        self.assertEqual(public["fail"]["outcome"], "ROLLED_BACK")
        self.assertNotIn(result.pass_case.hub_id, result.to_json())
        self.assertNotIn(result.fail_case.hub_id, result.to_json())

    def test_wrong_root_name_blocks_before_creating_children(self) -> None:
        drive = DriveModel()
        root = drive.create_folder("root", "Production Hub", label="setup.wrong-root")
        drive.create_blob(root.file_id, "README.md", SENTINEL_BYTES, label="setup.sentinel")
        before = tuple(item.file_id for item in drive.list_children(root.file_id))
        with self.assertRaises(DisposableAcceptanceBlocked):
            run_disposable_acceptance(drive, root.file_id, "model-2")
        after = tuple(item.file_id for item in drive.list_children(root.file_id))
        self.assertEqual(after, before)

    def test_wrong_or_duplicate_sentinel_blocks_read_only(self) -> None:
        for mode in ("wrong", "duplicate"):
            with self.subTest(mode=mode):
                drive = DriveModel()
                root = drive.create_folder("root", ACCEPTANCE_ROOT_NAME, label="setup.accept-root")
                raw = b"not the sentinel\n" if mode == "wrong" else SENTINEL_BYTES
                drive.create_blob(root.file_id, "README.md", raw, label="setup.sentinel")
                if mode == "duplicate":
                    drive.create_blob(root.file_id, "README.md", SENTINEL_BYTES, label="setup.sentinel-2")
                before = tuple(item.file_id for item in drive.list_children(root.file_id))
                with self.assertRaises(DisposableAcceptanceBlocked):
                    verify_acceptance_root(drive, root.file_id)
                self.assertEqual(tuple(item.file_id for item in drive.list_children(root.file_id)), before)

    def test_unknown_object_in_acceptance_root_blocks_before_mutation(self) -> None:
        drive, root_id = self.guarded_root()
        drive.create_blob(root_id, "personal-data.txt", b"must not touch", label="setup.unknown")
        before = tuple(item.file_id for item in drive.list_children(root_id))
        with self.assertRaises(DisposableAcceptanceBlocked):
            run_disposable_acceptance(drive, root_id, "model-3")
        self.assertEqual(tuple(item.file_id for item in drive.list_children(root_id)), before)

    def test_prior_acceptance_child_is_allowed_but_invalid_child_shape_blocks(self) -> None:
        drive, root_id = self.guarded_root()
        drive.create_folder(root_id, f"{CHILD_PREFIX}older_PASS", label="setup.prior")
        verify_acceptance_root(drive, root_id)
        drive.create_blob(root_id, f"{CHILD_PREFIX}fake", b"blob", label="setup.fake")
        with self.assertRaises(DisposableAcceptanceBlocked):
            verify_acceptance_root(drive, root_id)

    def test_run_id_validation_happens_before_any_drive_mutation(self) -> None:
        drive, root_id = self.guarded_root()
        before = tuple(item.file_id for item in drive.list_children(root_id))
        with self.assertRaises(DisposableAcceptanceBlocked):
            run_disposable_acceptance(drive, root_id, "bad run id")
        self.assertEqual(tuple(item.file_id for item in drive.list_children(root_id)), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
