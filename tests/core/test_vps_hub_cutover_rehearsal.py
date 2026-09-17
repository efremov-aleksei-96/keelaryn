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

import hub_cutover_rehearsal as rehearsal  # noqa: E402


class ZeroBasedVpsHubCutoverRehearsalTests(unittest.TestCase):
    SOURCE = "a" * 40

    def test_rehearsal_verifies_accept_and_rollback_without_identity_leak(self) -> None:
        first = rehearsal.run_rehearsal(self.SOURCE)
        second = rehearsal.run_rehearsal(self.SOURCE)
        self.assertEqual(first, second)
        self.assertEqual(
            first,
            {
                "schema": rehearsal.SCHEMA,
                "source_commit": self.SOURCE,
                "accept_path_verified": True,
                "rollback_path_verified": True,
                "restart_recovery_verified": True,
                "terminal_history_verified": True,
                "selector_bytes_verified": True,
                "hub_bytes_touched": False,
            },
        )
        encoded = json.dumps(first, sort_keys=True).encode("utf-8")
        self.assertNotIn(rehearsal.OLD_HUB_ROOT_ID.encode("ascii"), encoded)
        self.assertNotIn(rehearsal.NEW_HUB_ROOT_ID.encode("ascii"), encoded)
        self.assertNotIn(b"transaction_id", encoded)

    def test_written_evidence_is_exact_private_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "evidence.json"
            evidence = rehearsal.run_rehearsal(self.SOURCE)
            rehearsal.write_evidence(output, evidence)
            expected = (
                json.dumps(
                    evidence,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8")
            self.assertEqual(output.read_bytes(), expected)
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            self.assertNotIn(rehearsal.OLD_HUB_ROOT_ID.encode("ascii"), expected)
            self.assertNotIn(rehearsal.NEW_HUB_ROOT_ID.encode("ascii"), expected)

    def test_existing_evidence_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "evidence.json"
            output.write_bytes(b"preserve-me\n")
            os.chmod(output, 0o600)
            with self.assertRaises(rehearsal.HubCutoverRehearsalError):
                rehearsal.write_evidence(output, rehearsal.run_rehearsal(self.SOURCE))
            self.assertEqual(output.read_bytes(), b"preserve-me\n")

    def test_invalid_source_commit_blocks_before_rehearsal(self) -> None:
        for invalid in ("", "A" * 40, "a" * 39, "g" * 40):
            with self.subTest(invalid=invalid):
                with self.assertRaises(rehearsal.HubCutoverRehearsalError):
                    rehearsal.run_rehearsal(invalid)


if __name__ == "__main__":
    unittest.main(verbosity=2)
