from __future__ import annotations

import importlib.util
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "operation_control_r0009_stage_runtime.py"
SPEC = importlib.util.spec_from_file_location(
    "operation_control_r0009_stage_runtime",
    MODULE_PATH,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load r0009 stage-runtime module")
runtime = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runtime
SPEC.loader.exec_module(runtime)


class R0009StageRuntimeTests(unittest.TestCase):
    def test_runtime_reuses_single_execution_authority_graph(self) -> None:
        self.assertIs(runtime.execution, runtime.transaction.execution)
        self.assertIs(runtime.execution.authority, runtime.private_input.authority)
        self.assertIs(runtime.execution.authority, runtime.transaction.authority)

    def test_cli_surface_is_only_reconcile_or_stage(self) -> None:
        parser = runtime._parser()
        action = next(item for item in parser._actions if item.dest == "command")
        self.assertEqual(set(action.choices), {"reconcile", "stage"})
        destinations = {item.dest for item in parser._actions}
        for forbidden in (
            "repository_root",
            "input_root",
            "releases_root",
            "witness_root",
            "output",
            "activate",
        ):
            self.assertNotIn(forbidden, destinations)

    def test_canonical_roots_are_fixed(self) -> None:
        self.assertEqual(
            runtime.DEFAULT_INPUT_ROOT,
            Path("/var/lib/keelaryn/operation-control/r0009-stage-input"),
        )
        self.assertEqual(
            runtime.DEFAULT_RELEASES_ROOT,
            Path("/opt/keelaryn/releases"),
        )
        self.assertEqual(
            runtime.DEFAULT_WITNESS_ROOT,
            Path("/var/lib/keelaryn/operation-control/r0009-stage-witness"),
        )
        self.assertEqual(runtime.SCRIPT_REPOSITORY_ROOT, ROOT)

    def test_expected_input_identity_is_exact(self) -> None:
        self.assertEqual(
            runtime.EXPECTED_INPUT_IDENTITY,
            {
                "source_commit": "e42a4f156abb048f5c8f0bd1884fcae51674a55f",
                "payload_sha256": "8592a314b084a2a1ccc1608168b3c0776cccb1277ffc049f42f3efd5291d4876",
                "payload_size": 442514,
                "file_count": 227,
            },
        )

    def test_ensure_witness_root_creates_0700(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            if os.name == "posix":
                os.chmod(parent, 0o700)
            target = parent / "witness"
            with mock.patch.object(runtime, "DEFAULT_WITNESS_ROOT", target):
                root, created = runtime._ensure_witness_root()
            self.assertTrue(created)
            self.assertEqual(root, target.absolute())
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)

    def test_insecure_witness_parent_is_rejected(self) -> None:
        if os.name != "posix":
            self.skipTest("POSIX ownership/mode contract")
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            os.chmod(parent, 0o777)
            with mock.patch.object(
                runtime,
                "DEFAULT_WITNESS_ROOT",
                parent / "witness",
            ):
                with self.assertRaisesRegex(
                    runtime.StageRuntimeError,
                    "not group/world writable",
                ):
                    runtime._ensure_witness_root()

    def test_verify_input_requires_exact_identity(self) -> None:
        expected = {
            "state": "INPUT_EXACT",
            "exact": True,
            "identity": dict(runtime.EXPECTED_INPUT_IDENTITY),
            "path": f"{runtime.TRANSACTION_ID}.r0009.tar.gz",
        }
        payload = Path("/private/input.tar.gz")
        with mock.patch.object(
            runtime.transaction,
            "reconcile_private_input",
            return_value=expected,
        ), mock.patch.object(
            runtime.transaction,
            "_input_path",
            return_value=payload,
        ):
            observed_path, observed = runtime._verify_input(object())
        self.assertEqual(observed_path, payload)
        self.assertEqual(observed, expected)

    def test_verify_input_rejects_foreign_identity(self) -> None:
        bad = {
            "state": "INPUT_EXACT",
            "exact": True,
            "identity": {
                **runtime.EXPECTED_INPUT_IDENTITY,
                "payload_size": 1,
            },
        }
        with mock.patch.object(
            runtime.transaction,
            "reconcile_private_input",
            return_value=bad,
        ):
            with self.assertRaisesRegex(
                runtime.StageRuntimeError,
                "not exact",
            ):
                runtime._verify_input(object())

    def test_absent_witness_root_reconcile_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            witness = Path(td) / "absent"
            ctx = {
                "repo": ROOT,
                "issued": mock.Mock(),
                "payload": Path("/payload"),
                "materializer": object(),
            }
            with mock.patch.object(runtime, "DEFAULT_WITNESS_ROOT", witness), mock.patch.object(
                runtime.execution,
                "_expected_prepared",
            ), mock.patch.object(
                runtime.stage,
                "reconcile_stage",
                return_value={"state": "NOT_STAGED"},
            ):
                before = set(Path(td).iterdir())
                value = runtime._reconcile_context(ctx)
                after = set(Path(td).iterdir())
            self.assertEqual(value["state"], "NEW")
            self.assertEqual(value["witness_root_state"], "ABSENT")
            self.assertEqual(before, after)

    def test_absent_witness_root_rejects_unattributed_release(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            witness = Path(td) / "absent"
            ctx = {
                "repo": ROOT,
                "issued": mock.Mock(),
                "payload": Path("/payload"),
                "materializer": object(),
            }
            with mock.patch.object(runtime, "DEFAULT_WITNESS_ROOT", witness), mock.patch.object(
                runtime.execution,
                "_expected_prepared",
            ), mock.patch.object(
                runtime.stage,
                "reconcile_stage",
                return_value={"state": "STAGED_EXACT"},
            ):
                with self.assertRaisesRegex(
                    runtime.StageRuntimeError,
                    "witness root is absent",
                ):
                    runtime._reconcile_context(ctx)

    def test_reconcile_main_never_exposes_mutation(self) -> None:
        value = {"schema": runtime.SCHEMA, "command": "reconcile"}
        with mock.patch.object(runtime, "reconcile", return_value=value), mock.patch(
            "builtins.print",
        ):
            rc = runtime.main(["reconcile"])
        self.assertEqual(rc, 0)

    def test_stage_failure_marks_release_and_witness_outcome_unknown(self) -> None:
        with mock.patch.object(
            runtime,
            "stage_once",
            side_effect=runtime.StageRuntimeError("TEST", "failed"),
        ), mock.patch("builtins.print") as output:
            rc = runtime.main(["stage"])
        self.assertEqual(rc, 2)
        raw = output.call_args.args[0]
        self.assertIn('"reconcile_required":true', raw)
        self.assertIn('"release_publication_performed":null', raw)
        self.assertIn('"stage_witness_mutation_performed":null', raw)
        self.assertIn('"activation_performed":false', raw)


if __name__ == "__main__":
    unittest.main()
