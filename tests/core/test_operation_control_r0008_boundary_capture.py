from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "tools" / "operation_control_r0008_boundary_capture.py"
SPEC = importlib.util.spec_from_file_location(
    "operation_control_r0008_boundary_capture",
    PATH,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load r0008 boundary capture")
capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture)


class R0008BoundaryCaptureTests(unittest.TestCase):
    def _reconcile(self):
        return {
            "schema": "keelaryn.operation-control-r0008-bootstrap-reconcile.v1",
            "candidate": "operation-control-r0008-20260923-01",
            "production_authorized": False,
            "production_mutations_performed": False,
            "drive_mutations_performed": False,
            "legacy_hub_authority_scope": "RUNTIME_SAFETY_ONLY",
            "production_boundary": {
                "production_source_commit": (
                    "e63f371d14eb9b6069cb2f1b5fad5f4b68a49d4f"
                ),
                "control_source_commit": (
                    "08f2e211f53764590f6ff0f05f86b2de62c14418"
                ),
                "credential": {
                    "sha256": (
                        "7002ed72a223dd7fc860451c53a4ec8f264d14f7144000559a295522b7cbe928"
                    )
                },
                "legacy_hub": {
                    "status": "PREPARED",
                    "transaction_id": "61a2bfb65c9a47d088a76eee0df89d14",
                    "selector_role": "OLD",
                    "mutation_inhibit": {"authority_matches": True},
                },
                "services": {
                    "writer": {
                        "active_state": "INACTIVE",
                        "main_pid": 0,
                    },
                    "operation_units": {
                        "keelaryn-operation-transport.service": {
                            "active_state": "ACTIVE",
                            "enabled": "enabled",
                            "exact_release_bytes": True,
                        },
                        "keelaryn-operation-agent.service": {
                            "active_state": "ACTIVE",
                            "enabled": "enabled",
                            "exact_release_bytes": True,
                        },
                    },
                },
                "r0008_snapshot_unit": "ABSENT",
            },
        }

    def test_capture_emits_exact_authority_boundary(self) -> None:
        with mock.patch.object(
            capture.vps,
            "reconcile",
            side_effect=self._reconcile,
        ), mock.patch.object(
            capture,
            "_utc_now",
            return_value="2026-09-23T08:30:00Z",
        ):
            value = capture.capture()
        self.assertEqual(
            value["schema"],
            "keelaryn.operation-control-r0008-stage-boundary-evidence.v1",
        )
        self.assertEqual(value["observed_at_utc"], "2026-09-23T08:30:00Z")
        self.assertEqual(
            value["control_source_commit"],
            "08f2e211f53764590f6ff0f05f86b2de62c14418",
        )
        self.assertFalse(value["production_mutations_performed"])
        self.assertFalse(value["drive_mutations_performed"])

    def test_capture_rejects_nonexact_service_boundary(self) -> None:
        value = self._reconcile()
        value["production_boundary"]["services"]["operation_units"][
            "keelaryn-operation-transport.service"
        ]["exact_release_bytes"] = False
        with mock.patch.object(capture.vps, "reconcile", return_value=value):
            with self.assertRaisesRegex(
                capture.BoundaryCaptureError,
                "persistent control unit boundary mismatch",
            ):
                capture.capture()

    def test_cli_surface_is_capture_only(self) -> None:
        parser = capture._parser()
        action = next(
            item for item in parser._actions if item.dest == "command"
        )
        self.assertEqual(tuple(action.choices), ("capture",))


if __name__ == "__main__":
    unittest.main()
