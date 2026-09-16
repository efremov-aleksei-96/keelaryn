from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from keelaryn_core.drive_control import DriveControl
from keelaryn_core.drive_model import DriveModel
from keelaryn_core.drive_transaction import BlobState, DriveOperation, DrivePublicationTransaction
from keelaryn_core.protocol import FaultInjector, InjectedCrash, ProtocolError


class DriveControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.drive = DriveModel()
        self.hub = self.drive.create_folder("root", "Hub")
        self.canonical = self.drive.create_folder(self.hub.file_id, "canonical")
        self.control = self.drive.create_folder(self.hub.file_id, "control")
        self.stage = self.drive.create_folder(self.control.file_id, "stage")
        self.history = self.drive.create_folder(self.hub.file_id, "history")
        self.original = self.drive.create_folder(self.history.file_id, "original")
        self.rejected = self.drive.create_folder(self.history.file_id, "rejected")

    def _replace_control(self) -> tuple[DriveControl, DriveOperation]:
        old = b"old\n"
        new = b"new\n"
        old_item = self.drive.create_blob(self.canonical.file_id, "x.txt", old)
        new_item = self.drive.create_blob(self.stage.file_id, "x.new", new)
        op = DriveOperation(
            operation_id="replace-x",
            kind="REPLACE",
            canonical_parent_id=self.canonical.file_id,
            target_name="x.txt",
            old=BlobState.from_bytes(old),
            new=BlobState.from_bytes(new),
            staged_new_id=new_item.file_id,
            staged_parent_id=self.stage.file_id,
            old_original_id=old_item.file_id,
        )
        control = DriveControl(
            change_id="change-1",
            hub_root_id=self.hub.file_id,
            canonical_root_id=self.canonical.file_id,
            history_original_parent_id=self.original.file_id,
            rejected_parent_id=self.rejected.file_id,
            operations=(op,),
        )
        return control, op

    def test_roundtrip_is_byte_deterministic(self) -> None:
        control, _ = self._replace_control()
        first = control.to_bytes()
        restored = DriveControl.from_bytes(first)
        second = restored.to_bytes()
        self.assertEqual(second, first)
        self.assertEqual(restored.operations[0].old_original_id, control.operations[0].old_original_id)
        self.assertEqual(restored.operations[0].staged_new_id, control.operations[0].staged_new_id)

    def test_duplicate_json_key_rejected(self) -> None:
        raw = b'{"schema":"keelaryn.drive-control.v1","schema":"keelaryn.drive-control.v1"}'
        with self.assertRaises(ProtocolError):
            DriveControl.from_bytes(raw)

    def test_illegal_add_identity_rejected(self) -> None:
        control, _ = self._replace_control()
        raw = control.to_bytes().replace(b'"kind": "REPLACE"', b'"kind": "ADD"')
        with self.assertRaises(ProtocolError):
            DriveControl.from_bytes(raw)

    def test_restart_after_replace_displacement_uses_only_durable_control_bytes(self) -> None:
        drive = DriveModel(fault=FaultInjector("drive.tx.replace-x.replace.displace_old.after"))
        hub = drive.create_folder("root", "Hub", label="setup.hub")
        canonical = drive.create_folder(hub.file_id, "canonical", label="setup.canonical")
        control_parent = drive.create_folder(hub.file_id, "control", label="setup.control")
        stage = drive.create_folder(control_parent.file_id, "stage", label="setup.stage")
        history = drive.create_folder(hub.file_id, "history", label="setup.history")
        original = drive.create_folder(history.file_id, "original", label="setup.original")
        rejected = drive.create_folder(history.file_id, "rejected", label="setup.rejected")
        old = b"old"
        new = b"new"
        old_item = drive.create_blob(canonical.file_id, "x", old, label="setup.old")
        new_item = drive.create_blob(stage.file_id, "new", new, label="setup.new")
        original_control = DriveControl(
            change_id="crash-change",
            hub_root_id=hub.file_id,
            canonical_root_id=canonical.file_id,
            history_original_parent_id=original.file_id,
            rejected_parent_id=rejected.file_id,
            operations=(
                DriveOperation(
                    "replace-x",
                    "REPLACE",
                    canonical.file_id,
                    "x",
                    BlobState.from_bytes(old),
                    BlobState.from_bytes(new),
                    new_item.file_id,
                    stage.file_id,
                    old_item.file_id,
                ),
            ),
        )
        control_blob = drive.create_blob(
            control_parent.file_id,
            "DRIVE_CONTROL.json",
            original_control.to_bytes(),
            label="setup.control-record",
        )
        tx = DrivePublicationTransaction(drive, original.file_id, rejected.file_id)
        with self.assertRaises(InjectedCrash):
            tx.apply(original_control.operations[0])

        # Simulated process restart: discard all Python transaction objects and
        # reconstruct only from exact durable control bytes plus remote state.
        restored = DriveControl.from_bytes(drive.download(control_blob.file_id))
        restarted_tx = DrivePublicationTransaction(
            drive,
            restored.history_original_parent_id,
            restored.rejected_parent_id,
        )
        restarted_op = restored.operations[0]
        self.assertEqual(restarted_tx.classify(restarted_op), "OLD_DISPLACED")
        restarted_tx.apply(restarted_op)
        self.assertEqual(restarted_tx.classify(restarted_op), "NEW")
        self.assertEqual(drive.exact_name(canonical.file_id, "x").file_id, new_item.file_id)

    def test_restart_mid_rollback_uses_durable_control_ids(self) -> None:
        control, op = self._replace_control()
        raw = control.to_bytes()
        tx = DrivePublicationTransaction(self.drive, self.original.file_id, self.rejected.file_id)
        tx.apply(op)
        self.drive.fault.point = "drive.tx.replace-x.replace.reject_new.after"
        self.drive.fault.fired = False
        with self.assertRaises(InjectedCrash):
            tx.rollback(op)

        restored = DriveControl.from_bytes(raw)
        restarted = DrivePublicationTransaction(
            self.drive,
            restored.history_original_parent_id,
            restored.rejected_parent_id,
        )
        restored_op = restored.operations[0]
        self.assertEqual(restarted.classify(restored_op), "NEW_REJECTED")
        restarted.rollback(restored_op)
        self.assertEqual(restarted.classify(restored_op), "OLD")


if __name__ == "__main__":
    unittest.main(verbosity=2)
