from __future__ import annotations

import shlex
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
DEPLOY = REPO / "deploy" / "zero-based-vps"


class ZeroBasedVpsDeploymentTests(unittest.TestCase):
    def test_systemd_unit_preserves_blocked_state_and_single_writer_runtime_contract(self) -> None:
        text = (DEPLOY / "keelaryn-drive.service").read_text(encoding="utf-8")
        required = (
            "User=keelaryn",
            "Group=keelaryn",
            "WorkingDirectory=/opt/keelaryn/current",
            "EnvironmentFile=/etc/keelaryn/drive.env",
            "Environment=PYTHONPATH=/opt/keelaryn/current/core",
            "Environment=KEELARYN_RUNTIME_DIR=/run/keelaryn",
            "RuntimeDirectory=keelaryn",
            "RuntimeDirectoryMode=0700",
            "UMask=0077",
            "Restart=on-failure",
            "RestartPreventExitStatus=2",
            "NoNewPrivileges=true",
            "ProtectSystem=strict",
            "ProtectHome=true",
            "CapabilityBoundingSet=",
            "AmbientCapabilities=",
            "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
        )
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, text)
        self.assertNotIn("Restart=always", text)
        self.assertNotIn("KEELARYN_GOOGLE_CLIENT_SECRET=", text)
        self.assertNotIn("KEELARYN_GOOGLE_REFRESH_TOKEN=", text)

        exec_line = next(line for line in text.splitlines() if line.startswith("ExecStart="))
        argv = shlex.split(exec_line.removeprefix("ExecStart="))
        self.assertEqual(
            argv,
            [
                "/usr/bin/python3",
                "-m",
                "keelaryn_core.drive_poller",
                "serve",
                "--interval-seconds",
                "30",
            ],
        )

    def test_environment_example_contains_only_required_refresh_auth_contract(self) -> None:
        lines = [
            line.strip()
            for line in (DEPLOY / "keelaryn-drive.env.example").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        pairs = [line.split("=", 1) for line in lines]
        keys = [key for key, _ in pairs]
        self.assertEqual(
            keys,
            [
                "KEELARYN_HUB_ROOT_ID",
                "KEELARYN_GOOGLE_CLIENT_ID",
                "KEELARYN_GOOGLE_CLIENT_SECRET",
                "KEELARYN_GOOGLE_REFRESH_TOKEN",
            ],
        )
        self.assertNotIn("KEELARYN_GOOGLE_ACCESS_TOKEN", keys)
        for key, value in pairs:
            with self.subTest(key=key):
                self.assertTrue(value.startswith("REPLACE_WITH_"))

    def test_deployment_document_requires_immutable_exact_commit_and_atomic_rollback(self) -> None:
        text = (DEPLOY / "README.md").read_text(encoding="utf-8")
        required_phrases = (
            "/opt/keelaryn/releases/<exact-source-commit>",
            "immutable after validation",
            "atomically changing the `current` symlink",
            "systemctl stop keelaryn-drive.service",
            "atomically restore `current`",
            "MUST NOT attempt to rewrite Drive canonical data",
            "does not authorize use against the production/personal Hub",
        )
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
