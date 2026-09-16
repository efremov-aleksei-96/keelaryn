from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEPLOY = REPO / "deploy" / "zero-based-vps"
sys.path.insert(0, str(DEPLOY))

import build_payload as builder  # noqa: E402
import materialize_payload as materializer  # noqa: E402
import release_switch as switchmod  # noqa: E402


class ZeroBasedVpsReleaseSwitchToolIdentityTests(unittest.TestCase):
    OLD = "3" * 40
    NEW = "4" * 40

    def layout(self, root: Path):
        install = root / "opt" / "keelaryn"
        releases = install / "releases"
        releases.mkdir(parents=True)
        state = root / "var" / "lib" / "keelaryn" / "deployment"

        for commit in (self.OLD, self.NEW):
            payload = root / f"{commit}.tar.gz"
            builder.build_payload(REPO, commit, payload)
            materializer.materialize_payload(payload, releases, expected_source_commit=commit)

        os.symlink(f"releases/{self.OLD}", install / "current")
        old_tool = releases / self.OLD / switchmod.TOOL_RELATIVE
        new_tool = releases / self.NEW / switchmod.TOOL_RELATIVE
        return install, state, old_tool, new_tool

    def test_active_transaction_remains_bound_to_old_tool_after_current_switch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            install, state, old_tool, new_tool = self.layout(Path(temp))

            old = switchmod.ReleaseSwitch(install, state, executing_tool=old_tool)
            self.assertEqual(old.prepare(self.NEW)["status"], "PREPARED")
            self.assertEqual(old.apply()["status"], "APPLIED")
            self.assertEqual(os.readlink(install / "current"), f"releases/{self.NEW}")

            new = switchmod.ReleaseSwitch(install, state, executing_tool=new_tool)
            for operation in (new.status, new.accept, new.rollback):
                with self.subTest(operation=operation.__name__):
                    with self.assertRaises(switchmod.ReleaseSwitchError):
                        operation()

            self.assertEqual(old.status()["status"], "APPLIED")
            self.assertEqual(old.accept(), {"status": "IDLE"})

            with self.assertRaises(switchmod.ReleaseSwitchError):
                old.status()
            self.assertEqual(new.status(), {"status": "IDLE"})

    def test_old_tool_can_rollback_after_new_tool_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            install, state, old_tool, new_tool = self.layout(Path(temp))

            old = switchmod.ReleaseSwitch(install, state, executing_tool=old_tool)
            old.prepare(self.NEW)
            old.apply()

            with self.assertRaises(switchmod.ReleaseSwitchError):
                switchmod.ReleaseSwitch(install, state, executing_tool=new_tool).rollback()

            self.assertEqual(old.rollback(), {"status": "IDLE"})
            self.assertEqual(os.readlink(install / "current"), f"releases/{self.OLD}")
            self.assertEqual(old.status(), {"status": "IDLE"})

    def test_readme_pins_one_transaction_to_captured_old_switch_tool(self) -> None:
        text = (DEPLOY / "README.md").read_text(encoding="utf-8")
        required = (
            'OLD_RELEASE="$(readlink -f /opt/keelaryn/current)"',
            'SWITCH_TOOL="$OLD_RELEASE/deploy/zero-based-vps/release_switch.py"',
            '"$SWITCH_TOOL"',
            "atomically restore `current`",
        )
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
