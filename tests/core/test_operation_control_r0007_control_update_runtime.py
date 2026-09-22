from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "tools" / "operation_control_r0007_control_update_runtime.py"
SPEC = importlib.util.spec_from_file_location(
    "operation_control_r0007_control_update_runtime",
    MODULE,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load control-update runtime")
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


class R0007ControlUpdateRuntimeTests(unittest.TestCase):
    def test_cli_surface_is_only_reconcile_or_update(self) -> None:
        parser = runtime._parser()
        action = next(item for item in parser._actions if item.dest == "command")
        self.assertEqual(set(action.choices), {"reconcile", "update"})
        destinations = {item.dest for item in parser._actions}
        for forbidden in (
            "install_root",
            "unit_dir",
            "credential_path",
            "operation_root",
            "transport_root",
            "update_root",
            "old_source",
            "new_source",
            "output",
        ):
            self.assertNotIn(forbidden, destinations)

    def test_canonical_paths_and_identities_are_fixed(self) -> None:
        self.assertEqual(runtime.INSTALL_ROOT, Path("/opt/keelaryn"))
        self.assertEqual(runtime.UNIT_DIR, Path("/etc/systemd/system"))
        self.assertEqual(
            runtime.UPDATE_ROOT,
            Path("/var/lib/keelaryn/operation-control-d0-updates"),
        )
        self.assertEqual(
            runtime.OLD_SOURCE,
            "08f2e211f53764590f6ff0f05f86b2de62c14418",
        )
        self.assertEqual(
            runtime.NEW_SOURCE,
            "833123b6a7ad2c61087ee8a86700bb9ad8a46298",
        )

    def test_runtime_reuses_authority_graph(self) -> None:
        self.assertIs(
            runtime.execution,
            runtime.transaction.execution,
        )
        self.assertIs(
            runtime.execution.authority,
            runtime.private_input.authority,
        )

    def test_completed_expected_is_exact(self) -> None:
        fake = mock.Mock()
        fake.COMPLETED_SCHEMA = "completed"
        self.assertEqual(
            runtime._completed_expected(fake, "a" * 64),
            {
                "schema": "completed",
                "transaction_id": "a" * 64,
                "production_current_unchanged": True,
                "control_current": "SUCCESSOR",
                "persistent_services": "ACTIVE_STABLE",
                "static_unit": "STATIC_INACTIVE",
                "remote_mutation_handlers": "ABSENT",
                "credential_unchanged": True,
            },
        )

    def test_absent_update_root_is_new_for_old_boundary(self) -> None:
        fake = mock.Mock()
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(
                runtime,
                "UPDATE_ROOT",
                Path(td) / "absent",
            ):
                value = runtime._inspect_transaction(
                    fake,
                    digest="a" * 64,
                    prepared_expected={},
                    live="OLD_EXACT",
                )
        self.assertEqual(value["state"], "NEW")
        self.assertEqual(value["update_root_state"], "ABSENT")

    def test_absent_update_root_rejects_unattributed_successor(self) -> None:
        fake = mock.Mock()
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(
                runtime,
                "UPDATE_ROOT",
                Path(td) / "absent",
            ):
                with self.assertRaisesRegex(
                    runtime.ControlUpdateRuntimeError,
                    "without update authority",
                ):
                    runtime._inspect_transaction(
                        fake,
                        digest="a" * 64,
                        prepared_expected={},
                        live="NEW_EXACT",
                    )

    def test_rolled_back_state_is_not_actionable(self) -> None:
        before = {
            "transaction": {"state": "ROLLED_BACK_EXACT"},
        }
        with mock.patch.object(
            runtime,
            "_context",
            return_value=before,
        ):
            with self.assertRaisesRegex(
                runtime.ControlUpdateRuntimeError,
                "previously rolled back",
            ):
                runtime.update_once()

    def test_completed_state_is_idempotent_no_mutation(self) -> None:
        before = {
            "transaction": {"state": "COMPLETED_EXACT"},
            "branch": {"expected": "a" * 40},
            "stage_witness": {},
            "old_identity": {},
            "new_identity": {},
            "production_target": "releases/" + "b" * 40,
            "credential_sha256": "c" * 64,
            "live": "NEW_EXACT",
        }
        with mock.patch.object(
            runtime,
            "_context",
            return_value=before,
        ):
            value = runtime.update_once()
        self.assertFalse(value["control_update_mutation_performed"])
        self.assertEqual(
            value["result"]["state"],
            "ALREADY_COMPLETED_EXACT",
        )

    def test_update_failure_reports_unknown_mutation_outcome(self) -> None:
        with mock.patch.object(
            runtime,
            "update_once",
            side_effect=runtime.ControlUpdateRuntimeError(
                "TEST",
                "failed",
            ),
        ), mock.patch("builtins.print") as output:
            rc = runtime.main(["update"])
        self.assertEqual(rc, 2)
        raw = output.call_args.args[0]
        self.assertIn('"reconcile_required":true', raw)
        self.assertIn('"control_update_mutation_performed":null', raw)
        self.assertIn('"credential_mutation_performed":null', raw)
        self.assertIn('"production_current_mutation_performed":false', raw)
        self.assertIn('"drive_mutations_performed":false', raw)

    def test_reconcile_failure_claims_no_mutation(self) -> None:
        with mock.patch.object(
            runtime,
            "reconcile",
            side_effect=runtime.ControlUpdateRuntimeError(
                "TEST",
                "failed",
            ),
        ), mock.patch("builtins.print") as output:
            rc = runtime.main(["reconcile"])
        self.assertEqual(rc, 2)
        raw = output.call_args.args[0]
        self.assertIn('"reconcile_required":false', raw)
        self.assertIn('"control_update_mutation_performed":false', raw)
        self.assertIn('"credential_mutation_performed":false', raw)


if __name__ == "__main__":
    unittest.main()
