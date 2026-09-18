from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from keelaryn_core.drive_mutation_gate import (
    DriveMutationGate,
    DriveMutationGateAdmin,
    DriveMutationGateError,
    INHIBIT_NAME,
    MUTATION_GATE_ROOT_ENV,
)


@unittest.skipUnless(os.name == "posix", "production mutation gate is POSIX-only")
class DriveMutationGateTests(unittest.TestCase):
    def layout(self, root: Path) -> Path:
        gate = root / "mutation-gate"
        gate.mkdir(mode=0o2750)
        os.chmod(gate, 0o2750)
        lock = gate / "LOCK"
        lock.write_bytes(b"")
        os.chmod(lock, 0o640)
        return gate

    @staticmethod
    def inhibit(txid: str = "1" * 32) -> dict[str, str]:
        return {
            "schema": "keelaryn.drive-mutation-inhibit.v1",
            "transaction_id": txid,
            "active_transaction_sha256": "2" * 64,
            "source_commit": "3" * 40,
            "tool_sha256": "4" * 64,
            "old_selector_sha256": "5" * 64,
            "new_selector_sha256": "6" * 64,
        }

    def test_shared_mutation_blocks_exclusive_cutover_and_releases_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            gate = self.layout(Path(temp))
            mutation = DriveMutationGate(gate)
            admin = DriveMutationGateAdmin(gate)
            with mutation:
                with self.assertRaisesRegex(DriveMutationGateError, "active Drive mutation"):
                    with admin.locked():
                        pass
            with admin.locked():
                self.assertIsNone(admin.read())

    def test_durable_inhibit_blocks_new_mutation_until_exact_release(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            gate = self.layout(Path(temp))
            admin = DriveMutationGateAdmin(gate)
            expected = self.inhibit()
            with admin.locked():
                self.assertEqual(admin.publish(expected), expected)

            inhibit_path = gate / INHIBIT_NAME
            self.assertEqual(stat.S_IMODE(inhibit_path.stat().st_mode), 0o640)
            with self.assertRaisesRegex(DriveMutationGateError, "inhibited"):
                DriveMutationGate(gate).acquire()

            with admin.locked():
                admin.clear(expected)
            self.assertFalse(inhibit_path.exists())
            with DriveMutationGate(gate):
                pass

    def test_conflicting_inhibit_and_inexact_clear_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            gate = self.layout(Path(temp))
            admin = DriveMutationGateAdmin(gate)
            first = self.inhibit("1" * 32)
            second = self.inhibit("2" * 32)
            with admin.locked():
                admin.publish(first)
                with self.assertRaises(DriveMutationGateError):
                    admin.publish(second)
                with self.assertRaises(DriveMutationGateError):
                    admin.clear(second)
                self.assertEqual(admin.read(), first)

    def test_root_lock_and_inhibit_security_drift_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            gate = self.layout(Path(temp))
            os.chmod(gate, 0o0750)
            with self.assertRaises(DriveMutationGateError):
                DriveMutationGate(gate)

        with tempfile.TemporaryDirectory() as temp:
            gate = self.layout(Path(temp))
            os.chmod(gate / "LOCK", 0o644)
            with self.assertRaises(DriveMutationGateError):
                DriveMutationGate(gate).acquire()

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gate = self.layout(root)
            admin = DriveMutationGateAdmin(gate)
            with admin.locked():
                admin.publish(self.inhibit())
            os.chmod(gate / INHIBIT_NAME, 0o644)
            with self.assertRaises(DriveMutationGateError):
                DriveMutationGate(gate).acquire()

    def test_environment_binding_is_required_and_absolute(self) -> None:
        with self.assertRaisesRegex(DriveMutationGateError, "required"):
            DriveMutationGate.from_environment({})
        with self.assertRaisesRegex(DriveMutationGateError, "absolute"):
            DriveMutationGate.from_environment({MUTATION_GATE_ROOT_ENV: "relative"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
