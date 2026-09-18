from __future__ import annotations

import hashlib
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
sys.path.insert(0, str(REPO / "core"))

import hub_cutover as cutovermod  # noqa: E402
from keelaryn_core.drive_mutation_gate import (  # noqa: E402
    DriveMutationGate,
    DriveMutationGateError,
)


class Crash(RuntimeError):
    pass


class ZeroBasedVpsHubCutoverTests(unittest.TestCase):
    SOURCE = "a" * 40
    OTHER_SOURCE = "b" * 40
    OLD = "OLDHubRoot_0123456789abcdef"
    NEW = "NEWHubRoot_0123456789abcdef"
    OTHER = "OtherHubRoot_0123456789abcdef"

    @staticmethod
    def hook(point: str):
        def invoke(actual: str) -> None:
            if actual == point:
                raise Crash(actual)
        return invoke

    def layout(self, root: Path):
        etc = root / "etc" / "keelaryn"
        etc.mkdir(parents=True, mode=0o755)
        selector = etc / "hub.env"
        selector.write_bytes(cutovermod._selector_bytes(self.OLD))
        os.chmod(selector, 0o600)
        state = root / "var" / "lib" / "keelaryn" / "hub-cutover"
        gate = state.parent / "mutation-gate"
        gate.mkdir(parents=True, mode=0o2750)
        os.chmod(gate, 0o2750)
        lock = gate / "LOCK"
        lock.write_bytes(b"")
        os.chmod(lock, 0o640)
        return selector, state

    def switch(self, selector: Path, state: Path, **kwargs):
        return cutovermod.HubSelectorCutover(
            selector,
            state,
            self.SOURCE,
            mutation_gate_root=state.parent / "mutation-gate",
            executing_tool=DEPLOY / "hub_cutover.py",
            **kwargs,
        )

    @staticmethod
    def selected(selector: Path) -> str:
        return cutovermod._parse_selector(selector.read_bytes())

    def accept_and_release(self, switch, state: Path, txid: str) -> None:
        raw = (state / cutovermod.ACTIVE_NAME).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        result = switch.accept(expected_active_transaction_sha256=digest)
        self.assertEqual(result["status"], "INHIBITED_IDLE")
        self.assertEqual(switch.status()["status"], "INHIBITED_IDLE")
        self.assertEqual(
            switch.release_mutation_inhibit_after_accept(txid, digest),
            {"status": "IDLE"},
        )
        self.assertEqual(switch.status(), {"status": "IDLE"})

    def test_prepare_apply_accept_archives_exact_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            selector, state = self.layout(Path(temp))
            switch = self.switch(selector, state)
            prepared = switch.prepare(self.NEW)
            txid = prepared["transaction_id"]
            self.assertEqual(prepared["status"], "PREPARED")
            self.assertNotIn(self.OLD, json.dumps(prepared))
            self.assertNotIn(self.NEW, json.dumps(prepared))

            self.assertEqual(switch.apply()["status"], "APPLIED")
            self.assertEqual(self.selected(selector), self.NEW)
            self.accept_and_release(switch, state, txid)

            self.assertFalse((state / cutovermod.ACTIVE_NAME).exists())
            history = state / "history" / f"{txid}.json"
            self.assertTrue(history.is_file())
            record = json.loads(history.read_text(encoding="utf-8"))
            self.assertEqual(record["old_hub_root_id"], self.OLD)
            self.assertEqual(record["new_hub_root_id"], self.NEW)
            terminal = json.loads((state / "terminal" / f"{txid}.json").read_text(encoding="utf-8"))
            self.assertEqual(terminal["outcome"], "ACCEPTED")
            self.assertEqual(terminal["tool"], record["tool"])

    def test_failed_external_acceptance_rolls_back_exact_old_selector(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            selector, state = self.layout(Path(temp))
            switch = self.switch(selector, state)
            txid = switch.prepare(self.NEW)["transaction_id"]
            switch.apply()
            self.assertEqual(self.selected(selector), self.NEW)

            # External read-only acceptance is deliberately represented by the
            # caller choosing rollback instead of accept. The cutover tool itself
            # never mutates either Hub.
            self.assertEqual(switch.rollback(), {"status": "IDLE"})
            self.assertEqual(self.selected(selector), self.OLD)
            terminal = json.loads((state / "terminal" / f"{txid}.json").read_text(encoding="utf-8"))
            self.assertEqual(terminal["outcome"], "ROLLED_BACK")

    def test_crash_after_prepare_recovers_from_durable_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            selector, state = self.layout(Path(temp))
            with self.assertRaises(Crash):
                self.switch(selector, state, fault_hook=self.hook("prepare.after_active_create")).prepare(self.NEW)
            recovered = self.switch(selector, state)
            self.assertEqual(recovered.status()["status"], "PREPARED")
            self.assertEqual(recovered.apply()["status"], "APPLIED")

    def test_crash_after_selector_commit_is_observed_as_applied(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            selector, state = self.layout(Path(temp))
            self.switch(selector, state).prepare(self.NEW)
            with self.assertRaises(Crash):
                self.switch(selector, state, fault_hook=self.hook("apply.after_selector_replace")).apply()
            self.assertEqual(self.selected(selector), self.NEW)
            recovered = self.switch(selector, state)
            self.assertEqual(recovered.status()["status"], "APPLIED")
            txid = recovered.status()["transaction_id"]
            self.accept_and_release(recovered, state, txid)

    def test_apply_expected_transaction_hash_and_inhibit_are_commit_boundary_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            selector, state = self.layout(Path(temp))
            switch = self.switch(selector, state)
            switch.prepare(self.NEW)
            active_raw = (state / cutovermod.ACTIVE_NAME).read_bytes()
            active_sha = hashlib.sha256(active_raw).hexdigest()

            with self.assertRaisesRegex(
                cutovermod.HubCutoverError,
                "changed at selector apply boundary",
            ):
                switch.apply(expected_active_transaction_sha256="0" * 64)
            self.assertEqual(self.selected(selector), self.OLD)

            inhibit = state.parent / "mutation-gate" / "INHIBIT.json"
            inhibit.unlink()
            with self.assertRaisesRegex(
                cutovermod.HubCutoverError,
                "mutation inhibit",
            ):
                switch.apply(expected_active_transaction_sha256=active_sha)
            self.assertEqual(self.selected(selector), self.OLD)

    def test_accept_expected_transaction_hash_blocks_replaced_active_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            selector, state = self.layout(Path(temp))
            first = self.switch(selector, state)
            first.prepare(self.NEW)
            first.apply()
            first_raw = (state / cutovermod.ACTIVE_NAME).read_bytes()
            first_sha = __import__("hashlib").sha256(first_raw).hexdigest()

            first.rollback()
            second = self.switch(selector, state)
            second.prepare(self.OTHER)
            second.apply()

            with self.assertRaisesRegex(
                cutovermod.HubCutoverError,
                "changed at terminal accept boundary",
            ):
                second.accept(expected_active_transaction_sha256=first_sha)

            self.assertEqual(second.status()["status"], "APPLIED")
            self.assertEqual(self.selected(selector), self.OTHER)
            self.assertEqual(list((state / "terminal").glob("*.json"))[-1].name.endswith(".json"), True)
            second_txid = json.loads((state / cutovermod.ACTIVE_NAME).read_text(encoding="utf-8"))["transaction_id"]
            self.assertFalse((state / "terminal" / f"{second_txid}.json").exists())

    def test_crash_after_accept_terminal_cannot_be_changed_to_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            selector, state = self.layout(Path(temp))
            base = self.switch(selector, state)
            base.prepare(self.NEW)
            base.apply()
            with self.assertRaises(Crash):
                self.switch(selector, state, fault_hook=self.hook("accept.after_terminal_create")).accept()
            recovered = self.switch(selector, state)
            status = recovered.status()
            self.assertEqual(status["status"], "FINALIZE_PENDING")
            self.assertEqual(status["terminal"], "ACCEPTED")
            with self.assertRaises(cutovermod.HubCutoverError):
                recovered.rollback()
            active_raw = (state / cutovermod.ACTIVE_NAME).read_bytes()
            active_sha = hashlib.sha256(active_raw).hexdigest()
            result = recovered.accept(
                expected_active_transaction_sha256=active_sha
            )
            self.assertEqual(result["status"], "INHIBITED_IDLE")
            self.assertEqual(
                recovered.release_mutation_inhibit_after_accept(
                    status["transaction_id"],
                    active_sha,
                ),
                {"status": "IDLE"},
            )
            self.assertEqual(self.selected(selector), self.NEW)

    def test_rollback_crash_matrix_recovers(self) -> None:
        for point in ("rollback.after_selector_replace", "rollback.after_terminal_create"):
            with self.subTest(point=point), tempfile.TemporaryDirectory() as temp:
                selector, state = self.layout(Path(temp))
                base = self.switch(selector, state)
                base.prepare(self.NEW)
                base.apply()
                with self.assertRaises(Crash):
                    self.switch(selector, state, fault_hook=self.hook(point)).rollback()
                recovered = self.switch(selector, state)
                self.assertIn(recovered.status()["status"], {"PREPARED", "FINALIZE_PENDING"})
                self.assertEqual(recovered.rollback(), {"status": "IDLE"})
                self.assertEqual(self.selected(selector), self.OLD)

    def test_crash_after_history_create_is_restart_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            selector, state = self.layout(Path(temp))
            base = self.switch(selector, state)
            base.prepare(self.NEW)
            base.apply()
            with self.assertRaises(Crash):
                self.switch(selector, state, fault_hook=self.hook("finalize.after_history_create")).accept()
            recovered = self.switch(selector, state)
            pending = recovered.status()
            self.assertEqual(pending["status"], "FINALIZE_PENDING")
            active_raw = (state / cutovermod.ACTIVE_NAME).read_bytes()
            active_sha = hashlib.sha256(active_raw).hexdigest()
            result = recovered.accept(
                expected_active_transaction_sha256=active_sha
            )
            self.assertEqual(result["status"], "INHIBITED_IDLE")
            self.assertEqual(
                recovered.release_mutation_inhibit_after_accept(
                    pending["transaction_id"],
                    active_sha,
                ),
                {"status": "IDLE"},
            )

    def test_unknown_selector_blocks_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            selector, state = self.layout(Path(temp))
            switch = self.switch(selector, state)
            switch.prepare(self.NEW)
            selector.write_bytes(cutovermod._selector_bytes(self.OTHER))
            os.chmod(selector, 0o600)
            with self.assertRaises(cutovermod.HubCutoverError):
                switch.apply()
            self.assertEqual(switch.status()["status"], "BLOCKED")
            self.assertEqual(self.selected(selector), self.OTHER)

    def test_tool_identity_mismatch_blocks_active_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            selector, state = self.layout(Path(temp))
            self.switch(selector, state).prepare(self.NEW)
            wrong = cutovermod.HubSelectorCutover(
                selector,
                state,
                self.OTHER_SOURCE,
                mutation_gate_root=state.parent / "mutation-gate",
                executing_tool=DEPLOY / "hub_cutover.py",
            )
            with self.assertRaises(cutovermod.HubCutoverError):
                wrong.status()
            self.assertEqual(self.selected(selector), self.OLD)

    def test_noncanonical_or_insecure_selector_is_rejected(self) -> None:
        for kind in ("mode", "extra-line", "symlink"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                selector, state = self.layout(root)
                if kind == "mode":
                    os.chmod(selector, 0o644)
                elif kind == "extra-line":
                    selector.write_bytes(cutovermod._selector_bytes(self.OLD) + b"EXTRA=x\n")
                    os.chmod(selector, 0o600)
                else:
                    outside = root / "outside-selector"
                    outside.write_bytes(cutovermod._selector_bytes(self.OLD))
                    os.chmod(outside, 0o600)
                    selector.unlink()
                    os.symlink(outside, selector)
                with self.assertRaises(cutovermod.HubCutoverError):
                    self.switch(selector, state)

    def test_cli_does_not_expose_raw_apply_or_terminal_accept(self) -> None:
        parser = cutovermod._parser()
        for command in ("apply", "accept"):
            with self.subTest(command=command), self.assertRaises(SystemExit):
                parser.parse_args(
                    [
                        "--selector-path",
                        "/tmp/keelaryn/hub.env",
                        "--state-root",
                        "/tmp/keelaryn/deployment",
                        "--mutation-gate-root",
                        "/tmp/keelaryn/mutation-gate",
                        "--source-commit",
                        self.SOURCE,
                        command,
                    ]
                )

    def test_transaction_authority_files_remain_owner_private(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            old_umask = os.umask(0)
            try:
                selector, state = self.layout(Path(temp))
                switch = self.switch(selector, state)
                txid = switch.prepare(self.NEW)["transaction_id"]
                active = state / cutovermod.ACTIVE_NAME
                self.assertEqual(stat.S_IMODE(active.stat().st_mode), 0o600)
                self.assertEqual(active.stat().st_uid, os.geteuid())
                switch.apply()
                switch.accept()
                history = state / "history" / f"{txid}.json"
                terminal = state / "terminal" / f"{txid}.json"
                self.assertEqual(stat.S_IMODE(history.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(terminal.stat().st_mode), 0o600)
            finally:
                os.umask(old_umask)

    def test_active_or_terminal_mode_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            selector, state = self.layout(Path(temp))
            switch = self.switch(selector, state)
            switch.prepare(self.NEW)
            os.chmod(state / cutovermod.ACTIVE_NAME, 0o644)
            with self.assertRaises(cutovermod.HubCutoverError):
                switch.status()

        with tempfile.TemporaryDirectory() as temp:
            selector, state = self.layout(Path(temp))
            switch = self.switch(selector, state)
            txid = switch.prepare(self.NEW)["transaction_id"]
            switch.apply()
            with self.assertRaises(Crash):
                self.switch(selector, state, fault_hook=self.hook("accept.after_terminal_create")).accept()
            os.chmod(state / "terminal" / f"{txid}.json", 0o644)
            with self.assertRaises(cutovermod.HubCutoverError):
                self.switch(selector, state).status()

    def test_mutation_gate_quiesces_prepare_and_blocks_new_mutations(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            selector, state = self.layout(Path(temp))
            gate = state.parent / "mutation-gate"
            switch = self.switch(selector, state)
            with DriveMutationGate(gate):
                with self.assertRaises(DriveMutationGateError):
                    switch.prepare(self.NEW)

            prepared = switch.prepare(self.NEW)
            with self.assertRaisesRegex(DriveMutationGateError, "inhibited"):
                DriveMutationGate(gate).acquire()
            self.assertEqual(switch.rollback(), {"status": "IDLE"})
            with DriveMutationGate(gate):
                pass
            self.assertEqual(prepared["status"], "PREPARED")

    def test_prepare_recovers_orphan_inhibit_before_active_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            selector, state = self.layout(Path(temp))
            with self.assertRaises(Crash):
                self.switch(
                    selector,
                    state,
                    fault_hook=self.hook("prepare.after_mutation_inhibit_create"),
                ).prepare(self.NEW)
            self.assertFalse((state / cutovermod.ACTIVE_NAME).exists())
            recovered = self.switch(selector, state)
            prepared = recovered.prepare(self.NEW)
            self.assertEqual(prepared["status"], "PREPARED")
            self.assertEqual(recovered.rollback(), {"status": "IDLE"})

    def test_insecure_state_or_lock_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            selector, state = self.layout(Path(temp))
            state.mkdir(parents=True, mode=0o700)
            os.chmod(state, 0o755)
            with self.assertRaises(cutovermod.HubCutoverError):
                self.switch(selector, state)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            selector, state = self.layout(root)
            switch = self.switch(selector, state)
            lock = state / cutovermod.LOCK_NAME
            outside = root / "outside-lock"
            outside.write_text("x", encoding="utf-8")
            os.symlink(outside, lock)
            with self.assertRaises(cutovermod.HubCutoverError):
                switch.status()


if __name__ == "__main__":
    unittest.main(verbosity=2)
