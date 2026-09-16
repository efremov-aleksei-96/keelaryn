from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from keelaryn_core.engine import CoreEngine
from keelaryn_core.protocol import FaultInjector, InjectedCrash, canonical_json_bytes, fingerprint_bytes, sha256_bytes, strict_json_bytes
from keelaryn_core.storage import StorageRuntime


def write_json(path: Path, value: object) -> bytes:
    raw = canonical_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


class FaultMatrix(unittest.TestCase):
    COMMIT_POINTS = [
        "atomic.master.activate.after_temp_fsync",
        "atomic.master.activate.after_replace",
        "atomic.claim.change.after_temp_fsync",
        "atomic.claim.change.after_replace",
        "atomic.claim.prepared.op-add.after_temp_fsync",
        "atomic.claim.prepared.op-add.after_replace",
        "atomic.claim.prepared.op-replace.after_temp_fsync",
        "atomic.claim.prepared.op-replace.after_replace",
        "atomic.claim.control.after_temp_fsync",
        "atomic.claim.control.after_replace",
        "atomic.master.claim_done.after_temp_fsync",
        "atomic.master.claim_done.after_replace",
        "atomic.snapshot.op-replace.after_temp_fsync",
        "atomic.snapshot.op-replace.after_replace",
        "atomic.snapshot.op-delete.after_temp_fsync",
        "atomic.snapshot.op-delete.after_replace",
        "atomic.snapshot.history.after_temp_fsync",
        "atomic.snapshot.history.after_replace",
        "atomic.master.snapshot_done.after_temp_fsync",
        "atomic.master.snapshot_done.after_replace",
        "atomic.master.enter_unsafe.after_temp_fsync",
        "atomic.master.enter_unsafe.after_replace",
        "apply.op-add.before",
        "atomic.publish.op-add.after_temp_fsync",
        "atomic.publish.op-add.after_replace",
        "apply.op-add.after",
        "apply.op-replace.before",
        "atomic.publish.op-replace.after_temp_fsync",
        "atomic.publish.op-replace.after_replace",
        "apply.op-replace.after",
        "apply.op-delete.before",
        "apply.op-delete.after_delete",
        "apply.op-delete.after",
        "atomic.master.apply_done.after_temp_fsync",
        "atomic.master.apply_done.after_replace",
        "atomic.postcheck.accept.after_temp_fsync",
        "atomic.postcheck.accept.after_replace",
        "atomic.master.postcheck_decision.after_temp_fsync",
        "atomic.master.postcheck_decision.after_replace",
        "cleanup.change.after_file_delete",
        "cleanup.change.after_root_delete",
        "cleanup.postcheck.after_delete",
        "cleanup.control.after_file_delete",
        "cleanup.control.after_change_delete",
        "cleanup.control.after_root_delete",
        "atomic.master.finalize.committed.after_temp_fsync",
        "atomic.master.finalize.committed.after_replace",
    ]

    ROLLBACK_POINTS = [
        "atomic.master.postcheck_decision.after_temp_fsync",
        "atomic.master.postcheck_decision.after_replace",
        "rollback.op-delete.before",
        "atomic.rollback.restore.op-delete.after_temp_fsync",
        "atomic.rollback.restore.op-delete.after_replace",
        "rollback.op-delete.after",
        "rollback.op-replace.before",
        "atomic.rollback.restore.op-replace.after_temp_fsync",
        "atomic.rollback.restore.op-replace.after_replace",
        "rollback.op-replace.after",
        "rollback.op-add.before",
        "rollback.op-add.after_delete",
        "rollback.op-add.after",
        "atomic.master.rollback_done.after_temp_fsync",
        "atomic.master.rollback_done.after_replace",
        "atomic.master.finalize.rolled_back.after_temp_fsync",
        "atomic.master.finalize.rolled_back.after_replace",
    ]

    def _scenario(self, decision: str):
        temporary = tempfile.TemporaryDirectory()
        hub = Path(temporary.name) / "hub"
        hub.mkdir()
        StorageRuntime.bootstrap(hub)

        old_replace = b"old replace\n"
        old_delete = b"old delete\n"
        new_replace = b"new replace\n"
        new_add = b"new add\n"
        (hub / "canonical" / "replace.txt").write_bytes(old_replace)
        (hub / "canonical" / "delete.txt").write_bytes(old_delete)

        change_id = "matrix"
        change_dir = hub / "work" / "reconciliation" / "changes" / change_id
        (change_dir / "prepared").mkdir(parents=True)
        (change_dir / "prepared" / "add.bin").write_bytes(new_add)
        (change_dir / "prepared" / "replace.bin").write_bytes(new_replace)
        change = {
            "schema": "keelaryn.change.v1",
            "change_id": change_id,
            "base_canonical_epoch": 0,
            "operations": [
                {
                    "operation_id": "op-add",
                    "kind": "ADD",
                    "target": "add.txt",
                    "old": {"state": "ABSENT"},
                    "new": fingerprint_bytes(new_add),
                    "prepared_path": "prepared/add.bin",
                },
                {
                    "operation_id": "op-replace",
                    "kind": "REPLACE",
                    "target": "replace.txt",
                    "old": fingerprint_bytes(old_replace),
                    "new": fingerprint_bytes(new_replace),
                    "prepared_path": "prepared/replace.bin",
                },
                {
                    "operation_id": "op-delete",
                    "kind": "DELETE",
                    "target": "delete.txt",
                    "old": fingerprint_bytes(old_delete),
                    "new": {"state": "ABSENT"},
                },
            ],
        }
        raw = write_json(change_dir / "CHANGE.json", change)
        digest = sha256_bytes(raw)
        write_json(change_dir / "READY.json", {
            "schema": "keelaryn.ready.v1",
            "state": "READY_FOR_COMMIT",
            "change_id": change_id,
            "change_sha256": digest,
        })
        write_json(hub / "work" / "reconciliation" / "postcheck" / f"{change_id}.json", {
            "schema": "keelaryn.postcheck.v1",
            "change_id": change_id,
            "change_sha256": digest,
            "base_canonical_epoch": 0,
            "decision": decision,
            "reason": f"matrix {decision}",
        })
        data = {
            "old_replace": old_replace,
            "old_delete": old_delete,
            "new_replace": new_replace,
            "new_add": new_add,
        }
        return temporary, hub, data

    def _assert_final(self, hub: Path, data: dict[str, bytes], expected: str) -> None:
        master = strict_json_bytes((hub / "MASTER.json").read_bytes(), label="MASTER")
        self.assertEqual(master["state"], "READY")
        self.assertEqual(master["canonical_read_status"], "SAFE")
        self.assertEqual(master["canonical_epoch"], 1)
        self.assertEqual(master["last_completed_change"]["outcome"], expected)
        self.assertFalse((hub / "control" / "active").exists())
        self.assertTrue((hub / "history" / "matrix" / "HISTORY.json").is_file())
        if expected == "COMMITTED":
            self.assertEqual((hub / "canonical" / "add.txt").read_bytes(), data["new_add"])
            self.assertEqual((hub / "canonical" / "replace.txt").read_bytes(), data["new_replace"])
            self.assertFalse((hub / "canonical" / "delete.txt").exists())
        else:
            self.assertFalse((hub / "canonical" / "add.txt").exists())
            self.assertEqual((hub / "canonical" / "replace.txt").read_bytes(), data["old_replace"])
            self.assertEqual((hub / "canonical" / "delete.txt").read_bytes(), data["old_delete"])

    def _run_point(self, point: str, decision: str, expected: str) -> None:
        temporary, hub, data = self._scenario(decision)
        try:
            with self.assertRaises(InjectedCrash, msg=f"fault point was not reached: {point}"):
                CoreEngine(hub, fault=FaultInjector(point)).run()
            CoreEngine(hub).run()
            self._assert_final(hub, data, expected)
        finally:
            temporary.cleanup()

    def test_commit_crash_matrix(self) -> None:
        for point in self.COMMIT_POINTS:
            with self.subTest(point=point):
                self._run_point(point, "PASS", "COMMITTED")

    def test_rollback_crash_matrix(self) -> None:
        for point in self.ROLLBACK_POINTS:
            with self.subTest(point=point):
                self._run_point(point, "FAIL", "ROLLED_BACK")


if __name__ == "__main__":
    unittest.main(verbosity=2)
