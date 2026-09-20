from __future__ import annotations

import io
import json
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))

from keelaryn_core.drive_model import DriveModel  # noqa: E402
from keelaryn_core.gate_progress import GateProgressJournal  # noqa: E402
from keelaryn_core.migration_drive_source import (  # noqa: E402
    verify_migration_source_against_drive,
)
from keelaryn_core.migration_source import parse_source  # noqa: E402
from keelaryn_core.protocol import canonical_json_bytes  # noqa: E402


class GateProgressTests(unittest.TestCase):
    def test_private_journal_is_0600_and_emits_sanitized_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            os.chmod(root, 0o700)
            path = root / "progress.jsonl"
            stream = io.StringIO()

            journal = GateProgressJournal(
                path,
                operation="TEST_GATE",
                heartbeat_seconds=60,
                stream=stream,
            )
            journal.record(
                {
                    "phase": "SOURCE_VERIFY_PRE",
                    "event": "SOURCE_ITEM_COMPLETE",
                    "mutation_state": "MUTATION_NOT_STARTED",
                    "authority_state": "ABSENT",
                    "target_state": "ABSENT",
                    "evidence_state": "ABSENT",
                    "pass_index": 1,
                    "pass_total": 2,
                    "item_index": 7,
                    "item_total": 10,
                }
            )
            heartbeat = journal.heartbeat_once()
            terminal = journal.finish("PASS", phase="COMPLETE")

            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            rows = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertGreaterEqual(len(rows), 4)
            self.assertEqual(rows[0]["event"], "START")
            self.assertEqual(rows[-1]["event"], "PASS")
            self.assertEqual(heartbeat["event"], "HEARTBEAT")
            self.assertEqual(terminal["phase"], "COMPLETE")
            self.assertIn("item_index", rows[1])
            self.assertNotIn(str(path), stream.getvalue())

    def test_drive_source_verification_reports_both_passes_and_items(self) -> None:
        drive = DriveModel()
        source_root = drive.create_folder("root", "legacy").file_id
        raw = b"exact legacy bytes\n"
        drive.create_blob(source_root, "identity.md", raw)

        source = parse_source(
            canonical_json_bytes(
                {
                    "schema": "keelaryn.migration-source.v1",
                    "candidate_id": "candidate-progress",
                    "entries": [
                        {
                            "source": "identity.md",
                            "sha256": sha256(raw).hexdigest(),
                            "size": len(raw),
                        }
                    ],
                }
            )
        )
        events: list[dict[str, int | str]] = []

        verify_migration_source_against_drive(
            drive,
            source_root,
            source,
            progress=events.append,
            phase="SOURCE_VERIFY_PRE",
        )

        items = [
            event
            for event in events
            if event["event"] == "SOURCE_ITEM_COMPLETE"
        ]
        self.assertEqual(len(items), 2)
        self.assertEqual(
            [(event["pass_index"], event["item_index"]) for event in items],
            [(1, 1), (2, 1)],
        )
        self.assertEqual(events[-1]["event"], "SOURCE_VERIFY_COMPLETE")
        self.assertEqual(events[-1]["item_total"], 1)


    def test_append_retries_short_writes_until_complete_record(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.chmod(root, 0o700)
            path = root / "progress.jsonl"
            stream = io.StringIO()
            original_write = os.write
            calls = {"count": 0}

            def short_write(fd, raw):
                calls["count"] += 1
                if len(raw) > 1:
                    raw = raw[: max(1, len(raw) // 2)]
                return original_write(fd, raw)

            with mock.patch("keelaryn_core.gate_progress.os.write", side_effect=short_write):
                journal = GateProgressJournal(
                    path,
                    operation="TEST",
                    heartbeat_seconds=60,
                    stream=stream,
                )
                journal.finish("PASS", phase="COMPLETE")

            self.assertGreater(calls["count"], 2)
            records = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertGreaterEqual(len(records), 2)
            self.assertEqual(records[-1]["event"], "PASS")


if __name__ == "__main__":
    unittest.main(verbosity=2)
