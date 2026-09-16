from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))


class DriveOperationalContractTests(unittest.TestCase):
    @staticmethod
    def _unit(name: str) -> str:
        return (REPO / "core/deploy/systemd" / name).read_text(encoding="utf-8")

    def test_systemd_service_has_single_writer_runtime_and_blocked_restart_semantics(self) -> None:
        unit = self._unit("keelaryn-drive.service")
        required = (
            "User=keelaryn",
            "Group=keelaryn",
            "Environment=KEELARYN_RUNTIME_DIR=/run/keelaryn",
            "EnvironmentFile=/etc/keelaryn/drive.env",
            "RuntimeDirectory=keelaryn",
            "RuntimeDirectoryMode=0700",
            "UMask=0077",
            "ExecStart=/usr/bin/python3 -m keelaryn_core.drive_poller serve --interval-seconds 30",
            "Restart=on-failure",
            "RestartPreventExitStatus=2 130",
            "NoNewPrivileges=true",
            "ProtectSystem=strict",
            "ProtectHome=true",
            "PrivateTmp=true",
            "ReadWritePaths=/run/keelaryn",
        )
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, unit)
        self.assertNotIn("GOOGLE_CLIENT_SECRET=", unit)
        self.assertNotIn("GOOGLE_REFRESH_TOKEN=", unit)
        self.assertNotIn("KEELARYN_HUB_ROOT_ID=", unit)

    def test_systemd_bootstrap_is_explicit_unprivileged_oneshot(self) -> None:
        unit = self._unit("keelaryn-drive-bootstrap.service")
        required = (
            "Type=oneshot",
            "User=keelaryn",
            "Group=keelaryn",
            "Environment=PYTHONPATH=/opt/keelaryn/core",
            "Environment=KEELARYN_RUNTIME_DIR=/run/keelaryn",
            "EnvironmentFile=/etc/keelaryn/drive.env",
            "RuntimeDirectory=keelaryn",
            "RuntimeDirectoryMode=0700",
            "UMask=0077",
            "ExecStart=/usr/bin/python3 -m keelaryn_core.drive_poller bootstrap",
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

    def test_deployment_readme_forbids_root_shell_bootstrap(self) -> None:
        readme = (REPO / "core/deploy/systemd/README.md").read_text(encoding="utf-8")
        self.assertIn("systemctl start keelaryn-drive-bootstrap.service", readme)
        self.assertIn("do not run the poller bootstrap directly as root", readme.lower())
        self.assertNotIn(". /etc/keelaryn/drive.env", readme)
        self.assertNotIn("set -a", readme)

    def test_environment_template_contains_placeholders_only(self) -> None:
        example = (REPO / "core/deploy/systemd/drive.env.example").read_text(encoding="utf-8")
        names = (
            "KEELARYN_HUB_ROOT_ID",
            "KEELARYN_GOOGLE_CLIENT_ID",
            "KEELARYN_GOOGLE_CLIENT_SECRET",
            "KEELARYN_GOOGLE_REFRESH_TOKEN",
        )
        for name in names:
            with self.subTest(name=name):
                line = next(line for line in example.splitlines() if line.startswith(name + "="))
                self.assertIn("REPLACE_WITH_", line)
        self.assertNotIn("ya29.", example)
        self.assertNotIn("1//", example)

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
