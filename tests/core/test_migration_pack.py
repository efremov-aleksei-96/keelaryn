from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))

from keelaryn_core.migration_pack import (  # noqa: E402
    MIGRATION_MAPPING_NAME,
    MIGRATION_PACK_NAME,
    MigrationPackBlocked,
    build_migration_pack,
    capture_migration_source,
    verify_migration_mapping,
    verify_migration_pack,
    verify_migration_source,
)
from keelaryn_core.protocol import canonical_json_bytes  # noqa: E402


class MigrationPackTests(unittest.TestCase):
    def _fixture(self, root: Path):
        source = root / "source"
        source.mkdir()
        (source / "alpha.md").write_bytes(b"alpha\r\n")
        nested = source / "nested"
        nested.mkdir()
        (nested / "beta.json").write_bytes(b'{"beta":2}\r\n')
        (source / "tech.txt").write_bytes(b"legacy-runtime\r\n")

        selection = root / "MIGRATION_SELECTION.json"
        selection.write_bytes(
            canonical_json_bytes(
                {
                    "schema": "keelaryn.migration-selection.v1",
                    "candidate_id": "migration-001",
                    "sources": ["tech.txt", "nested/beta.json", "alpha.md"],
                }
            )
        )
        source_manifest = root / "MIGRATION_SOURCE.json"
        capture_migration_source(source, selection, source_manifest)

        prepared = root / "prepared"
        prepared.mkdir()
        (prepared / "beta-prepared.md").write_bytes(b"# Beta\r\nvalue=2\r\n")
        (prepared / "INDEX.md").write_bytes(b"# Migrated Index\r\n")

        mapping = root / "MIGRATION_MAPPING.json"
        mapping.write_bytes(
            canonical_json_bytes(
                {
                    "schema": "keelaryn.migration-mapping.v1",
                    "candidate_id": "migration-001",
                    "source_manifest_sha256": verify_migration_source(source_manifest).digest,
                    "source_actions": [
                        {"source": "alpha.md", "classification": "CANONICAL_IMPORT"},
                        {"source": "nested/beta.json", "classification": "CANONICAL_IMPORT"},
                        {"source": "tech.txt", "classification": "DROP_TECHNICAL"},
                    ],
                    "canonical_outputs": [
                        {
                            "target": "data/beta.md",
                            "semantic_sources": ["nested/beta.json"],
                            "payload": {
                                "kind": "PREPARED",
                                "prepared_path": "beta-prepared.md",
                            },
                        },
                        {
                            "target": "identity/alpha.md",
                            "semantic_sources": ["alpha.md"],
                            "payload": {"kind": "SOURCE", "source": "alpha.md"},
                        },
                    ],
                    "root_index": {
                        "semantic_sources": ["alpha.md", "nested/beta.json"],
                        "prepared_path": "INDEX.md",
                    },
                }
            )
        )
        return source, selection, source_manifest, prepared, mapping

    def test_deterministic_pack_preserves_exact_crlf_and_sanitizes_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, _, source_manifest, prepared, mapping = self._fixture(root)
            first = build_migration_pack(
                source, source_manifest, mapping, root / "pack-a", prepared_root=prepared
            )
            second = build_migration_pack(
                source, source_manifest, mapping, root / "pack-b", prepared_root=prepared
            )

            self.assertEqual(first.manifest_raw, second.manifest_raw)
            self.assertEqual(first.pack_sha256, second.pack_sha256)
            self.assertEqual(
                (first.root / "canonical" / "canonical-00001.bin").read_bytes(),
                b"# Beta\r\nvalue=2\r\n",
            )
            self.assertEqual(
                (first.root / "canonical" / "canonical-00002.bin").read_bytes(),
                b"alpha\r\n",
            )
            self.assertEqual((first.root / "root" / "INDEX.md").read_bytes(), b"# Migrated Index\r\n")
            summary = first.public_summary()
            encoded = json.dumps(summary, sort_keys=True)
            self.assertEqual(summary["candidate_id"], "migration-001")
            self.assertEqual(summary["source_file_count"], 3)
            self.assertEqual(summary["canonical_file_count"], 2)
            self.assertNotIn("alpha.md", encoded)
            self.assertNotIn("data/beta.md", encoded)
            self.assertNotIn("target", encoded)

    def test_capture_is_independent_of_selection_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, selection, source_manifest, _, _ = self._fixture(root)
            value = json.loads(selection.read_text(encoding="utf-8"))
            value["sources"] = list(reversed(value["sources"]))
            alternate_selection = root / "MIGRATION_SELECTION_2.json"
            alternate_selection.write_bytes(canonical_json_bytes(value))
            alternate_source = root / "MIGRATION_SOURCE_2.json"
            capture_migration_source(source, alternate_selection, alternate_source)
            self.assertEqual(source_manifest.read_bytes(), alternate_source.read_bytes())

    def test_capture_rejects_source_drift_between_observations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "alpha.md").write_bytes(b"alpha\n")
            selection = root / "selection.json"
            selection.write_bytes(
                canonical_json_bytes(
                    {
                        "schema": "keelaryn.migration-selection.v1",
                        "candidate_id": "migration-drift",
                        "sources": ["alpha.md"],
                    }
                )
            )
            with patch(
                "keelaryn_core.migration_source.source_file",
                side_effect=[b"first\n", b"second\n"],
            ):
                with self.assertRaisesRegex(MigrationPackBlocked, "changed after capture"):
                    capture_migration_source(source, selection, root / "source.json")

    def test_build_rejects_drift_from_frozen_source_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, _, source_manifest, prepared, mapping = self._fixture(root)
            (source / "alpha.md").write_bytes(b"changed\r\n")
            with self.assertRaisesRegex(MigrationPackBlocked, "drift from frozen manifest"):
                build_migration_pack(
                    source, source_manifest, mapping, root / "pack", prepared_root=prepared
                )

    def test_mapping_requires_every_source_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, source_manifest, _, mapping = self._fixture(root)
            value = json.loads(mapping.read_text(encoding="utf-8"))
            value["source_actions"] = value["source_actions"][:-1]
            mapping.write_bytes(canonical_json_bytes(value))
            with self.assertRaisesRegex(MigrationPackBlocked, "classify every source"):
                verify_migration_mapping(source_manifest, mapping)

    def test_mapping_rejects_one_source_with_two_canonical_owners(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, source_manifest, _, mapping = self._fixture(root)
            value = json.loads(mapping.read_text(encoding="utf-8"))
            value["canonical_outputs"].append(
                {
                    "target": "other/alpha.md",
                    "semantic_sources": ["alpha.md"],
                    "payload": {"kind": "SOURCE", "source": "alpha.md"},
                }
            )
            mapping.write_bytes(canonical_json_bytes(value))
            with self.assertRaisesRegex(MigrationPackBlocked, "multiple canonical owners"):
                verify_migration_mapping(source_manifest, mapping)

    def test_archive_only_is_fail_closed_until_preservation_is_implemented(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, _, source_manifest, prepared, mapping = self._fixture(root)
            value = json.loads(mapping.read_text(encoding="utf-8"))
            value["source_actions"][2]["classification"] = "ARCHIVE_ONLY"
            mapping.write_bytes(canonical_json_bytes(value))
            verify_migration_mapping(source_manifest, mapping)
            with self.assertRaisesRegex(MigrationPackBlocked, "does not yet materialize"):
                build_migration_pack(
                    source, source_manifest, mapping, root / "pack", prepared_root=prepared
                )

    def test_verify_rejects_payload_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, _, source_manifest, prepared, mapping = self._fixture(root)
            pack = build_migration_pack(
                source, source_manifest, mapping, root / "pack", prepared_root=prepared
            )
            (pack.root / "canonical" / "canonical-00001.bin").write_bytes(b"tampered\n")
            with self.assertRaisesRegex(MigrationPackBlocked, "fingerprint mismatch"):
                verify_migration_pack(pack.root)

    def test_verify_rejects_packed_mapping_authority_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, _, source_manifest, prepared, mapping = self._fixture(root)
            pack = build_migration_pack(
                source, source_manifest, mapping, root / "pack", prepared_root=prepared
            )
            packed_mapping = pack.root / "authority" / MIGRATION_MAPPING_NAME
            packed_mapping.write_bytes(packed_mapping.read_bytes() + b" \n")
            with self.assertRaisesRegex(MigrationPackBlocked, "authority fingerprint mismatch"):
                verify_migration_pack(pack.root)

    def test_verify_rejects_extra_material(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, _, source_manifest, prepared, mapping = self._fixture(root)
            pack = build_migration_pack(
                source, source_manifest, mapping, root / "pack", prepared_root=prepared
            )
            (pack.root / "unexpected.txt").write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(MigrationPackBlocked, "unexpected material"):
                verify_migration_pack(pack.root)

    def test_selection_rejects_traversal_duplicate_and_duplicate_json_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "alpha.md").write_bytes(b"alpha\n")
            selection = root / "selection.json"

            with self.subTest("traversal"):
                selection.write_bytes(
                    canonical_json_bytes(
                        {
                            "schema": "keelaryn.migration-selection.v1",
                            "candidate_id": "migration-bad",
                            "sources": ["../alpha.md"],
                        }
                    )
                )
                with self.assertRaisesRegex(MigrationPackBlocked, "unsafe path"):
                    capture_migration_source(source, selection, root / "out-a.json")

            with self.subTest("duplicate"):
                selection.write_bytes(
                    canonical_json_bytes(
                        {
                            "schema": "keelaryn.migration-selection.v1",
                            "candidate_id": "migration-bad",
                            "sources": ["alpha.md", "alpha.md"],
                        }
                    )
                )
                with self.assertRaisesRegex(MigrationPackBlocked, "duplicate source"):
                    capture_migration_source(source, selection, root / "out-b.json")

            with self.subTest("duplicate-json-key"):
                selection.write_bytes(
                    b'{"schema":"keelaryn.migration-selection.v1","candidate_id":"a","candidate_id":"b","sources":["alpha.md"]}\n'
                )
                with self.assertRaisesRegex(MigrationPackBlocked, "duplicate JSON key"):
                    capture_migration_source(source, selection, root / "out-c.json")

    def test_source_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            real = source / "real.md"
            real.write_bytes(b"real\n")
            link = source / "link.md"
            try:
                os.symlink(real, link)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            selection = root / "selection.json"
            selection.write_bytes(
                canonical_json_bytes(
                    {
                        "schema": "keelaryn.migration-selection.v1",
                        "candidate_id": "migration-link",
                        "sources": ["link.md"],
                    }
                )
            )
            with self.assertRaisesRegex(MigrationPackBlocked, "link/reparse"):
                capture_migration_source(source, selection, root / "source.json")


if __name__ == "__main__":
    unittest.main()
