from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from keelaryn_core.engine import CoreEngine
from keelaryn_core.protocol import (
    FaultInjector,
    InjectedCrash,
    ProtocolError,
    RecoveryBlocked,
    canonical_json_bytes,
    fingerprint_bytes,
    sha256_bytes,
    strict_json_bytes,
)
from keelaryn_core.storage import StorageRuntime


def write_json(path: Path, value: object) -> bytes:
    raw = canonical_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


class CoreHarness(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.hub = Path(self.tmp.name) / "hub"
        self.hub.mkdir()
        StorageRuntime.bootstrap(self.hub)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def master(self) -> dict:
        return strict_json_bytes((self.hub / "MASTER.json").read_bytes(), label="MASTER")

    def seed(self, relative: str, data: bytes) -> dict:
        path = self.hub / "canonical" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return fingerprint_bytes(data)

    @staticmethod
    def absent() -> dict:
        return {"state": "ABSENT"}

    def prepare_change(self, change_id: str, operations: list[dict], *, epoch: int = 0) -> tuple[dict, str]:
        change_dir = self.hub / "work" / "reconciliation" / "changes" / change_id
        change_dir.mkdir(parents=True)
        change_ops = []
        for op in operations:
            item = dict(op)
            prepared = item.pop("prepared_bytes", None)
            if prepared is not None:
                path = change_dir / item["prepared_path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(prepared)
            change_ops.append(item)
        change = {
            "schema": "keelaryn.change.v1",
            "change_id": change_id,
            "base_canonical_epoch": epoch,
            "operations": change_ops,
        }
        raw = write_json(change_dir / "CHANGE.json", change)
        digest = sha256_bytes(raw)
        write_json(
            change_dir / "READY.json",
            {
                "schema": "keelaryn.ready.v1",
                "state": "READY_FOR_COMMIT",
                "change_id": change_id,
                "change_sha256": digest,
            },
        )
        return change, digest

    def postcheck(self, change_id: str, digest: str, decision: str, *, epoch: int = 0) -> None:
        write_json(
            self.hub / "work" / "reconciliation" / "postcheck" / f"{change_id}.json",
            {
                "schema": "keelaryn.postcheck.v1",
                "change_id": change_id,
                "change_sha256": digest,
                "base_canonical_epoch": epoch,
                "decision": decision,
                "reason": f"test {decision}",
            },
        )

    def mixed_operations(self) -> tuple[list[dict], dict[str, bytes]]:
        old_replace = b"old replace\n"
        old_delete = b"old delete\n"
        new_replace = b"new replace\n"
        new_add = b"new add\n"
        self.seed("replace.txt", old_replace)
        self.seed("delete.txt", old_delete)
        operations = [
            {
                "operation_id": "op-add",
                "kind": "ADD",
                "target": "add.txt",
                "old": self.absent(),
                "new": fingerprint_bytes(new_add),
                "prepared_path": "prepared/add.bin",
                "prepared_bytes": new_add,
            },
            {
                "operation_id": "op-replace",
                "kind": "REPLACE",
                "target": "replace.txt",
                "old": fingerprint_bytes(old_replace),
                "new": fingerprint_bytes(new_replace),
                "prepared_path": "prepared/replace.bin",
                "prepared_bytes": new_replace,
            },
            {
                "operation_id": "op-delete",
                "kind": "DELETE",
                "target": "delete.txt",
                "old": fingerprint_bytes(old_delete),
                "new": self.absent(),
            },
        ]
        return operations, {
            "old_replace": old_replace,
            "old_delete": old_delete,
            "new_replace": new_replace,
            "new_add": new_add,
        }

    def advance_to_wait(self, change_id: str = "c1") -> tuple[str, dict[str, bytes]]:
        ops, data = self.mixed_operations()
        _, digest = self.prepare_change(change_id, ops)
        self.assertEqual(CoreEngine(self.hub).run(), "WAIT_POSTCHECK")
        self.assertEqual(self.master()["current_stage"], "WAIT_POSTCHECK")
        return digest, data

    def test_commit_add_replace_delete(self) -> None:
        digest, data = self.advance_to_wait()
        self.postcheck("c1", digest, "PASS")
        self.assertEqual(CoreEngine(self.hub).run(), "COMMITTED")
        master = self.master()
        self.assertEqual((master["state"], master["canonical_read_status"], master["canonical_epoch"]), ("READY", "SAFE", 1))
        self.assertEqual(master["last_completed_change"]["outcome"], "COMMITTED")
        self.assertEqual((self.hub / "canonical" / "add.txt").read_bytes(), data["new_add"])
        self.assertEqual((self.hub / "canonical" / "replace.txt").read_bytes(), data["new_replace"])
        self.assertFalse((self.hub / "canonical" / "delete.txt").exists())
        self.assertFalse((self.hub / "control" / "active").exists())
        self.assertTrue((self.hub / "history" / "c1" / "HISTORY.json").is_file())

    def test_semantic_fail_rolls_back(self) -> None:
        digest, data = self.advance_to_wait()
        self.postcheck("c1", digest, "FAIL")
        self.assertEqual(CoreEngine(self.hub).run(), "ROLLED_BACK")
        master = self.master()
        self.assertEqual(master["canonical_epoch"], 1)
        self.assertEqual(master["last_completed_change"]["outcome"], "ROLLED_BACK")
        self.assertFalse((self.hub / "canonical" / "add.txt").exists())
        self.assertEqual((self.hub / "canonical" / "replace.txt").read_bytes(), data["old_replace"])
        self.assertEqual((self.hub / "canonical" / "delete.txt").read_bytes(), data["old_delete"])

    def test_duplicate_ready_is_noop_failure(self) -> None:
        for cid in ("a", "b"):
            data = cid.encode()
            self.prepare_change(cid, [{
                "operation_id": f"op-{cid}",
                "kind": "ADD",
                "target": f"{cid}.txt",
                "old": self.absent(),
                "new": fingerprint_bytes(data),
                "prepared_path": "prepared/new.bin",
                "prepared_bytes": data,
            }])
        with self.assertRaises(ProtocolError):
            CoreEngine(self.hub).run()
        self.assertEqual((self.master()["state"], self.master()["canonical_epoch"]), ("READY", 0))

    def test_stale_epoch_rejected_before_activation(self) -> None:
        data = b"x"
        self.prepare_change("stale", [{
            "operation_id": "op", "kind": "ADD", "target": "x.txt", "old": self.absent(),
            "new": fingerprint_bytes(data), "prepared_path": "prepared/new.bin", "prepared_bytes": data,
        }], epoch=1)
        with self.assertRaises(ProtocolError):
            CoreEngine(self.hub).run()
        self.assertEqual(self.master()["state"], "READY")

    def test_prepared_hash_mismatch_rejected(self) -> None:
        self.prepare_change("badprep", [{
            "operation_id": "op", "kind": "ADD", "target": "x.txt", "old": self.absent(),
            "new": fingerprint_bytes(b"declared"), "prepared_path": "prepared/new.bin", "prepared_bytes": b"actual",
        }])
        with self.assertRaises(ProtocolError):
            CoreEngine(self.hub).run()
        self.assertEqual(self.master()["state"], "READY")

    def test_old_target_mismatch_rejected(self) -> None:
        self.seed("x.txt", b"other")
        new = b"new"
        self.prepare_change("badold", [{
            "operation_id": "op", "kind": "REPLACE", "target": "x.txt", "old": fingerprint_bytes(b"expected"),
            "new": fingerprint_bytes(new), "prepared_path": "prepared/new.bin", "prepared_bytes": new,
        }])
        with self.assertRaises(ProtocolError):
            CoreEngine(self.hub).run()
        self.assertEqual(self.master()["state"], "READY")

    def test_external_modification_blocks_recovery(self) -> None:
        self.advance_to_wait()
        (self.hub / "canonical" / "replace.txt").write_bytes(b"rogue")
        with self.assertRaises(RecoveryBlocked):
            CoreEngine(self.hub).run()
        self.assertEqual((self.master()["state"], self.master()["canonical_read_status"]), ("RECOVERY_BLOCKED", "UNSAFE"))
        self.assertTrue((self.hub / "control" / "active" / "RECOVERY_BLOCK.json").is_file())

    def test_crash_after_enter_unsafe_recovers(self) -> None:
        ops, _ = self.mixed_operations()
        self.prepare_change("crash1", ops)
        with self.assertRaises(InjectedCrash):
            CoreEngine(self.hub, fault=FaultInjector("atomic.master.enter_unsafe.after_replace")).run()
        self.assertEqual(self.master()["current_stage"], "APPLY")
        self.assertEqual(CoreEngine(self.hub).run(), "WAIT_POSTCHECK")

    def test_crash_after_publish_recovers_idempotently(self) -> None:
        ops, data = self.mixed_operations()
        self.prepare_change("crash2", ops)
        with self.assertRaises(InjectedCrash):
            CoreEngine(self.hub, fault=FaultInjector("atomic.publish.op-replace.after_replace")).run()
        self.assertEqual(CoreEngine(self.hub).run(), "WAIT_POSTCHECK")
        self.assertEqual((self.hub / "canonical" / "replace.txt").read_bytes(), data["new_replace"])

    def test_crash_during_rollback_recovers(self) -> None:
        digest, data = self.advance_to_wait("crashrb")
        self.postcheck("crashrb", digest, "FAIL")
        with self.assertRaises(InjectedCrash):
            CoreEngine(self.hub, fault=FaultInjector("rollback.op-replace.after")).run()
        self.assertEqual(CoreEngine(self.hub).run(), "ROLLED_BACK")
        self.assertEqual((self.hub / "canonical" / "replace.txt").read_bytes(), data["old_replace"])

    def test_crash_during_change_cleanup_recovers(self) -> None:
        digest, _ = self.advance_to_wait("cleanup1")
        self.postcheck("cleanup1", digest, "PASS")
        with self.assertRaises(InjectedCrash):
            CoreEngine(self.hub, fault=FaultInjector("cleanup.change.after_file_delete")).run()
        self.assertEqual(CoreEngine(self.hub).run(), "COMMITTED")

    def test_crash_after_control_change_delete_recovers(self) -> None:
        digest, _ = self.advance_to_wait("cleanup2")
        self.postcheck("cleanup2", digest, "PASS")
        with self.assertRaises(InjectedCrash):
            CoreEngine(self.hub, fault=FaultInjector("cleanup.control.after_change_delete")).run()
        self.assertEqual(CoreEngine(self.hub).run(), "COMMITTED")

    def test_crash_after_control_root_delete_recovers(self) -> None:
        digest, _ = self.advance_to_wait("cleanup3")
        self.postcheck("cleanup3", digest, "PASS")
        with self.assertRaises(InjectedCrash):
            CoreEngine(self.hub, fault=FaultInjector("cleanup.control.after_root_delete")).run()
        self.assertFalse((self.hub / "control" / "active").exists())
        self.assertEqual(CoreEngine(self.hub).run(), "COMMITTED")

    def test_fresh_preunsafe_staged_revalidation_aborts_without_epoch(self) -> None:
        ops, data = self.mixed_operations()
        self.prepare_change("fresh", ops)
        with self.assertRaises(InjectedCrash):
            CoreEngine(self.hub, fault=FaultInjector("atomic.master.snapshot_done.after_replace")).run()
        self.assertEqual(self.master()["current_stage"], "ENTER_UNSAFE")
        (self.hub / "control" / "active" / "prepared" / "replace.bin").write_bytes(b"corrupt")
        self.assertEqual(CoreEngine(self.hub).run(), "ABORTED_PRECOMMIT")
        master = self.master()
        self.assertEqual((master["state"], master["canonical_epoch"]), ("READY", 0))
        self.assertEqual((self.hub / "canonical" / "replace.txt").read_bytes(), data["old_replace"])
        self.assertTrue((self.hub / "work" / "reconciliation" / "changes" / "fresh" / "READY.json").is_file())

    def test_duplicate_json_key_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            strict_json_bytes(b'{"a":1,"a":2}', label="dup")

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink unavailable")
    def test_symlink_target_rejected(self) -> None:
        outside = Path(self.tmp.name) / "outside.txt"
        outside.write_bytes(b"old")
        os.symlink(outside, self.hub / "canonical" / "link.txt")
        new = b"new"
        self.prepare_change("link", [{
            "operation_id": "op", "kind": "REPLACE", "target": "link.txt", "old": fingerprint_bytes(b"old"),
            "new": fingerprint_bytes(new), "prepared_path": "prepared/new.bin", "prepared_bytes": new,
        }])
        with self.assertRaises(ProtocolError):
            CoreEngine(self.hub).run()
        self.assertEqual(outside.read_bytes(), b"old")


if __name__ == "__main__":
    unittest.main(verbosity=2)
