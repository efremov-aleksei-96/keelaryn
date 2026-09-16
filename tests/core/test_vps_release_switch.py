from __future__ import annotations

import json
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


class Crash(RuntimeError):
    pass


class ZeroBasedVpsReleaseSwitchTests(unittest.TestCase):
    OLD = "1" * 40
    NEW = "2" * 40

    def layout(self, root: Path):
        install = root / "opt" / "keelaryn"
        releases = install / "releases"
        releases.mkdir(parents=True)
        state = root / "var" / "lib" / "keelaryn" / "deployment"

        for commit in (self.OLD, self.NEW):
            payload = root / f"{commit}.tar.gz"
            builder.build_payload(REPO, commit, payload)
            materializer.materialize_payload(
                payload,
                releases,
                expected_source_commit=commit,
            )
        os.symlink(f"releases/{self.OLD}", install / "current")
        return install, state

    @staticmethod
    def hook(point: str):
        def invoke(actual: str) -> None:
            if actual == point:
                raise Crash(actual)
        return invoke

    def current(self, install: Path) -> str:
        return os.readlink(install / "current")

    def tamper_new_release(self, install: Path) -> None:
        release = install / "releases" / self.NEW
        manifest = json.loads((release / "PAYLOAD_MANIFEST.json").read_text(encoding="utf-8"))
        target = release / manifest["files"][0]["path"]
        os.chmod(target, 0o644)
        target.write_bytes(target.read_bytes() + b"tamper")
        os.chmod(target, 0o444)

    def test_prepare_apply_accept_archives_exact_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            install, state = self.layout(Path(temp))
            switch = switchmod.ReleaseSwitch(install, state)
            prepared = switch.prepare(self.NEW)
            self.assertEqual(prepared["status"], "PREPARED")
            txid = prepared["transaction_id"]
            self.assertEqual(switch.apply()["status"], "APPLIED")
            self.assertEqual(self.current(install), f"releases/{self.NEW}")
            self.assertEqual(switch.accept(), {"status": "IDLE"})
            self.assertFalse((state / switchmod.ACTIVE_NAME).exists())
            self.assertTrue((state / "history" / f"{txid}.json").is_file())
            terminal = json.loads((state / "terminal" / f"{txid}.json").read_text(encoding="utf-8"))
            self.assertEqual(terminal["outcome"], "ACCEPTED")

    def test_apply_then_rollback_restores_exact_old_release(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            install, state = self.layout(Path(temp))
            switch = switchmod.ReleaseSwitch(install, state)
            txid = switch.prepare(self.NEW)["transaction_id"]
            switch.apply()
            self.assertEqual(switch.rollback(), {"status": "IDLE"})
            self.assertEqual(self.current(install), f"releases/{self.OLD}")
            terminal = json.loads((state / "terminal" / f"{txid}.json").read_text(encoding="utf-8"))
            self.assertEqual(terminal["outcome"], "ROLLED_BACK")

    def test_crash_after_prepare_record_recovers_from_durable_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            install, state = self.layout(Path(temp))
            with self.assertRaises(Crash):
                switchmod.ReleaseSwitch(
                    install,
                    state,
                    fault_hook=self.hook("prepare.after_active_create"),
                ).prepare(self.NEW)
            recovered = switchmod.ReleaseSwitch(install, state)
            self.assertEqual(recovered.status()["status"], "PREPARED")
            self.assertEqual(recovered.apply()["status"], "APPLIED")

    def test_crash_after_current_swap_recovers_as_applied(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            install, state = self.layout(Path(temp))
            switchmod.ReleaseSwitch(install, state).prepare(self.NEW)
            with self.assertRaises(Crash):
                switchmod.ReleaseSwitch(
                    install,
                    state,
                    fault_hook=self.hook("apply.after_current_swap"),
                ).apply()
            recovered = switchmod.ReleaseSwitch(install, state)
            self.assertEqual(recovered.status()["status"], "APPLIED")
            self.assertEqual(recovered.accept(), {"status": "IDLE"})

    def test_crash_after_accept_terminal_finishes_without_new_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            install, state = self.layout(Path(temp))
            base = switchmod.ReleaseSwitch(install, state)
            base.prepare(self.NEW)
            base.apply()
            with self.assertRaises(Crash):
                switchmod.ReleaseSwitch(
                    install,
                    state,
                    fault_hook=self.hook("accept.after_terminal_create"),
                ).accept()
            recovered = switchmod.ReleaseSwitch(install, state)
            status = recovered.status()
            self.assertEqual(status["status"], "FINALIZE_PENDING")
            self.assertEqual(status["terminal"], "ACCEPTED")
            with self.assertRaises(switchmod.ReleaseSwitchError):
                recovered.rollback()
            self.assertEqual(recovered.accept(), {"status": "IDLE"})
            self.assertEqual(self.current(install), f"releases/{self.NEW}")

    def test_rollback_crash_matrix_recovers(self) -> None:
        for point in ("rollback.after_current_swap", "rollback.after_terminal_create"):
            with self.subTest(point=point), tempfile.TemporaryDirectory() as temp:
                install, state = self.layout(Path(temp))
                base = switchmod.ReleaseSwitch(install, state)
                base.prepare(self.NEW)
                base.apply()
                with self.assertRaises(Crash):
                    switchmod.ReleaseSwitch(install, state, fault_hook=self.hook(point)).rollback()
                recovered = switchmod.ReleaseSwitch(install, state)
                status = recovered.status()
                self.assertIn(status["status"], {"PREPARED", "FINALIZE_PENDING"})
                self.assertEqual(recovered.rollback(), {"status": "IDLE"})
                self.assertEqual(self.current(install), f"releases/{self.OLD}")

    def test_crash_after_archive_is_durably_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            install, state = self.layout(Path(temp))
            base = switchmod.ReleaseSwitch(install, state)
            base.prepare(self.NEW)
            base.apply()
            with self.assertRaises(Crash):
                switchmod.ReleaseSwitch(
                    install,
                    state,
                    fault_hook=self.hook("finalize.after_active_archive"),
                ).accept()
            self.assertEqual(switchmod.ReleaseSwitch(install, state).status(), {"status": "IDLE"})
            self.assertEqual(self.current(install), f"releases/{self.NEW}")

    def test_unknown_current_blocks_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            install, state = self.layout(Path(temp))
            switch = switchmod.ReleaseSwitch(install, state)
            switch.prepare(self.NEW)
            current = install / "current"
            current.unlink()
            os.symlink("releases/ffffffffffffffffffffffffffffffffffffffff", current)
            with self.assertRaises(switchmod.ReleaseSwitchError):
                switch.apply()
            self.assertEqual(switch.status()["status"], "BLOCKED")
            self.assertEqual(os.readlink(current), "releases/ffffffffffffffffffffffffffffffffffffffff")

    def test_new_release_corruption_blocks_accept_but_not_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            install, state = self.layout(Path(temp))
            switch = switchmod.ReleaseSwitch(install, state)
            switch.prepare(self.NEW)
            switch.apply()
            self.tamper_new_release(install)
            with self.assertRaises(switchmod.ReleaseSwitchError):
                switch.accept()
            self.assertEqual(self.current(install), f"releases/{self.NEW}")
            self.assertEqual(switch.rollback(), {"status": "IDLE"})
            self.assertEqual(self.current(install), f"releases/{self.OLD}")

    def test_old_release_corruption_blocks_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            install, state = self.layout(Path(temp))
            switch = switchmod.ReleaseSwitch(install, state)
            switch.prepare(self.NEW)
            switch.apply()
            release = install / "releases" / self.OLD
            manifest = json.loads((release / "PAYLOAD_MANIFEST.json").read_text(encoding="utf-8"))
            target = release / manifest["files"][0]["path"]
            os.chmod(target, 0o644)
            target.write_bytes(target.read_bytes() + b"tamper")
            os.chmod(target, 0o444)
            with self.assertRaises(switchmod.ReleaseSwitchError):
                switch.rollback()
            self.assertEqual(self.current(install), f"releases/{self.NEW}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
