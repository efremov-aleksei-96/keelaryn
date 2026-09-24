from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "operation_control_r0009_stage_execution.py"
SPEC = importlib.util.spec_from_file_location(
    "operation_control_r0009_stage_execution",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
execution = importlib.util.module_from_spec(SPEC)
import sys
sys.modules[SPEC.name] = execution
SPEC.loader.exec_module(execution)


class StageExecutionTests(unittest.TestCase):
    def test_cli_is_qualification_only(self) -> None:
        parser = execution._parser()
        action = next(item for item in parser._actions if item.dest == "command")
        self.assertEqual(tuple(action.choices), ("qualify",))
        rendered = parser.format_help()
        for forbidden in (" stage", " execute", " activate", " retry", " delete"):
            self.assertNotIn(forbidden, rendered)

    def test_witness_paths_are_transaction_bound_and_flat(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "witness"
            root.mkdir()
            if os.name == "posix":
                os.chmod(root, 0o700)
            prepared, completed = execution._witness_paths(root, "7" * 32)
            self.assertEqual(prepared.parent, root)
            self.assertEqual(completed.parent, root)
            self.assertEqual(prepared.name, ("7" * 32) + ".PREPARED.json")
            self.assertEqual(completed.name, ("7" * 32) + ".COMPLETED.json")

    def test_immutable_witness_cannot_be_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "witness"
            root.mkdir()
            if os.name == "posix":
                os.chmod(root, 0o700)
            path = root / "x.PREPARED.json"
            value = {"schema": "test", "value": 1}
            execution._write_immutable(path, value, "test witness")
            before = path.read_bytes()
            with self.assertRaises(execution.StageExecutionError) as caught:
                execution._write_immutable(path, {"schema": "other"}, "test witness")
            self.assertEqual(caught.exception.code, "WITNESS_EXISTS")
            self.assertEqual(path.read_bytes(), before)

    def test_live_projection_rejects_missing_runtime_anchors(self) -> None:
        with self.assertRaises(execution.StageExecutionError) as caught:
            execution._live_projection({"production_source_commit": "x"})
        self.assertEqual(caught.exception.code, "LIVE_BOUNDARY_INVALID")

    def test_completed_receipt_never_authorizes_activation_or_retry(self) -> None:
        prepared = {
            "transaction_id": "7" * 32,
            "authority_commit": "a" * 40,
            "authority_git_blob": "b" * 40,
            "source_commit": execution.authority.SOURCE_COMMIT,
            "payload_sha256": execution.authority.PAYLOAD_SHA256,
        }
        completed = execution._completed_value(
            prepared,
            stage_state="STAGED_EXACT",
            replay=False,
        )
        self.assertFalse(completed["activation_authorized"])
        self.assertFalse(completed["release_deletion_allowed"])
        self.assertFalse(completed["blind_retry_allowed"])
        self.assertEqual(completed["release_state"], "STAGED_EXACT")


if __name__ == "__main__":
    unittest.main(verbosity=2)
