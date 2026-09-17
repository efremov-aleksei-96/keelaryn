from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from keelaryn_core import migration_cli
from keelaryn_core.migration_common import (
    MAX_MIGRATION_FILE_BYTES,
    MigrationPackBlocked,
)
from keelaryn_core.migration_inventory import (
    MIGRATION_SOURCE_INVENTORY_SCHEMA,
    _enumerate_source,
    inventory_migration_source,
    parse_migration_source_inventory,
    verify_migration_source_inventory,
)
from keelaryn_core.protocol import canonical_json_bytes


class MigrationSourceInventoryTests(unittest.TestCase):
    CANDIDATE = "migration-inventory-test"

    @staticmethod
    def _snapshot(root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    def test_inventory_is_deterministic_private_sanitized_and_source_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "legacy"
            output_root = root / "private"
            source.mkdir()
            output_root.mkdir()
            (source / "nested").mkdir()
            (source / "b.txt").write_bytes(b"B\r\n")
            (source / "nested" / "a.md").write_bytes(b"alpha\n")

            before = self._snapshot(source)
            first_path = output_root / "inventory-1.json"
            second_path = output_root / "inventory-2.json"
            first = inventory_migration_source(source, self.CANDIDATE, first_path)
            second = inventory_migration_source(source, self.CANDIDATE, second_path)

            self.assertEqual(first.raw, second.raw)
            self.assertEqual(first.digest, second.digest)
            self.assertEqual(
                [entry.source for entry in first.entries],
                ["b.txt", "nested/a.md"],
            )
            by_name = {entry.source: entry for entry in first.entries}
            self.assertEqual(by_name["b.txt"].sha256, sha256(b"B\r\n").hexdigest())
            self.assertEqual(by_name["nested/a.md"].sha256, sha256(b"alpha\n").hexdigest())
            self.assertTrue(all(entry.selectable for entry in first.entries))
            self.assertEqual(self._snapshot(source), before)
            self.assertEqual(verify_migration_source_inventory(first_path), first)
            summary = first.public_summary()
            self.assertEqual(summary["schema"], MIGRATION_SOURCE_INVENTORY_SCHEMA)
            self.assertEqual(summary["file_count"], 2)
            self.assertEqual(summary["selectable_file_count"], 2)
            self.assertEqual(summary["oversized_file_count"], 0)
            rendered = json.dumps(summary, sort_keys=True)
            self.assertNotIn("b.txt", rendered)
            self.assertNotIn("nested/a.md", rendered)
            self.assertNotIn(str(source), rendered)
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(first_path.stat().st_mode), 0o600)

    def test_cli_emits_only_sanitized_inventory_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "legacy"
            output_root = root / "private"
            source.mkdir()
            output_root.mkdir()
            secret_name = "private-personal-name.md"
            (source / secret_name).write_bytes(b"private bytes\n")
            output = output_root / "inventory.json"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = migration_cli.main(
                    [
                        "source-inventory",
                        "--source-root",
                        str(source),
                        "--candidate-id",
                        self.CANDIDATE,
                        "--output-manifest",
                        str(output),
                    ]
                )
            self.assertEqual(code, 0)
            self.assertEqual(stderr.getvalue(), "")
            value = json.loads(stdout.getvalue())
            self.assertEqual(value["inventory"]["file_count"], 1)
            self.assertNotIn(secret_name, stdout.getvalue())
            self.assertNotIn(str(source), stdout.getvalue())
            self.assertTrue(output.is_file())

    def test_inventory_output_inside_source_is_blocked_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "legacy"
            source.mkdir()
            (source / "a.txt").write_bytes(b"a")
            output = source / "inventory.json"
            with self.assertRaisesRegex(
                MigrationPackBlocked,
                "output must be outside source root",
            ):
                inventory_migration_source(source, self.CANDIDATE, output)
            self.assertFalse(output.exists())

    def test_inventory_rejects_linklike_or_reparse_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "legacy"
            output_root = root / "private"
            source.mkdir()
            output_root.mkdir()
            blocked = source / "blocked.txt"
            blocked.write_bytes(b"x")

            with patch(
                "keelaryn_core.migration_inventory._is_linklike",
                side_effect=lambda path: Path(path).name == "blocked.txt",
            ):
                with self.assertRaisesRegex(
                    MigrationPackBlocked,
                    "symlink/reparse",
                ):
                    inventory_migration_source(
                        source,
                        self.CANDIDATE,
                        output_root / "inventory.json",
                    )

    def test_inventory_detects_structure_drift_between_observations(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "legacy"
            output_root = root / "private"
            source.mkdir()
            output_root.mkdir()
            (source / "a.txt").write_bytes(b"x")
            (source / "b.txt").write_bytes(b"y")
            first = (("a.txt", 1),)
            second = (("a.txt", 1), ("b.txt", 1))
            with patch(
                "keelaryn_core.migration_inventory._enumerate_source",
                side_effect=[first, second],
            ), patch(
                "keelaryn_core.migration_inventory.source_file",
                return_value=b"x",
            ):
                with self.assertRaisesRegex(
                    MigrationPackBlocked,
                    "structure changed",
                ):
                    inventory_migration_source(
                        source,
                        self.CANDIDATE,
                        output_root / "inventory.json",
                    )

    def test_inventory_detects_byte_drift_between_observations(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "legacy"
            output_root = root / "private"
            source.mkdir()
            output_root.mkdir()
            (source / "a.txt").write_bytes(b"x")
            structure = (("a.txt", 1),)
            with patch(
                "keelaryn_core.migration_inventory._enumerate_source",
                side_effect=[structure, structure],
            ), patch(
                "keelaryn_core.migration_inventory.source_file",
                side_effect=[b"x", b"y"],
            ):
                with self.assertRaisesRegex(
                    MigrationPackBlocked,
                    "source changed during inventory",
                ):
                    inventory_migration_source(
                        source,
                        self.CANDIDATE,
                        output_root / "inventory.json",
                    )

    def test_oversized_entry_is_recorded_but_not_read_or_selectable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "legacy"
            output_root = root / "private"
            source.mkdir()
            output_root.mkdir()
            (source / "large.bin").write_bytes(b"x")
            size = MAX_MIGRATION_FILE_BYTES + 1
            structure = (("large.bin", size),)
            with patch(
                "keelaryn_core.migration_inventory._enumerate_source",
                side_effect=[structure, structure],
            ), patch(
                "keelaryn_core.migration_inventory.source_file"
            ) as read_source:
                result = inventory_migration_source(
                    source,
                    self.CANDIDATE,
                    output_root / "inventory.json",
                )
            read_source.assert_not_called()
            self.assertEqual(len(result.entries), 1)
            self.assertFalse(result.entries[0].selectable)
            self.assertIsNone(result.entries[0].sha256)
            self.assertEqual(result.entries[0].size, size)
            self.assertEqual(result.public_summary()["oversized_file_count"], 1)

    def test_parser_rejects_noncanonical_and_selectability_tamper(self) -> None:
        valid = {
            "schema": MIGRATION_SOURCE_INVENTORY_SCHEMA,
            "candidate_id": self.CANDIDATE,
            "entries": [
                {
                    "source": "a.txt",
                    "size": 1,
                    "sha256": sha256(b"x").hexdigest(),
                    "selectable": True,
                }
            ],
        }
        raw = canonical_json_bytes(valid)
        parsed = parse_migration_source_inventory(raw)
        self.assertEqual(parsed.entries[0].source, "a.txt")

        with self.assertRaisesRegex(MigrationPackBlocked, "canonical JSON"):
            parse_migration_source_inventory(
                json.dumps(valid, indent=2).encode("utf-8")
            )

        tampered = json.loads(raw.decode("utf-8"))
        tampered["entries"][0]["selectable"] = False
        tampered["entries"][0]["sha256"] = None
        with self.assertRaisesRegex(MigrationPackBlocked, "selectable"):
            parse_migration_source_inventory(canonical_json_bytes(tampered))

    def test_enumerator_is_sorted_and_parser_rejects_case_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "legacy"
            source.mkdir()
            (source / "z.txt").write_bytes(b"z")
            (source / "a.txt").write_bytes(b"a")
            self.assertEqual(
                [name for name, _ in _enumerate_source(source.resolve())],
                ["a.txt", "z.txt"],
            )

        conflict = {
            "schema": MIGRATION_SOURCE_INVENTORY_SCHEMA,
            "candidate_id": self.CANDIDATE,
            "entries": [
                {
                    "source": "A.txt",
                    "size": 1,
                    "sha256": sha256(b"A").hexdigest(),
                    "selectable": True,
                },
                {
                    "source": "a.txt",
                    "size": 1,
                    "sha256": sha256(b"a").hexdigest(),
                    "selectable": True,
                },
            ],
        }
        with self.assertRaisesRegex(MigrationPackBlocked, "case-conflicting"):
            parse_migration_source_inventory(canonical_json_bytes(conflict))


if __name__ == "__main__":
    unittest.main(verbosity=2)
