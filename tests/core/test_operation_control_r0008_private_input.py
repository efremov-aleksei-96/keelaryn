from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "operation_control_r0008_private_input.py"
SPEC = importlib.util.spec_from_file_location(
    "operation_control_r0008_private_input",
    MODULE_PATH,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load r0008 private-input module")
private_input = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = private_input
SPEC.loader.exec_module(private_input)


class R0008PrivateInputTests(unittest.TestCase):
    def _live(self) -> dict:
        expected = private_input.production._qualification_boundary()
        value = {
            "schema": "keelaryn.operation-control-r0008-bootstrap-reconcile.v1",
            "production_boundary": json.loads(json.dumps(expected)),
            "production_mutations_performed": False,
            "drive_mutations_performed": False,
        }
        for unit in value["production_boundary"]["services"]["operation_units"].values():
            unit["main_pid"] = 123
            unit["sha256"] = "0" * 64
        return value

    def test_resolved_authority_compares_full_issued_record(self) -> None:
        record = {
            "transaction_id": private_input.TRANSACTION_ID,
            "scope": "R0008_RELEASE_STAGE_ONLY",
            "candidate": "operation-control-r0008-20260923-01",
            "source_commit": private_input.transaction.SOURCE_COMMIT,
            "source_tree": private_input.transaction.SOURCE_TREE,
            "payload_sha256": private_input.transaction.PAYLOAD_SHA256,
            "payload_size": private_input.transaction.PAYLOAD_SIZE,
            "file_count": private_input.transaction.PAYLOAD_FILE_COUNT,
            "production_stage_authorized": True,
            "activation_authorized": False,
            "drive_content_mutation_authorized": False,
            "legacy_hub_mutation_authorized": False,
            "writer_mutation_authorized": False,
            "credential_mutation_authorized": False,
        }
        provenance = {
            "authority_commit": private_input.AUTHORITY_COMMIT,
            "authority_path": private_input.AUTHORITY_PATH,
            "authority_git_blob": private_input.AUTHORITY_BLOB,
            "authority_sha256": private_input.AUTHORITY_SHA256,
            "boundary_evidence_git_blob": private_input.BOUNDARY_BLOB,
            "boundary_evidence_sha256": private_input.BOUNDARY_SHA256,
        }

        class FakeIssued:
            @property
            def record(self):
                return dict(record)

            @property
            def provenance(self):
                return dict(provenance)

        issued = FakeIssued()
        with mock.patch.object(
            private_input.authority,
            "resolve_git_authorization",
            return_value=issued,
        ), mock.patch.object(
            private_input.authority,
            "require_issued_authorization",
            return_value={
                "scope": "R0008_RELEASE_STAGE_ONLY",
                "candidate": record["candidate"],
                "source_commit": record["source_commit"],
                "source_tree": record["source_tree"],
                "payload_sha256": record["payload_sha256"],
                "payload_size": record["payload_size"],
                "file_count": record["file_count"],
                "production_stage_authorized": True,
                "activation_authorized": False,
                "drive_content_mutation_authorized": False,
                "legacy_hub_mutation_authorized": False,
                "writer_mutation_authorized": False,
                "credential_mutation_authorized": False,
            },
        ):
            observed = private_input._resolve_issued(ROOT)

        self.assertIs(observed, issued)

    def test_live_projection_matches_qualified_boundary(self) -> None:
        projected = private_input._project_live_boundary(self._live())
        self.assertEqual(
            projected,
            private_input.production._qualification_boundary(),
        )

    def test_live_projection_drift_fails_closed(self) -> None:
        value = self._live()
        value["production_boundary"]["legacy_hub"]["selector_role"] = "NEW"
        with mock.patch.object(
            private_input.production.prep,
            "reconcile",
            return_value=value,
        ):
            with self.assertRaisesRegex(
                private_input.PrivateInputError,
                "differs from qualified exact boundary",
            ):
                private_input._fresh_live_boundary()

    def test_absent_root_reconcile_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "missing"
            before = set(Path(td).iterdir())
            value = private_input._input_prestate(
                root,
                materializer=None,
            )
            after = set(Path(td).iterdir())
        self.assertEqual(value["state"], "INPUT_ROOT_ABSENT")
        self.assertEqual(before, after)

    def test_secure_root_creation_is_0700(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            if os.name == "posix":
                os.chmod(parent, 0o700)
            root = parent / "input"
            observed, created = private_input._ensure_input_root(root)
            self.assertTrue(created)
            self.assertEqual(observed, root.absolute())
            if os.name == "posix":
                self.assertEqual(
                    stat.S_IMODE(root.stat().st_mode),
                    0o700,
                )

    def test_insecure_parent_rejected(self) -> None:
        if os.name != "posix":
            self.skipTest("POSIX ownership/mode contract")
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            os.chmod(parent, 0o777)
            with self.assertRaisesRegex(
                private_input.PrivateInputError,
                "not group/world writable",
            ):
                private_input._inspect_parent_for_root(parent / "input")

    def test_repository_verification_derives_exact_live_tip(self) -> None:
        expected = "1" * 40
        with mock.patch.object(
            private_input,
            "_git_commit",
            side_effect=[expected, expected],
        ), mock.patch.object(
            private_input,
            "_remote_branch_tip",
            return_value=expected,
        ):
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                (root / ".git").mkdir()
                value = private_input._verify_repository(root)
        self.assertEqual(value["expected"], expected)
        self.assertEqual(value["remote_branch"], expected)

    def test_repository_verification_rejects_remote_drift(self) -> None:
        expected = "1" * 40
        with mock.patch.object(
            private_input,
            "_git_commit",
            side_effect=[expected, expected],
        ), mock.patch.object(
            private_input,
            "_remote_branch_tip",
            return_value="2" * 40,
        ):
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                (root / ".git").mkdir()
                with self.assertRaisesRegex(
                    private_input.PrivateInputError,
                    "live remote branch differ",
                ):
                    private_input._verify_repository(root)

    def test_cli_exposes_no_stage_or_activation_command(self) -> None:
        parser = private_input._parser()
        action = next(
            item
            for item in parser._actions
            if item.dest == "command"
        )
        self.assertEqual(set(action.choices), {"reconcile", "acquire"})
        self.assertNotIn("stage", action.choices)
        self.assertNotIn("activate", action.choices)

    def test_cli_has_no_input_root_or_output_override(self) -> None:
        parser = private_input._parser()
        destinations = {item.dest for item in parser._actions}
        self.assertNotIn("input_root", destinations)
        self.assertNotIn("output", destinations)
        self.assertNotIn("expected_branch_tip", destinations)
        self.assertNotIn("repository_root", destinations)

    def test_cli_main_pins_script_repository_and_default_input_root(self) -> None:
        value = {
            "schema": private_input.SCHEMA,
            "command": "reconcile",
        }
        with mock.patch.object(
            private_input,
            "reconcile",
            return_value=value,
        ) as reconcile_call, mock.patch(
            "builtins.print",
        ):
            rc = private_input.main(["reconcile"])
        self.assertEqual(rc, 0)
        reconcile_call.assert_called_once_with(
            repository_root=private_input.SCRIPT_REPOSITORY_ROOT,
            input_root=private_input.DEFAULT_INPUT_ROOT,
        )

    def test_mutation_boundary_recheck_can_pin_precheck_tip(self) -> None:
        expected = "4" * 40
        with mock.patch.object(
            private_input,
            "_git_commit",
            side_effect=[expected, expected],
        ), mock.patch.object(
            private_input,
            "_remote_branch_tip",
            return_value=expected,
        ):
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                (root / ".git").mkdir()
                value = private_input._verify_repository(root, expected)
        self.assertEqual(value["expected"], expected)

    def test_transaction_binding_is_exact(self) -> None:
        self.assertEqual(
            private_input.TRANSACTION_ID,
            "a6383609e9a6442ad86445ba62baff93",
        )
        self.assertEqual(
            private_input.AUTHORITY_COMMIT,
            "03f3e794fdcbd18e07d21dcb633c463674ce4e6b",
        )
        self.assertEqual(
            private_input.AUTHORITY_BLOB,
            "101b05042471abf7d10415cea36ba3053093364d",
        )
        self.assertEqual(
            private_input.DEFAULT_INPUT_ROOT,
            Path("/var/lib/keelaryn/operation-control/r0008-stage-input"),
        )
        self.assertEqual(private_input.SCRIPT_REPOSITORY_ROOT, ROOT)


if __name__ == "__main__":
    unittest.main()
