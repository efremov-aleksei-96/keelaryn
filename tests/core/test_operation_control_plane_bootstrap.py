from __future__ import annotations

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy" / "zero-based-vps"
sys.path.insert(0, str(DEPLOY))

import operation_control_plane_bootstrap as bootstrap  # noqa: E402


class ControlPlaneBootstrapTests(unittest.TestCase):
    def layout(self, root: Path):
        install = root / "opt" / "keelaryn"
        releases = install / "releases"
        commit = "a" * 40
        release = releases / commit
        release.mkdir(parents=True)
        qualified = release / "deploy" / "zero-based-vps"
        qualified.mkdir(parents=True)
        for name in bootstrap.UNIT_NAMES:
            target = qualified / name
            target.write_bytes((DEPLOY / name).read_bytes())
            os.chmod(target, 0o444)
        os.chmod(qualified, 0o555)
        os.chmod(release / "deploy", 0o555)
        os.chmod(install, 0o755)
        os.chmod(releases, 0o755)
        os.chmod(release, 0o555)
        os.symlink("releases/" + ("b" * 40), install / "current")

        unit_dir = root / "systemd"
        unit_dir.mkdir(mode=0o755)
        config_dir = root / "etc" / "keelaryn"
        config_dir.mkdir(parents=True, mode=0o700)
        bootstrap_root = root / "bootstrap"
        os.chmod(config_dir, 0o700)
        return install, release, commit, unit_dir, config_dir, bootstrap_root

    def identity(self, commit: str):
        return {
            "schema": "test",
            "source_commit": commit,
            "payload_sha256": "c" * 64,
            "payload_size": 1,
            "file_count": 1,
        }

    def test_units_are_pinned_to_control_current_not_production_current(self) -> None:
        for name in bootstrap.UNIT_NAMES:
            raw = (DEPLOY / name).read_text(encoding="utf-8")
            self.assertIn("/opt/keelaryn/control-current", raw)
            self.assertNotIn("WorkingDirectory=/opt/keelaryn/current", raw)

    def test_root_precondition_is_isolated_and_fail_closed(self) -> None:
        with mock.patch.object(bootstrap.os, "geteuid", return_value=1000):
            with self.assertRaisesRegex(
                bootstrap.ControlPlaneBootstrapError,
                "requires root",
            ):
                bootstrap._require_root()

        with mock.patch.object(bootstrap.os, "geteuid", return_value=0):
            bootstrap._require_root()

    def test_credential_bytes_are_canonical_and_secret_never_enters_receipt(self) -> None:
        raw = bootstrap._credential_bytes(
            token="github_pat_" + ("A" * 40),
            repository="efremov-aleksei-96/keelaryn",
            issue=65,
            actors="efremov-aleksei-96",
        )
        self.assertIn(b"KEELARYN_GITHUB_OPERATIONS_ISSUE=65\n", raw)
        self.assertNotIn(b" ", raw)


    def test_atomic_new_file_identity_is_captured_after_hard_link(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "created"
            identity = bootstrap._atomic_new_file(target, b"ours", 0o600)
            self.assertEqual(identity, bootstrap._path_identity(target))

    def test_atomic_new_file_never_replaces_existing_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "credential"
            target.write_bytes(b"existing")
            os.chmod(target, 0o600)

            with self.assertRaisesRegex(
                bootstrap.ControlPlaneBootstrapError,
                "refuses to replace existing path",
            ):
                bootstrap._atomic_new_file(target, b"new", 0o600)

            self.assertEqual(target.read_bytes(), b"existing")

    def test_created_path_rollback_rejects_delete_recreate_even_if_inode_reused(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "created"
            identity = bootstrap._atomic_new_file(target, b"ours", 0o600)
            target.unlink()
            target.write_bytes(b"replacement")
            os.chmod(target, 0o600)

            with self.assertRaisesRegex(
                bootstrap.ControlPlaneBootstrapError,
                "identity changed before rollback",
            ):
                bootstrap._unlink_created(target, identity)

            self.assertEqual(target.read_bytes(), b"replacement")

    @mock.patch.object(bootstrap, "verify_release_directory")
    @mock.patch.object(bootstrap.pwd, "getpwnam")
    def test_preflight_proves_production_current_without_mutating_it(
        self,
        getpwnam,
        verify,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            install, release, commit, unit_dir, config, receipt_root = self.layout(root)
            verify.return_value = self.identity(commit)
            getpwnam.return_value = type("Pw", (), {"pw_uid": 1000})()

            with mock.patch.object(bootstrap, "_require_root", return_value=None):
                value = bootstrap.preflight(
                    release=release,
                    expected_source_commit=commit,
                    expected_payload_sha256="c" * 64,
                    production_current=install / "current",
                    control_current=install / "control-current",
                    unit_dir=unit_dir,
                    config_dir=config,
                    bootstrap_root=receipt_root,
                )

            self.assertEqual(value["control_current_state"], "ABSENT")
            self.assertEqual(value["bootstrap_root_state"], "ABSENT")
            self.assertFalse(receipt_root.exists())
            self.assertEqual(
                os.readlink(install / "current"),
                "releases/" + ("b" * 40),
            )

    @mock.patch.object(bootstrap, "verify_release_directory")
    @mock.patch.object(bootstrap.pwd, "getpwnam")
    def test_install_is_transactional_and_keeps_production_selector_unchanged(
        self,
        getpwnam,
        verify,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            install, release, commit, unit_dir, config, receipt_root = self.layout(root)
            verify.return_value = self.identity(commit)
            getpwnam.return_value = type("Pw", (), {"pw_uid": 1000})()
            calls: list[list[str]] = []

            with mock.patch.object(bootstrap, "_require_root", return_value=None):
                receipt = bootstrap.install(
                    release=release,
                    expected_source_commit=commit,
                    expected_payload_sha256="c" * 64,
                    repository="efremov-aleksei-96/keelaryn",
                    issue=65,
                    actors="efremov-aleksei-96",
                    token="github_pat_" + ("A" * 40),
                    production_current=install / "current",
                    control_current=install / "control-current",
                    unit_dir=unit_dir,
                    config_dir=config,
                    bootstrap_root=receipt_root,
                    systemctl=lambda args: calls.append(args),
                    active_probe=lambda unit: False if not calls else True,
                )

            self.assertTrue(receipt["production_current_unchanged"])
            self.assertTrue(receipt_root.is_dir())
            self.assertEqual(stat.S_IMODE(receipt_root.stat().st_mode), 0o700)
            self.assertEqual(
                os.readlink(install / "current"),
                "releases/" + ("b" * 40),
            )
            self.assertEqual(
                os.readlink(install / "control-current"),
                "releases/" + commit,
            )
            credential = config / "github-operations.env"
            self.assertEqual(stat.S_IMODE(credential.stat().st_mode), 0o600)
            self.assertNotIn(
                "github_pat_",
                (receipt_root / "bootstrap-receipt.json").read_text(encoding="utf-8"),
            )

    @mock.patch.object(bootstrap, "verify_release_directory")
    @mock.patch.object(bootstrap.pwd, "getpwnam")
    def test_failed_partial_agent_activation_rolls_back_all_created_state(
        self,
        getpwnam,
        verify,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            install, release, commit, unit_dir, config, receipt_root = self.layout(root)
            verify.return_value = self.identity(commit)
            getpwnam.return_value = type("Pw", (), {"pw_uid": 1000})()
            active: set[str] = set()
            calls: list[list[str]] = []

            def systemctl(args):
                calls.append(list(args))
                if args[:2] == ["enable", "--now"]:
                    unit = args[-1]
                    active.add(unit)
                    if unit.endswith("agent.service"):
                        raise bootstrap.ControlPlaneBootstrapError(
                            "injected partial agent start failure"
                        )
                elif args[:2] == ["disable", "--now"]:
                    active.discard(args[-1])

            with mock.patch.object(bootstrap, "_require_root", return_value=None):
                with self.assertRaisesRegex(
                    bootstrap.ControlPlaneBootstrapError,
                    "injected partial agent start failure",
                ):
                    bootstrap.install(
                        release=release,
                        expected_source_commit=commit,
                        expected_payload_sha256="c" * 64,
                        repository="efremov-aleksei-96/keelaryn",
                        issue=65,
                        actors="efremov-aleksei-96",
                        token="github_pat_" + ("A" * 40),
                        production_current=install / "current",
                        control_current=install / "control-current",
                        unit_dir=unit_dir,
                        config_dir=config,
                        bootstrap_root=receipt_root,
                        systemctl=systemctl,
                        active_probe=lambda unit: unit in active,
                    )

            self.assertEqual(active, set())
            self.assertFalse(receipt_root.exists())
            self.assertFalse((install / "control-current").exists())
            self.assertFalse((config / "github-operations.env").exists())
            for name in bootstrap.UNIT_NAMES:
                self.assertFalse((unit_dir / name).exists())
                self.assertIn(["disable", "--now", name], calls)
            self.assertEqual(
                os.readlink(install / "current"),
                "releases/" + ("b" * 40),
            )

    def test_agent_transport_dependency_is_resilient_wants_not_requires(self) -> None:
        raw = (DEPLOY / "keelaryn-operation-agent.service").read_text(encoding="utf-8")
        self.assertIn("Wants=keelaryn-operation-transport.service", raw)
        self.assertNotIn("Requires=keelaryn-operation-transport.service", raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
