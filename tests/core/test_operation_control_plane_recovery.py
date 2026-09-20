from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy" / "zero-based-vps"
sys.path.insert(0, str(DEPLOY))

import operation_control_plane_recovery as recovery  # noqa: E402


class FakeSystemctl:
    def __init__(self) -> None:
        self.enabled = {name: True for name in recovery.UNIT_NAMES}
        self.active = {name: False for name in recovery.UNIT_NAMES}
        self.calls: list[list[str]] = []
        self.fail_disable_once: str | None = None

    def __call__(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(args))
        command = args[0]
        if command == "is-active":
            unit = args[-1]
            if unit == "keelaryn-drive.service":
                return subprocess.CompletedProcess(args, 3, "inactive\n", "")
            if self.active.get(unit, False):
                return subprocess.CompletedProcess(args, 0, "active\n", "")
            return subprocess.CompletedProcess(args, 3, "failed\n", "")
        if command == "is-enabled":
            unit = args[-1]
            if self.enabled.get(unit, False):
                return subprocess.CompletedProcess(args, 0, "enabled\n", "")
            return subprocess.CompletedProcess(args, 1, "disabled\n", "")
        if command == "disable":
            unit = args[-1]
            self.active[unit] = False
            self.enabled[unit] = False
            if self.fail_disable_once == unit:
                self.fail_disable_once = None
                return subprocess.CompletedProcess(args, 1, "", "injected")
            return subprocess.CompletedProcess(args, 0, "", "")
        if command in {"reset-failed", "daemon-reload"}:
            return subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError(args)


class OperationControlRecoveryTests(unittest.TestCase):
    REJECTED = "a" * 40
    PRODUCTION = "b" * 40
    PAYLOAD = "c" * 64

    def setUp(self) -> None:
        patcher = mock.patch.object(
            recovery,
            "_service_identity",
            return_value=(os.geteuid(), os.getegid()),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_root_precondition_is_fail_closed(self) -> None:
        with mock.patch.object(recovery.os, "geteuid", return_value=1000):
            with self.assertRaisesRegex(
                recovery.OperationControlRecoveryError,
                "requires root",
            ):
                recovery._require_root()

        with mock.patch.object(recovery.os, "geteuid", return_value=0):
            recovery._require_root()

    def spec(self) -> recovery.RecoverySpec:
        return recovery.RecoverySpec(
            rejected_source_commit=self.REJECTED,
            rejected_payload_sha256=self.PAYLOAD,
            production_source_commit=self.PRODUCTION,
            repository="efremov-aleksei-96/keelaryn",
            issue=65,
            actors="efremov-aleksei-96",
            status_actor="efremov-aleksei-96",
        )

    def boundary(self):
        return {
            "current_source": self.PRODUCTION,
            "writer": "INACTIVE",
            "hub_cutover": "PREPARED",
        }

    def layout(self, root: Path):
        install = root / "opt" / "keelaryn"
        release = install / "releases" / self.REJECTED
        deploy = release / "deploy" / "zero-based-vps"
        deploy.mkdir(parents=True)
        os.chmod(install, 0o755)
        os.chmod(install / "releases", 0o755)

        for name in recovery.UNIT_NAMES:
            path = deploy / name
            path.write_bytes(("unit:" + name + "\n").encode("ascii"))
            os.chmod(path, 0o444)

        # Materialize fixture bytes first, then freeze the release tree exactly
        # like a real immutable materialized release.
        os.chmod(deploy, 0o555)
        os.chmod(release / "deploy", 0o555)
        os.chmod(release, 0o555)

        os.symlink("releases/" + self.PRODUCTION, install / "current")
        os.symlink("releases/" + self.REJECTED, install / "control-current")

        unit_dir = root / "systemd"
        unit_dir.mkdir(mode=0o755)
        for name in recovery.UNIT_NAMES:
            target = unit_dir / name
            target.write_bytes((deploy / name).read_bytes())
            os.chmod(target, 0o644)

        config_dir = root / "etc" / "keelaryn" / "operation-control"
        config_dir.mkdir(parents=True, mode=0o700)
        os.chmod(config_dir, 0o700)
        token = "github_pat_" + ("A" * 40)
        credential_raw = recovery._credential_bytes(
            token=token,
            repository="efremov-aleksei-96/keelaryn",
            issue=65,
            actors="efremov-aleksei-96",
            status_actor="efremov-aleksei-96",
        )
        credential = config_dir / "github-operations.env"
        credential.write_bytes(credential_raw)
        os.chmod(credential, 0o600)

        bootstrap_root = root / "bootstrap"
        bootstrap_root.mkdir(mode=0o700)
        os.chmod(bootstrap_root, 0o700)
        marker_name = recovery._expected_marker(
            self.spec(),
            recovery.sha256(credential_raw).hexdigest(),
        )
        marker = bootstrap_root / marker_name
        marker.mkdir(mode=0o700)
        os.chmod(marker, 0o700)
        receipt = bootstrap_root / "bootstrap-receipt.json"
        receipt.write_bytes(recovery._expected_receipt(self.spec()))
        os.chmod(receipt, 0o600)

        transport_root = root / "runtime-transport"
        transport_root.mkdir(mode=0o700)
        os.chmod(transport_root, 0o700)

        operation_root = root / "runtime-operations"
        operation_root.mkdir(mode=0o700)
        os.chmod(operation_root, 0o700)

        operation_control_root = root / "runtime-control"
        operation_control_root.mkdir(mode=0o700)
        os.chmod(operation_control_root, 0o700)
        for name in ("processed", "rejected"):
            child = operation_control_root / name
            child.mkdir(mode=0o700)
            os.chmod(child, 0o700)

        recovery_root = root / "recovery"
        layout = recovery.RecoveryLayout(
            install_root=install,
            unit_dir=unit_dir,
            config_dir=config_dir,
            bootstrap_root=bootstrap_root,
            recovery_root=recovery_root,
            transport_root=transport_root,
            operation_root=operation_root,
            operation_control_root=operation_control_root,
            selector=root / "unused-selector",
            deployment_state_root=root / "unused-deployment",
            mutation_gate_root=root / "unused-gate",
        )
        return layout, release

    def release_probe(self, path: Path, source: str, payload: str):
        self.assertEqual(path.name, self.REJECTED)
        self.assertEqual(source, self.REJECTED)
        self.assertEqual(payload, self.PAYLOAD)
        return {
            "source_commit": source,
            "payload_sha256": payload,
            "payload_size": 1,
            "file_count": 1,
        }

    @mock.patch.object(recovery, "_require_root", return_value=None)
    def test_inspect_is_read_only_and_binds_marker_to_credential(
        self,
        _geteuid,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout, _ = self.layout(Path(td))
            ctl = FakeSystemctl()
            value = recovery.inspect_rejected_install(
                self.spec(),
                layout,
                systemctl=ctl,
                boundary_probe=self.boundary,
                release_probe=self.release_probe,
            )
            self.assertEqual(value["recovery_state"], "READY")
            self.assertFalse(value["persistent_mutations_performed"])
            self.assertEqual(value["credential"], "PRESENT")
            self.assertEqual(value["bootstrap_transaction"], "PRESENT")
            self.assertEqual(
                value["runtime_state"],
                {
                    "transport_root": "EXACT",
                    "operation_root": "EXACT",
                    "operation_control_root": "EXACT",
                },
            )
            self.assertFalse(layout.recovery_root.exists())

    @mock.patch.object(recovery, "_require_root", return_value=None)
    def test_cleanup_is_resumable_and_retains_rejected_release(
        self,
        _geteuid,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout, release = self.layout(Path(td))
            ctl = FakeSystemctl()

            value = recovery.cleanup_rejected_install(
                self.spec(),
                layout,
                systemctl=ctl,
                boundary_probe=self.boundary,
                release_probe=self.release_probe,
            )

            self.assertTrue(value["sidecar_clean"])
            self.assertTrue(release.is_dir())
            self.assertFalse(layout.control_current.exists())
            self.assertFalse(layout.config_dir.exists())
            self.assertFalse(layout.bootstrap_root.exists())
            self.assertFalse(layout.transport_root.exists())
            self.assertFalse(layout.operation_root.exists())
            self.assertFalse(layout.operation_control_root.exists())
            self.assertTrue(value["runtime_state_clean"])
            self.assertTrue(value["runtime_state_directories_touched"])
            for name in recovery.UNIT_NAMES:
                self.assertFalse((layout.unit_dir / name).exists())

            replay = recovery.cleanup_rejected_install(
                self.spec(),
                layout,
                systemctl=ctl,
                boundary_probe=self.boundary,
                release_probe=self.release_probe,
            )
            self.assertTrue(replay["replayed"])
            inspected = recovery.inspect_rejected_install(
                self.spec(),
                layout,
                systemctl=ctl,
                boundary_probe=self.boundary,
                release_probe=self.release_probe,
            )
            self.assertEqual(inspected["recovery_state"], "COMPLETED")

    @mock.patch.object(recovery, "_require_root", return_value=None)
    def test_disable_failure_leaves_prepared_authority_and_retry_recovers(
        self,
        _geteuid,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout, _ = self.layout(Path(td))
            ctl = FakeSystemctl()
            ctl.fail_disable_once = recovery.UNIT_NAMES[1]

            with self.assertRaisesRegex(
                recovery.OperationControlRecoveryError,
                "systemctl operation failed",
            ):
                recovery.cleanup_rejected_install(
                    self.spec(),
                    layout,
                    systemctl=ctl,
                    boundary_probe=self.boundary,
                    release_probe=self.release_probe,
                )

            prepared, completed = recovery._recovery_paths(layout, self.spec())
            self.assertTrue(prepared.is_file())
            self.assertFalse(completed.exists())

            value = recovery.cleanup_rejected_install(
                self.spec(),
                layout,
                systemctl=ctl,
                boundary_probe=self.boundary,
                release_probe=self.release_probe,
            )
            self.assertTrue(value["sidecar_clean"])
            self.assertTrue(completed.is_file())

    @mock.patch.object(recovery, "_require_root", return_value=None)
    def test_runtime_state_foreign_material_blocks_before_prepared_authority(
        self,
        _require_root,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout, _ = self.layout(Path(td))
            foreign = layout.transport_root / "unexpected"
            foreign.write_text("foreign", encoding="utf-8")
            os.chmod(foreign, 0o600)

            with self.assertRaisesRegex(
                recovery.OperationControlRecoveryError,
                "transport runtime root contains unexpected material",
            ):
                recovery.cleanup_rejected_install(
                    self.spec(),
                    layout,
                    systemctl=FakeSystemctl(),
                    boundary_probe=self.boundary,
                    release_probe=self.release_probe,
                )
            self.assertFalse(layout.recovery_root.exists())
            self.assertTrue(foreign.is_file())

    @mock.patch.object(recovery, "_require_root", return_value=None)
    def test_runtime_cleanup_resumes_from_exact_partial_control_tree(
        self,
        _require_root,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout, _ = self.layout(Path(td))
            ctl = FakeSystemctl()
            ctl.fail_disable_once = recovery.UNIT_NAMES[0]

            with self.assertRaises(recovery.OperationControlRecoveryError):
                recovery.cleanup_rejected_install(
                    self.spec(),
                    layout,
                    systemctl=ctl,
                    boundary_probe=self.boundary,
                    release_probe=self.release_probe,
                )

            (layout.operation_control_root / "processed").rmdir()

            value = recovery.cleanup_rejected_install(
                self.spec(),
                layout,
                systemctl=ctl,
                boundary_probe=self.boundary,
                release_probe=self.release_probe,
            )
            self.assertTrue(value["runtime_state_clean"])
            self.assertFalse(layout.operation_control_root.exists())

    @mock.patch.object(recovery, "_require_root", return_value=None)
    def test_completed_authority_is_exactly_bound_to_prepared_record(
        self,
        _require_root,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout, _ = self.layout(Path(td))
            ctl = FakeSystemctl()
            recovery.cleanup_rejected_install(
                self.spec(),
                layout,
                systemctl=ctl,
                boundary_probe=self.boundary,
                release_probe=self.release_probe,
            )

            prepared_path, completed_path = recovery._recovery_paths(
                layout,
                self.spec(),
            )
            prepared = recovery._read_canonical_record(
                prepared_path,
                recovery.PREPARED_SCHEMA,
            )
            self.assertIsNotNone(prepared)

            completed = recovery._read_canonical_record(
                completed_path,
                recovery.COMPLETED_SCHEMA,
            )
            self.assertIsNotNone(completed)
            completed["prepared_sha256"] = "0" * 64
            completed_path.write_bytes(recovery._canonical_json(completed))
            os.chmod(completed_path, 0o600)

            with self.assertRaisesRegex(
                recovery.OperationControlRecoveryError,
                "completed recovery authority mismatch: prepared_sha256",
            ):
                recovery.inspect_rejected_install(
                    self.spec(),
                    layout,
                    systemctl=ctl,
                    boundary_probe=self.boundary,
                    release_probe=self.release_probe,
                )

    @mock.patch.object(recovery, "_require_root", return_value=None)
    def test_prepared_recovery_rejects_credential_substitution(
        self,
        _geteuid,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout, _ = self.layout(Path(td))
            ctl = FakeSystemctl()
            ctl.fail_disable_once = recovery.UNIT_NAMES[0]
            with self.assertRaises(recovery.OperationControlRecoveryError):
                recovery.cleanup_rejected_install(
                    self.spec(),
                    layout,
                    systemctl=ctl,
                    boundary_probe=self.boundary,
                    release_probe=self.release_probe,
                )

            credential = layout.credential
            raw = recovery._credential_bytes(
                token="github_pat_" + ("B" * 40),
                repository="efremov-aleksei-96/keelaryn",
                issue=65,
                actors="efremov-aleksei-96",
                status_actor="efremov-aleksei-96",
            )
            credential.write_bytes(raw)
            os.chmod(credential, 0o600)

            with self.assertRaisesRegex(
                recovery.OperationControlRecoveryError,
                "credential differs",
            ):
                recovery.cleanup_rejected_install(
                    self.spec(),
                    layout,
                    systemctl=ctl,
                    boundary_probe=self.boundary,
                    release_probe=self.release_probe,
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
