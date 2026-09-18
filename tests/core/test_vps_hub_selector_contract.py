from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEPLOY = REPO / "deploy" / "zero-based-vps"
sys.path.insert(0, str(DEPLOY))

import hub_cutover as cutovermod  # noqa: E402


class ZeroBasedVpsHubSelectorContractTests(unittest.TestCase):
    def test_credentials_and_selector_are_separate(self) -> None:
        credentials = (DEPLOY / "keelaryn-drive.env.example").read_text(encoding="utf-8")
        selector = (DEPLOY / "keelaryn-hub.env.example").read_text(encoding="utf-8")
        self.assertNotIn("KEELARYN_HUB_ROOT_ID=", credentials)
        assignments = [
            line
            for line in selector.splitlines()
            if line and not line.startswith("#")
        ]
        self.assertEqual(
            assignments,
            ["KEELARYN_HUB_ROOT_ID=REPLACE_WITH_APPROVED_GOOGLE_DRIVE_HUB_ROOT_ID"],
        )

    def test_all_checked_in_drive_services_load_the_single_selector(self) -> None:
        for name in ("keelaryn-drive.service", "keelaryn-drive-bootstrap.service"):
            with self.subTest(name=name):
                raw = (DEPLOY / name).read_text(encoding="utf-8")
                self.assertEqual(raw.count("EnvironmentFile=/etc/keelaryn/drive.env"), 1)
                self.assertEqual(raw.count("EnvironmentFile=/etc/keelaryn/hub.env"), 1)
                self.assertEqual(
                    raw.count(
                        "Environment=KEELARYN_MUTATION_GATE_ROOT=/var/lib/keelaryn/mutation-gate"
                    ),
                    1,
                )
                self.assertNotIn("ExecStartPre=/usr/bin/test -r /etc/keelaryn/drive.env", raw)
                self.assertNotIn("ExecStartPre=/usr/bin/test -r /etc/keelaryn/hub.env", raw)
                self.assertNotIn("KEELARYN_HUB_ROOT_ID=", raw)

    def test_cutover_tool_uses_same_selector_key_as_runtime(self) -> None:
        selector = (DEPLOY / "keelaryn-hub.env.example").read_text(encoding="utf-8")
        self.assertIn(f"{cutovermod.SELECTOR_KEY}=", selector)
        self.assertEqual(cutovermod.SELECTOR_KEY, "KEELARYN_HUB_ROOT_ID")


if __name__ == "__main__":
    unittest.main(verbosity=2)
