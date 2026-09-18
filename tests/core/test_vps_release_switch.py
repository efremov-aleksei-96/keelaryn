from __future__ import annotations

import json
import os
import stat
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
            materializer.materialize_payload(payload, releases, expected_source_commit=commit)
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

    def tamper_release(self, install: Path, commit: str) -> None:
        release = install / "releases" / commit
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
                switchmod.ReleaseSwitch(install, state, fault_hook=self.hook("prepare.after_active_create")).prepare(self.NEW)
            recovered = switchmod.ReleaseSwitch(install, state)
            self.assertEqual(recovered.status()["status"], "PREPARED")
            self.assertEqual(recovered.apply()["status"], "APPLIED")

    def test_crash_after_current_swap_recovers_as_applied(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            install, state = self.layout(Path(temp))
            switchmod.ReleaseSwitch(install, state).prepare(self.NEW)
            with self.assertRaises(Crash):
                switchmod.ReleaseSwitch(install, state, fault_hook=self.hook("apply.after_current_swap")).apply()
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
                switchmod.ReleaseSwitch(install, state, fault_hook=self.hook("accept.after_terminal_create")).accept()
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
                self.assertIn(recovered.status()["status"], {"PREPARED", "FINALIZE_PENDING"})
                self.assertEqual(recovered.rollback(), {"status": "IDLE"})
                self.assertEqual(self.current(install), f"releases/{self.OLD}")

    def test_crash_after_archive_is_durably_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            install, state = self.layout(Path(temp))
            base = switchmod.ReleaseSwitch(install, state)
            base.prepare(self.NEW)
            base.apply()
            with self.assertRaises(Crash):
                switchmod.ReleaseSwitch(install, state, fault_hook=self.hook("finalize.after_active_archive")).accept()
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
            self.tamper_release(install, self.NEW)
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
            self.tamper_release(install, self.OLD)
            with self.assertRaises(switchmod.ReleaseSwitchError):
                switch.rollback()
            self.assertEqual(self.current(install), f"releases/{self.NEW}")

    def test_world_readable_state_root_is_rejected_before_current_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            install, state = self.layout(Path(temp))
            state.mkdir(parents=True, mode=0o700)
            os.chmod(state, 0o755)
            before = self.current(install)
            with self.assertRaises(switchmod.ReleaseSwitchError):
                switchmod.ReleaseSwitch(install, state)
            self.assertEqual(self.current(install), before)

    def test_symlink_state_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            install, state = self.layout(root)
            real = root / "real-state"
            real.mkdir(mode=0o700)
            state.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(real, state)
            with self.assertRaises(switchmod.ReleaseSwitchError):
                switchmod.ReleaseSwitch(install, state)
            self.assertEqual(self.current(install), f"releases/{self.OLD}")

    def test_symlink_or_wrong_mode_lock_is_rejected(self) -> None:
        for kind in ("symlink", "mode"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                install, state = self.layout(root)
                switch = switchmod.ReleaseSwitch(install, state)
                lock = state / switchmod.LOCK_NAME
                if kind == "symlink":
                    outside = root / "outside-lock"
                    outside.write_text("x", encoding="utf-8")
                    os.symlink(outside, lock)
                else:
                    lock.write_text("x", encoding="utf-8")
                    os.chmod(lock, 0o644)
                with self.assertRaises(switchmod.ReleaseSwitchError):
                    switch.status()
                self.assertEqual(self.current(install), f"releases/{self.OLD}")

    def test_transaction_authority_files_are_private_even_with_umask_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            old_umask = os.umask(0)
            try:
                install, state = self.layout(Path(temp))
                switch = switchmod.ReleaseSwitch(install, state)
                txid = switch.prepare(self.NEW)["transaction_id"]
                active = state / switchmod.ACTIVE_NAME
                self.assertEqual(stat.S_IMODE(active.stat().st_mode), 0o600)
                self.assertEqual(active.stat().st_uid, os.geteuid())
                switch.apply()
                switch.accept()
                history = state / "history" / f"{txid}.json"
                terminal = state / "terminal" / f"{txid}.json"
                self.assertEqual(stat.S_IMODE(history.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(terminal.stat().st_mode), 0o600)
                self.assertEqual(history.stat().st_uid, os.geteuid())
                self.assertEqual(terminal.stat().st_uid, os.geteuid())
            finally:
                os.umask(old_umask)

    def test_active_transaction_mode_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            install, state = self.layout(Path(temp))
            switch = switchmod.ReleaseSwitch(install, state)
            switch.prepare(self.NEW)
            os.chmod(state / switchmod.ACTIVE_NAME, 0o644)
            with self.assertRaises(switchmod.ReleaseSwitchError):
                switch.status()

    def test_terminal_or_history_mode_drift_is_rejected(self) -> None:
        for name in ("terminal", "history"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                install, state = self.layout(Path(temp))
                switchmod.ReleaseSwitch(install, state)
                os.chmod(state / name, 0o755)
                with self.assertRaises(switchmod.ReleaseSwitchError):
                    switchmod.ReleaseSwitch(install, state)
                self.assertEqual(self.current(install), f"releases/{self.OLD}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
