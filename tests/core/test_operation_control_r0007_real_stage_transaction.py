from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "operation_control_r0007_real_stage_transaction.py"
SPEC = importlib.util.spec_from_file_location(
    "operation_control_r0007_real_stage_transaction",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
transaction = importlib.util.module_from_spec(SPEC)
import sys
sys.modules[SPEC.name] = transaction
SPEC.loader.exec_module(transaction)


class RealStageTransactionTests(unittest.TestCase):
    def test_cli_is_qualification_only(self) -> None:
        parser = transaction._parser()
        action = next(item for item in parser._actions if item.dest == "command")
        self.assertEqual(tuple(action.choices), ("qualify",))
        rendered = parser.format_help()
        for forbidden in (" stage", " execute", " authorize", " activate", " publish"):
            self.assertNotIn(forbidden, rendered)

    def test_input_path_is_transaction_bound_and_flat(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "input"
            root.mkdir()
            if os.name == "posix":
                os.chmod(root, 0o700)
            path = transaction._input_path(root, "7" * 32)
            self.assertEqual(path.parent, root)
            self.assertEqual(path.name, ("7" * 32) + ".r0007.tar.gz")

    def test_boundary_evidence_is_sanitized_stage_projection(self) -> None:
        boundary = transaction.production._qualification_boundary()
        value = transaction.boundary_evidence_from_live(
            boundary,
            observed_at_utc="2026-09-22T00:00:00Z",
        )
        self.assertEqual(value["conclusion"], "PASS")
        self.assertEqual(
            value["legacy_hub_authority_scope"],
            "RUNTIME_SAFETY_ONLY",
        )
        self.assertFalse(value["production_mutations_performed"])
        self.assertFalse(value["drive_mutations_performed"])
        self.assertNotIn("old_hub_root_id", value)
        self.assertNotIn("new_hub_root_id", value)

    def test_result_checkpoint_never_authorizes_activation(self) -> None:
        class Issued:
            transaction_id = "7" * 32
            provenance = {
                "authority_commit": "a" * 40,
                "authority_path": "docs/authorizations/test.json",
                "authority_git_blob": "b" * 40,
                "authority_sha256": "c" * 64,
                "authority_parent_checkpoint": "d" * 40,
                "boundary_evidence_path": "docs/evidence/test.json",
                "boundary_evidence_git_blob": "e" * 40,
                "boundary_evidence_sha256": "f" * 64,
            }

        completed = {
            "transaction_id": "7" * 32,
            "prepared_sha256": "1" * 64,
            "authority_commit": "a" * 40,
            "authority_git_blob": "b" * 40,
            "source_commit": transaction.SOURCE_COMMIT,
            "payload_sha256": transaction.PAYLOAD_SHA256,
            "stage_state": "STAGED_EXACT",
            "release_state": "STAGED_EXACT",
            "post_reconcile": "PASS",
            "activation_authorized": False,
        }
        identity = {
            "source_commit": transaction.SOURCE_COMMIT,
            "payload_sha256": transaction.PAYLOAD_SHA256,
            "payload_size": transaction.PAYLOAD_SIZE,
            "file_count": transaction.PAYLOAD_FILE_COUNT,
        }
        value = transaction.render_result_checkpoint(
            issued=Issued(),
            input_identity=identity,
            completed=completed,
        )
        self.assertFalse(value["activation_authorized"])
        self.assertFalse(value["drive_content_mutation_performed"])
        self.assertFalse(value["legacy_hub_mutation_performed"])
        self.assertEqual(value["release_state"], "STAGED_EXACT")

    def test_result_checkpoint_rejects_cross_authority_receipt(self) -> None:
        class Issued:
            transaction_id = "7" * 32
            provenance = {
                "authority_commit": "a" * 40,
                "authority_path": "docs/authorizations/test.json",
                "authority_git_blob": "b" * 40,
                "authority_sha256": "c" * 64,
                "authority_parent_checkpoint": "d" * 40,
                "boundary_evidence_path": "docs/evidence/test.json",
                "boundary_evidence_git_blob": "e" * 40,
                "boundary_evidence_sha256": "f" * 64,
            }

        completed = {
            "transaction_id": "7" * 32,
            "prepared_sha256": "1" * 64,
            "authority_commit": "9" * 40,
            "authority_git_blob": "b" * 40,
            "source_commit": transaction.SOURCE_COMMIT,
            "payload_sha256": transaction.PAYLOAD_SHA256,
            "release_state": "STAGED_EXACT",
            "activation_authorized": False,
        }
        identity = {
            "source_commit": transaction.SOURCE_COMMIT,
            "payload_sha256": transaction.PAYLOAD_SHA256,
            "payload_size": transaction.PAYLOAD_SIZE,
            "file_count": transaction.PAYLOAD_FILE_COUNT,
        }
        with self.assertRaises(transaction.RealStageTransactionError) as caught:
            transaction.render_result_checkpoint(
                issued=Issued(),
                input_identity=identity,
                completed=completed,
            )
        self.assertEqual(caught.exception.code, "RESULT_INVALID")


if __name__ == "__main__":
    unittest.main(verbosity=2)
