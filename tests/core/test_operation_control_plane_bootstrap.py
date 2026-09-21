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
        config_parent = root / "etc" / "keelaryn"
        config_parent.mkdir(parents=True, mode=0o755)
        config_dir = config_parent / "operation-control"
        bootstrap_root = root / "bootstrap"
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

    def test_transport_sandbox_tolerates_absent_legacy_runtime_path(self) -> None:
        raw = (DEPLOY / "keelaryn-operation-transport.service").read_text(
            encoding="utf-8"
        )
        self.assertIn("-/run/keelaryn", raw)
        self.assertNotIn(" /run/keelaryn", raw)

    def test_transport_systemd_readiness_waits_for_authenticated_live_poll(self) -> None:
        raw = (DEPLOY / "keelaryn-operation-transport.service").read_text(
            encoding="utf-8"
        )
        self.assertIn("Type=notify", raw)
        self.assertIn("NotifyAccess=main", raw)
        self.assertIn("TimeoutStartSec=60s", raw)
        source = (
            ROOT / "core" / "keelaryn_core" / "operation_transport.py"
        ).read_text(encoding="utf-8")
        startup_index = source.index("startup = transport.startup_probe()")
        notify_index = source.index("_sd_notify_ready()", startup_index)
        loop_index = source.index("while True:", notify_index)
        self.assertLess(startup_index, notify_index)
        self.assertLess(notify_index, loop_index)

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
            status_actor="efremov-aleksei-96",
        )
        self.assertIn(b"KEELARYN_GITHUB_OPERATIONS_ISSUE=65\n", raw)
        self.assertIn(
            b"KEELARYN_GITHUB_OPERATIONS_STATUS_ACTOR=efremov-aleksei-96\n",
            raw,
        )
        self.assertNotIn(b" ", raw)


    def test_private_parent_pin_failure_never_deletes_unpinned_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "private"
            with mock.patch.object(
                bootstrap,
                "_pin_path",
                side_effect=bootstrap.ControlPlaneBootstrapError("injected pin failure"),
            ):
                with self.assertRaisesRegex(
                    bootstrap.ControlPlaneBootstrapError,
                    "ownership is ambiguous",
                ):
                    bootstrap._create_private_parent(target)

            self.assertTrue(target.is_dir())
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o700)

    def test_exclusive_new_file_pin_matches_installed_object(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "created"
            pin_fd, identity = bootstrap._exclusive_new_file(target, b"ours", 0o600)
            try:
                self.assertEqual(identity, bootstrap._object_identity(target))
                self.assertEqual(identity, bootstrap._fd_identity(pin_fd))
            finally:
                bootstrap._close_pin(pin_fd)

    def test_exclusive_new_file_never_replaces_existing_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "credential"
            target.write_bytes(b"existing")
            os.chmod(target, 0o600)

            with self.assertRaisesRegex(
                bootstrap.ControlPlaneBootstrapError,
                "refuses to replace existing path",
            ):
                bootstrap._exclusive_new_file(target, b"new", 0o600)

            self.assertEqual(target.read_bytes(), b"existing")

    def test_created_path_rollback_rejects_delete_recreate_while_pin_holds_inode(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "created"
            pin_fd, identity = bootstrap._exclusive_new_file(target, b"ours", 0o600)
            target.unlink()
            target.write_bytes(b"replacement")
            os.chmod(target, 0o600)

            try:
                with self.assertRaisesRegex(
                    bootstrap.ControlPlaneBootstrapError,
                    "identity changed before rollback",
                ):
                    bootstrap._unlink_created(target, pin_fd, identity)
            finally:
                bootstrap._close_pin(pin_fd)

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
                    status_actor="efremov-aleksei-96",
                    token="github_pat_" + ("A" * 40),
                    production_current=install / "current",
                    control_current=install / "control-current",
                    unit_dir=unit_dir,
                    config_dir=config,
                    bootstrap_root=receipt_root,
                    systemctl=lambda args: calls.append(args),
                    active_probe=lambda unit: False if not calls else True,
                    restart_probe=lambda unit: 0,
                    sleeper=lambda seconds: None,
                )

            self.assertTrue(receipt["production_current_unchanged"])
            self.assertTrue(receipt_root.is_dir())
            self.assertEqual(stat.S_IMODE(receipt_root.stat().st_mode), 0o700)
            self.assertTrue(config.is_dir())
            self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o700)
            self.assertEqual(receipt["status_actor"], "efremov-aleksei-96")
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
                        status_actor="efremov-aleksei-96",
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
            self.assertFalse(config.exists())
            self.assertFalse((install / "control-current").exists())
            for name in bootstrap.UNIT_NAMES:
                self.assertFalse((unit_dir / name).exists())
                self.assertIn(["disable", "--now", name], calls)
            self.assertEqual(
                os.readlink(install / "current"),
                "releases/" + ("b" * 40),
            )

    @mock.patch.object(bootstrap, "verify_release_directory")
    @mock.patch.object(bootstrap.pwd, "getpwnam")
    def test_crash_partial_transaction_is_repaired_and_exact_replay_is_read_only(
        self,
        getpwnam,
        verify,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            install, release, commit, unit_dir, config, receipt_root = self.layout(root)
            verify.return_value = self.identity(commit)
            getpwnam.return_value = type("Pw", (), {"pw_uid": 1000})()
            config.mkdir(mode=0o700)
            receipt_root.mkdir(mode=0o700)

            token = "github_pat_" + ("A" * 40)
            credential_raw = bootstrap._credential_bytes(
                token=token,
                repository="efremov-aleksei-96/keelaryn",
                issue=65,
                actors="efremov-aleksei-96",
                status_actor="efremov-aleksei-96",
            )
            digest = bootstrap._transaction_digest(
                expected_source_commit=commit,
                expected_payload_sha256="c" * 64,
                repository="efremov-aleksei-96/keelaryn",
                issue=65,
                actors="efremov-aleksei-96",
                status_actor="efremov-aleksei-96",
                credential_raw=credential_raw,
            )
            marker, marker_pin, _ = bootstrap._create_transaction_marker(
                receipt_root,
                digest=digest,
                config_preexisting=False,
                bootstrap_preexisting=False,
            )
            bootstrap._close_pin(marker_pin)

            credential = config / "github-operations.env"
            credential.write_bytes(b"partial credential")
            os.chmod(credential, 0o600)
            first_unit = unit_dir / bootstrap.UNIT_NAMES[0]
            first_unit.write_bytes(b"partial unit")
            os.chmod(first_unit, 0o644)

            active: set[str] = set()
            calls: list[list[str]] = []

            def systemctl(args):
                calls.append(list(args))
                if args[:2] == ["enable", "--now"]:
                    active.add(args[-1])
                elif args[:2] == ["disable", "--now"]:
                    active.discard(args[-1])

            with mock.patch.object(bootstrap, "_require_root", return_value=None):
                receipt = bootstrap.install(
                    release=release,
                    expected_source_commit=commit,
                    expected_payload_sha256="c" * 64,
                    repository="efremov-aleksei-96/keelaryn",
                    issue=65,
                    actors="efremov-aleksei-96",
                    status_actor="efremov-aleksei-96",
                    token=token,
                    production_current=install / "current",
                    control_current=install / "control-current",
                    unit_dir=unit_dir,
                    config_dir=config,
                    bootstrap_root=receipt_root,
                    systemctl=systemctl,
                    active_probe=lambda unit: unit in active,
                    restart_probe=lambda unit: 0,
                    sleeper=lambda seconds: None,
                )

            self.assertTrue(receipt["control_current_exact"])
            self.assertEqual(credential.read_bytes(), credential_raw)
            for name in bootstrap.UNIT_NAMES:
                self.assertEqual(
                    (unit_dir / name).read_bytes(),
                    (release / "deploy" / "zero-based-vps" / name).read_bytes(),
                )
            self.assertTrue(marker.is_dir())
            self.assertEqual(active, set(bootstrap.UNIT_NAMES))

            calls_before_replay = list(calls)
            with mock.patch.object(bootstrap, "_require_root", return_value=None):
                replay = bootstrap.install(
                    release=release,
                    expected_source_commit=commit,
                    expected_payload_sha256="c" * 64,
                    repository="efremov-aleksei-96/keelaryn",
                    issue=65,
                    actors="efremov-aleksei-96",
                    status_actor="efremov-aleksei-96",
                    token=token,
                    production_current=install / "current",
                    control_current=install / "control-current",
                    unit_dir=unit_dir,
                    config_dir=config,
                    bootstrap_root=receipt_root,
                    systemctl=systemctl,
                    active_probe=lambda unit: unit in active,
                    restart_probe=lambda unit: 0,
                    sleeper=lambda seconds: None,
                )

            self.assertEqual(replay, receipt)
            self.assertEqual(calls, calls_before_replay)

    @mock.patch.object(bootstrap, "verify_release_directory")
    @mock.patch.object(bootstrap.pwd, "getpwnam")
    def test_restart_during_stability_window_rolls_back_before_receipt(
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
            restarts = {name: 0 for name in bootstrap.UNIT_NAMES}

            def systemctl(args):
                if args[:2] == ["enable", "--now"]:
                    active.add(args[-1])
                elif args[:2] == ["disable", "--now"]:
                    active.discard(args[-1])

            def sleeper(seconds):
                self.assertEqual(seconds, bootstrap.SERVICE_STABILITY_SECONDS)
                restarts[bootstrap.UNIT_NAMES[0]] += 1

            with mock.patch.object(bootstrap, "_require_root", return_value=None):
                with self.assertRaisesRegex(
                    bootstrap.ControlPlaneBootstrapError,
                    "restarted during stability window",
                ):
                    bootstrap.install(
                        release=release,
                        expected_source_commit=commit,
                        expected_payload_sha256="c" * 64,
                        repository="efremov-aleksei-96/keelaryn",
                        issue=65,
                        actors="efremov-aleksei-96",
                        status_actor="efremov-aleksei-96",
                        token="github_pat_" + ("A" * 40),
                        production_current=install / "current",
                        control_current=install / "control-current",
                        unit_dir=unit_dir,
                        config_dir=config,
                        bootstrap_root=receipt_root,
                        systemctl=systemctl,
                        active_probe=lambda unit: unit in active,
                        restart_probe=lambda unit: restarts[unit],
                        sleeper=sleeper,
                    )

            self.assertEqual(active, set())
            self.assertFalse(receipt_root.exists())
            self.assertFalse(config.exists())
            self.assertFalse((install / "control-current").exists())
            for name in bootstrap.UNIT_NAMES:
                self.assertFalse((unit_dir / name).exists())

    def test_active_probe_fails_closed_on_unclassified_systemctl_error(self) -> None:
        with mock.patch.object(
            bootstrap,
            "_systemctl",
            return_value=bootstrap.subprocess.CompletedProcess(
                ["systemctl", "is-active", "--quiet", "x.service"],
                1,
                stdout="",
                stderr="manager error",
            ),
        ):
            with self.assertRaisesRegex(
                bootstrap.ControlPlaneBootstrapError,
                "active-state probe failed",
            ):
                bootstrap._is_active("x.service")

        for returncode in (3, 4):
            with mock.patch.object(
                bootstrap,
                "_systemctl",
                return_value=bootstrap.subprocess.CompletedProcess(
                    ["systemctl", "is-active", "--quiet", "x.service"],
                    returncode,
                    stdout="",
                    stderr="",
                ),
            ):
                self.assertFalse(bootstrap._is_active("x.service"))

    def test_agent_transport_dependency_is_resilient_wants_not_requires(self) -> None:
        raw = (DEPLOY / "keelaryn-operation-agent.service").read_text(encoding="utf-8")
        self.assertIn("Wants=keelaryn-operation-transport.service", raw)
        self.assertNotIn("Requires=keelaryn-operation-transport.service", raw)


    def test_agent_transport_relay_uses_narrow_shared_group_dac(self) -> None:
        transport_unit = (DEPLOY / "keelaryn-operation-transport.service").read_text(
            encoding="utf-8"
        )
        agent_unit = (DEPLOY / "keelaryn-operation-agent.service").read_text(
            encoding="utf-8"
        )
        transport_source = (
            ROOT / "core" / "keelaryn_core" / "operation_transport.py"
        ).read_text(encoding="utf-8")
        agent_source = (
            ROOT / "core" / "keelaryn_core" / "operation_agent.py"
        ).read_text(encoding="utf-8")

        self.assertIn("User=keelaryn", transport_unit)
        self.assertIn("Group=keelaryn", transport_unit)
        self.assertIn("StateDirectoryMode=0750", transport_unit)
        self.assertIn("UMask=0007", transport_unit)
        self.assertIn("RestrictSUIDSGID=true", transport_unit)
        self.assertIn("User=root", agent_unit)
        self.assertIn("Group=keelaryn", agent_unit)
        self.assertIn("CapabilityBoundingSet=\n", agent_unit)
        self.assertNotIn("CAP_DAC_OVERRIDE", agent_unit)

        for source in (transport_source, agent_source):
            self.assertIn("RELAY_ROOT_MODE = 0o750", source)
            self.assertIn("RELAY_DIRECTORY_MODE = 0o770", source)
            self.assertIn("RELAY_FILE_MODE = 0o640", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
