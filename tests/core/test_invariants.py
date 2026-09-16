from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from keelaryn_core.engine import CoreEngine
from keelaryn_core.protocol import FaultInjector, InjectedCrash, ProtocolError, RecoveryBlocked, canonical_json_bytes, fingerprint_bytes
from test_core import CoreHarness, write_json


class FailClosedInvariants(CoreHarness):
    def _single_add(self, change_id: str = "one") -> tuple[str, bytes]:
        data = b"new bytes\n"
        _, digest = self.prepare_change(change_id, [{
            "operation_id": "op",
            "kind": "ADD",
            "target": "new.txt",
            "old": self.absent(),
            "new": fingerprint_bytes(data),
            "prepared_path": "prepared/new.bin",
            "prepared_bytes": data,
        }])
        return digest, data

    def test_change_id_reuse_history_collision_rejected_preflight(self) -> None:
        self._single_add("reused")
        history = self.hub / "history" / "reused"
        history.mkdir()
        (history / "sentinel").write_text("old durable identity", encoding="utf-8")
        with self.assertRaises(ProtocolError):
            CoreEngine(self.hub).run()
        self.assertEqual(self.master()["state"], "READY")
        self.assertEqual(self.master()["canonical_epoch"], 0)
        self.assertTrue((history / "sentinel").is_file())

    def test_malformed_postcheck_cannot_authorize_transition(self) -> None:
        digest, _ = self._single_add("malformed")
        self.assertEqual(CoreEngine(self.hub).run(), "WAIT_POSTCHECK")
        post = self.hub / "work" / "reconciliation" / "postcheck" / "malformed.json"
        post.write_bytes(b'{"schema":"keelaryn.postcheck.v1",')
        self.assertEqual(CoreEngine(self.hub).run(), "WAIT_POSTCHECK")
        master = self.master()
        self.assertEqual(master["current_stage"], "WAIT_POSTCHECK")
        self.assertEqual(master["canonical_read_status"], "UNSAFE")
        self.assertEqual(master["active_change"]["change_sha256"], digest)

    def test_identity_mismatched_postcheck_cannot_authorize_transition(self) -> None:
        digest, _ = self._single_add("mismatch")
        self.assertEqual(CoreEngine(self.hub).run(), "WAIT_POSTCHECK")
        write_json(self.hub / "work" / "reconciliation" / "postcheck" / "mismatch.json", {
            "schema": "keelaryn.postcheck.v1",
            "change_id": "mismatch",
            "change_sha256": "0" * 64 if digest != "0" * 64 else "1" * 64,
            "base_canonical_epoch": 0,
            "decision": "PASS",
            "reason": "wrong identity",
        })
        self.assertEqual(CoreEngine(self.hub).run(), "WAIT_POSTCHECK")
        self.assertEqual(self.master()["current_stage"], "WAIT_POSTCHECK")

    def test_history_corruption_after_unsafe_blocks_recovery(self) -> None:
        self.advance_to_wait("history-corrupt")
        snapshot = self.hub / "history" / "history-corrupt" / "old" / "op-replace.bin"
        snapshot.write_bytes(b"corrupt snapshot")
        with self.assertRaises(RecoveryBlocked):
            CoreEngine(self.hub).run()
        master = self.master()
        self.assertEqual(master["state"], "RECOVERY_BLOCKED")
        self.assertEqual(master["canonical_read_status"], "UNSAFE")

    def test_ready_with_active_control_residue_is_rejected(self) -> None:
        residue = self.hub / "control" / "active"
        residue.mkdir()
        (residue / "unknown.txt").write_text("residue", encoding="utf-8")
        with self.assertRaises(ProtocolError):
            CoreEngine(self.hub).run()
        self.assertEqual(self.master()["state"], "READY")

    def test_cleanup_extra_material_blocks_instead_of_deleting(self) -> None:
        digest, _ = self.advance_to_wait("cleanup-tamper")
        self.postcheck("cleanup-tamper", digest, "PASS")
        with self.assertRaises(InjectedCrash):
            CoreEngine(
                self.hub,
                fault=FaultInjector("atomic.master.postcheck_decision.after_replace"),
            ).run()
        self.assertEqual(self.master()["current_stage"], "FINALIZE_COMMIT")
        extra = self.hub / "work" / "reconciliation" / "changes" / "cleanup-tamper" / "unexpected.txt"
        extra.write_text("must not be silently deleted", encoding="utf-8")
        with self.assertRaises(RecoveryBlocked):
            CoreEngine(self.hub).run()
        self.assertTrue(extra.is_file())
        self.assertEqual(self.master()["state"], "RECOVERY_BLOCKED")

    def test_staged_corruption_after_unsafe_blocks_finalization(self) -> None:
        digest, _ = self.advance_to_wait("staged-tamper")
        staged = self.hub / "control" / "active" / "prepared" / "replace.bin"
        staged.write_bytes(b"tampered after publication")
        self.postcheck("staged-tamper", digest, "PASS")
        with self.assertRaises(RecoveryBlocked):
            CoreEngine(self.hub).run()
        self.assertEqual(self.master()["state"], "RECOVERY_BLOCKED")


if __name__ == "__main__":
    import unittest
    unittest.main(verbosity=2)
