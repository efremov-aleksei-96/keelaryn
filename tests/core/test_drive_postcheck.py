from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from drive_http_model import ModelDriveHttp
from keelaryn_core.drive_backend import DriveUncertainMutation
from keelaryn_core.drive_model import DriveModel
from keelaryn_core.drive_postcheck import (
    DrivePostcheckBinding,
    DrivePostcheckBlocked,
    DrivePostcheckReceipts,
)
from keelaryn_core.drive_rest import GoogleDriveBackend
from keelaryn_core.protocol import canonical_json_bytes


CHANGE_SHA = "a" * 64


def postcheck_bytes(
    decision: str,
    *,
    change_id: str = "change-1",
    change_sha256: str = CHANGE_SHA,
    base_canonical_epoch: int = 7,
) -> bytes:
    return canonical_json_bytes(
        {
            "schema": "keelaryn.postcheck.v1",
            "change_id": change_id,
            "change_sha256": change_sha256,
            "base_canonical_epoch": base_canonical_epoch,
            "decision": decision,
            "reason": f"semantic {decision}",
        }
    )


class DrivePostcheckTests(unittest.TestCase):
    def build_model(self) -> tuple[DriveModel, DrivePostcheckBinding, str, str]:
        drive = DriveModel()
        hub = drive.create_folder("root", "Hub")
        source = drive.create_folder(hub.file_id, "postcheck")
        receipts = drive.create_folder(hub.file_id, "receipts")
        binding = DrivePostcheckBinding.plan(
            drive,
            change_id="change-1",
            change_sha256=CHANGE_SHA,
            base_canonical_epoch=7,
            source_parent_id=source.file_id,
            source_name="change-1.json",
            receipt_parent_id=receipts.file_id,
        )
        return drive, binding, source.file_id, receipts.file_id

    def test_binding_roundtrip_preserves_distinct_decision_ids(self) -> None:
        _, binding, _, _ = self.build_model()
        restored = DrivePostcheckBinding.from_bytes(binding.to_bytes())
        self.assertEqual(restored, binding)
        self.assertNotEqual(restored.pass_receipt_id, restored.fail_receipt_id)

    def test_missing_malformed_and_identity_mismatched_source_do_not_authorize(self) -> None:
        drive, binding, source, _ = self.build_model()
        receipts = DrivePostcheckReceipts(drive, binding)
        self.assertIsNone(receipts.accept())

        drive.create_blob(source, binding.source_name, b"not-json")
        self.assertIsNone(receipts.accept())

        source_item = drive.exact_name(source, binding.source_name)
        assert source_item is not None
        drive.update_content(source_item.file_id, postcheck_bytes("PASS", change_id="other-change"))
        self.assertIsNone(receipts.accept())

    def test_pass_receipt_becomes_authority_and_source_can_change_afterward(self) -> None:
        drive, binding, source, _ = self.build_model()
        source_item = drive.create_blob(source, binding.source_name, postcheck_bytes("PASS"))
        receipts = DrivePostcheckReceipts(drive, binding)

        self.assertEqual(receipts.accept(), "PASS")
        accepted = drive.get(binding.pass_receipt_id, include_trashed=False)
        self.assertEqual(accepted.parent_id, binding.receipt_parent_id)
        self.assertEqual(accepted.name, binding.pass_receipt_name)
        self.assertEqual(drive.download(accepted.file_id), postcheck_bytes("PASS"))

        # External reconciliation material is no longer authority after acceptance.
        drive.update_content(source_item.file_id, postcheck_bytes("FAIL"))
        self.assertEqual(receipts.decision(), "PASS")
        self.assertEqual(receipts.accept(), "PASS")

    def test_fail_receipt_is_bound_to_separate_reserved_id(self) -> None:
        drive, binding, source, _ = self.build_model()
        drive.create_blob(source, binding.source_name, postcheck_bytes("FAIL"))
        receipts = DrivePostcheckReceipts(drive, binding)

        self.assertEqual(receipts.accept(), "FAIL")
        self.assertEqual(drive.get(binding.fail_receipt_id).name, binding.fail_receipt_name)
        self.assertEqual(drive.download(binding.fail_receipt_id), postcheck_bytes("FAIL"))

    def test_dual_receipts_fail_closed(self) -> None:
        drive, binding, source, receipts_parent = self.build_model()
        drive.create_blob(source, binding.source_name, postcheck_bytes("PASS"))
        receipts = DrivePostcheckReceipts(drive, binding)
        self.assertEqual(receipts.accept(), "PASS")

        drive.create_blob(
            receipts_parent,
            binding.fail_receipt_name,
            postcheck_bytes("FAIL"),
            mime_type="application/json",
            file_id=binding.fail_receipt_id,
        )
        with self.assertRaises(DrivePostcheckBlocked):
            receipts.decision()

    def test_decision_content_on_wrong_reserved_id_fails_closed(self) -> None:
        drive, binding, _, receipts_parent = self.build_model()
        drive.create_blob(
            receipts_parent,
            binding.pass_receipt_name,
            postcheck_bytes("FAIL"),
            mime_type="application/json",
            file_id=binding.pass_receipt_id,
        )
        with self.assertRaises(DrivePostcheckBlocked):
            DrivePostcheckReceipts(drive, binding).decision()

    def test_core_owned_receipt_mutation_fails_closed(self) -> None:
        drive, binding, source, _ = self.build_model()
        drive.create_blob(source, binding.source_name, postcheck_bytes("PASS"))
        receipts = DrivePostcheckReceipts(drive, binding)
        self.assertEqual(receipts.accept(), "PASS")

        drive.update_content(binding.pass_receipt_id, postcheck_bytes("FAIL"))
        with self.assertRaises(DrivePostcheckBlocked):
            receipts.decision()

    def test_duplicate_source_objects_fail_closed_before_acceptance(self) -> None:
        drive, binding, source, _ = self.build_model()
        drive.create_blob(source, binding.source_name, postcheck_bytes("PASS"))
        drive.create_blob(source, binding.source_name, postcheck_bytes("PASS"))
        with self.assertRaises(DrivePostcheckBlocked):
            DrivePostcheckReceipts(drive, binding).accept()

    def test_rest_lost_receipt_create_response_recovers_from_binding_only(self) -> None:
        drive = DriveModel()
        hub = drive.create_folder("root", "Hub")
        source = drive.create_folder(hub.file_id, "postcheck")
        receipts_parent = drive.create_folder(hub.file_id, "receipts")
        drive.create_blob(source.file_id, "change-1.json", postcheck_bytes("PASS"))

        failing_backend = GoogleDriveBackend(
            "token",
            http=ModelDriveHttp(drive, fail_after_mutation=1),
        )
        binding = DrivePostcheckBinding.plan(
            failing_backend,
            change_id="change-1",
            change_sha256=CHANGE_SHA,
            base_canonical_epoch=7,
            source_parent_id=source.file_id,
            source_name="change-1.json",
            receipt_parent_id=receipts_parent.file_id,
        )
        raw_binding = binding.to_bytes()

        with self.assertRaises(DriveUncertainMutation):
            DrivePostcheckReceipts(failing_backend, binding).accept()

        # Simulate process restart: discard backend/receipt objects and recover only
        # from immutable binding bytes plus actual Drive state.
        restored = DrivePostcheckBinding.from_bytes(raw_binding)
        restarted_backend = GoogleDriveBackend("token", http=ModelDriveHttp(drive))
        restarted = DrivePostcheckReceipts(restarted_backend, restored)
        self.assertEqual(restarted.decision(), "PASS")
        self.assertEqual(restarted.accept(), "PASS")
        self.assertEqual(restarted_backend.download(restored.pass_receipt_id), postcheck_bytes("PASS"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
