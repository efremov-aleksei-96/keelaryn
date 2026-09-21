from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))

from keelaryn_core.drive_mutation_gate import mutation_inhibit_bytes  # noqa: E402
from keelaryn_core.production_snapshot import (  # noqa: E402
    ProductionSnapshotError,
    ProductionSnapshotLayout,
    SNAPSHOT_NAME,
    collect_production_snapshot,
    read_production_snapshot,
    validate_production_snapshot,
    write_production_snapshot,
)


def compact(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


class FakeSystemd:
    def __init__(self, *, drift_writer: bool = False) -> None:
        self.calls: list[str] = []
        self.writer_calls = 0
        self.drift_writer = drift_writer

    def __call__(
        self,
        args: list[str],
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        self.assert_command(args, timeout)
        unit = args[2]
        self.calls.append(unit)
        if unit == "keelaryn-drive.service":
            self.writer_calls += 1
            active = (
                "active"
                if self.drift_writer and self.writer_calls > 1
                else "inactive"
            )
            pid = 999 if active == "active" else 0
        elif unit == "keelaryn-operation-agent.service":
            active, pid = "active", 111
        elif unit == "keelaryn-operation-transport.service":
            active, pid = "active", 222
        else:  # pragma: no cover
            raise AssertionError(unit)
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=f"ActiveState={active}\nMainPID={pid}\n",
            stderr="",
        )

    @staticmethod
    def assert_command(args: list[str], timeout: int) -> None:
        if args[:2] != ["systemctl", "show"] or timeout != 30:
            raise AssertionError(args)
        if args[3:] != [
            "--property=ActiveState",
            "--property=MainPID",
        ]:
            raise AssertionError(args)


class ProductionSnapshotTests(unittest.TestCase):
    PROD = "a" * 40
    CONTROL = "b" * 40
    TXID = "1" * 32

    def layout(self, root: Path) -> tuple[ProductionSnapshotLayout, str, str]:
        install = root / "opt" / "keelaryn"
        releases = install / "releases"
        releases.mkdir(parents=True)
        (releases / self.PROD).mkdir()
        (releases / self.CONTROL).mkdir()
        os.symlink(f"releases/{self.PROD}", install / "current")
        os.symlink(f"releases/{self.CONTROL}", install / "control-current")

        etc = root / "etc" / "keelaryn"
        etc.mkdir(parents=True)
        old_id = "OLD_PRIVATE_HUB_12345"
        new_id = "NEW_PRIVATE_HUB_67890"
        selector = etc / "hub.env"
        selector.write_text(
            f"KEELARYN_HUB_ROOT_ID={old_id}\n",
            encoding="ascii",
        )
        os.chmod(selector, 0o600)

        deployment = root / "var" / "lib" / "keelaryn" / "deployment"
        (deployment / "terminal").mkdir(parents=True)
        active = {
            "schema": "keelaryn.zero-vps-hub-cutover.v2",
            "transaction_id": self.TXID,
            "tool": {"source_commit": self.PROD, "sha256": "6" * 64},
            "finalizers": {
                "pre_apply_sha256": "7" * 64,
                "post_cutover_sha256": "8" * 64,
            },
            "old_hub_root_id": old_id,
            "new_hub_root_id": new_id,
        }
        active_raw = compact(active)
        active_path = deployment / "ACTIVE_TRANSACTION.json"
        active_path.write_bytes(active_raw)
        os.chmod(active_path, 0o600)

        gate = root / "var" / "lib" / "keelaryn" / "mutation-gate"
        gate.mkdir(mode=0o2750)
        os.chmod(gate, 0o2750)
        lock = gate / "LOCK"
        lock.write_bytes(b"")
        os.chmod(lock, 0o640)
        inhibit_raw = mutation_inhibit_bytes(
            {
                "schema": "keelaryn.drive-mutation-inhibit.v1",
                "transaction_id": self.TXID,
                "active_transaction_sha256": hashlib.sha256(
                    active_raw
                ).hexdigest(),
                "source_commit": self.PROD,
                "tool_sha256": "6" * 64,
                "old_selector_sha256": hashlib.sha256(
                    f"KEELARYN_HUB_ROOT_ID={old_id}\n".encode("ascii")
                ).hexdigest(),
                "new_selector_sha256": hashlib.sha256(
                    f"KEELARYN_HUB_ROOT_ID={new_id}\n".encode("ascii")
                ).hexdigest(),
            }
        )
        inhibit = gate / "INHIBIT.json"
        inhibit.write_bytes(inhibit_raw)
        os.chmod(inhibit, 0o640)

        return (
            ProductionSnapshotLayout(
                install_root=install,
                selector_path=selector,
                deployment_state_root=deployment,
                mutation_gate_root=gate,
            ),
            old_id,
            new_id,
        )

    def test_collects_stable_sanitized_prepared_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            layout, old_id, new_id = self.layout(root)
            runner = FakeSystemd()

            value = collect_production_snapshot(layout, run=runner)

            self.assertEqual(value["production_source_commit"], self.PROD)
            self.assertEqual(value["control_source_commit"], self.CONTROL)
            self.assertEqual(value["services"]["writer"]["active_state"], "INACTIVE")
            self.assertEqual(value["services"]["writer"]["main_pid"], 0)
            self.assertEqual(value["legacy_hub"]["status"], "PREPARED")
            self.assertEqual(value["legacy_hub"]["selector_role"], "OLD")
            self.assertEqual(
                value["legacy_hub"]["mutation_inhibit"]["transaction_matches"],
                True,
            )
            self.assertEqual(
                value["legacy_hub"]["mutation_inhibit"][
                    "active_transaction_matches"
                ],
                True,
            )
            self.assertEqual(
                value["legacy_hub"]["mutation_inhibit"]["authority_matches"],
                True,
            )
            rendered = json.dumps(value, sort_keys=True)
            self.assertNotIn(old_id, rendered)
            self.assertNotIn(new_id, rendered)
            self.assertEqual(len(runner.calls), 6)
            self.assertFalse(value["production_mutations_performed"])
            self.assertFalse(value["drive_mutations_performed"])

    def test_two_pass_observation_rejects_service_drift(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout, _, _ = self.layout(Path(td))
            with self.assertRaisesRegex(
                ProductionSnapshotError,
                "changed during read-only observation",
            ):
                collect_production_snapshot(
                    layout,
                    run=FakeSystemd(drift_writer=True),
                )

    def test_snapshot_result_is_create_once_private_and_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.chmod(root, 0o700)
            layout, _, _ = self.layout(root / "fixture")
            value = collect_production_snapshot(layout, run=FakeSystemd())
            operation = root / ("f" * 32)
            operation.mkdir(mode=0o700)
            os.chmod(operation, 0o700)
            path = operation / SNAPSHOT_NAME

            written = write_production_snapshot(path, value)
            self.assertEqual(written, value)
            self.assertEqual(read_production_snapshot(path), value)
            if os.name == "posix":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(
                ProductionSnapshotError,
                "already exists",
            ):
                write_production_snapshot(path, value)

    def test_snapshot_schema_rejects_secret_shaped_extra_field(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout, _, _ = self.layout(Path(td))
            value = collect_production_snapshot(layout, run=FakeSystemd())
            value["hub_root_id"] = "PRIVATE_ID"
            with self.assertRaises(ProductionSnapshotError):
                validate_production_snapshot(value)

    def test_worker_unit_is_static_networkless_and_hides_known_secrets(self) -> None:
        unit = (
            ROOT
            / "deploy"
            / "zero-based-vps"
            / "keelaryn-production-snapshot@.service"
        ).read_text(encoding="utf-8")
        self.assertIn("PrivateNetwork=true", unit)
        self.assertIn("CapabilityBoundingSet=", unit)
        self.assertIn("AmbientCapabilities=", unit)
        self.assertIn("RestrictAddressFamilies=AF_UNIX", unit)
        self.assertIn("/etc/keelaryn/drive.env", unit)
        self.assertIn("/etc/keelaryn/operation-control", unit)
        self.assertIn("/var/lib/keelaryn/migration", unit)
        self.assertIn("/var/lib/keelaryn-operation-transport", unit)
        self.assertIn(
            "/var/lib/keelaryn/operations/%i/production-snapshot.json",
            unit,
        )
        self.assertNotIn("[Install]", unit)

    def test_inhibit_authority_mismatch_is_reported_blocked_without_identity_leak(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            layout, old_id, new_id = self.layout(root)
            inhibit_path = layout.mutation_gate_root / "INHIBIT.json"
            value = json.loads(inhibit_path.read_text(encoding="utf-8"))
            value["tool_sha256"] = "f" * 64
            inhibit_path.write_bytes(mutation_inhibit_bytes(value))
            os.chmod(inhibit_path, 0o640)

            observed = collect_production_snapshot(
                layout,
                run=FakeSystemd(),
            )

            self.assertEqual(observed["legacy_hub"]["status"], "BLOCKED")
            self.assertEqual(
                observed["legacy_hub"]["reason"],
                "MUTATION_INHIBIT_AUTHORITY_MISMATCH",
            )
            self.assertFalse(
                observed["legacy_hub"]["mutation_inhibit"]["authority_matches"]
            )
            rendered = json.dumps(observed, sort_keys=True)
            self.assertNotIn(old_id, rendered)
            self.assertNotIn(new_id, rendered)




if __name__ == "__main__":
    unittest.main(verbosity=2)
