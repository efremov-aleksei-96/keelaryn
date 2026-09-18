from __future__ import annotations

import fcntl
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

import deployment_state_normalize as norm  # noqa: E402
import target_host_validate as targetmod  # noqa: E402


class ZeroBasedDeploymentStateNormalizationTests(unittest.TestCase):
    def _state(self, root: Path) -> Path:
        state = root / "deployment"
        terminal = state / "terminal"
        history = state / "history"
        terminal.mkdir(parents=True, mode=0o700)
        history.mkdir(mode=0o700)
        os.chmod(state, 0o700)
        os.chmod(terminal, 0o700)
        os.chmod(history, 0o700)
        lock = state / "LOCK"
        lock.write_bytes(b"")
        os.chmod(lock, 0o600)
        return state

    def _record(
        self,
        state: Path,
        directory: str,
        txid: str,
        schema: str,
        mode: int,
    ) -> Path:
        value = {
            "schema": schema,
            "transaction_id": txid,
            "test_payload": "preserve-these-exact-bytes",
        }
        path = state / directory / f"{txid}.json"
        path.write_bytes(
            (
                json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8")
        )
        os.chmod(path, mode)
        return path

    def test_check_is_read_only_and_apply_preserves_exact_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = self._state(Path(td))
            release_tx = "1" * 32
            cutover_tx = "2" * 32
            legacy_terminal = self._record(
                state,
                "terminal",
                release_tx,
                "keelaryn.zero-vps-release-switch-terminal.v1",
                0o644,
            )
            legacy_history = self._record(
                state,
                "history",
                release_tx,
                "keelaryn.zero-vps-release-switch.v1",
                0o644,
            )
            private_terminal = self._record(
                state,
                "terminal",
                cutover_tx,
                "keelaryn.zero-vps-hub-cutover-terminal.v1",
                0o600,
            )
            private_history = self._record(
                state,
                "history",
                cutover_tx,
                "keelaryn.zero-vps-hub-cutover.v1",
                0o600,
            )

            paths = (
                legacy_terminal,
                legacy_history,
                private_terminal,
                private_history,
            )
            before = {
                path: (
                    path.read_bytes(),
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                    stat.S_IMODE(path.stat().st_mode),
                )
                for path in paths
            }

            checked = norm.normalize_deployment_state(state, apply=False)
            self.assertEqual(checked["status"], "NORMALIZATION_REQUIRED")
            self.assertEqual(checked["legacy_count"], 2)
            self.assertEqual(checked["changed_count"], 0)
            for path in paths:
                self.assertEqual(path.read_bytes(), before[path][0])
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), before[path][2])

            with self.assertRaises(targetmod.TargetHostValidationError):
                targetmod.validate_deployment_state(state)

            applied = norm.normalize_deployment_state(state, apply=True)
            self.assertEqual(applied["status"], "NORMALIZED")
            self.assertEqual(applied["changed_count"], 2)
            self.assertTrue(applied["byte_identity_preserved"])
            for path in paths:
                self.assertEqual(path.read_bytes(), before[path][0])
                self.assertEqual(
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                    before[path][1],
                )
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

            targetmod.validate_deployment_state(state)
            repeated = norm.normalize_deployment_state(state, apply=True)
            self.assertEqual(repeated["status"], "CLEAN")
            self.assertEqual(repeated["changed_count"], 0)

    def test_unknown_record_mode_fails_before_any_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = self._state(Path(td))
            first = self._record(
                state,
                "history",
                "3" * 32,
                "keelaryn.zero-vps-release-switch.v1",
                0o644,
            )
            bad = self._record(
                state,
                "terminal",
                "4" * 32,
                "keelaryn.zero-vps-release-switch-terminal.v1",
                0o660,
            )
            with self.assertRaisesRegex(
                norm.DeploymentStateNormalizationError,
                "neither 0600 nor legacy 0644",
            ):
                norm.normalize_deployment_state(state, apply=True)
            self.assertEqual(stat.S_IMODE(first.stat().st_mode), 0o644)
            self.assertEqual(stat.S_IMODE(bad.stat().st_mode), 0o660)

    def test_invalid_schema_fails_before_any_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = self._state(Path(td))
            valid = self._record(
                state,
                "history",
                "5" * 32,
                "keelaryn.zero-vps-release-switch.v1",
                0o644,
            )
            invalid = self._record(
                state,
                "terminal",
                "6" * 32,
                "unknown.schema",
                0o644,
            )
            with self.assertRaisesRegex(
                norm.DeploymentStateNormalizationError,
                "schema is not recognized",
            ):
                norm.normalize_deployment_state(state, apply=True)
            self.assertEqual(stat.S_IMODE(valid.stat().st_mode), 0o644)
            self.assertEqual(stat.S_IMODE(invalid.stat().st_mode), 0o644)

    def test_active_transaction_blocks_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = self._state(Path(td))
            active = state / norm.ACTIVE_NAME
            active.write_text("{}\n", encoding="utf-8")
            os.chmod(active, 0o600)
            with self.assertRaisesRegex(
                norm.DeploymentStateNormalizationError,
                "not IDLE",
            ):
                norm.normalize_deployment_state(state, apply=True)

    def test_busy_deployment_lock_blocks_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = self._state(Path(td))
            fd = os.open(state / norm.LOCK_NAME, os.O_RDWR)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaisesRegex(
                    norm.DeploymentStateNormalizationError,
                    "busy",
                ):
                    norm.normalize_deployment_state(state, apply=True)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def test_transaction_id_mismatch_and_symlink_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = self._state(root)
            mismatch = state / "history" / (("7" * 32) + ".json")
            mismatch.write_text(
                json.dumps(
                    {
                        "schema": "keelaryn.zero-vps-release-switch.v1",
                        "transaction_id": "8" * 32,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            os.chmod(mismatch, 0o644)
            with self.assertRaisesRegex(
                norm.DeploymentStateNormalizationError,
                "transaction_id mismatch",
            ):
                norm.normalize_deployment_state(state, apply=True)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = self._state(root)
            outside = root / "outside.json"
            outside.write_text("{}\n", encoding="utf-8")
            os.symlink(
                outside,
                state / "terminal" / (("9" * 32) + ".json"),
            )
            with self.assertRaisesRegex(
                norm.DeploymentStateNormalizationError,
                "without following symlinks",
            ):
                norm.normalize_deployment_state(state, apply=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
