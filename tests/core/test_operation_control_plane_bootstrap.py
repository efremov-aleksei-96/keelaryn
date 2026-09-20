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
        bootstrap_root.mkdir(mode=0o700)
        for path in (config_dir, bootstrap_root):
            os.chmod(path, 0o700)
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

    def test_credential_bytes_are_canonical_and_secret_never_enters_receipt(self) -> None:
        raw = bootstrap._credential_bytes(
            token="github_pat_" + ("A" * 40),
            repository="efremov-aleksei-96/keelaryn",
            issue=65,
            actors="efremov-aleksei-96",
        )
        self.assertIn(b"KEELARYN_GITHUB_OPERATIONS_ISSUE=65\n", raw)
        self.assertNotIn(b" ", raw)

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

            with mock.patch.object(bootstrap.os, "geteuid", return_value=0):
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

            with mock.patch.object(bootstrap.os, "geteuid", return_value=0):
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
    def test_failed_service_start_rolls_back_new_files_and_control_selector(
        self,
        getpwnam,
        verify,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            install, release, commit, unit_dir, config, receipt_root = self.layout(root)
            verify.return_value = self.identity(commit)
            getpwnam.return_value = type("Pw", (), {"pw_uid": 1000})()

            def systemctl(args):
                if args[:2] == ["enable", "--now"] and args[-1].endswith("agent.service"):
                    raise bootstrap.ControlPlaneBootstrapError("injected start failure")

            with mock.patch.object(bootstrap.os, "geteuid", return_value=0):
                with self.assertRaises(bootstrap.ControlPlaneBootstrapError):
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
                        active_probe=lambda unit: False,
                    )

            self.assertFalse((install / "control-current").exists())
            self.assertFalse((config / "github-operations.env").exists())
            for name in bootstrap.UNIT_NAMES:
                self.assertFalse((unit_dir / name).exists())
            self.assertEqual(
                os.readlink(install / "current"),
                "releases/" + ("b" * 40),
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
