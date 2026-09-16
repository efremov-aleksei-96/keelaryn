from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))

from keelaryn_core.pilot_pack import (  # noqa: E402
    PILOT_PACK_NAME,
    PilotPackBlocked,
    build_pilot_pack,
    verify_pilot_pack,
)
from keelaryn_core.protocol import canonical_json_bytes  # noqa: E402


class PilotPackTests(unittest.TestCase):
    def _source(self, root: Path) -> tuple[Path, Path]:
        source = root / "source"
        source.mkdir()
        (source / "alpha.md").write_bytes(b"alpha\n")
        nested = source / "nested"
        nested.mkdir()
        (nested / "beta.json").write_bytes(b'{"beta":2}\n')
        manifest = root / "PILOT_SOURCE.json"
        manifest.write_bytes(
            canonical_json_bytes(
                {
                    "schema": "keelaryn.pilot-source.v1",
                    "pilot_id": "pilot-real-subset-001",
                    "entries": [
                        {"source": "alpha.md", "target": "alpha.md"},
                        {"source": "nested/beta.json", "target": "beta.json"},
                    ],
                }
            )
        )
        return source, manifest

    def test_build_is_deterministic_and_summary_is_sanitized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, manifest = self._source(root)
            first = build_pilot_pack(source, manifest, root / "pack-a")
            second = build_pilot_pack(source, manifest, root / "pack-b")

            self.assertEqual(first.manifest_raw, second.manifest_raw)
            self.assertEqual(first.pack_sha256, second.pack_sha256)
            self.assertEqual(first.total_bytes, second.total_bytes)
            self.assertEqual(
                [first.payload_bytes(entry) for entry in first.entries],
                [second.payload_bytes(entry) for entry in second.entries],
            )
            summary = first.public_summary()
            self.assertEqual(summary["pilot_id"], "pilot-real-subset-001")
            self.assertEqual(summary["file_count"], 2)
            self.assertNotIn("source", json.dumps(summary))
            self.assertNotIn("target", json.dumps(summary))
            self.assertNotIn("alpha.md", json.dumps(summary))

    def test_verify_rejects_payload_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, manifest = self._source(root)
            pack = build_pilot_pack(source, manifest, root / "pack")
            payload = pack.root / "files" / "import-001.bin"
            payload.write_bytes(b"tampered\n")
            with self.assertRaisesRegex(PilotPackBlocked, "fingerprint mismatch"):
                verify_pilot_pack(pack.root)

    def test_verify_rejects_extra_material(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, manifest = self._source(root)
            pack = build_pilot_pack(source, manifest, root / "pack")
            (pack.root / "unexpected.txt").write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(PilotPackBlocked, "unexpected material"):
                verify_pilot_pack(pack.root)

    def test_build_rejects_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, manifest = self._source(root)
            output = root / "pack"
            output.mkdir()
            with self.assertRaisesRegex(PilotPackBlocked, "output already exists"):
                build_pilot_pack(source, manifest, output)

    def test_source_manifest_rejects_nested_canonical_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, manifest = self._source(root)
            value = json.loads(manifest.read_text(encoding="utf-8"))
            value["entries"][0]["target"] = "topic/alpha.md"
            manifest.write_bytes(canonical_json_bytes(value))
            with self.assertRaisesRegex(PilotPackBlocked, "canonical-root file"):
                build_pilot_pack(source, manifest, root / "pack")

    def test_source_manifest_rejects_duplicate_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, manifest = self._source(root)
            value = json.loads(manifest.read_text(encoding="utf-8"))
            value["entries"][1]["target"] = value["entries"][0]["target"]
            manifest.write_bytes(canonical_json_bytes(value))
            with self.assertRaisesRegex(PilotPackBlocked, "duplicate target"):
                build_pilot_pack(source, manifest, root / "pack")

    def test_source_manifest_rejects_duplicate_json_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, manifest = self._source(root)
            manifest.write_bytes(
                b'{"schema":"keelaryn.pilot-source.v1","pilot_id":"pilot-a","pilot_id":"pilot-b","entries":[{"source":"alpha.md","target":"alpha.md"}]}\n'
            )
            with self.assertRaisesRegex(PilotPackBlocked, "duplicate JSON key"):
                build_pilot_pack(source, manifest, root / "pack")

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
            manifest = root / "PILOT_SOURCE.json"
            manifest.write_bytes(
                canonical_json_bytes(
                    {
                        "schema": "keelaryn.pilot-source.v1",
                        "pilot_id": "pilot-link",
                        "entries": [{"source": "link.md", "target": "link.md"}],
                    }
                )
            )
            with self.assertRaisesRegex(PilotPackBlocked, "link/reparse"):
                build_pilot_pack(source, manifest, root / "pack")

    def test_source_parent_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            real_dir = source / "real"
            real_dir.mkdir()
            (real_dir / "data.md").write_bytes(b"data\n")
            linked_dir = source / "linked"
            try:
                os.symlink(real_dir, linked_dir, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"directory symlink creation unavailable: {exc}")
            manifest = root / "PILOT_SOURCE.json"
            manifest.write_bytes(
                canonical_json_bytes(
                    {
                        "schema": "keelaryn.pilot-source.v1",
                        "pilot_id": "pilot-parent-link",
                        "entries": [{"source": "linked/data.md", "target": "data.md"}],
                    }
                )
            )
            with self.assertRaisesRegex(PilotPackBlocked, "link/reparse"):
                build_pilot_pack(source, manifest, root / "pack")

    def test_pack_manifest_requires_exact_payload_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, manifest = self._source(root)
            pack = build_pilot_pack(source, manifest, root / "pack")
            value = json.loads((pack.root / PILOT_PACK_NAME).read_text(encoding="utf-8"))
            value["entries"][0]["payload"] = "files/other.bin"
            (pack.root / PILOT_PACK_NAME).write_bytes(canonical_json_bytes(value))
            with self.assertRaisesRegex(PilotPackBlocked, "must equal"):
                verify_pilot_pack(pack.root)


if __name__ == "__main__":
    unittest.main()
