from __future__ import annotations

import shlex
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEPLOY = REPO / "deploy" / "zero-based-vps"
sys.path.insert(0, str(REPO / "core"))


class DriveOperationalContractTests(unittest.TestCase):
    @staticmethod
    def _unit(name: str) -> str:
        return (DEPLOY / name).read_text(encoding="utf-8")

    def test_systemd_service_has_single_writer_runtime_and_blocked_restart_semantics(self) -> None:
        unit = self._unit("keelaryn-drive.service")
        required = (
            "User=keelaryn",
            "Group=keelaryn",
            "WorkingDirectory=/opt/keelaryn/current",
            "Environment=PYTHONPATH=/opt/keelaryn/current/core",
            "Environment=KEELARYN_RUNTIME_DIR=/run/keelaryn",
            "Environment=PYTHONDONTWRITEBYTECODE=1",
            "EnvironmentFile=/etc/keelaryn/drive.env",
            "EnvironmentFile=/etc/keelaryn/hub.env",
            "ExecStartPre=/usr/bin/test -r /etc/keelaryn/hub.env",
            "RuntimeDirectory=keelaryn",
            "RuntimeDirectoryMode=0700",
            "UMask=0077",
            "ExecStart=/usr/bin/python3 -B -m keelaryn_core.drive_poller serve --interval-seconds 30",
            "Restart=on-failure",
            "RestartPreventExitStatus=2 130",
            "NoNewPrivileges=true",
            "ProtectSystem=strict",
            "ProtectHome=true",
            "PrivateTmp=true",
            "ReadWritePaths=/run/keelaryn",
            "CapabilityBoundingSet=",
            "AmbientCapabilities=",
            "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
        )
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, unit)
        self.assertNotIn("Restart=always", unit)
        self.assertNotIn("GOOGLE_CLIENT_SECRET=", unit)
        self.assertNotIn("GOOGLE_REFRESH_TOKEN=", unit)
        self.assertNotIn("KEELARYN_HUB_ROOT_ID=", unit)

        exec_line = next(line for line in unit.splitlines() if line.startswith("ExecStart="))
        self.assertEqual(
            shlex.split(exec_line.removeprefix("ExecStart=")),
            [
                "/usr/bin/python3",
                "-B",
                "-m",
                "keelaryn_core.drive_poller",
                "serve",
                "--interval-seconds",
                "30",
            ],
        )

    def test_systemd_bootstrap_is_explicit_unprivileged_oneshot(self) -> None:
        unit = self._unit("keelaryn-drive-bootstrap.service")
        required = (
            "Type=oneshot",
            "User=keelaryn",
            "Group=keelaryn",
            "WorkingDirectory=/opt/keelaryn/current",
            "Environment=PYTHONPATH=/opt/keelaryn/current/core",
            "Environment=KEELARYN_RUNTIME_DIR=/run/keelaryn",
            "Environment=PYTHONDONTWRITEBYTECODE=1",
            "EnvironmentFile=/etc/keelaryn/drive.env",
            "EnvironmentFile=/etc/keelaryn/hub.env",
            "ExecStartPre=/usr/bin/test -r /etc/keelaryn/hub.env",
            "RuntimeDirectory=keelaryn",
            "RuntimeDirectoryMode=0700",
            "UMask=0077",
            "ExecStart=/usr/bin/python3 -B -m keelaryn_core.drive_poller bootstrap",
            "NoNewPrivileges=true",
            "ProtectSystem=strict",
            "ProtectHome=true",
            "PrivateTmp=true",
            "ReadWritePaths=/run/keelaryn",
        )
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, unit)
        self.assertNotIn(" drive_poller serve", unit)
        self.assertNotIn("Restart=", unit)
        self.assertNotIn("GOOGLE_CLIENT_SECRET=", unit)
        self.assertNotIn("GOOGLE_REFRESH_TOKEN=", unit)
        self.assertNotIn("KEELARYN_HUB_ROOT_ID=", unit)

    def test_deployment_readme_enforces_immutable_payload_and_unprivileged_bootstrap(self) -> None:
        readme = (DEPLOY / "README.md").read_text(encoding="utf-8")
        required = (
            "single canonical deployment source",
            "/opt/keelaryn/releases/<exact-source-commit>",
            "0444",
            "0555",
            "--expected-source-commit",
            "--expected-payload-sha256",
            "PYTHONDONTWRITEBYTECODE=1",
            "systemctl start keelaryn-drive-bootstrap.service",
            "do not run the poller bootstrap directly as root",
            "systemctl stop keelaryn-drive.service",
            "atomically restore `current`",
            "MUST NOT attempt to rewrite Drive canonical data",
            "does not authorize use against the production/personal Hub",
        )
        lowered = readme.lower()
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value.lower(), lowered)
        self.assertNotIn("python3 -m compileall", readme)
        self.assertNotIn(". /etc/keelaryn/drive.env", readme)
        self.assertNotIn("set -a", readme)

    def test_environment_templates_contain_placeholders_only(self) -> None:
        credentials = (DEPLOY / "keelaryn-drive.env.example").read_text(encoding="utf-8")
        credential_names = (
            "KEELARYN_GOOGLE_CLIENT_ID",
            "KEELARYN_GOOGLE_CLIENT_SECRET",
            "KEELARYN_GOOGLE_REFRESH_TOKEN",
        )
        credential_lines = [
            line.strip()
            for line in credentials.splitlines()
            if line.strip() and not line.startswith("#")
        ]
        self.assertEqual(
            [line.split("=", 1)[0] for line in credential_lines],
            list(credential_names),
        )
        for name in credential_names:
            with self.subTest(name=name):
                line = next(line for line in credential_lines if line.startswith(name + "="))
                self.assertIn("REPLACE_WITH_", line)
        self.assertNotIn("KEELARYN_HUB_ROOT_ID=", credentials)
        self.assertNotIn("KEELARYN_GOOGLE_ACCESS_TOKEN=", credentials)
        self.assertNotIn("ya29.", credentials)
        self.assertNotIn("1//", credentials)

        selector = (DEPLOY / "keelaryn-hub.env.example").read_text(encoding="utf-8")
        selector_lines = [
            line.strip()
            for line in selector.splitlines()
            if line.strip() and not line.startswith("#")
        ]
        self.assertEqual(
            selector_lines,
            ["KEELARYN_HUB_ROOT_ID=REPLACE_WITH_APPROVED_GOOGLE_DRIVE_HUB_ROOT_ID"],
        )
        self.assertNotIn("KEELARYN_GOOGLE_CLIENT_ID=", selector)
        self.assertNotIn("KEELARYN_GOOGLE_CLIENT_SECRET=", selector)
        self.assertNotIn("KEELARYN_GOOGLE_REFRESH_TOKEN=", selector)

    def test_legacy_core_deployment_source_is_absent(self) -> None:
        self.assertFalse((REPO / "core/deploy/systemd").exists())

    def test_zero_based_branch_is_excluded_from_legacy_manager_job(self) -> None:
        workflow = (REPO / ".github/workflows/development-validation.yml").read_text(encoding="utf-8")
        self.assertIn("if: ${{ github.ref != 'refs/heads/dev/zero-based-keelaryn' }}", workflow)
        self.assertIn(
            "cancel-in-progress: ${{ github.ref != 'refs/heads/dev/zero-based-keelaryn' }}",
            workflow,
        )
        self.assertIn("zero-based-drive-disposable-acceptance:", workflow)
        self.assertIn("github.event_name == 'workflow_dispatch'", workflow)
        self.assertIn("github.ref == 'refs/heads/dev/zero-based-keelaryn'", workflow)
        self.assertIn("github.actor == github.repository_owner", workflow)
        self.assertIn("KEELARYN_DRIVE_ACCEPT_DISPOSABLE: ${{ secrets.KEELARYN_DISPOSABLE_ENABLE }}", workflow)
        self.assertIn("KEELARYN_DISPOSABLE_ACCEPTANCE_ROOT_ID: ${{ secrets.KEELARYN_DISPOSABLE_ACCEPTANCE_ROOT_ID }}", workflow)

    def test_unreachable_standalone_acceptance_workflow_is_absent(self) -> None:
        obsolete = REPO / ".github/workflows/zero-based-drive-disposable-acceptance.yml"
        self.assertFalse(obsolete.exists())

    def test_zero_based_validation_watches_dispatch_routing(self) -> None:
        workflow = (REPO / ".github/workflows/zero-based-core-validation.yml").read_text(encoding="utf-8")
        self.assertIn("'.github/workflows/development-validation.yml'", workflow)
        self.assertNotIn("zero-based-drive-disposable-acceptance.yml", workflow)


if __name__ == "__main__":
    unittest.main(verbosity=2)
